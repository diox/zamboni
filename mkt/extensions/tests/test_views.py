# -*- coding: utf-8 -*-
import hashlib
import json
import mock
from datetime import datetime

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test.utils import override_settings

from nose.tools import eq_, ok_

from mkt.api.tests.test_oauth import RestOAuth
from mkt.constants import comm
from mkt.constants.apps import MANIFEST_CONTENT_TYPE
from mkt.constants.base import (STATUS_NULL, STATUS_OBSOLETE, STATUS_PENDING,
                                STATUS_PUBLIC, STATUS_REJECTED)
from mkt.extensions.models import Extension, ExtensionVersion
from mkt.files.models import FileUpload
from mkt.files.tests.test_models import UploadTest
from mkt.site.fixtures import fixture
from mkt.site.storage_utils import private_storage
from mkt.site.tests import ESTestCase, MktPaths, TestCase
from mkt.users.models import UserProfile


class TestExtensionValidationViewSet(MktPaths, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestExtensionValidationViewSet, self).setUp()
        self.list_url = reverse('api-v2:extension-validation-list')
        self.user = UserProfile.objects.get(pk=2519)

    def _test_create_success(self, client):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/zip',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        with open(self.packaged_app_path('extension.zip'), 'rb') as fd:
            response = client.post(self.list_url, fd.read(),
                                   content_type='application/zip', **headers)

        eq_(response.status_code, 202)
        data = response.json
        upload = FileUpload.objects.get(pk=data['id'])
        eq_(upload.valid, True)  # We directly set uploads as valid atm.
        eq_(upload.name, 'foo.zip')
        ok_(upload.hash.startswith('sha256:58ef3f15dd423c3ab9b0285ac01e692c5'))
        ok_(upload.path)
        ok_(private_storage.exists(upload.path))
        return upload

    def test_create_anonymous(self):
        upload = self._test_create_success(client=self.anon)
        eq_(upload.user, None)

    def test_create_logged_in(self):
        upload = self._test_create_success(client=self.client)
        eq_(upload.user, self.user)

    def test_create_missing_no_data(self):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/zip',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        response = self.anon.post(self.list_url,
                                  content_type='application/zip', **headers)
        eq_(response.status_code, 400)

    def test_cors(self):
        response = self.anon.post(self.list_url)
        self.assertCORS(response, 'get', 'post',
                        headers=['Content-Disposition', 'Content-Type'])

    def test_create_missing_content_disposition(self):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/zip',
        }
        with open(self.packaged_app_path('extension.zip'), 'rb') as fd:
            response = self.client.post(
                self.list_url, fd.read(), content_type='application/zip',
                **headers)
        eq_(response.status_code, 400)

    def test_create_wrong_type(self):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/foobar',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        with open(self.packaged_app_path('extension.zip'), 'rb') as fd:
            response = self.client.post(
                self.list_url, fd.read(), content_type='application/foobar',
                **headers)
        eq_(response.status_code, 400)

    def test_create_invalid_zip(self):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/zip',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        response = self.client.post(
            self.list_url, 'XXXXXX', content_type='application/zip', **headers)
        eq_(response.status_code, 400)

    def test_create_no_manifest_json(self):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/zip',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        # mozball.zip is an app, not an extension, it has no manifest.json.
        with open(self.packaged_app_path('mozball.zip'), 'rb') as fd:
            response = self.client.post(
                self.list_url, fd.read(), content_type='application/zip',
                **headers)
        eq_(response.status_code, 400)

    @mock.patch('mkt.extensions.views.ExtensionValidator.validate')
    def test_validation_called(self, mock_validate):
        headers = {
            'HTTP_CONTENT_TYPE': 'application/foobar',
            'HTTP_CONTENT_DISPOSITION': 'form-data; name="binary_data"; '
                                        'filename="foo.zip"'
        }
        with open(self.packaged_app_path('extension.zip'), 'rb') as fd:
            self.client.post(self.list_url, fd.read(),
                             content_type='application/zip', **headers)
        ok_(mock_validate.called)

    def test_view_result_anonymous(self):
        upload = FileUpload.objects.create(valid=True)
        url = reverse('api-v2:extension-validation-detail',
                      kwargs={'pk': upload.pk})
        response = self.anon.get(url)
        eq_(response.status_code, 200)
        eq_(response.json['valid'], True)


