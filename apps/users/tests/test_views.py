import collections
import json

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.forms.models import model_to_dict
from django.utils.http import urlsafe_base64_encode

import waffle
from mock import patch
from nose import SkipTest
from nose.tools import eq_
from waffle import helpers  # NOQA

import amo
import amo.tests
import users.notifications as email
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import Addon, AddonPremium, AddonUser
from amo.helpers import urlparams
from amo.pyquery_wrapper import PyQuery as pq
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from market.models import Price
from users.models import BlacklistedPassword, UserNotification, UserProfile
from users.utils import EmailResetCode, UnsubscribeCode


def check_sidebar_links(self, expected):
    r = self.client.get(self.url)
    eq_(r.status_code, 200)
    links = pq(r.content)('#secondary-nav ul a')
    amo.tests.check_links(expected, links)
    eq_(links.filter('.selected').attr('href'), self.url)


class UserViewBase(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = amo.tests.TestClient()
        self.client.get('/')
        self.user = UserProfile.objects.get(id='4043307')

    def get_profile(self):
        return UserProfile.objects.get(id=self.user.id)


class TestAjax(UserViewBase):

    def setUp(self):
        super(TestAjax, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='foo')

    def test_ajax_404(self):
        r = self.client.get(reverse('users.ajax'), follow=True)
        eq_(r.status_code, 404)

    def test_ajax_success(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'fligtar@gmail.com'},
                            follow=True)
        data = json.loads(r.content)
        eq_(data, {'status': 1, 'message': '', 'id': 9945,
                   'name': u'Justin Scott \u0627\u0644\u062a\u0637\u0628'})

    def test_ajax_xss(self):
        self.user.display_name = '<script>alert("xss")</script>'
        self.user.save()
        assert '<script>' in self.user.display_name, (
            'Expected <script> to be in display name')
        r = self.client.get(reverse('users.ajax'),
                            {'q': self.user.email, 'dev': 0})
        assert '<script>' not in r.content
        assert '&lt;script&gt;' in r.content

    def test_ajax_failure_incorrect_email_mkt(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'incorrect'},
                            follow=True)
        data = json.loads(r.content)
        eq_(data,
            {'status': 0,
             'message': 'A user with that email address does not exist, or the'
                        ' user has not yet accepted the developer agreement.'})

    def test_ajax_failure_no_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': ''}, follow=True)
        data = json.loads(r.content)
        eq_(data,
            {'status': 0,
             'message': 'An email address is required.'})

    def test_forbidden(self):
        self.client.logout()
        r = self.client.get(reverse('users.ajax'))
        eq_(r.status_code, 401)


