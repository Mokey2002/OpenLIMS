import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1"])
class BootstrapDemoTests(TestCase):
    def setUp(self):
        self.password = "generated-demo-credential-" + "a" * 32
        self.environment = patch.dict(os.environ, {
            "OPENLIMS_DEMO_MODE": "true", "OPENLIMS_DOMAIN": "",
            "OPENLIMS_DEMO_PASSWORD": self.password,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_requires_explicit_demo_mode_before_seeding(self):
        with patch.dict(os.environ, {"OPENLIMS_DEMO_MODE": "false"}), \
             patch("core.management.commands.bootstrap_demo.call_command") as seed:
            with self.assertRaises(CommandError):
                call_command("bootstrap_demo")
            seed.assert_not_called()

    @override_settings(ALLOWED_HOSTS=["lims.example.org"])
    def test_rejects_nonlocal_hosts(self):
        with self.assertRaises(CommandError):
            call_command("bootstrap_demo")

    def test_rejects_production_domain_and_missing_password(self):
        for setting in ({"OPENLIMS_DOMAIN": "lims.example.org"}, {"OPENLIMS_DEMO_PASSWORD": ""}):
            with self.subTest(setting=next(iter(setting))), patch.dict(os.environ, setting):
                with self.assertRaises(CommandError):
                    call_command("bootstrap_demo")

    def test_generated_password_is_set_once_and_retry_does_not_reseed(self):
        def seed(*args, **kwargs):
            user = get_user_model().objects.create_user("director")
            user.set_unusable_password()
            user.save()
        with patch("core.management.commands.bootstrap_demo.call_command", side_effect=seed) as seeder:
            call_command("bootstrap_demo")
            call_command("bootstrap_demo")
            self.assertEqual(seeder.call_count, 1)
        self.assertTrue(get_user_model().objects.get(username="director").check_password(self.password))

    def test_existing_credentials_are_not_reset(self):
        user = get_user_model().objects.create_user("director", password="existing-long-password")
        with patch("core.management.commands.bootstrap_demo.call_command") as seed:
            with self.assertRaises(CommandError):
                call_command("bootstrap_demo")
            seed.assert_not_called()
        user.refresh_from_db()
        self.assertTrue(user.check_password("existing-long-password"))

    def test_failed_seed_rolls_back_without_creating_login_credentials(self):
        def broken(*args, **kwargs):
            get_user_model().objects.create_user("director")
            raise CommandError("Seed interrupted")
        with patch("core.management.commands.bootstrap_demo.call_command", side_effect=broken):
            with self.assertRaises(CommandError):
                call_command("bootstrap_demo")
        self.assertFalse(get_user_model().objects.filter(username="director").exists())