class TestExtensionViewSetPost(UploadTest, RestOAuth):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        super(TestExtensionViewSetPost, self).setUp()
        self.list_url = reverse('api-v2:extension-list')
        self.user = UserProfile.objects.get(pk=2519)

    def tearDown(self):
        super(TestExtensionViewSetPost, self).tearDown()
        # Explicitely delete the Extensions to clean up leftover files.
        Extension.objects.all().delete()

    def test_create_logged_in(self):
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=self.user)
        eq_(upload.valid, True)
        response = self.client.post(self.list_url,
                                    json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 201)
        data = response.json

        eq_(data['description'], {'en-US': u'A Dummÿ Extension'})
        eq_(data['disabled'], False)
        eq_(data['last_updated'], None)  # The extension is not public yet.
        eq_(data['latest_version']['size'], 319)
        eq_(data['latest_version']['version'], '0.1')
        eq_(data['name'], {'en-US': u'My Lîttle Extension'})
        eq_(data['slug'], u'my-lîttle-extension')
        eq_(data['status'], 'pending')
        eq_(Extension.objects.count(), 1)
        eq_(ExtensionVersion.objects.count(), 1)
        extension = Extension.objects.get(pk=data['id'])
        eq_(extension.status, STATUS_PENDING)
        eq_(list(extension.authors.all()), [self.user])

        eq_(extension.threads.get().notes.get().note_type, comm.SUBMISSION)

    def test_create_upload_has_no_user(self):
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=None)
        response = self.client.post(
            self.list_url, json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 404)

    def test_create_upload_has_wrong_user(self):
        second_user = UserProfile.objects.get(pk=999)
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=second_user)
        response = self.client.post(
            self.list_url, json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 404)

    def test_invalid_pk(self):
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=self.user)
        eq_(upload.valid, True)
        response = self.client.post(
            self.list_url, json.dumps({'validation_id': upload.pk + 'lol'}))
        eq_(response.status_code, 404)

    def test_not_validated(self):
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=self.user,
            validation=json.dumps({'errors': 1}))
        response = self.client.post(self.list_url,
                                    json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 400)

    def test_not_an_addon(self):
        upload = self.get_upload(
            abspath=self.packaged_app_path('mozball.zip'), user=self.user)
        response = self.client.post(
            self.list_url, json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 400)
        ok_(u'manifest.json' in response.json['detail'])


class TestExtensionViewSetDelete(RestOAuth):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        super(TestExtensionViewSetDelete, self).setUp()
        self.extension = Extension.objects.create()
        self.other_extension = Extension.objects.create()
        self.user = UserProfile.objects.get(pk=2519)
        self.other_user = UserProfile.objects.get(pk=999)
        self.detail_url = reverse(
            'api-v2:extension-detail', kwargs={'pk': self.extension.slug})

    def test_delete_logged_in_has_rights(self):
        eq_(Extension.objects.count(), 2)
        self.extension.authors.add(self.user)
        response = self.client.delete(self.detail_url)
        eq_(response.status_code, 204)
        eq_(Extension.objects.count(), 1)
        ok_(not Extension.objects.filter(pk=self.extension.pk).exists())
        ok_(Extension.objects.filter(pk=self.other_extension.pk).exists())

    def test_delete_logged_in_no_rights(self):
        self.extension.authors.add(self.other_user)
        response = self.client.delete(self.detail_url)
        eq_(response.status_code, 403)
        eq_(Extension.objects.count(), 2)

    def test_delete_anonymous_no_rights(self):
        response = self.anon.delete(self.detail_url)
        eq_(response.status_code, 403)
        eq_(Extension.objects.count(), 2)

    def test_delete__404(self):
        self.detail_url = reverse(
            'api-v2:extension-detail', kwargs={'pk': self.extension.pk + 666})
        response = self.client.delete(self.detail_url)
        eq_(response.status_code, 404)
        eq_(Extension.objects.count(), 2)


