from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from samples.models import Sample
from inventory.models import Location, Container
from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event


class Command(BaseCommand):
    help = "Initialize default roles (admin, tech, viewer) with permissions"

    def handle(self, *args, **options):
        # Create groups
        admin_group, _ = Group.objects.get_or_create(name="admin")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")

        models = [
            Sample,
            Location,
            Container,
            FieldDefinition,
            FieldValue,
            Event,
        ]

        for model in models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct)

            view_perms = [p for p in perms if p.codename.startswith("view_")]
            add_perms = [p for p in perms if p.codename.startswith("add_")]
            change_perms = [p for p in perms if p.codename.startswith("change_")]
            delete_perms = [p for p in perms if p.codename.startswith("delete_")]

            # Viewer: read-only
            viewer_group.permissions.add(*view_perms)

            # Tech: read + create + update
            tech_group.permissions.add(*view_perms, *add_perms, *change_perms)

            # Admin: full access
            admin_group.permissions.add(
                *view_perms,
                *add_perms,
                *change_perms,
                *delete_perms,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Roles initialized: admin (full), tech (read/write), viewer (read-only)"
            )
        )
