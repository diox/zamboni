import json
import os
import shutil
import tempfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import requests
from celeryutils import task
from django_statsd.clients import statsd
from signing_clients.apps import JarExtractor

from mkt.versions.models import Version


log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign_app(src, dest, ids, reviewer=False):
    tempname = tempfile.mktemp()
    try:
        return _sign_app(src, dest, ids, reviewer, tempname)
    finally:
        try:
            os.unlink(tempname)
        except OSError:
            # If the file has already been removed, don't worry about it.
            pass


def _sign_app(src, dest, ids, reviewer, tempname):
    """
    Generate a manifest and signature and send signature to signing server to
    be signed.
    """
    active_endpoint = _get_endpoint(reviewer)
    timeout = settings.SIGNED_APPS_SERVER_TIMEOUT

    if not active_endpoint:
        _no_sign(src, dest)
        return

    # Extract necessary info from the archive
    try:
        jar = JarExtractor(
            storage.open(src, 'r'), tempname,
            ids,
            omit_signature_sections=settings.SIGNED_APPS_OMIT_PER_FILE_SIGS)
    except:
        log.error('Archive extraction failed. Bad archive?', exc_info=True)
        raise SigningError('Archive extraction failed. Bad archive?')

    log.info('App signature contents: %s' % jar.signatures)

    log.info('Calling service: %s' % active_endpoint)
    try:
        with statsd.timer('services.sign.app'):
            response = requests.post(active_endpoint, timeout=timeout,
                                     files={'file': ('zigbert.sf',
                                                     str(jar.signatures))})
    except requests.exceptions.HTTPError, error:
        # Will occur when a 3xx or greater code is returned.
        log.error('Posting to app signing failed: %s, %s' % (
            error.response.status, error))
        raise SigningError('Posting to app signing failed: %s, %s' % (
            error.response.status, error))

    except:
        # Will occur when some other error occurs.
        log.error('Posting to app signing failed', exc_info=True)
        raise SigningError('Posting to app signing failed')

    if response.status_code != 200:
        log.error('Posting to app signing failed: %s' % response.reason)
        raise SigningError('Posting to app signing failed: %s'
                           % response.reason)

    pkcs7 = b64decode(json.loads(response.content)['zigbert.rsa'])
    try:
        jar.make_signed(pkcs7)
    except:
        log.error('App signing failed', exc_info=True)
        raise SigningError('App signing failed')
    with storage.open(dest, 'w') as destf:
        tempf = open(tempname)
        shutil.copyfileobj(tempf, destf)


def _get_endpoint(reviewer=False):
    """
    Returns the proper API endpoint depending whether we are signing for
    reviewer or for public consumption.
    """
    active = (settings.SIGNED_APPS_REVIEWER_SERVER_ACTIVE if reviewer else
              settings.SIGNED_APPS_SERVER_ACTIVE)
    server = (settings.SIGNED_APPS_REVIEWER_SERVER if reviewer else
              settings.SIGNED_APPS_SERVER)

    if active:
        if not server:
            # If no API endpoint is set. Just ignore this request.
            raise ValueError(
                'Invalid config. The %sserver setting is empty.' % (
                    'reviewer ' if reviewer else ''))
        return server + '/1.0/sign_app'


def _no_sign(src, dest):
    # If this is a local development instance, just copy the file around
    # so that everything seems to work locally.
    log.info('Not signing the app, no signing server is active.')
    dest_dir = os.path.dirname(dest)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    shutil.copy(src, dest)


# def sign_langpack(obj):
#     log.info('[LangPack:%s] Signing version: %s' % (obj.pk, obj.version))
#     if not obj.filename or not storage.exists(obj.file_path):
#         log.error('[LangPack:%s] Attempt to sign with no filename.' % obj.pk)
#         raise SigningError('No file')
#     path = obj.signed_file_path
#     if storage.exists(path):
#         log.info('[LangPack:%s] Already signed file exists.' % obj.pk)
#         return path
#     ids = json.dumps({
#         'id': obj.pk,
#         # `version` needs to be unique. We don't have a Version model for
#         # LangPacks, but the instance hash of the original filename should be
#         # unique and properly represent the current version.
#         'version': obj.hash
#     })
#     with statsd.timer('services.sign.app'):
#         try:
#             sign_app(obj.file_path, path, ids, reviewer=False)
#         except SigningError:
#             log.info('[LangPack:%s] Signing failed' % obj.pk)
#             if storage.exists(path):
#                 storage.delete(path)
#             raise
#     log.info('[LangPack:%s] Signing complete.' % obj.pk)
#     return path



# Need to finish or abandon this refactor. See https://github.com/mozilla/olympia/pull/431/
# for inspiration. Passing version instead of version_id is better, but it'd be
# even better if I could pass an arbitrary model instance with a similar API to
# access files - to make LangPacks work. Need to know if I'm doing multiple models
# or keeping the single model first, though.

@task
def sign(version, reviewer=False, resign=False, **kw):
    app = version.addon
    log.info('Signing version: %s of app: %s' % (version.pk, app))

    if not app.is_packaged:
        log.error('[Webapp:%s] Attempt to sign a non-packaged app.' % app.pk)
        raise SigningError('Not packaged')

    try:
        file_obj = version.all_files[0]
    except IndexError:
        log.error(
            '[Webapp:%s] Attempt to sign an app with no files in version.' %
            app.pk)
        raise SigningError('No file')

    path = (file_obj.signed_reviewer_file_path if reviewer else
            file_obj.signed_file_path)

    if storage.exists(path) and not resign:
        log.info('[Webapp:%s] Already signed app exists.' % app.pk)
        return path

    if reviewer:
        # Reviewers get a unique 'id' so the reviewer installed app won't
        # conflict with the public app, and also so multiple versions of the
        # same app won't conflict with themselves.
        ids = json.dumps({
            'id': 'reviewer-{guid}-{version_id}'.format(guid=app.guid,
                                                        version_id=version.pk),
            'version': version.pk
        })
    else:
        ids = json.dumps({
            'id': app.guid,
            'version': version.pk
        })
    with statsd.timer('services.sign.app'):
        try:
            sign_app(file_obj.file_path, path, ids, reviewer)
        except SigningError:
            log.info('[Webapp:%s] Signing failed' % app.pk)
            if storage.exists(path):
                storage.delete(path)
            raise
    log.info('[Webapp:%s] Signing complete.' % app.pk)
    return path