class TestExtensionViewSetGet(RestOAuth):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        super(TestExtensionViewSetGet, self).setUp()
        self.list_url = reverse('api-v2:extension-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=999)
        self.extension = Extension.objects.create(
            name=u'Mŷ Extension', description=u'Mÿ Extension Description')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, size=4242, status=STATUS_PENDING,
            version='0.42')
        self.extension.authors.add(self.user)
        self.extension2 = Extension.objects.create(name=u'NOT Mŷ Extension')
        self.version2 = ExtensionVersion.objects.create(
            extension=self.extension2, status=STATUS_PENDING, version='0.a1')
        self.extension2.authors.add(self.user2)
        self.url = reverse('api-v2:extension-detail',
                           kwargs={'pk': self.extension.pk})
        self.url2 = reverse('api-v2:extension-detail',
                            kwargs={'pk': self.extension2.pk})

    def test_has_cors(self):
        self.assertCORS(
            self.anon.get(self.list_url),
            'get', 'patch', 'put', 'post', 'delete')
        self.assertCORS(
            self.anon.get(self.url),
            'get', 'patch', 'put', 'post', 'delete')

    def test_list_anonymous(self):
        response = self.anon.get(self.list_url)
        eq_(response.status_code, 403)

    def test_list_logged_in(self):
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        meta = response.json['meta']
        eq_(meta['total_count'], 1)
        eq_(len(response.json['objects']), 1)
        data = response.json['objects'][0]
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        eq_(data['last_updated'], None)  # The extension is not public yet.
        eq_(data['latest_version']['download_url'],
            self.version.download_url)
        eq_(data['latest_version']['unsigned_download_url'],
            self.version.unsigned_download_url)
        eq_(data['latest_version']['version'], self.version.version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'pending')

    def test_detail_anonymous(self):
        response = self.anon.get(self.url)
        eq_(response.status_code, 403)

        self.version.update(status=STATUS_PUBLIC)
        self.extension.update(last_updated=datetime.now())
        response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        self.assertCloseToNow(data['last_updated'])
        eq_(data['latest_version']['download_url'],
            self.version.download_url)
        eq_(data['latest_version']['size'], self.version.size)
        eq_(data['latest_version']['unsigned_download_url'],
            self.version.unsigned_download_url)
        eq_(data['latest_version']['version'], self.version.version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'public')

    def test_detail_anonymous_disabled(self):
        self.version.update(status=STATUS_PUBLIC)
        self.extension.update(disabled=True)
        response = self.anon.get(self.url)
        eq_(response.status_code, 403)

    def test_detail_with_slug(self):
        self.url = reverse('api-v2:extension-detail',
                           kwargs={'pk': self.extension.slug})
        self.test_detail_anonymous()

    def test_detail_logged_in(self):
        response = self.client.get(self.url2)
        eq_(response.status_code, 403)

        # user is the owner, he can access the extension even if it's not
        # public.
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        eq_(data['last_updated'], None)  # The extension is not public yet.
        eq_(data['latest_version']['download_url'],
            self.version.download_url)
        eq_(data['latest_version']['size'], self.version.size)
        eq_(data['latest_version']['unsigned_download_url'],
            self.version.unsigned_download_url)
        eq_(data['latest_version']['version'], self.version.version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'pending')

        # Even works if disabled.
        self.extension.update(disabled=True)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.extension.id)
        eq_(data['disabled'], True)


class TestExtensionViewSetPatchPut(RestOAuth):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        super(TestExtensionViewSetPatchPut, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=999)
        self.extension = Extension.objects.create(
            name=u'Mŷ Extension', description=u'Mÿ Extension Description',
            slug=u'mŷ-extension')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, size=4343, status=STATUS_PUBLIC,
            version='0.43')
        self.url = reverse('api-v2:extension-detail',
                           kwargs={'pk': self.extension.pk})

    def test_put(self):
        self.extension.authors.add(self.user)
        response = self.client.put(self.url, json.dumps({'slug': 'lol'}))
        eq_(response.status_code, 405)

    def test_patch_without_rights(self):
        response = self.anon.patch(self.url, json.dumps({'slug': 'lol'}))
        eq_(response.status_code, 403)
        response = self.client.patch(self.url, json.dumps({'slug': 'lol'}))
        eq_(response.status_code, 403)
        eq_(self.extension.reload().slug, u'mŷ-extension')

    def test_patch_with_rights(self):
        self.extension.authors.add(self.user)
        response = self.client.patch(self.url, json.dumps({
            'slug': u'lolé', 'disabled': True}))
        eq_(response.status_code, 200)
        eq_(response.json['slug'], u'lolé')
        eq_(response.json['disabled'], True)
        self.extension.reload()
        eq_(self.extension.disabled, True)
        eq_(self.extension.slug, u'lolé')


class TestExtensionSearchView(RestOAuth, ESTestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.last_updated_date = datetime.now()
        self.extension = Extension.objects.create(
            name=u'Mŷ Extension', description=u'Mÿ Extension Description',
            last_updated=self.last_updated_date)
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, size=333, status=STATUS_PUBLIC,
            version='1.0.0')
        self.url = reverse('api-v2:extension-search')
        super(TestExtensionSearchView, self).setUp()
        self.refresh('extension')

    def tearDown(self):
        Extension.get_indexer().unindexer(_all=True)
        super(TestExtensionSearchView, self).tearDown()

    def test_verbs(self):
        self._allowed_verbs(self.url, ['get'])

    def test_has_cors(self):
        self.assertCORS(self.anon.get(self.url), 'get')

    def test_basic(self):
        with self.assertNumQueries(0):
            response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)
        data = response.json['objects'][0]
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        self.assertCloseToNow(data['last_updated'], now=self.last_updated_date)
        eq_(data['latest_public_version']['download_url'],
            self.version.download_url)
        eq_(data['latest_public_version']['size'], self.version.size)
        eq_(data['latest_public_version']['unsigned_download_url'],
            self.version.unsigned_download_url)
        eq_(data['latest_public_version']['version'], self.version.version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'public')

    def test_list(self):
        self.extension2 = Extension.objects.create(name=u'Mŷ Second Extension')
        self.version2 = ExtensionVersion.objects.create(
            extension=self.extension2, status=STATUS_PUBLIC, version='a.b.c')
        self.refresh('extension')
        with self.assertNumQueries(0):
            response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 2)

    def test_not_public(self):
        self.extension.update(status=STATUS_PENDING)
        self.refresh('extension')
        with self.assertNumQueries(0):
            response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 0)

    def test_disabled(self):
        self.extension.update(disabled=True)
        self.refresh('extension')
        with self.assertNumQueries(0):
            response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 0)


