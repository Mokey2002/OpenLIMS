import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from core.management.commands.seed_demo import create_demo_user


User = get_user_model()


class DemoUserCredentialTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="tech")

    def create_demo_user(self, *, password=None):
        return create_demo_user(
            "demo-tech",
            self.group,
            email="demo-tech@example.invalid",
            first_name="Demo",
            last_name="Technician",
            password=password,
        )

    def test_new_demo_user_has_no_usable_default_password(self):
        user = self.create_demo_user()

        self.assertFalse(user.has_usable_password())

    def test_existing_password_is_preserved_without_environment_password(self):
        existing_password = secrets.token_urlsafe(24)
        user = User.objects.create_user(
            username="demo-tech",
            email="old@example.invalid",
            password=existing_password,
        )

        updated_user = self.create_demo_user()

        self.assertTrue(updated_user.check_password(existing_password))

    def test_environment_password_replaces_existing_password(self):
        old_password = secrets.token_urlsafe(24)
        new_password = secrets.token_urlsafe(24)
        User.objects.create_user(
            username="demo-tech",
            email="old@example.invalid",
            password=old_password,
        )

        updated_user = self.create_demo_user(password=new_password)

        self.assertFalse(updated_user.check_password(old_password))
        self.assertTrue(updated_user.check_password(new_password))