class TestEdit(UserViewBase):

    def setUp(self):
        super(TestEdit, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.user = UserProfile.objects.get(username='jbalogh')
        self.url = reverse('users.edit')
        self.data = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                     'oldpassword': 'foo', 'password': 'longenough',
                     'password2': 'longenough'}

    def test_password_logs(self):
        res = self.client.post(self.url, self.data)
        eq_(res.status_code, 302)
        eq_(self.user.userlog_set
                .filter(activity_log__action=amo.LOG.CHANGE_PASSWORD.id)
                .count(), 1)

    def test_password_empty(self):
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        homepage = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                    'homepage': 'http://cbc.ca'}
        res = self.client.post(self.url, homepage)
        eq_(res.status_code, 302)

    def test_password_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        bad = self.data.copy()
        bad['password'] = 'password'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'That password is not allowed.'])

    def test_password_short(self):
        bad = self.data.copy()
        bad['password'] = 'short'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'Must be 8 characters or more.'])

    def test_email_change_mail_sent(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, 'An email has been sent to %s' % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = UserProfile.objects.get(id='4043307')
        self.assertEquals(u.name, 'DJ SurfNTurf')
        self.assertEquals(u.email, 'jbalogh@mozilla.com')

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject.find('Please confirm your email'), 0)
        assert mail.outbox[0].body.find('%s/emailchange/' % self.user.id) > 0

    @patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_email_change_mail_send_even_with_fake_email(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf'}

        self.client.post(self.url, data, follow=True)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject.find('Please confirm your email'), 0)

    @patch.object(settings, 'APP_PREVIEW', True)
    def test_email_cant_change(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf', }

        res = self.client.post(self.url, data, follow=True)
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('div.error')), 1)
        eq_(len(mail.outbox), 0)

    def test_edit_bio(self):
        eq_(self.get_profile().bio, None)

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'bio': 'xxx unst unst'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

        data['bio'] = 'yyy unst unst'
        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

    def check_default_choices(self, choices, checked=True):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('input[name=notifications]:checkbox').length, len(choices))
        for id, label in choices:
            box = doc('input[name=notifications][value=%s]' % id)
            if checked:
                eq_(box.filter(':checked').length, 1)
            else:
                eq_(box.length, 1)
            parent = box.parent('label')
            if checked:
                eq_(parent.find('.msg').length, 1)  # Check for "NEW" message.
            eq_(parent.remove('.msg, .req').text(), label)

    def post_notifications(self, choices):
        self.check_default_choices(choices)

        self.data['notifications'] = []
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url, 302)

        eq_(UserNotification.objects.count(), len(email.NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(),
            len(filter(lambda x: x.mandatory, email.NOTIFICATIONS)))
        self.check_default_choices(choices, checked=False)

    def test_edit_notifications(self):
        # Make jbalogh a developer.
        AddonUser.objects.create(user=self.user,
            addon=Addon.objects.create(type=amo.ADDON_EXTENSION))

        choices = email.NOTIFICATIONS_CHOICES
        self.check_default_choices(choices)

        self.data['notifications'] = [2, 4, 6]
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url, 302)

        mandatory = [n.id for n in email.NOTIFICATIONS if n.mandatory]
        total = len(self.data['notifications'] + mandatory)
        eq_(UserNotification.objects.count(), len(email.NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(), total)

        doc = pq(self.client.get(self.url, self.data).content)
        eq_(doc('input[name=notifications]:checked').length, total)

        eq_(doc('.more-none').length, len(email.NOTIFICATION_GROUPS))
        eq_(doc('.more-all').length, len(email.NOTIFICATION_GROUPS))

    def test_edit_notifications_non_dev(self):
        self.post_notifications(email.NOTIFICATIONS_CHOICES_NOT_DEV)

    def test_edit_notifications_non_dev_error(self):
        self.data['notifications'] = [2, 4, 6]
        r = self.client.post(self.url, self.data)
        assert r.context['form'].errors['notifications']

    def test_remove_locale_bad_request(self):
        r = self.client.post(self.user.get_user_url('remove-locale'))
        eq_(r.status_code, 400)

    @patch.object(UserProfile, 'remove_locale')
    def test_remove_locale(self, remove_locale_mock):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': 'el'})
        eq_(r.status_code, 200)
        remove_locale_mock.assert_called_with('el')

    def test_remove_locale_default_locale(self):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': settings.LANGUAGE_CODE})
        eq_(r.status_code, 400)


class TestEditAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.regular = self.get_user()
        self.url = reverse('users.admin_edit', args=[self.regular.pk])

    def get_data(self):
        data = model_to_dict(self.regular)
        data['admin_log'] = 'test'
        for key in ['password', 'resetcode_expires']:
            del data[key]
        return data

    def get_user(self):
        # Using pk so that we can still get the user after anonymize.
        return UserProfile.objects.get(pk=10482)

    def test_edit(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_edit_forbidden(self):
        self.client.logout()
        self.client.login(username='editor@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 403)

    def test_edit_forbidden_anon(self):
        self.client.logout()
        res = self.client.get(self.url)
        eq_(res.status_code, 302)

    def test_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        res = self.client.post(self.url, data)
        eq_(res.status_code, 302)
        eq_(self.get_user().password, "sha512$Anonymous$Password")

    def test_anonymize_fails(self):
        data = self.get_data()
        data['anonymize'] = True
        data['email'] = 'something@else.com'
        res = self.client.post(self.url, data)
        eq_(res.status_code, 200)
        eq_(self.get_user().password, self.regular.password)  # Hasn't changed.

    def test_admin_logs_edit(self):
        data = self.get_data()
        data['email'] = 'something@else.com'
        self.client.post(self.url, data)
        res = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(res.count(), 1)
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_logs_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        self.client.post(self.url, data)
        res = (ActivityLog.objects
                          .filter(action=amo.LOG.ADMIN_USER_ANONYMIZED.id))
        eq_(res.count(), 1)
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_no_password(self):
        data = self.get_data()
        data.update({'password': 'pass1234',
                     'password2': 'pass1234',
                     'oldpassword': 'password'})
        self.client.post(self.url, data)
        logs = ActivityLog.objects.filter
        eq_(logs(action=amo.LOG.CHANGE_PASSWORD.id).count(), 0)
        res = logs(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(res.count(), 1)
        eq_(res[0].details['password'][0], u'****')


FakeResponse = collections.namedtuple("FakeResponse", "status_code content")


class TestPasswordAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='editor@mozilla.com', password='password')
        self.url = reverse('users.edit')
        self.correct = {'username': 'editor',
                        'email': 'editor@mozilla.com',
                        'oldpassword': 'password', 'password': 'longenough',
                        'password2': 'longenough'}

    def test_password_admin(self):
        res = self.client.post(self.url, self.correct, follow=False)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'Letters and numbers required.'])

    def test_password(self):
        UserProfile.objects.get(username='editor').groups.all().delete()
        res = self.client.post(self.url, self.correct, follow=False)
        eq_(res.status_code, 302)


class TestEmailChange(UserViewBase):

    def setUp(self):
        super(TestEmailChange, self).setUp()
        self.token, self.hash = EmailResetCode.create(self.user.id,
                                                      'nobody@mozilla.org')

    def test_fail(self):
        # Completely invalid user, valid code
        url = reverse('users.emailchange', args=[1234, self.token, self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 404)

        # User is in the system, but not attached to this code, valid code
        url = reverse('users.emailchange', args=[9945, self.token, self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)

        # Valid user, invalid code
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash[:-3]])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)

    def test_success(self):
        self.assertEqual(self.user.email, 'jbalogh@mozilla.com')
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)
        u = UserProfile.objects.get(id=self.user.id)
        self.assertEqual(u.email, 'nobody@mozilla.org')