class TestReviewersExtensionViewSetGet(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestReviewersExtensionViewSetGet, self).setUp()
        self.list_url = reverse('api-v2:extension-queue-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.extension = Extension.objects.create(
            name=u'Än Extension', description=u'Än Extension Description')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, size=999, status=STATUS_PENDING,
            version='48.1516.2342')
        another_extension = Extension.objects.create(
            name=u'Anothër Extension', description=u'Anothër Description')
        ExtensionVersion.objects.create(
            extension=another_extension, size=888, status=STATUS_PUBLIC,
            version='0.1')
        self.url = reverse('api-v2:extension-queue-detail',
                           kwargs={'pk': self.extension.pk})

    def test_has_cors(self):
        self.assertCORS(self.anon.get(self.list_url), 'get', 'post')
        self.assertCORS(self.anon.get(self.url), 'get', 'post')

    def test_list_anonymous(self):
        response = self.anon.get(self.list_url)
        eq_(response.status_code, 403)

    def test_list_logged_in_no_rights(self):
        response = self.client.get(self.list_url)
        eq_(response.status_code, 403)

    def test_list_logged_in_with_rights_status(self):
        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)

    def test_list_logged_in_with_rights_disabled(self):
        self.grant_permission(self.user, 'Extensions:Review')
        # Disabled extensions do not show up in the review queue.
        self.extension.update(disabled=True)
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 0)

    def test_list_logged_in_with_rights(self):
        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        data = response.json['objects'][0]
        expected_data_version = {
            'id': self.version.pk,
            'download_url': self.version.download_url,
            'size': 999,
            'status': 'pending',
            'unsigned_download_url': self.version.unsigned_download_url,
            'version': self.version.version
        }
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        eq_(data['last_updated'], None)  # The extension is not public yet.
        eq_(data['latest_public_version'], None)
        eq_(data['latest_version'], expected_data_version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'pending')

    def test_detail_anonymous(self):
        response = self.anon.get(self.url)
        eq_(response.status_code, 403)

    def test_detail_logged_in_no_rights(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 403)

    def test_detail_logged_in_with_rights_status_public(self):
        self.version.update(status=STATUS_PUBLIC)
        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.url)
        eq_(response.status_code, 404)

    def test_detail_logged_in_with_rights(self):
        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        expected_data_version = {
            'id': self.version.pk,
            'download_url': self.version.download_url,
            'size': 999,
            'status': 'pending',
            'unsigned_download_url': self.version.unsigned_download_url,
            'version': self.version.version
        }
        eq_(data['id'], self.extension.id)
        eq_(data['description'], {'en-US': self.extension.description})
        eq_(data['disabled'], False)
        eq_(data['last_updated'], None)  # The extension is not public yet.
        eq_(data['latest_public_version'], None)
        eq_(data['latest_version'], expected_data_version)
        eq_(data['mini_manifest_url'], self.extension.mini_manifest_url)
        eq_(data['name'], {'en-US': self.extension.name})
        eq_(data['slug'], self.extension.slug)
        eq_(data['status'], 'pending')

    def test_detail_with_slug(self):
        self.url = reverse('api-v2:extension-queue-detail',
                           kwargs={'pk': self.extension.slug})
        self.test_detail_logged_in_with_rights()


