from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from samples.models import Sample
from inventory.models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from results.models import Result, WorkItem
from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from assistant.models import (
    BarcodeLabel,
    GeneratedArtifact,
    NotificationDelivery,
    NotificationSubscription,
    SOPDocument,
)


class Command(BaseCommand):
    help = "Initialize default roles (admin, tech, viewer, qc_reviewer) with permissions"

    def handle(self, *args, **options):
        # Create groups
        admin_group, _ = Group.objects.get_or_create(name="admin")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        qc_reviewer_group, _ = Group.objects.get_or_create(name="qc_reviewer")

        models = [
            Sample,
            Location,
            Container,
            FieldDefinition,
            FieldValue,
            Event,
            WorkItem,
            Result,
            InventoryItem,
            InventoryLot,
            InventoryReservation,
            BarcodeLabel,
            GeneratedArtifact,
            NotificationSubscription,
            NotificationDelivery,
            SOPDocument,
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

            # SOP authoring and approval are reserved for directors/admins.
            # Remove legacy write grants as well, so rerunning init_roles repairs
            # databases initialized before the SOP management policy existed.
            if model is SOPDocument:
                tech_group.permissions.add(*view_perms)
                tech_group.permissions.remove(
                    *add_perms,
                    *change_perms,
                    *delete_perms,
                )
                viewer_group.permissions.remove(
                    *add_perms,
                    *change_perms,
                    *delete_perms,
                )
                qc_reviewer_group.permissions.remove(
                    *add_perms,
                    *change_perms,
                    *delete_perms,
                )
            else:
                # Tech: read + create + update
                tech_group.permissions.add(
                    *view_perms,
                    *add_perms,
                    *change_perms,
                )

            # QC reviewers can read lab records and update QC review state.
            qc_reviewer_group.permissions.add(*view_perms)
            if model in [WorkItem, Result]:
                qc_reviewer_group.permissions.add(*change_perms)

            # Admin: full access
            admin_group.permissions.add(
                *view_perms,
                *add_perms,
                *change_perms,
                *delete_perms,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Roles initialized: admin, tech, viewer, and qc_reviewer"
            )
        )