class TestLogin(UserViewBase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def setUp(self):
        super(TestLogin, self).setUp()
        self.url = reverse('users.login')
        self.data = {'username': 'jbalogh@mozilla.com', 'password': 'foo'}

    def test_client_login(self):
        """
        This is just here to make sure Test Client's login() works with
        our custom code.
        """
        assert not self.client.login(username='jbalogh@mozilla.com',
                                     password='wrong')
        assert self.client.login(**self.data)

    def test_double_login(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        # If you go to the login page when you're already logged in we bounce
        # you.
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

    def test_ok_redirects(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        r = self.client.get(self.url + '?to=/de/firefox/', follow=True)
        self.assertRedirects(r, '/de/firefox/')

    def test_bad_redirects(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        for redirect in ['http://xx.com',
                         'data:text/html,<script>window.alert("xss")</script>',
                         'mailto:test@example.com',
                         'file:///etc/passwd',
                         'javascript:window.alert("xss");']:
            self.assertRedirects(r, '/en-US/firefox/')

    def test_login_link(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#aux-nav li.login').length, 1)

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#aux-nav li.logout').length, 1)

    @amo.tests.mobile_test
    def test_mobile_login(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('header')
        eq_(doc('nav').length, 1)
        eq_(doc('#home').length, 1)
        eq_(doc('#auth-nav li.login').length, 0)

    @amo.tests.mobile_test
    @patch.object(settings, 'APP_PREVIEW', True)
    def test_mobile_login_apps_preview(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('header')
        eq_(doc('nav').length, 1)
        eq_(doc('#home').length, 0)
        eq_(doc('#auth-nav li.login').length, 0)

    def test_login_ajax(self):
        url = reverse('users.login_modal')
        r = self.client.get(url)
        eq_(r.status_code, 200)

        res = self.client.post(url, data=self.data)
        eq_(res.status_code, 302)

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    def test_login_paypal(self):
        raise SkipTest
        addon = Addon.objects.all()[0]
        price = Price.objects.create(price='0.99')
        AddonPremium.objects.create(addon=addon, price=price)
        addon.update(premium_type=amo.ADDON_PREMIUM)

        url = reverse('addons.purchase.start', args=[addon.slug])
        r = self.client.get_ajax(url)
        eq_(r.status_code, 200)

        res = self.client.post_ajax(url, data=self.data)
        eq_(res.status_code, 200)

    def test_login_ajax_error(self):
        url = reverse('users.login_modal')
        data = self.data
        data['username'] = ''

        res = self.client.post(url, data=self.data)
        eq_(res.context['form'].errors['username'][0],
            'This field is required.')

    def test_login_ajax_wrong(self):
        url = reverse('users.login_modal')
        data = self.data
        data['username'] = 'jeffb@mozilla.com'

        res = self.client.post(url, data=self.data)
        text = 'Please enter a correct username and password.'
        assert res.context['form'].errors['__all__'][0].startswith(text)

    def test_login_no_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 302)

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    def test_login_attempts_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 200)
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    def test_login_shown_recaptcha(self):
        data = self.data.copy()
        data['recaptcha_shown'] = ''
        res = self.client.post(self.url, data=data)
        eq_(res.status_code, 200)
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_login_with_recaptcha(self, clean):
        clean.return_value = ''
        data = self.data.copy()
        data.update({'recaptcha': '', 'recaptcha_shown': ''})
        res = self.client.post(self.url, data=data)
        eq_(res.status_code, 302)

    def test_login_fails_increment(self):
        # It increments even when the form is wrong.
        user = UserProfile.objects.filter(email=self.data['username'])
        eq_(user.get().failed_login_attempts, 3)
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(user.get().failed_login_attempts, 4)

    def test_doubled_account(self):
        """
        Logging in to an account that shares a User object with another
        account works properly.
        """
        profile = UserProfile.objects.create(username='login_test',
                                             email='bob@example.com')
        profile.set_password('baz')
        profile.email = 'charlie@example.com'
        profile.save()
        profile2 = UserProfile.objects.create(username='login_test2',
                                              email='bob@example.com')
        profile2.set_password('foo')
        profile2.save()

        res = self.client.post(self.url,
                               data={'username': 'charlie@example.com',
                                     'password': 'wrong'})
        eq_(res.status_code, 200)
        eq_(UserProfile.objects.get(email='charlie@example.com')
            .failed_login_attempts, 1)
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'baz'})
        eq_(res2.status_code, 302)
        res3 = self.client.post(self.url,
                                data={'username': 'bob@example.com',
                                      'password': 'foo'})
        eq_(res3.status_code, 302)

    def test_changed_account(self):
        """
        Logging in to an account that had its email changed succeeds.
        """
        profile = UserProfile.objects.create(username='login_test',
                                             email='bob@example.com')
        profile.set_password('baz')
        profile.email = 'charlie@example.com'
        profile.save()

        res = self.client.post(self.url,
                               data={'username': 'charlie@example.com',
                                     'password': 'wrong'})
        eq_(res.status_code, 200)
        eq_(UserProfile.objects.get(email='charlie@example.com')
            .failed_login_attempts, 1)
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'baz'})
        eq_(res2.status_code, 302)


@patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', '')
@patch('users.models.UserProfile.log_login_attempt')
class TestFailedCount(UserViewBase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def setUp(self):
        super(TestFailedCount, self).setUp()
        self.url = reverse('users.login')
        self.data = {'username': 'jbalogh@mozilla.com', 'password': 'foo'}

    def log_calls(self, obj):
        return [call[0][0] for call in obj.call_args_list]

    def test_login_passes(self, log_login_attempt):
        self.client.post(self.url, data=self.data)
        eq_(self.log_calls(log_login_attempt), [True])

    def test_login_fails(self, log_login_attempt):
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_deleted(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(deleted=True))
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_confirmation(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(confirmationcode='123'))
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_get(self, log_login_attempt):
        self.client.get(self.url, data={'username': self.data['username']})
        eq_(log_login_attempt.called, False)

    def test_login_get_no_data(self, log_login_attempt):
        self.client.get(self.url)
        eq_(log_login_attempt.called, False)


class TestUnsubscribe(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

    def test_correct_url_update_notification(self):
        # Make sure the user is subscribed
        perm_setting = email.NOTIFICATIONS[0]
        un = UserNotification.objects.create(notification_id=perm_setting.id,
                                             user=self.user,
                                             enabled=True)

        # Create a URL
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        eq_(doc('#standalone ul li').length, 1)

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        eq_(un.count(), 1)
        eq_(un.all()[0].enabled, False)

    def test_correct_url_new_notification(self):
        # Make sure the user is subscribed
        assert not UserNotification.objects.count()

        # Create a URL
        perm_setting = email.NOTIFICATIONS[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        eq_(doc('#standalone ul li').length, 1)

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        eq_(un.count(), 1)
        eq_(un.all()[0].enabled, False)

    def test_wrong_url(self):
        perm_setting = email.NOTIFICATIONS[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        hash = hash[::-1]  # Reverse the hash, so it's wrong

        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])
        r = self.client.get(url)
        doc = pq(r.content)

        eq_(doc('#unsubscribe-fail').length, 1)


class TestReset(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        user = UserProfile.objects.get(email='editor@mozilla.com').get_profile()
        self.token = [urlsafe_base64_encode(str(user.id)),
                      default_token_generator.make_token(user)]

    def test_reset_msg(self):
        res = self.client.get(reverse('users.pwreset_confirm',
                                       args=self.token))
        assert 'For your account' in res.content

    def test_reset_fails(self):
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'spassword',
                                     'new_password2': 'spassword'})
        eq_(res.context['form'].errors['new_password1'][0],
            'Letters and numbers required.')


class TestLogout(UserViewBase):

    def test_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.login(username=user.email, password='foo')
        r = self.client.get('/', follow=True)
        eq_(pq(r.content.decode('utf-8'))('.account .user').text(),
            user.display_name)
        eq_(pq(r.content)('.account .user').attr('title'), user.email)

        r = self.client.get('/users/logout', follow=True)
        assert not pq(r.content)('.account .user')

    def test_redirect(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.client.get('/', follow=True)
        url = '/en-US/about'
        r = self.client.get(urlparams(reverse('users.logout'), to=url),
                            follow=True)
        self.assertRedirects(r, url, status_code=302)

        # Test a valid domain.  Note that assertRedirects doesn't work on
        # external domains
        url = urlparams(reverse('users.logout'), to='/addon/new',
                        domain='builder')
        r = self.client.get(url, follow=True)
        to, code = r.redirect_chain[0]
        self.assertEqual(to, 'https://builder.addons.mozilla.org/addon/new')
        self.assertEqual(code, 302)

        # Test an invalid domain
        url = urlparams(reverse('users.logout'), to='/en-US/about',
                        domain='http://evil.com')
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, '/en-US/about', status_code=302)


class TestRegistration(UserViewBase):

    def test_new_confirm(self):
        # User doesn't have a confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        is_anonymous = pq(r.content)('body').attr('data-anonymous')
        eq_(json.loads(is_anonymous), True)

        self.user.update(confirmationcode='code')

        # URL has the wrong confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'blah'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Invalid confirmation code!')

        # URL has the right confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Successfully verified!')

    def test_new_confirm_resend(self):
        # User doesn't have a confirmation code.
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)

        self.user.update(confirmationcode='code')

        # URL has the right confirmation code now.
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'An email has been sent to your address')