class TestExtensionVersionViewSetGet(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestExtensionVersionViewSetGet, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.extension = Extension.objects.create(name=u'Än Extension')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, status=STATUS_PENDING,
            version='4815.1623.42')
        self.list_url = reverse('api-v2:extension-version-list', kwargs={
            'extension_pk': self.extension.pk})
        self.url = reverse('api-v2:extension-version-detail', kwargs={
            'extension_pk': self.extension.pk, 'pk': self.version.pk})

    def test_has_cors(self):
        self.assertCORS(self.anon.options(self.list_url),
                        'get', 'patch', 'put', 'post', 'delete')
        self.assertCORS(self.anon.options(self.url),
                        'get', 'patch', 'put', 'post', 'delete')

    def test_get_non_existing_extension(self):
        self.extension.authors.add(self.user)
        self.list_url = reverse('api-v2:extension-version-list', kwargs={
            'extension_pk': self.extension.pk + 42})
        self.url = reverse('api-v2:extension-version-detail', kwargs={
            'extension_pk': self.extension.pk + 42, 'pk': self.version.pk})
        self.url2 = reverse('api-v2:extension-version-detail', kwargs={
            'extension_pk': self.extension.pk, 'pk': self.version.pk + 42})
        response = self.client.get(self.list_url)
        eq_(response.status_code, 404)
        response = self.client.get(self.url)
        eq_(response.status_code, 404)
        response = self.client.get(self.url2)
        eq_(response.status_code, 404)

    def test_detail_anonymous(self):
        response = self.anon.get(self.url)
        eq_(response.status_code, 403)
        self.version.update(status=STATUS_PUBLIC)
        response = self.anon.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'public')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_detail_anonymous_disabled(self):
        self.version.update(status=STATUS_PUBLIC)
        self.extension.update(disabled=True)
        response = self.anon.get(self.url)
        eq_(response.status_code, 403)

    def test_detail_logged_in_no_rights(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 403)
        self.version.update(status=STATUS_PUBLIC)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'public')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_list_anonymous(self):
        response = self.anon.get(self.list_url)
        eq_(response.status_code, 403)
        self.version.update(status=STATUS_PUBLIC)
        response = self.anon.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)
        data = response.json['objects'][0]
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'public')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_list_no_rights(self):
        response = self.client.get(self.list_url)
        eq_(response.status_code, 403)
        self.version.update(status=STATUS_PUBLIC)
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)
        data = response.json['objects'][0]
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'public')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_list_owner(self):
        self.extension.authors.add(self.user)
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)
        data = response.json['objects'][0]
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'pending')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_list_owner_disabled(self):
        self.extension.authors.add(self.user)
        self.extension.update(disabled=True)
        response = self.client.get(self.list_url)
        eq_(response.status_code, 200)
        eq_(len(response.json['objects']), 1)

    def test_detail_owner_disabled(self):
        self.extension.authors.add(self.user)
        self.extension.update(disabled=True)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.version.pk)

    def test_detail_owner(self):
        self.extension.authors.add(self.user)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.version.pk)
        eq_(data['download_url'], self.version.download_url)
        eq_(data['status'], 'pending')
        eq_(data['unsigned_download_url'], self.version.unsigned_download_url)
        eq_(data['version'], self.version.version)

    def test_detail_owner_obsolete(self):
        self.version.update(status=STATUS_OBSOLETE)
        self.extension.authors.add(self.user)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        data = response.json
        eq_(data['id'], self.version.pk)
        eq_(data['status'], 'obsolete')


