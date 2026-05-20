from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

#from projects.models import Project
from inventory.models import Location, Container
from samples.models import Sample
from results.models import WorkItem, Result
from imports.models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from events.models import Event
from notifications.models import Notification
from sequences.models import Sequence, SequenceFeature
from projects.models import Project, ProjectPost


User = get_user_model()


def field_exists(model, field_name):
    return any(field.name == field_name for field in model._meta.fields)


def clean_kwargs(model, kwargs):
    return {
        key: value
        for key, value in kwargs.items()
        if field_exists(model, key)
    }


def get_or_create_safe(model, lookup, defaults=None):
    defaults = defaults or {}
    lookup = clean_kwargs(model, lookup)
    defaults = clean_kwargs(model, defaults)

    obj, created = model.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )
    return obj, created


def set_password(user, password):
    user.set_password(password)
    user.is_active = True
    user.save()


class Command(BaseCommand):
    help = "Seed OpenLIMS with demo data"

    def handle(self, *args, **options):
        self.stdout.write("Seeding OpenLIMS demo data...")

        # --------------------------------------------------
        # Groups
        # --------------------------------------------------
        admin_group, _ = Group.objects.get_or_create(name="admin")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")

        # --------------------------------------------------
        # Users
        # --------------------------------------------------
        admin, _ = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@example.com"},
        )
        admin.set_password("Admin123456!")
        admin.is_staff = True
        admin.is_superuser = True
        admin.is_active = True
        admin.save()
        admin.groups.add(admin_group)

        peter, _ = User.objects.get_or_create(
            username="peter",
            defaults={"email": "peter@example.com"},
        )
        peter.set_password("peter123")
        peter.is_staff = False
        peter.is_superuser = False
        peter.is_active = True
        peter.save()
        peter.groups.add(tech_group)

        viewer, _ = User.objects.get_or_create(
            username="viewer",
            defaults={"email": "viewer@example.com"},
        )
        viewer.set_password("viewer123")
        viewer.is_active = True
        viewer.save()
        viewer.groups.add(viewer_group)

        # --------------------------------------------------
        # Projects
        # --------------------------------------------------
        project_alpha, _ = get_or_create_safe(
            Project,
            {"code": "PRJ-ALPHA"},
            {
                "name": "Alpha Assay Validation",
                "description": "Demo validation project for instrument-imported assay results.",
                "status": "ACTIVE",
            },
        )

        project_beta, _ = get_or_create_safe(
            Project,
            {"code": "PRJ-BETA"},
            {
                "name": "Beta Stability Study",
                "description": "Demo project tracking sample stability across storage conditions.",
                "status": "ACTIVE",
            },
        )

        # Add members if the Project model has a members many-to-many field
        if hasattr(project_alpha, "members"):
            project_alpha.members.add(admin, peter)
            project_beta.members.add(admin, peter, viewer)

        # --------------------------------------------------
        # Inventory
        # --------------------------------------------------
        freezer, _ = get_or_create_safe(
            Location,
            {"name": "Freezer A"},
            {
                "description": "Main -80C freezer",
                "room": "Lab 101",
            },
        )

        fridge, _ = get_or_create_safe(
            Location,
            {"name": "Fridge B"},
            {
                "description": "4C reagent and sample fridge",
                "room": "Lab 102",
            },
        )

        rack_a, _ = get_or_create_safe(
            Container,
            {"container_id": "BOX-A1"},
            {
                "kind": "96-well box",
                "location": freezer,
                "description": "Demo sample box in Freezer A",
            },
        )

        rack_b, _ = get_or_create_safe(
            Container,
            {"container_id": "BOX-B1"},
            {
                "kind": "Tube rack",
                "location": fridge,
                "description": "Demo rack in Fridge B",
            },
        )

        # --------------------------------------------------
        # Instrument profile + mappings
        # --------------------------------------------------
        novaflex, _ = get_or_create_safe(
            InstrumentProfile,
            {"code": "NOVAFLEX"},
            {
                "name": "NovaFlex Analyzer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
            },
        )

        mappings = [
            {
                "source_column": "concentration",
                "target_key": "concentration",
                "value_type": "NUMBER",
                "min_value": 0,
                "max_value": 100,
            },
            {
                "source_column": "purity",
                "target_key": "purity",
                "value_type": "NUMBER",
                "min_value": 0,
                "max_value": 100,
            },
            {
                "source_column": "yield",
                "target_key": "yield",
                "value_type": "NUMBER",
                "min_value": 0,
                "max_value": 100,
            },
            {
                "source_column": "qc_flag",
                "target_key": "qc_flag",
                "value_type": "STRING",
                "allowed_values": ["PASS", "FAIL", "REVIEW"],
            },
        ]

        for mapping in mappings:
            get_or_create_safe(
                InstrumentColumnMapping,
                {
                    "instrument": novaflex,
                    "source_column": mapping["source_column"],
                },
                mapping,
            )

        # --------------------------------------------------
        # Samples
        # --------------------------------------------------
        sample_data = [
            {
                "sample_id": "S-ALPHA-001",
                "status": "RECEIVED",
                "project": project_alpha,
                "container": rack_a,
            },
            {
                "sample_id": "S-ALPHA-002",
                "status": "IN_PROGRESS",
                "project": project_alpha,
                "container": rack_a,
            },
            {
                "sample_id": "S-ALPHA-003",
                "status": "QC",
                "project": project_alpha,
                "container": rack_a,
            },
            {
                "sample_id": "S-BETA-001",
                "status": "REPORTED",
                "project": project_beta,
                "container": rack_b,
            },
            {
                "sample_id": "S-BETA-002",
                "status": "ARCHIVED",
                "project": project_beta,
                "container": rack_b,
            },
        ]

        samples = []

        for row in sample_data:
            sample, created = get_or_create_safe(
                Sample,
                {"sample_id": row["sample_id"]},
                row,
            )
            samples.append(sample)

            if created:
                Event.objects.create(
                    entity_type="Sample",
                    entity_id=str(sample.id),
                    action="CREATED",
                    actor=admin,
                    payload={
                        "sample_id": sample.id,
                        "sample_code": sample.sample_id,
                        "source": "demo_seed",
                        "project_id": getattr(sample, "project_id", None),
                        "container_id": getattr(sample, "container_id", None),
                    },
                )

        # --------------------------------------------------
        # Work items + results
        # --------------------------------------------------
        result_values = {
            "S-ALPHA-001": {
                "concentration": 12.4,
                "purity": 97.1,
                "yield": 88.0,
                "qc_flag": "PASS",
            },
            "S-ALPHA-002": {
                "concentration": 10.2,
                "purity": 95.8,
                "yield": 79.3,
                "qc_flag": "PASS",
            },
            "S-ALPHA-003": {
                "concentration": 6.5,
                "purity": 89.2,
                "yield": 61.0,
                "qc_flag": "REVIEW",
            },
            "S-BETA-001": {
                "concentration": 15.1,
                "purity": 98.4,
                "yield": 91.2,
                "qc_flag": "PASS",
            },
            "S-BETA-002": {
                "concentration": 4.7,
                "purity": 76.8,
                "yield": 44.9,
                "qc_flag": "FAIL",
            },
        }

        for sample in samples:
            work_item, _ = get_or_create_safe(
                WorkItem,
                {
                    "sample": sample,
                    "name": "NovaFlex Import Results",
                },
                {
                    "status": "COMPLETED",
                    "notes": "Demo imported instrument results.",
                },
            )

            values = result_values.get(sample.sample_id, {})

            for key, value in values.items():
                if isinstance(value, (int, float)):
                    defaults = {
                        "value_type": "NUMBER",
                        "value_number": value,
                        "value_string": "",
                        "value_boolean": None,
                    }
                else:
                    defaults = {
                        "value_type": "STRING",
                        "value_string": value,
                        "value_number": None,
                        "value_boolean": None,
                    }

                Result.objects.update_or_create(
                    work_item=work_item,
                    key=key,
                    defaults=clean_kwargs(Result, defaults),
                )

        # --------------------------------------------------
        # Demo import job
        # --------------------------------------------------
        touched_sample_ids = [sample.id for sample in samples]
        created_sample_ids = [samples[0].id, samples[1].id]
        matched_sample_ids = [sample.id for sample in samples[2:]]

        import_job, _ = get_or_create_safe(
            ImportJob,
            {
                "instrument": novaflex,
                "run_id": "DEMO-RUN-001",
            },
            {
                "project": project_alpha,
                "uploaded_by": peter,
                "source_type": "UPLOAD",
                "status": "COMPLETED",
                "progress_current": 5,
                "progress_total": 5,
                "progress_message": "Demo import completed",
                "summary": {
                    "rows_processed": 5,
                    "samples_created": 2,
                    "samples_matched": 3,
                    "results_created": 20,
                    "skipped_rows": [
                        {
                            "row": 6,
                            "sample_id": "S-DEMO-BAD",
                            "column": "concentration",
                            "reason": "Invalid NUMBER 'bad-value'",
                        }
                    ],
                    "project_id": project_alpha.id,
                    "created_sample_ids": created_sample_ids,
                    "matched_sample_ids": matched_sample_ids,
                    "touched_sample_ids": touched_sample_ids,
                },
            },
        )

        Event.objects.get_or_create(
            entity_type="ImportJob",
            entity_id=str(import_job.id),
            action="RESULTS_IMPORTED",
            defaults={
                "actor": peter,
                "payload": {
                    "instrument_code": novaflex.code,
                    "instrument_name": novaflex.name,
                    "run_id": "DEMO-RUN-001",
                    "rows_processed": 5,
                    "results_created": 20,
                    "touched_sample_ids": touched_sample_ids,
                },
            },
        )

        for sample in samples:
            Event.objects.get_or_create(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="RESULTS_IMPORTED",
                defaults={
                    "actor": peter,
                    "payload": {
                        "sample_id": sample.id,
                        "sample_code": sample.sample_id,
                        "source": "instrument_import",
                        "instrument_code": novaflex.code,
                        "import_job_id": import_job.id,
                        "run_id": "DEMO-RUN-001",
                    },
                },
            )

        # --------------------------------------------------
        # Notifications
        # --------------------------------------------------
        Notification.objects.get_or_create(
            user=peter,
            title="Demo import completed",
            defaults={
                "message": "NovaFlex demo import completed with 20 results created.",
                "link": f"/imports/{import_job.id}",
            },
        )

        Notification.objects.get_or_create(
            user=admin,
            title="Demo environment ready",
            defaults={
                "message": "OpenLIMS demo data has been seeded successfully.",
                "link": "/",
            },
        )
                # --------------------------------------------------
        # Demo sequence workspace linked to PRJ-ALPHA
        # --------------------------------------------------
        demo_sequence_text = (
            "TTGACGGCTAGCTCAGTCCTAGGTACAGTGCTAGCGGATCCATGGTGAGCAAGGGCGAGGAG"
            "CTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTC"
            "AGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGC"
            "ACCACCGGCAAGCTGCCCGTGCCCTGGCCCACCCTCGTGACCACCCTGACCTACGGCGTGCAG"
            "TGCTTCAGCCGCTACCCCGACCACATGAAGCAGCACGACTTCTTCAAGTCCGCCATGCCCGA"
            "AGGCTACGTCCAGGAGCGCACCATCTTCTTCAAGGACGACGGCAACTACAAGACCCGCGCCGA"
            "GGTGAAGTTCGAGGGCGACACCCTGGTGAACCGCATCGAGCTGAAGGGCATCGACTTCAAGGA"
            "GGACGGCAACATCCTGGGGCACAAGCTGGAGTACAACTACAACAGCCACAACGTCTATATCAT"
            "GGCCGACAAGCAGAAGAACGGCATCAAGGTGAACTTCAAGATCCGCCACAACATCGAGGACGG"
            "CAGCGTGCAGCTCGCCGACCACTACCAGCAGAACACCCCCATCGGCGACGGCCCCGTGCTGCT"
            "GCCCGACAACCACTACCTGAGCACCCAGTCCGCCCTGAGCAAAGACCCCAACGAGAAGCGCGA"
            "TCACATGGTCCTGCTGGAGTTCGTGACCGCCGCCGGGATCACTCTCGGCATGGACGAGCTGTA"
            "CAAGTAA"
        )

        sequence_workspace, _ = Sequence.objects.update_or_create(
            name="Alpha GFP Construct Review",
            project=project_alpha,
            defaults={
                "description": "Demo SeqViz workspace linked to the Alpha Assay Validation project.",
                "sequence_type": "DNA",
                "sequence": demo_sequence_text,
                "sample": samples[0] if samples else None,
                "viewer": "both",
                "show_complement": True,
                "rotate_on_scroll": False,
                "zoom": 50,
                "enzymes": ["EcoRI", "BamHI", "HindIII", "PstI", "XhoI"],
                "bp_colors": {
                    "A": "#ef4444",
                    "T": "#3b82f6",
                    "G": "#22c55e",
                    "C": "#f59e0b",
                },
                "created_by": peter,
            },
        )

        sequence_workspace.features.all().delete()

        demo_features = [
            {
                "feature_type": "ANNOTATION",
                "name": "Promoter",
                "start": 0,
                "end": 35,
                "direction": 1,
                "color": "#2563eb",
                "metadata": {},
            },
            {
                "feature_type": "ANNOTATION",
                "name": "BamHI",
                "start": 37,
                "end": 43,
                "direction": 1,
                "color": "#f97316",
                "metadata": {},
            },
            {
                "feature_type": "ANNOTATION",
                "name": "GFP CDS",
                "start": 43,
                "end": 763,
                "direction": 1,
                "color": "#22c55e",
                "metadata": {},
            },
            {
                "feature_type": "PRIMER",
                "name": "GFP Forward",
                "start": 43,
                "end": 63,
                "direction": 1,
                "color": "#9333ea",
                "metadata": {},
            },
            {
                "feature_type": "PRIMER",
                "name": "GFP Reverse",
                "start": 730,
                "end": 760,
                "direction": -1,
                "color": "#db2777",
                "metadata": {},
            },
            {
                "feature_type": "TRANSLATION",
                "name": "GFP Translation",
                "start": 43,
                "end": 763,
                "direction": 1,
                "color": "#16a34a",
                "metadata": {},
            },
            {
                "feature_type": "HIGHLIGHT",
                "name": "QC Review Region",
                "start": 120,
                "end": 180,
                "direction": 1,
                "color": "#fde047",
                "metadata": {},
            },
        ]

        for feature_data in demo_features:
            SequenceFeature.objects.create(
                sequence_record=sequence_workspace,
                **feature_data,
            )

        Event.objects.get_or_create(
            entity_type="Sequence",
            entity_id=str(sequence_workspace.id),
            action="SEQUENCE_WORKSPACE_SEEDED",
            defaults={
                "actor": peter,
                "payload": {
                    "sequence_id": sequence_workspace.id,
                    "name": sequence_workspace.name,
                    "project_id": project_alpha.id,
                    "features_count": len(demo_features),
                },
            },
        )
                # --------------------------------------------------
        # Demo project feed posts
        # --------------------------------------------------
        demo_project_posts = [
            {
                "project": project_alpha,
                "author": admin,
                "note": (
                    "Initial project setup is complete. Alpha validation samples "
                    "S-ALPHA-001 through S-ALPHA-003 are assigned to BOX-A1."
                ),
            },
            {
                "project": project_alpha,
                "author": peter,
                "note": (
                    "NovaFlex import completed for the Alpha sample set. "
                    "Concentration, purity, yield, and QC flag values are now available."
                ),
            },
            {
                "project": project_alpha,
                "author": viewer,
                "note": (
                    "Review note: S-ALPHA-003 appears to need QC review because "
                    "purity and yield are lower than the expected range."
                ),
            },
            {
                "project": project_beta,
                "author": admin,
                "note": (
                    "Beta Stability Study has been initialized. Samples are linked "
                    "to storage locations for tracking."
                ),
            },
            {
                "project": project_beta,
                "author": peter,
                "note": (
                    "Storage check completed. Beta samples are currently assigned "
                    "to BOX-B1 in Fridge B."
                ),
            },
        ]

        for post_data in demo_project_posts:
            ProjectPost.objects.get_or_create(
                project=post_data["project"],
                author=post_data["author"],
                note=post_data["note"],
            )
                # --------------------------------------------------
        # Demo project feed posts
        # --------------------------------------------------
        demo_project_posts = [
            {
                "project": project_alpha,
                "author": admin,
                "note": (
                    "Initial project setup is complete. Alpha validation samples "
                    "S-ALPHA-001 through S-ALPHA-003 are assigned to BOX-A1."
                ),
            },
            {
                "project": project_alpha,
                "author": peter,
                "note": (
                    "NovaFlex import completed for the Alpha sample set. "
                    "Concentration, purity, yield, and QC flag values are now available."
                ),
            },
            {
                "project": project_alpha,
                "author": viewer,
                "note": (
                    "Review note: S-ALPHA-003 appears to need QC review because "
                    "purity and yield are lower than the expected range."
                ),
            },
            {
                "project": project_beta,
                "author": admin,
                "note": (
                    "Beta Stability Study has been initialized. Samples are linked "
                    "to storage locations for tracking."
                ),
            },
            {
                "project": project_beta,
                "author": peter,
                "note": (
                    "Storage check completed. Beta samples are currently assigned "
                    "to BOX-B1 in Fridge B."
                ),
            },
        ]

        for post_data in demo_project_posts:
            ProjectPost.objects.get_or_create(
                project=post_data["project"],
                author=post_data["author"],
                note=post_data["note"],
            )

        # --------------------------------------------------
        # Demo sequence workspace linked to PRJ-ALPHA
        # --------------------------------------------------
        demo_sequence_text = (
            "TTGACGGCTAGCTCAGTCCTAGGTACAGTGCTAGCGGATCCATGGTGAGCAAGGGCGAGGAG"
            "CTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTC"
            "AGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGC"
            "ACCACCGGCAAGCTGCCCGTGCCCTGGCCCACCCTCGTGACCACCCTGACCTACGGCGTGCAG"
            "TGCTTCAGCCGCTACCCCGACCACATGAAGCAGCACGACTTCTTCAAGTCCGCCATGCCCGA"
            "AGGCTACGTCCAGGAGCGCACCATCTTCTTCAAGGACGACGGCAACTACAAGACCCGCGCCGA"
            "GGTGAAGTTCGAGGGCGACACCCTGGTGAACCGCATCGAGCTGAAGGGCATCGACTTCAAGGA"
            "GGACGGCAACATCCTGGGGCACAAGCTGGAGTACAACTACAACAGCCACAACGTCTATATCAT"
            "GGCCGACAAGCAGAAGAACGGCATCAAGGTGAACTTCAAGATCCGCCACAACATCGAGGACGG"
            "CAGCGTGCAGCTCGCCGACCACTACCAGCAGAACACCCCCATCGGCGACGGCCCCGTGCTGCT"
            "GCCCGACAACCACTACCTGAGCACCCAGTCCGCCCTGAGCAAAGACCCCAACGAGAAGCGCGA"
            "TCACATGGTCCTGCTGGAGTTCGTGACCGCCGCCGGGATCACTCTCGGCATGGACGAGCTGTA"
            "CAAGTAA"
        )

        sequence_workspace, _ = Sequence.objects.update_or_create(
            name="Alpha GFP Construct Review",
            project=project_alpha,
            defaults={
                "description": (
                    "Demo SeqViz workspace linked to the Alpha Assay Validation project."
                ),
                "sequence_type": "DNA",
                "sequence": demo_sequence_text,
                "sample": samples[0] if samples else None,
                "viewer": "both",
                "show_complement": True,
                "rotate_on_scroll": False,
                "zoom": 50,
                "enzymes": ["EcoRI", "BamHI", "HindIII", "PstI", "XhoI"],
                "bp_colors": {
                    "A": "#ef4444",
                    "T": "#3b82f6",
                    "G": "#22c55e",
                    "C": "#f59e0b",
                },
                "created_by": peter,
            },
        )

        sequence_workspace.features.all().delete()

        demo_features = [
            {
                "feature_type": "ANNOTATION",
                "name": "Promoter",
                "start": 0,
                "end": 35,
                "direction": 1,
                "color": "#2563eb",
                "metadata": {},
            },
            {
                "feature_type": "ANNOTATION",
                "name": "BamHI",
                "start": 37,
                "end": 43,
                "direction": 1,
                "color": "#f97316",
                "metadata": {},
            },
            {
                "feature_type": "ANNOTATION",
                "name": "GFP CDS",
                "start": 43,
                "end": 763,
                "direction": 1,
                "color": "#22c55e",
                "metadata": {},
            },
            {
                "feature_type": "PRIMER",
                "name": "GFP Forward",
                "start": 43,
                "end": 63,
                "direction": 1,
                "color": "#9333ea",
                "metadata": {},
            },
            {
                "feature_type": "PRIMER",
                "name": "GFP Reverse",
                "start": 730,
                "end": 760,
                "direction": -1,
                "color": "#db2777",
                "metadata": {},
            },
            {
                "feature_type": "TRANSLATION",
                "name": "GFP Translation",
                "start": 43,
                "end": 763,
                "direction": 1,
                "color": "#16a34a",
                "metadata": {},
            },
            {
                "feature_type": "HIGHLIGHT",
                "name": "QC Review Region",
                "start": 120,
                "end": 180,
                "direction": 1,
                "color": "#fde047",
                "metadata": {},
            },
        ]

        for feature_data in demo_features:
            SequenceFeature.objects.create(
                sequence_record=sequence_workspace,
                **feature_data,
            )

        Event.objects.get_or_create(
            entity_type="Sequence",
            entity_id=str(sequence_workspace.id),
            action="SEQUENCE_WORKSPACE_SEEDED",
            defaults={
                "actor": peter,
                "payload": {
                    "sequence_id": sequence_workspace.id,
                    "name": sequence_workspace.name,
                    "project_id": project_alpha.id,
                    "features_count": len(demo_features),
                },
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("")
        self.stdout.write("Demo users:")
        self.stdout.write("  admin / Admin123456!")
        self.stdout.write("  peter / peter123")
        self.stdout.write("  viewer / viewer123")
