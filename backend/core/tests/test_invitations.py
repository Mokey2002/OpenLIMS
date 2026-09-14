from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.core.cache import cache
from rest_framework.test import APITestCase, APIClient

User = get_user_model()


@override_settings(OPENLIMS_EMAIL_ENABLED=True,
                   OPENLIMS_PUBLIC_URL='https://agrobiom.matmor.unam.mx:8443',
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InvitationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('owner', 'owner@example.org', 'secret')
        self.client.force_authenticate(self.admin)

    def create_invited(self):
        response = self.client.post('/api/v1/admin-users/', {
            'username': 'scientist', 'email': 'scientist@example.org', 'role': 'tech',
            'send_invitation': True,
        })
        self.assertEqual(response.status_code, 201, response.data)
        return User.objects.get(username='scientist'), response

    def credentials(self):
        link = next(line for line in mail.outbox[-1].body.splitlines() if line.startswith('https://'))
        self.assertTrue(link.startswith('https://agrobiom.matmor.unam.mx:8443/set-password#'))
        return {key: values[0] for key, values in parse_qs(urlsplit(link).fragment).items()}

    def test_invite_and_single_use_password_setup(self):
        user, response = self.create_invited()
        self.assertEqual(response.data['invitation_status'], 'sent')
        self.assertFalse(user.has_usable_password())
        self.assertIn(user.username, mail.outbox[0].body)
        self.assertNotIn('token', response.data)
        data = {**self.credentials(), 'password': 'Long-private-password-927!'}
        anonymous = APIClient()
        result = anonymous.post('/api/v1/auth/set-password/', data)
        self.assertEqual(result.status_code, 200, result.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password(data['password']))
        self.assertEqual(anonymous.post('/api/v1/auth/set-password/', data).status_code, 400)

    def test_existing_account_invitation_does_not_replace_password(self):
        user = User.objects.create_user('existing', 'existing@example.org', 'original-password')
        result = self.client.post(f'/api/v1/admin-users/{user.pk}/invite/')
        self.assertEqual(result.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('original-password'))
        self.assertEqual(APIClient().post('/api/v1/auth/set-password/', {
            **self.credentials(), 'password': 'New-private-password-928!'}).status_code, 200)

    def test_delivery_failure_keeps_account_and_allows_retry(self):
        with patch('core.invitations.send_mail', side_effect=OSError('sensitive SMTP error')):
            user, response = self.create_invited()
        self.assertEqual(response.data['invitation_status'], 'failed')
        self.assertNotIn('sensitive', str(response.data))
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.post(f'/api/v1/admin-users/{user.pk}/invite/').status_code, 200)

    @override_settings(OPENLIMS_EMAIL_ENABLED=False)
    def test_unconfigured_email_rejected_before_account_creation(self):
        result = self.client.post('/api/v1/admin-users/', {
            'username': 'new', 'email': 'new@example.org', 'role': 'tech', 'send_invitation': True})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_non_admin_cannot_invite(self):
        user, _ = self.create_invited()
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post(f'/api/v1/admin-users/{user.pk}/invite/').status_code, 403)

    def test_invalid_expired_disabled_and_weak_password(self):
        user, _ = self.create_invited()
        anonymous = APIClient()
        data = {**self.credentials(), 'password': '123'}
        self.assertEqual(anonymous.post('/api/v1/auth/set-password/', data).status_code, 400)
        data['password'] = 'Long-private-password-927!'
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertEqual(anonymous.post('/api/v1/auth/set-password/', data).status_code, 400)
        user.is_active = False
        user.save()
        self.assertEqual(anonymous.post('/api/v1/auth/set-password/', data).status_code, 400)
        self.assertEqual(anonymous.post('/api/v1/auth/set-password/', {**data, 'uid': '!'}).status_code, 400)

    def test_password_setup_requires_csrf(self):
        self.create_invited()
        result = APIClient(enforce_csrf_checks=True).post('/api/v1/auth/set-password/', {
            **self.credentials(), 'password': 'Long-private-password-927!'})
        self.assertEqual(result.status_code, 403)

    def test_manual_account_still_supported(self):
        result = self.client.post('/api/v1/admin-users/', {
            'username': 'manual', 'role': 'tech', 'password': 'manual-password', 'send_invitation': False})
        self.assertEqual(result.status_code, 201)
        self.assertTrue(User.objects.get(username='manual').check_password('manual-password'))