class TestExtensionVersionViewSetPost(UploadTest, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestExtensionVersionViewSetPost, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.extension = Extension.objects.create(name=u'Än Extension')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, status=STATUS_PENDING,
            version='0.0')
        self.list_url = reverse('api-v2:extension-version-list', kwargs={
            'extension_pk': self.extension.pk})
        self.publish_url = reverse('api-v2:extension-version-publish', kwargs={
            'extension_pk': self.extension.pk, 'pk': self.version.pk})
        self.reject_url = reverse('api-v2:extension-version-reject', kwargs={
            'extension_pk': self.extension.pk, 'pk': self.version.pk})

    def tearDown(self):
        super(TestExtensionVersionViewSetPost, self).tearDown()
        # Explicitely delete the Extensions to clean up leftover files.
        Extension.objects.all().delete()

    def test_has_cors(self):
        self.assertCORS(self.anon.options(self.publish_url), 'post')
        self.assertCORS(self.anon.options(self.reject_url), 'post')

    def test_post_anonymous(self):
        response = self.anon.post(self.publish_url)
        eq_(response.status_code, 403)
        response = self.anon.post(self.reject_url)
        eq_(response.status_code, 403)
        response = self.anon.post(self.list_url)
        eq_(response.status_code, 403)

    def test_post_logged_in_no_rights(self):
        response = self.client.post(self.publish_url)
        eq_(response.status_code, 403)
        response = self.client.post(self.reject_url)
        eq_(response.status_code, 403)
        response = self.client.post(self.list_url)
        eq_(response.status_code, 403)

    def test_post_non_existing_extension(self):
        self.grant_permission(self.user, 'Extensions:Review')
        self.list_url = reverse('api-v2:extension-version-list', kwargs={
            'extension_pk': self.extension.pk + 42})
        self.publish_url = reverse('api-v2:extension-version-publish', kwargs={
            'extension_pk': self.extension.pk + 42, 'pk': self.version.pk})
        self.reject_url = reverse('api-v2:extension-version-reject', kwargs={
            'extension_pk': self.extension.pk + 42, 'pk': self.version.pk})
        self.publish_url2 = reverse(
            'api-v2:extension-version-publish',
            kwargs={'extension_pk': self.extension.pk,
                    'pk': self.version.pk + 42})
        self.reject_url2 = reverse('api-v2:extension-version-reject', kwargs={
            'extension_pk': self.extension.pk, 'pk': self.version.pk + 42})
        response = self.client.post(self.list_url)
        eq_(response.status_code, 404)
        response = self.client.post(self.publish_url)
        eq_(response.status_code, 404)
        response = self.client.post(self.reject_url)
        eq_(response.status_code, 404)
        response = self.client.post(self.publish_url2)
        eq_(response.status_code, 404)
        response = self.client.post(self.reject_url2)
        eq_(response.status_code, 404)

    def test_post_logged_in_with_rights(self):
        self.extension.authors.add(self.user)
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=self.user)
        eq_(upload.valid, True)
        response = self.client.post(self.list_url,
                                    json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 201)
        data = response.json
        eq_(data['size'], 319)  # extension.zip size in bytes.
        eq_(data['status'], 'pending')
        eq_(data['version'], '0.1')
        eq_(Extension.objects.count(), 1)
        eq_(ExtensionVersion.objects.count(), 2)
        self.extension.reload()
        new_version = ExtensionVersion.objects.get(pk=data['id'])
        eq_(self.extension.status, STATUS_PENDING)
        eq_(self.extension.latest_version, new_version)

    def test_post_logged_in_with_rights_disabled(self):
        self.extension.authors.add(self.user)
        self.extension.update(disabled=True)
        upload = self.get_upload(
            abspath=self.packaged_app_path('extension.zip'), user=self.user)
        eq_(upload.valid, True)
        response = self.client.post(self.list_url,
                                    json.dumps({'validation_id': upload.pk}))
        eq_(response.status_code, 403)

    @mock.patch('mkt.extensions.models.ExtensionVersion.sign_and_move_file')
    def test_publish_disabled(self, sign_and_move_file_mock):
        self.grant_permission(self.user, 'Extensions:Review')
        self.extension.update(disabled=True)
        response = self.client.post(self.publish_url)
        eq_(response.status_code, 403)
        ok_(not sign_and_move_file_mock.called)

    @mock.patch('mkt.extensions.models.ExtensionVersion.sign_and_move_file')
    def test_publish(self, sign_and_move_file_mock):
        self.grant_permission(self.user, 'Extensions:Review')
        sign_and_move_file_mock.return_value = 665
        response = self.client.post(self.publish_url)
        eq_(response.status_code, 202)
        eq_(sign_and_move_file_mock.call_count, 1)
        self.extension.reload()
        self.version.reload()
        eq_(self.extension.status, STATUS_PUBLIC)
        eq_(self.version.size, 665)
        eq_(self.version.status, STATUS_PUBLIC)

        eq_(self.version.threads.get().notes.get().note_type, comm.APPROVAL)

    @mock.patch('mkt.extensions.models.ExtensionVersion.remove_signed_file')
    def test_reject_disabled(self, remove_signed_file_mock):
        self.grant_permission(self.user, 'Extensions:Review')
        self.extension.update(disabled=True)
        response = self.client.post(self.reject_url)
        eq_(response.status_code, 403)
        ok_(not remove_signed_file_mock.called)

    @mock.patch('mkt.extensions.models.ExtensionVersion.remove_signed_file')
    def test_reject(self, remove_signed_file_mock):
        self.grant_permission(self.user, 'Extensions:Review')
        remove_signed_file_mock.return_value = 666
        response = self.client.post(self.reject_url)
        eq_(response.status_code, 202)
        eq_(remove_signed_file_mock.call_count, 1)
        self.extension.reload()
        self.version.reload()
        eq_(self.version.size, 666)
        eq_(self.version.status, STATUS_REJECTED)
        # Now that the Extension has no pending or public version left, it's
        # back to incomplete.
        eq_(self.extension.status, STATUS_NULL)

        eq_(self.version.threads.get().notes.get().note_type, comm.REJECTION)


