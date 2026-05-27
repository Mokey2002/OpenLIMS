from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

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


def result_defaults(value):
    if isinstance(value, bool):
        return {
            "value_type": "BOOLEAN",
            "value_boolean": value,
            "value_number": None,
            "value_string": "",
        }

    if isinstance(value, (int, float)):
        return {
            "value_type": "NUMBER",
            "value_number": value,
            "value_string": "",
            "value_boolean": None,
        }

    return {
        "value_type": "STRING",
        "value_string": str(value),
        "value_number": None,
        "value_boolean": None,
    }


def upsert_result(work_item, key, value):
    Result.objects.update_or_create(
        work_item=work_item,
        key=key,
        defaults=clean_kwargs(Result, result_defaults(value)),
    )


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

        project_gamma, _ = get_or_create_safe(
            Project,
            {"code": "PRJ-GAMMA"},
            {
                "name": "Gamma Endotoxin Release Testing",
                "description": "Demo project for LAL/endotoxin release testing and qPCR confirmation.",
                "status": "ACTIVE",
            },
        )

        if hasattr(project_alpha, "members"):
            project_alpha.members.add(admin, peter)
            project_beta.members.add(admin, peter, viewer)
            project_gamma.members.add(admin, peter)

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

        incubator, _ = get_or_create_safe(
            Location,
            {"name": "Incubator C"},
            {
                "description": "Controlled-temperature assay incubator",
                "room": "Lab 103",
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

        rack_c, _ = get_or_create_safe(
            Container,
            {"container_id": "PLATE-C1"},
            {
                "kind": "96-well plate",
                "location": incubator,
                "description": "Demo plate for endotoxin and qPCR testing",
            },
        )

        # --------------------------------------------------
        # Instrument profiles + mappings
        # --------------------------------------------------
        instrument_configs = [
            {
                "code": "NOVAFLEX",
                "name": "NovaFlex Analyzer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "concentration", "target_key": "concentration", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "purity", "target_key": "purity", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "yield", "target_key": "yield", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "qc_flag", "target_key": "qc_flag", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "MISEQ",
                "name": "Illumina MiSeq Sequencer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "read_count", "target_key": "read_count", "value_type": "NUMBER", "min_value": 0, "max_value": 10000000},
                    {"source_column": "mean_q_score", "target_key": "mean_q_score", "value_type": "NUMBER", "min_value": 0, "max_value": 50},
                    {"source_column": "percent_q30", "target_key": "percent_q30", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "sequencing_status", "target_key": "sequencing_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "SANGER-3500",
                "name": "Applied Biosystems 3500 Sanger Sequencer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "read_length", "target_key": "read_length", "value_type": "NUMBER", "min_value": 0, "max_value": 1200},
                    {"source_column": "quality_score", "target_key": "quality_score", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "basecalling_status", "target_key": "basecalling_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "ENDOSAFE",
                "name": "Charles River Endosafe Nexus",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "endotoxin_eu_ml", "target_key": "endotoxin_eu_ml", "value_type": "NUMBER", "min_value": 0, "max_value": 1000},
                    {"source_column": "spike_recovery_percent", "target_key": "spike_recovery_percent", "value_type": "NUMBER", "min_value": 0, "max_value": 200},
                    {"source_column": "lal_status", "target_key": "lal_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "SPECTRAMAX",
                "name": "Molecular Devices SpectraMax Plate Reader",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "abs_450", "target_key": "abs_450", "value_type": "NUMBER", "min_value": 0, "max_value": 5},
                    {"source_column": "abs_570", "target_key": "abs_570", "value_type": "NUMBER", "min_value": 0, "max_value": 5},
                    {"source_column": "plate_qc_status", "target_key": "plate_qc_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "QPCR-7500",
                "name": "Applied Biosystems 7500 qPCR System",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "ct_value", "target_key": "ct_value", "value_type": "NUMBER", "min_value": 0, "max_value": 45},
                    {"source_column": "delta_ct", "target_key": "delta_ct", "value_type": "NUMBER", "min_value": -50, "max_value": 50},
                    {"source_column": "qpcr_status", "target_key": "qpcr_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "NANODROP",
                "name": "Thermo Fisher NanoDrop One",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "nucleic_acid_concentration", "target_key": "nucleic_acid_concentration", "value_type": "NUMBER", "min_value": 0, "max_value": 10000},
                    {"source_column": "a260_280", "target_key": "a260_280", "value_type": "NUMBER", "min_value": 0, "max_value": 5},
                    {"source_column": "a260_230", "target_key": "a260_230", "value_type": "NUMBER", "min_value": 0, "max_value": 5},
                    {"source_column": "nanodrop_status", "target_key": "nanodrop_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "BIOANALYZER",
                "name": "Agilent 2100 Bioanalyzer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "rin", "target_key": "rin", "value_type": "NUMBER", "min_value": 0, "max_value": 10},
                    {"source_column": "fragment_size_bp", "target_key": "fragment_size_bp", "value_type": "NUMBER", "min_value": 0, "max_value": 50000},
                    {"source_column": "rna_concentration", "target_key": "rna_concentration", "value_type": "NUMBER", "min_value": 0, "max_value": 10000},
                    {"source_column": "bioanalyzer_status", "target_key": "bioanalyzer_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "CYTATION5",
                "name": "BioTek Cytation 5 Cell Imaging Reader",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "cell_count", "target_key": "cell_count", "value_type": "NUMBER", "min_value": 0, "max_value": 10000000},
                    {"source_column": "viability_percent", "target_key": "viability_percent", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "fluorescence_intensity", "target_key": "fluorescence_intensity", "value_type": "NUMBER", "min_value": 0, "max_value": 100000000},
                    {"source_column": "imaging_status", "target_key": "imaging_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "HAMILTON-STAR",
                "name": "Hamilton STAR Liquid Handler",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    {"source_column": "transfer_volume_ul", "target_key": "transfer_volume_ul", "value_type": "NUMBER", "min_value": 0, "max_value": 1000},
                    {"source_column": "pipette_error_count", "target_key": "pipette_error_count", "value_type": "NUMBER", "min_value": 0, "max_value": 100},
                    {"source_column": "liquid_handler_status", "target_key": "liquid_handler_status", "value_type": "STRING", "allowed_values": ["PASS", "FAIL", "REVIEW"]},
                ],
            },
            {
                "code": "FASTA-SEQ",
                "name": "Generic FASTA Sequencer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [],
            },
        ]

        instruments = {}

        for instrument_config in instrument_configs:
            instrument, _ = get_or_create_safe(
                InstrumentProfile,
                {"code": instrument_config["code"]},
                {
                    "name": instrument_config["name"],
                    "delimiter": instrument_config["delimiter"],
                    "has_header": instrument_config["has_header"],
                    "sample_id_column": instrument_config["sample_id_column"],
                },
            )
            instruments[instrument_config["code"]] = instrument

            for mapping in instrument_config["mappings"]:
                get_or_create_safe(
                    InstrumentColumnMapping,
                    {
                        "instrument": instrument,
                        "source_column": mapping["source_column"],
                    },
                    mapping,
                )

        novaflex = instruments["NOVAFLEX"]

        # --------------------------------------------------
        # Samples
        # --------------------------------------------------
        sample_data = [
            {"sample_id": "S-ALPHA-001", "status": "RECEIVED", "project": project_alpha, "container": rack_a},
            {"sample_id": "S-ALPHA-002", "status": "IN_PROGRESS", "project": project_alpha, "container": rack_a},
            {"sample_id": "S-ALPHA-003", "status": "QC", "project": project_alpha, "container": rack_a},
            {"sample_id": "S-ALPHA-004", "status": "IN_PROGRESS", "project": project_alpha, "container": rack_a},
            {"sample_id": "S-BETA-001", "status": "REPORTED", "project": project_beta, "container": rack_b},
            {"sample_id": "S-BETA-002", "status": "ARCHIVED", "project": project_beta, "container": rack_b},
            {"sample_id": "S-BETA-003", "status": "QC", "project": project_beta, "container": rack_b},
            {"sample_id": "S-GAMMA-001", "status": "RECEIVED", "project": project_gamma, "container": rack_c},
            {"sample_id": "S-GAMMA-002", "status": "IN_PROGRESS", "project": project_gamma, "container": rack_c},
        ]

        samples = []
        sample_by_code = {}

        for row in sample_data:
            sample, created = get_or_create_safe(
                Sample,
                {"sample_id": row["sample_id"]},
                row,
            )
            samples.append(sample)
            sample_by_code[sample.sample_id] = sample

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
            "S-ALPHA-001": {"concentration": 12.4, "purity": 97.1, "yield": 88.0, "qc_flag": "PASS"},
            "S-ALPHA-002": {"concentration": 10.2, "purity": 95.8, "yield": 79.3, "qc_flag": "PASS"},
            "S-ALPHA-003": {"concentration": 6.5, "purity": 89.2, "yield": 61.0, "qc_flag": "REVIEW"},
            "S-ALPHA-004": {"concentration": 9.8, "purity": 93.0, "yield": 73.6, "qc_flag": "PASS"},
            "S-BETA-001": {"concentration": 15.1, "purity": 98.4, "yield": 91.2, "qc_flag": "PASS"},
            "S-BETA-002": {"concentration": 4.7, "purity": 76.8, "yield": 44.9, "qc_flag": "FAIL"},
            "S-BETA-003": {"concentration": 7.3, "purity": 81.2, "yield": 52.1, "qc_flag": "REVIEW"},
            "S-GAMMA-001": {"concentration": 11.9, "purity": 96.4, "yield": 82.4, "qc_flag": "PASS"},
            "S-GAMMA-002": {"concentration": 5.9, "purity": 87.5, "yield": 58.7, "qc_flag": "REVIEW"},
        }

        for sample in samples:
            work_item, _ = get_or_create_safe(
                WorkItem,
                {"sample": sample, "name": "NovaFlex Import Results"},
                {"status": "COMPLETED", "notes": "Demo imported instrument results."},
            )

            values = result_values.get(sample.sample_id, {})
            for key, value in values.items():
                upsert_result(work_item, key, value)

        # --------------------------------------------------
        # Additional demo results from real-style lab instruments
        # --------------------------------------------------
        extra_instrument_results = {
            "S-ALPHA-001": {
                "Illumina MiSeq QC": {"read_count": 185420, "mean_q_score": 37.8, "percent_q30": 92.4, "sequencing_status": "PASS"},
                "Thermo Fisher NanoDrop One": {"nucleic_acid_concentration": 42.6, "a260_280": 1.91, "a260_230": 2.04, "nanodrop_status": "PASS"},
                "Endosafe Endotoxin Test": {"endotoxin_eu_ml": 0.03, "spike_recovery_percent": 96.2, "lal_status": "PASS"},
                "qPCR Quantification": {"ct_value": 21.4, "delta_ct": -1.2, "qpcr_status": "PASS"},
            },
            "S-ALPHA-002": {
                "Illumina MiSeq QC": {"read_count": 163900, "mean_q_score": 35.9, "percent_q30": 88.7, "sequencing_status": "PASS"},
                "Thermo Fisher NanoDrop One": {"nucleic_acid_concentration": 38.2, "a260_280": 1.87, "a260_230": 1.91, "nanodrop_status": "PASS"},
                "Endosafe Endotoxin Test": {"endotoxin_eu_ml": 0.08, "spike_recovery_percent": 91.1, "lal_status": "PASS"},
                "qPCR Quantification": {"ct_value": 23.8, "delta_ct": 0.4, "qpcr_status": "PASS"},
            },
            "S-ALPHA-003": {
                "Illumina MiSeq QC": {"read_count": 78400, "mean_q_score": 26.1, "percent_q30": 61.8, "sequencing_status": "REVIEW"},
                "Thermo Fisher NanoDrop One": {"nucleic_acid_concentration": 19.4, "a260_280": 1.62, "a260_230": 1.14, "nanodrop_status": "REVIEW"},
                "Endosafe Endotoxin Test": {"endotoxin_eu_ml": 0.42, "spike_recovery_percent": 72.5, "lal_status": "REVIEW"},
                "qPCR Quantification": {"ct_value": 32.6, "delta_ct": 8.1, "qpcr_status": "REVIEW"},
            },
            "S-ALPHA-004": {
                "Illumina MiSeq QC": {"read_count": 149250, "mean_q_score": 34.7, "percent_q30": 86.2, "sequencing_status": "PASS"},
                "Agilent Bioanalyzer RNA QC": {"rin": 8.4, "fragment_size_bp": 742, "rna_concentration": 38.8, "bioanalyzer_status": "PASS"},
                "Hamilton STAR Liquid Transfer": {"transfer_volume_ul": 25.0, "pipette_error_count": 0, "liquid_handler_status": "PASS"},
            },
            "S-BETA-001": {
                "SpectraMax Plate Reader": {"abs_450": 1.42, "abs_570": 0.18, "plate_qc_status": "PASS"},
                "Sanger Sequencing QC": {"read_length": 847, "quality_score": 88.2, "basecalling_status": "PASS"},
                "BioTek Cytation 5 Imaging": {"cell_count": 145200, "viability_percent": 94.2, "fluorescence_intensity": 48250, "imaging_status": "PASS"},
            },
            "S-BETA-002": {
                "SpectraMax Plate Reader": {"abs_450": 0.37, "abs_570": 0.28, "plate_qc_status": "FAIL"},
                "Sanger Sequencing QC": {"read_length": 312, "quality_score": 48.5, "basecalling_status": "REVIEW"},
                "BioTek Cytation 5 Imaging": {"cell_count": 68400, "viability_percent": 62.7, "fluorescence_intensity": 11800, "imaging_status": "REVIEW"},
            },
            "S-BETA-003": {
                "SpectraMax Plate Reader": {"abs_450": 0.88, "abs_570": 0.21, "plate_qc_status": "REVIEW"},
                "Agilent Bioanalyzer RNA QC": {"rin": 5.6, "fragment_size_bp": 510, "rna_concentration": 14.1, "bioanalyzer_status": "REVIEW"},
            },
            "S-GAMMA-001": {
                "Endosafe Endotoxin Test": {"endotoxin_eu_ml": 0.11, "spike_recovery_percent": 102.5, "lal_status": "PASS"},
                "qPCR Quantification": {"ct_value": 24.1, "delta_ct": 0.8, "qpcr_status": "PASS"},
            },
            "S-GAMMA-002": {
                "Endosafe Endotoxin Test": {"endotoxin_eu_ml": 0.91, "spike_recovery_percent": 68.4, "lal_status": "REVIEW"},
                "qPCR Quantification": {"ct_value": 36.7, "delta_ct": 11.4, "qpcr_status": "REVIEW"},
            },
        }

        for sample in samples:
            sample_results = extra_instrument_results.get(sample.sample_id, {})
            for work_item_name, values in sample_results.items():
                work_item, _ = get_or_create_safe(
                    WorkItem,
                    {"sample": sample, "name": work_item_name},
                    {"status": "COMPLETED", "notes": "Demo result set from a real-style lab instrument."},
                )
                for key, value in values.items():
                    upsert_result(work_item, key, value)

        # --------------------------------------------------
        # Demo import jobs
        # --------------------------------------------------
        touched_sample_ids = [sample.id for sample in samples]
        created_sample_ids = [sample_by_code["S-ALPHA-001"].id, sample_by_code["S-ALPHA-002"].id]
        matched_sample_ids = [sample.id for sample in samples if sample.id not in created_sample_ids]

        import_job, _ = get_or_create_safe(
            ImportJob,
            {"instrument": novaflex, "run_id": "DEMO-RUN-001"},
            {
                "project": project_alpha,
                "uploaded_by": peter,
                "source_type": "UPLOAD",
                "status": "COMPLETED",
                "progress_current": len(samples),
                "progress_total": len(samples),
                "progress_message": "Demo NovaFlex import completed",
                "summary": {
                    "rows_processed": len(samples),
                    "samples_created": 2,
                    "samples_matched": len(samples) - 2,
                    "results_created": len(samples) * 4,
                    "skipped_rows": [
                        {
                            "row": 10,
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
                    "rows_processed": len(samples),
                    "results_created": len(samples) * 4,
                    "touched_sample_ids": touched_sample_ids,
                },
            },
        )

        demo_import_jobs = [
            {"instrument": instruments["MISEQ"], "run_id": "MISEQ-RUN-2026-001", "project": project_alpha, "rows_processed": 4, "results_created": 16, "message": "MiSeq sequencing QC import completed", "sample_ids": [sample_by_code[k].id for k in ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003", "S-ALPHA-004"]]},
            {"instrument": instruments["NANODROP"], "run_id": "NANODROP-RUN-2026-001", "project": project_alpha, "rows_processed": 3, "results_created": 12, "message": "NanoDrop purity import completed", "sample_ids": [sample_by_code[k].id for k in ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003"]]},
            {"instrument": instruments["ENDOSAFE"], "run_id": "ENDOSAFE-RUN-2026-001", "project": project_gamma, "rows_processed": 5, "results_created": 15, "message": "Endotoxin test import completed", "sample_ids": [sample_by_code[k].id for k in ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003", "S-GAMMA-001", "S-GAMMA-002"]]},
            {"instrument": instruments["QPCR-7500"], "run_id": "QPCR-RUN-2026-001", "project": project_gamma, "rows_processed": 5, "results_created": 15, "message": "qPCR quantification import completed", "sample_ids": [sample_by_code[k].id for k in ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003", "S-GAMMA-001", "S-GAMMA-002"]]},
            {"instrument": instruments["SPECTRAMAX"], "run_id": "PLATE-RUN-2026-001", "project": project_beta, "rows_processed": 3, "results_created": 9, "message": "SpectraMax plate reader import completed", "sample_ids": [sample_by_code[k].id for k in ["S-BETA-001", "S-BETA-002", "S-BETA-003"]]},
            {"instrument": instruments["SANGER-3500"], "run_id": "SANGER-RUN-2026-001", "project": project_beta, "rows_processed": 2, "results_created": 6, "message": "Sanger sequencing QC import completed", "sample_ids": [sample_by_code[k].id for k in ["S-BETA-001", "S-BETA-002"]]},
            {"instrument": instruments["BIOANALYZER"], "run_id": "BIOANALYZER-RUN-2026-001", "project": project_beta, "rows_processed": 2, "results_created": 8, "message": "Bioanalyzer RNA QC import completed", "sample_ids": [sample_by_code[k].id for k in ["S-ALPHA-004", "S-BETA-003"]]},
            {"instrument": instruments["CYTATION5"], "run_id": "CYTATION-RUN-2026-001", "project": project_beta, "rows_processed": 2, "results_created": 8, "message": "Cytation imaging import completed", "sample_ids": [sample_by_code[k].id for k in ["S-BETA-001", "S-BETA-002"]]},
            {"instrument": instruments["HAMILTON-STAR"], "run_id": "HAMILTON-RUN-2026-001", "project": project_alpha, "rows_processed": 1, "results_created": 3, "message": "Liquid handler transfer log import completed", "sample_ids": [sample_by_code["S-ALPHA-004"].id]},
        ]

        for job_data in demo_import_jobs:
            demo_job, _ = get_or_create_safe(
                ImportJob,
                {"instrument": job_data["instrument"], "run_id": job_data["run_id"]},
                {
                    "project": job_data["project"],
                    "uploaded_by": peter,
                    "source_type": "UPLOAD",
                    "status": "COMPLETED",
                    "progress_current": job_data["rows_processed"],
                    "progress_total": job_data["rows_processed"],
                    "progress_message": job_data["message"],
                    "summary": {
                        "rows_processed": job_data["rows_processed"],
                        "samples_created": 0,
                        "samples_matched": len(job_data["sample_ids"]),
                        "results_created": job_data["results_created"],
                        "skipped_rows": [],
                        "project_id": job_data["project"].id,
                        "created_sample_ids": [],
                        "matched_sample_ids": job_data["sample_ids"],
                        "touched_sample_ids": job_data["sample_ids"],
                    },
                },
            )

            Event.objects.get_or_create(
                entity_type="ImportJob",
                entity_id=str(demo_job.id),
                action="RESULTS_IMPORTED",
                defaults={
                    "actor": peter,
                    "payload": {
                        "instrument_code": job_data["instrument"].code,
                        "instrument_name": job_data["instrument"].name,
                        "run_id": job_data["run_id"],
                        "rows_processed": job_data["rows_processed"],
                        "results_created": job_data["results_created"],
                        "touched_sample_ids": job_data["sample_ids"],
                    },
                },
            )

            for sample_id in job_data["sample_ids"]:
                Event.objects.get_or_create(
                    entity_type="Sample",
                    entity_id=str(sample_id),
                    action="RESULTS_IMPORTED",
                    defaults={
                        "actor": peter,
                        "payload": {
                            "sample_id": sample_id,
                            "source": "instrument_import",
                            "instrument_code": job_data["instrument"].code,
                            "import_job_id": demo_job.id,
                            "run_id": job_data["run_id"],
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
                "message": "Demo imports completed across sequencing, endotoxin, qPCR, plate reader, and NanoDrop instruments.",
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

        Notification.objects.get_or_create(
            user=peter,
            title="QC review needed",
            defaults={
                "message": "S-ALPHA-003 and S-GAMMA-002 have REVIEW instrument results.",
                "link": "/analyze",
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
            defaults=clean_kwargs(
                Sequence,
                {
                    "description": "Demo SeqViz workspace linked to the Alpha Assay Validation project.",
                    "sequence_type": "DNA",
                    "sequence": demo_sequence_text,
                    "sample": sample_by_code.get("S-ALPHA-001"),
                    "viewer": "both",
                    "show_complement": True,
                    "rotate_on_scroll": False,
                    "zoom": 50,
                    "enzymes": ["EcoRI", "BamHI", "HindIII", "PstI", "XhoI"],
                    "bp_colors": {"A": "#ef4444", "T": "#3b82f6", "G": "#22c55e", "C": "#f59e0b"},
                    "created_by": peter,
                    "source_type": "MANUAL",
                    "source_metadata": {"demo": True, "purpose": "seqviz_demo"},
                },
            ),
        )

        sequence_workspace.features.all().delete()

        demo_features = [
            {"feature_type": "ANNOTATION", "name": "Promoter", "start": 0, "end": 35, "direction": 1, "color": "#2563eb", "metadata": {}},
            {"feature_type": "ANNOTATION", "name": "BamHI", "start": 37, "end": 43, "direction": 1, "color": "#f97316", "metadata": {}},
            {"feature_type": "ANNOTATION", "name": "GFP CDS", "start": 43, "end": 763, "direction": 1, "color": "#22c55e", "metadata": {}},
            {"feature_type": "PRIMER", "name": "GFP Forward", "start": 43, "end": 63, "direction": 1, "color": "#9333ea", "metadata": {}},
            {"feature_type": "PRIMER", "name": "GFP Reverse", "start": 730, "end": 760, "direction": -1, "color": "#db2777", "metadata": {}},
            {"feature_type": "TRANSLATION", "name": "GFP Translation", "start": 43, "end": 763, "direction": 1, "color": "#16a34a", "metadata": {}},
            {"feature_type": "HIGHLIGHT", "name": "QC Review Region", "start": 120, "end": 180, "direction": 1, "color": "#fde047", "metadata": {}},
        ]

        for feature_data in demo_features:
            SequenceFeature.objects.create(sequence_record=sequence_workspace, **feature_data)

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
        # Additional demo sequences for alignment workflow
        # --------------------------------------------------
        alignment_demo_sequences = [
            {"name": "S-ALPHA-001 GFP Reference", "sample": sample_by_code.get("S-ALPHA-001"), "sequence": "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCACCGGCAAG"},
            {"name": "S-ALPHA-002 GFP Variant A", "sample": sample_by_code.get("S-ALPHA-002"), "sequence": "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCACCGGCAA"},
            {"name": "S-ALPHA-003 GFP Variant B", "sample": sample_by_code.get("S-ALPHA-003"), "sequence": "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCGGCAAG"},
            {"name": "S-ALPHA-004 MiSeq Consensus Read", "sample": sample_by_code.get("S-ALPHA-004"), "sequence": "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAG"},
        ]

        for item in alignment_demo_sequences:
            sequence_record, _ = Sequence.objects.update_or_create(
                name=item["name"],
                defaults=clean_kwargs(
                    Sequence,
                    {
                        "description": "Demo sequence for Clustal Omega alignment workflow.",
                        "sequence_type": "DNA",
                        "sequence": item["sequence"],
                        "sample": item["sample"],
                        "project": project_alpha,
                        "viewer": "both",
                        "show_complement": True,
                        "rotate_on_scroll": False,
                        "zoom": 50,
                        "enzymes": ["EcoRI", "BamHI", "HindIII"],
                        "bp_colors": {"A": "#ef4444", "T": "#3b82f6", "G": "#22c55e", "C": "#f59e0b"},
                        "created_by": peter,
                        "source_type": "MANUAL",
                        "source_metadata": {"demo": True, "purpose": "alignment_demo"},
                    },
                ),
            )

            Event.objects.get_or_create(
                entity_type="Sequence",
                entity_id=str(sequence_record.id),
                action="SEQUENCE_WORKSPACE_SEEDED",
                defaults={
                    "actor": peter,
                    "payload": {
                        "sequence_id": sequence_record.id,
                        "name": sequence_record.name,
                        "project_id": project_alpha.id,
                        "sample_id": item["sample"].id if item["sample"] else None,
                        "purpose": "alignment_demo",
                    },
                },
            )

        # --------------------------------------------------
        # Demo project feed posts
        # --------------------------------------------------
        demo_project_posts = [
            {"project": project_alpha, "author": admin, "note": "Initial project setup is complete. Alpha validation samples S-ALPHA-001 through S-ALPHA-004 are assigned to BOX-A1."},
            {"project": project_alpha, "author": peter, "note": "NovaFlex, MiSeq, NanoDrop, Endosafe, qPCR, and Hamilton demo imports have completed for the Alpha sample set."},
            {"project": project_alpha, "author": viewer, "note": "Review note: S-ALPHA-003 appears to need QC review due to lower sequencing quality and endotoxin recovery."},
            {"project": project_beta, "author": admin, "note": "Beta Stability Study has been initialized. Samples are linked to storage locations for tracking."},
            {"project": project_beta, "author": peter, "note": "SpectraMax, Sanger, Bioanalyzer, and Cytation demo results are available for review."},
            {"project": project_gamma, "author": admin, "note": "Gamma Endotoxin Release Testing is ready for endotoxin and qPCR review."},
            {"project": project_gamma, "author": peter, "note": "S-GAMMA-002 is flagged for review due to elevated endotoxin and high Ct value."},
        ]

        for post_data in demo_project_posts:
            ProjectPost.objects.get_or_create(
                project=post_data["project"],
                author=post_data["author"],
                note=post_data["note"],
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("")
        self.stdout.write("Demo users:")
        self.stdout.write("  admin / Admin123456!")
        self.stdout.write("  peter / peter123")
        self.stdout.write("  viewer / viewer123")
