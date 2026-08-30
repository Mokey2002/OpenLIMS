from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from settings_app.models import SystemSettings


User = get_user_model()


class BrowserAuthenticationHardeningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="hardening-admin",
            password="Hardening123!",
            is_staff=True,
            is_superuser=True,
        )
        group, _ = Group.objects.get_or_create(name="admin")
        self.user.groups.add(group)
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf_token(self):
        response = self.client.get("/api/v1/auth/csrf/")
        self.assertEqual(response.status_code, 200)
        return self.client.cookies["csrftoken"].value

    def login(self):
        csrf = self.csrf_token()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": self.user.username, "password": "Hardening123!"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_browser_tokens_are_httponly_and_not_returned_in_json(self):
        response = self.login()

        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertTrue(response.cookies["openlims_access"]["httponly"])
        self.assertTrue(response.cookies["openlims_refresh"]["httponly"])

        me = self.client.get("/api/v1/me/")
        self.assertEqual(me.status_code, 200, me.data)
        self.assertEqual(me.data["username"], self.user.username)

    @override_settings(CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:5173"])
    def test_trusted_browser_origin_can_log_in(self):
        csrf = self.csrf_token()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": self.user.username, "password": "Hardening123!"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://127.0.0.1:5173",
        )
        self.assertEqual(response.status_code, 200, response.data)

    @override_settings(CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:5173"])
    def test_untrusted_browser_origin_is_rejected(self):
        csrf = self.csrf_token()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": self.user.username, "password": "Hardening123!"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="https://untrusted.example",
        )
        self.assertEqual(response.status_code, 403)

    def test_cookie_authenticated_writes_require_csrf(self):
        self.login()

        blocked = self.client.post(
            "/api/v1/projects/",
            {"name": "Blocked Project", "code": "BLOCKED"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 403, blocked.data)

        csrf = self.client.cookies["csrftoken"].value
        allowed = self.client.post(
            "/api/v1/projects/",
            {"name": "Allowed Project", "code": "ALLOWED"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_refresh_rotates_and_logout_blacklists_refresh_tokens(self):
        self.login()
        old_refresh = self.client.cookies["openlims_refresh"].value
        old_jti = RefreshToken(old_refresh)["jti"]
        csrf = self.client.cookies["csrftoken"].value

        refreshed = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        new_refresh = self.client.cookies["openlims_refresh"].value
        self.assertNotEqual(old_refresh, new_refresh)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=old_jti).exists())

        new_jti = RefreshToken(new_refresh)["jti"]
        logged_out = self.client.post(
            "/api/v1/auth/logout/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(logged_out.status_code, 200, logged_out.data)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=new_jti).exists())


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
class FeatureFlagBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="feature-admin",
            password="Feature123!",
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.settings = SystemSettings.load()

    def test_registry_flag_blocks_legacy_and_versioned_api(self):
        self.settings.registry_enabled = False
        self.settings.save()
        self.assertEqual(self.client.get("/api/registry-records/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/registry-records/").status_code, 404)

        self.settings.registry_enabled = True
        self.settings.save()
        self.assertEqual(self.client.get("/api/registry-records/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/registry-records/").status_code, 200)

    def test_notebook_flag_blocks_legacy_and_versioned_api(self):
        self.settings.notebook_enabled = False
        self.settings.save()
        self.assertEqual(self.client.get("/api/notebooks/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/notebooks/").status_code, 404)

        self.settings.notebook_enabled = True
        self.settings.save()
        self.assertEqual(self.client.get("/api/notebooks/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/notebooks/").status_code, 200)