class TestExtensionVersionViewSetDelete(RestOAuth):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        super(TestExtensionVersionViewSetDelete, self).setUp()
        self.extension = Extension.objects.create(name=u'Än Extension')
        self.public_version = ExtensionVersion.objects.create(
            extension=self.extension, status=STATUS_PUBLIC,
            version='0.42')
        self.pending_version = ExtensionVersion.objects.create(
            extension=self.extension, status=STATUS_PENDING,
            version='0.43')
        self.other_extension = Extension.objects.create()
        self.other_version = ExtensionVersion.objects.create(
            extension=self.other_extension)
        self.user = UserProfile.objects.get(pk=2519)
        self.other_user = UserProfile.objects.get(pk=999)
        self.detail_url_public = reverse(
            'api-v2:extension-version-detail', kwargs={
                'extension_pk': self.extension.pk,
                'pk': self.public_version.pk})

    def test_delete_latest_public_version_logged_in_has_rights(self):
        eq_(ExtensionVersion.objects.count(), 3)
        self.extension.authors.add(self.user)
        response = self.client.delete(self.detail_url_public)
        eq_(response.status_code, 204)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 2)
        ok_(not ExtensionVersion.objects.filter(
            pk=self.public_version.pk).exists())
        ok_(ExtensionVersion.objects.filter(
            pk=self.pending_version.pk).exists())
        ok_(ExtensionVersion.objects.filter(
            pk=self.other_version.pk).exists())
        self.extension.reload()
        eq_(self.extension.status, STATUS_PENDING)

    def test_delete_latest_pending_version_logged_in_has_rights(self):
        self.detail_url_pending = reverse(
            'api-v2:extension-version-detail', kwargs={
                'extension_pk': self.extension.pk,
                'pk': self.pending_version.pk})

        eq_(ExtensionVersion.objects.count(), 3)
        self.extension.authors.add(self.user)
        response = self.client.delete(self.detail_url_pending)
        eq_(response.status_code, 204)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 2)
        ok_(ExtensionVersion.objects.filter(
            pk=self.public_version.pk).exists())
        ok_(not ExtensionVersion.objects.filter(
            pk=self.pending_version.pk).exists())
        ok_(ExtensionVersion.objects.filter(
            pk=self.other_version.pk).exists())
        self.extension.reload()
        eq_(self.extension.status, STATUS_PUBLIC)

    def test_delete_both_versions_logged_in_has_rights(self):
        self.detail_url_pending = reverse(
            'api-v2:extension-version-detail', kwargs={
                'extension_pk': self.extension.pk,
                'pk': self.pending_version.pk})

        eq_(ExtensionVersion.objects.count(), 3)
        self.extension.authors.add(self.user)
        response = self.client.delete(self.detail_url_pending)
        eq_(response.status_code, 204)
        response = self.client.delete(self.detail_url_public)
        eq_(response.status_code, 204)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 1)
        ok_(not ExtensionVersion.objects.filter(
            pk=self.public_version.pk).exists())
        ok_(not ExtensionVersion.objects.filter(
            pk=self.pending_version.pk).exists())
        ok_(ExtensionVersion.objects.filter(
            pk=self.other_version.pk).exists())
        self.extension.reload()
        eq_(self.extension.status, STATUS_NULL)

    def test_delete_logged_in_no_rights(self):
        self.extension.authors.add(self.other_user)
        response = self.client.delete(self.detail_url_public)
        eq_(response.status_code, 403)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 3)

    def test_delete_anonymous_no_rights(self):
        response = self.anon.delete(self.detail_url_public)
        eq_(response.status_code, 403)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 3)

    def test_delete__404(self):
        self.extension.authors.add(self.user)
        self.detail_url_public = reverse(
            'api-v2:extension-version-detail', kwargs={
                'extension_pk': self.extension.pk,
                'pk': self.public_version.pk + 555})
        response = self.client.delete(self.detail_url_public)
        eq_(response.status_code, 404)
        eq_(Extension.objects.count(), 2)
        eq_(ExtensionVersion.objects.count(), 3)


