"""Create credentials only inside an explicitly configured local demo installation."""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Initialize the isolated local demo and its generated director credentials."

    def handle(self, *args, **options):
        password = os.environ.get("OPENLIMS_DEMO_PASSWORD", "")
        if (os.environ.get("OPENLIMS_DEMO_MODE") != "true"
                or os.environ.get("OPENLIMS_DOMAIN")
                or not settings.ALLOWED_HOSTS
                or not set(settings.ALLOWED_HOSTS) <= {"localhost", "127.0.0.1", "[::1]"}):
            raise CommandError("Demo initialization requires explicit demo mode and loopback-only hosts.")
        if len(password) < 24 or any(character.isspace() for character in password):
            raise CommandError("A generated demo password of at least 24 characters is required.")
        with transaction.atomic():
            existing = get_user_model().objects.filter(username="director").first()
            if existing and existing.has_usable_password():
                if not existing.check_password(password):
                    raise CommandError("Existing credentials differ. Demo initialization never resets a password.")
                self.stdout.write("Demo was already initialized; existing records and credentials were retained.")
                return
            call_command("seed_demo", stdout=self.stdout)
            user = get_user_model().objects.get(username="director")
            user.set_password(password)
            user.save(update_fields=["password"])
        self.stdout.write("Local demo initialized. Credentials are stored in the installation's private configuration.")