class TestProfileView(UserViewBase):

    def setUp(self):
        self.user = UserProfile.objects.create(homepage='http://example.com')
        self.url = reverse('users.profile', args=[self.user.id])

    def test_non_developer_homepage_url(self):
        """Don't display homepage url if the user is not a developer."""
        r = self.client.get(self.url)
        self.assertNotContains(r, self.user.homepage)

    @patch.object(UserProfile, 'is_developer', True)
    def test_developer_homepage_url(self):
        """Display homepage url for a developer user."""
        r = self.client.get(self.url)
        self.assertContains(r, self.user.homepage)


class TestProfileLinks(UserViewBase):
    fixtures = ['base/apps',
                'base/appversion',
                'base/featured',
                'users/test_backends']

    def test_edit_buttons(self):
        """Ensure admin/user edit buttons are shown."""

        def get_links(id):
            """Grab profile, return edit links."""
            url = reverse('users.profile', args=[id])
            r = self.client.get(url)
            return pq(r.content)('#profile-actions a')

        # Anonymous user.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.abuse',
                                              args=[self.user.id]))

        # Non-admin, someone else's profile.
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        links = get_links(9945)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.abuse', args=[9945]))

        # Non-admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))

        # Admin, someone else's profile.
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        cache.clear()

        # Admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 2)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))
        # TODO XXX Uncomment when we have real user editing pages
        #eq_(links.eq(1).attr('href') + "/",
        #reverse('admin:users_userprofile_change', args=[self.user.id]))

    def test_amouser(self):
        # request.amo_user should be a special guy.
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        response = self.client.get(reverse('home'))
        request = response.context['request']
        assert hasattr(request.amo_user, 'mobile_addons')
        assert hasattr(request.user, 'mobile_addons')
        assert hasattr(request.amo_user, 'favorite_addons')
        assert hasattr(request.user, 'favorite_addons')