class TestExtensionNonAPIViews(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestExtensionNonAPIViews, self).setUp()
        self.fake_manifest = {
            'name': u'Fake Extënsion',
            'version': '0.1',
        }
        self.extension = Extension.objects.create(name=u'Fake Extënsion')
        self.version = ExtensionVersion.objects.create(
            extension=self.extension, manifest=self.fake_manifest,
            status=STATUS_PUBLIC, version='0.1')
        self.user = UserProfile.objects.get(pk=2519)
        self.extension.authors.add(self.user)

    def _expected_etag(self):
        expected_etag = hashlib.sha256()
        expected_etag.update(unicode(self.extension.guid))
        expected_etag.update(unicode(self.version.pk))
        return '"%s"' % expected_etag.hexdigest()

    @override_settings(
        XSENDFILE=True,
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.LocalFileStorage')
    def test_download_signed(self):
        ok_(self.version.download_url)
        response = self.client.get(self.version.download_url)

        eq_(response.status_code, 200)
        eq_(response[settings.XSENDFILE_HEADER],
            self.version.signed_file_path)
        eq_(response['Content-Type'], 'application/zip')
        eq_(response['ETag'], self._expected_etag())

        self.login(self.user)
        response = self.client.get(self.version.download_url)
        eq_(response.status_code, 200)

    @override_settings(
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.S3BotoPrivateStorage')
    @mock.patch('mkt.site.utils.public_storage')
    def test_download_signed_storage(self, public_storage_mock):
        expected_path = 'https://s3.pub/%s' % self.version.signed_file_path
        public_storage_mock.url = lambda path: 'https://s3.pub/%s' % path
        ok_(self.version.download_url)
        response = self.client.get(self.version.download_url)
        self.assert3xx(response, expected_path)

    def test_download_signed_not_public(self):
        self.version.update(status=STATUS_PENDING)
        ok_(self.version.download_url)
        response = self.client.get(self.version.download_url)
        eq_(response.status_code, 404)

        self.login(self.user)
        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.version.download_url)
        # Even authors and reviewers can't access it: it doesn't exist.
        eq_(response.status_code, 404)

    @override_settings(
        XSENDFILE=True,
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.LocalFileStorage')
    def test_download_unsigned(self):
        ok_(self.version.unsigned_download_url)
        response = self.client.get(self.version.unsigned_download_url)
        eq_(response.status_code, 403)

        self.login(self.user)  # Log in as author.
        response = self.client.get(self.version.unsigned_download_url)
        eq_(response.status_code, 200)

        eq_(response[settings.XSENDFILE_HEADER],
            self.version.file_path)
        eq_(response['Content-Type'], 'application/zip')
        eq_(response['ETag'], self._expected_etag())

    @override_settings(
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.S3BotoPrivateStorage')
    @mock.patch('mkt.site.utils.private_storage')
    def test_download_unsigned_storage(self, private_storage_mock):
        expected_path = 'https://s3.private/%s' % self.version.file_path
        private_storage_mock.url = lambda path: 'https://s3.private/%s' % path
        self.login(self.user)  # Log in as author.
        ok_(self.version.unsigned_download_url)
        response = self.client.get(self.version.unsigned_download_url)
        self.assert3xx(response, expected_path)

    @override_settings(
        XSENDFILE=True,
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.LocalFileStorage')
    def test_download_unsigned_reviewer(self):
        ok_(self.version.unsigned_download_url)
        self.extension.authors.remove(self.user)
        self.login(self.user)
        response = self.client.get(self.version.unsigned_download_url)
        eq_(response.status_code, 403)

        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.version.unsigned_download_url)
        eq_(response.status_code, 200)

        eq_(response[settings.XSENDFILE_HEADER],
            self.version.file_path)
        eq_(response['Content-Type'], 'application/zip')
        eq_(response['ETag'], self._expected_etag())

    @override_settings(
        DEFAULT_FILE_STORAGE='mkt.site.storage_utils.S3BotoPrivateStorage')
    @mock.patch('mkt.site.utils.private_storage')
    def test_download_unsigned_reviewer_storage(self, private_storage_mock):
        expected_path = 'https://s3.private/%s' % self.version.file_path
        private_storage_mock.url = lambda path: 'https://s3.private/%s' % path

        ok_(self.version.unsigned_download_url)
        self.extension.authors.remove(self.user)
        self.login(self.user)
        response = self.client.get(self.version.unsigned_download_url)
        eq_(response.status_code, 403)

        self.grant_permission(self.user, 'Extensions:Review')
        response = self.client.get(self.version.unsigned_download_url)
        self.assert3xx(response, expected_path)

    def test_manifest(self):
        ok_(self.extension.mini_manifest_url)
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 200)
        eq_(response['Content-Type'], MANIFEST_CONTENT_TYPE)
        eq_(json.loads(response.content), self.extension.mini_manifest)

    def test_manifest_etag(self):
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 200)
        original_etag = response['ETag']
        ok_(original_etag)

        # Test that the etag is the same if we just re-save the extension
        # or the version without changing the manifest.
        self.extension.save()
        self.version.save()
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 200)
        eq_(original_etag, response['ETag'])

        # Test that the etag is different if the version manifest changes.
        self.version.manifest['version'] = '9001'
        self.version.save()
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 200)
        ok_(original_etag != response['ETag'])

    def test_manifest_not_public(self):
        self.extension.update(status=STATUS_PENDING)
        # `mini_manifest_url` exists but is a 404 when the extension is not
        # public.
        ok_(self.extension.mini_manifest_url)
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 404)

        self.login(self.user)  # Even logged in you can't access it for now.
        response = self.client.get(self.extension.mini_manifest_url)
        eq_(response.status_code, 404)
