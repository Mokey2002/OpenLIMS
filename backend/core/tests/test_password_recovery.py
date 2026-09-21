from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient

from core.tasks import send_password_recovery
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


@override_settings(OPENLIMS_EMAIL_ENABLED=True, OPENLIMS_PUBLIC_URL='https://lims.example.org:8443',
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordRecoveryTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('scientist', 'person@example.org', 'Original-secret-184!')

    def test_same_response_and_queue_for_known_and_unknown(self):
        with patch('core.password_recovery.send_password_recovery.apply_async') as queue:
            known = self.client.post('/api/v1/auth/forgot-password/', {'email': self.user.email})
            unknown = self.client.post('/api/v1/auth/forgot-password/', {'email': 'unknown@example.org'})
        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(queue.call_count, 2)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Original-secret-184!'))

    def test_email_reset_and_reuse(self):
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        send_password_recovery('PERSON@example.org')
        self.assertEqual(len(mail.outbox), 1)
        link = next(line for line in mail.outbox[0].body.splitlines() if line.startswith('https://'))
        self.assertTrue(link.startswith('https://lims.example.org:8443/set-password#'))
        data = {key: values[0] for key, values in parse_qs(urlsplit(link).fragment).items()}
        data['password'] = 'Changed-secret-276!'
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertEqual(self.client.post('/api/v1/auth/set-password/', data).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/auth/set-password/', {**data, 'password': '123'}).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/auth/set-password/', data).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(data['password']))
        with self.assertRaises(AuthenticationFailed):
            JWTAuthentication().get_user(access)
        with self.assertRaises(TokenError):
            TokenRefreshSerializer(data={'refresh': str(refresh)}).is_valid(raise_exception=True)
        self.assertEqual(self.client.post('/api/v1/auth/set-password/', data).status_code, 400)
        self.client.cookies['openlims_refresh'] = str(refresh)
        self.assertEqual(self.client.post('/api/v1/auth/refresh/').status_code, 401)

    def test_ineligible_addresses_receive_no_mail(self):
        get_user_model().objects.create_user('disabled', 'disabled@example.org', 'secret', is_active=False)
        get_user_model().objects.create_user('invited', 'invited@example.org', None)
        for email in ['unknown@example.org', 'disabled@example.org', 'invited@example.org']:
            send_password_recovery(email)
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limit_and_csrf(self):
        with patch('core.password_recovery.send_password_recovery.apply_async'):
            for _ in range(3):
                self.assertEqual(self.client.post('/api/v1/auth/forgot-password/', {'email': self.user.email}).status_code, 200)
            self.assertEqual(self.client.post('/api/v1/auth/forgot-password/', {'email': self.user.email}).status_code, 429)
        cache.clear()
        self.assertEqual(APIClient(enforce_csrf_checks=True).post('/api/v1/auth/forgot-password/', {'email': self.user.email}).status_code, 403)

    def test_smtp_failure_does_not_change_password(self):
        with patch('core.tasks.send_mail', side_effect=OSError('mail unavailable')):
            send_password_recovery(self.user.email)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Original-secret-184!'))