class TestProfileSections(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5299_gcal', 'base/collections',
                'reviews/dev-reply']

    def setUp(self):
        self.user = UserProfile.objects.get(id=10482)
        self.url = reverse('users.profile', args=[self.user.id])

    def test_mine_anonymous(self):
        res = self.client.get('/user/me/', follow=True)
        eq_(res.status_code, 404)

    def test_mine_authenticated(self):
        self.login(self.user)
        res = self.client.get('/user/me/', follow=True)
        eq_(res.status_code, 200)
        eq_(res.context['user'].id, self.user.id)

    def test_my_last_login_anonymous(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.last-login-time').length, 0)
        eq_(doc('.last-login-ip').length, 0)

    def test_my_last_login_authenticated(self):
        self.user.update(last_login_ip='255.255.255.255')
        self.login(self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert doc('.last-login-time td').text()
        eq_(doc('.last-login-ip td').text(), '255.255.255.255')

    def test_not_my_last_login(self):
        res = self.client.get('/user/999/', follow=True)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.last-login-time').length, 0)
        eq_(doc('.last-login-ip').length, 0)

    def test_my_addons(self):
        eq_(pq(self.client.get(self.url).content)('.num-addons a').length, 0)

        AddonUser.objects.create(user=self.user, addon_id=3615)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        a = r.context['addons'].object_list
        eq_(list(a), sorted(a, key=lambda x: x.weekly_downloads, reverse=True))

        doc = pq(r.content)
        eq_(doc('.num-addons a[href="#my-submissions"]').length, 1)
        items = doc('#my-addons .item')
        eq_(items.length, 2)
        eq_(items('.install[data-addon=3615]').length, 1)
        eq_(items('.install[data-addon=5299]').length, 1)

    def test_user_abuse_form(self):
        abuse_url = reverse('users.abuse', args=[self.user.id])
        r = self.client.get(self.url)
        doc = pq(r.content)
        button = doc('#profile-actions #report-user-abuse')
        eq_(button.length, 1)
        eq_(button.attr('href'), abuse_url)
        modal = doc('#popup-staging #report-user-modal.modal')
        eq_(modal.length, 1)
        eq_(modal('form').attr('action'), abuse_url)
        eq_(modal('textarea[name=text]').length, 1)
        self.assertTemplateUsed(r, 'users/report_abuse.html')

    def test_no_self_abuse(self):
        self.client.login(username='clouserw@gmail.com', password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#profile-actions #report-user-abuse').length, 0)
        eq_(doc('#popup-staging #report-user-modal.modal').length, 0)
        self.assertTemplateNotUsed(r, 'users/report_abuse.html')


class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        settings.RECAPTCHA_PRIVATE_KEY = 'something'
        self.full_page = reverse('users.abuse', args=[10482])

    @patch('captcha.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        eq_(report.message, 'spammy')
        eq_(report.reporter, None)

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        eq_(report.message, 'spammy')
        eq_(report.reporter.email, 'regular@mozilla.com')

        r = self.client.get(self.full_page)
        eq_(pq(r.content)('.notification-box h2').length, 1)
