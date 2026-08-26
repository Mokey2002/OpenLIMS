import hashlib
import os
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.utils import timezone

from django.contrib.contenttypes.models import ContentType

from inventory.models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from samples.models import Sample, SampleBatch, SampleCustodyEvent, SampleRelationship
from results.models import WorkItem, Result
from imports.models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from events.models import Event
from notifications.models import Notification
from sequences.models import (
    AssemblyFragment,
    ConstructAssemblyPlan,
    Sequence,
    SequenceFeature,
    SequenceFeatureLibrary,
)
from projects.models import Project, ProjectPost
from blast.models import BlastDatabase
from blast.services import build_blast_database
from mass_spec.models import MassSpecRun

User = get_user_model()
def seed_blast_demo(project, sample, director):
    demo_query_sequence = (
        "ATGCGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTA"
    )

    demo_reference_fasta = """>BLAST_REF_ALPHA perfect_match_alpha
ATGCGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTA
>BLAST_REF_BETA near_match_beta
ATGCGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTT
>BLAST_REF_GAMMA distant_match_gamma
TTTTGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTA
"""

    sequence, _ = Sequence.objects.update_or_create(
        name="BLAST Demo Query",
        project=project,
        defaults={
            "description": (
                "Seeded DNA query sequence designed to match the demo BLAST database."
            ),
            "sequence_type": "DNA",
            "sequence": demo_query_sequence,
            "sample": sample,
            "source_type": "MANUAL",
            "source_metadata": {
                "demo": True,
                "purpose": "blast_demo_query",
            },
            "created_by": director,
        },
    )

    blast_db, _ = BlastDatabase.objects.update_or_create(
        name="Demo DNA BLAST DB",
        defaults={
            "description": "Seeded local DNA BLAST database for demo searches.",
            "database_type": BlastDatabase.DATABASE_TYPE_DNA,
            "created_by": director,
            "status": BlastDatabase.STATUS_NEW,
            "error_message": "",
        },
    )

    blast_db.source_fasta.save(
        "demo_dna_blast_db.fasta",
        ContentFile(demo_reference_fasta.encode("utf-8")),
        save=True,
    )

    try:
        build_blast_database(blast_db, actor=director)
    except Exception as exc:
        blast_db.status = BlastDatabase.STATUS_FAILED
        blast_db.error_message = str(exc)
        blast_db.save(update_fields=["status", "error_message", "updated_at"])

    Event.objects.get_or_create(
        entity_type="BlastDatabase",
        entity_id=str(blast_db.id),
        action="BLAST_DEMO_DATABASE_SEEDED",
        defaults={
            "actor": director,
            "payload": {
                "blast_database_id": blast_db.id,
                "name": blast_db.name,
                "database_type": blast_db.database_type,
                "status": blast_db.status,
                "query_sequence_id": sequence.id,
                "query_sequence_name": sequence.name,
            },
        },
    )

    return sequence, blast_db

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


def create_demo_user(
    username,
    group,
    *,
    email,
    first_name,
    last_name,
    is_admin=False,
    password=None,
):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
        },
    )

    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    if password:
        user.set_password(password)
    elif created:
        user.set_unusable_password()
    user.is_staff = is_admin
    user.is_superuser = is_admin
    user.is_active = True
    user.save()

    user.groups.add(group)

    return user


def set_result_value(work_item, key, value):
    if isinstance(value, bool):
        defaults = {
            "value_type": "BOOLEAN",
            "value_boolean": value,
            "value_number": None,
            "value_string": "",
        }
    elif isinstance(value, (int, float)):
        defaults = {
            "value_type": "NUMBER",
            "value_number": value,
            "value_string": "",
            "value_boolean": None,
        }
    else:
        defaults = {
            "value_type": "STRING",
            "value_string": str(value),
            "value_number": None,
            "value_boolean": None,
        }

    reference_ranges = {
        "mean_q_score": (30, 45, "score"),
        "percent_q30": (80, 100, "%"),
        "purity": (90, 100, "%"),
        "spike_recovery_percent": (80, 120, "%"),
        "quality_score": (60, 100, "score"),
        "rin": (7, 10, "score"),
    }
    if key in reference_ranges and isinstance(value, (int, float)):
        minimum, maximum, unit = reference_ranges[key]
        passed = minimum <= value <= maximum
        defaults.update(
            {
                "reference_min": minimum,
                "reference_max": maximum,
                "unit": unit,
                "qc_rule": f"{key} must be between {minimum} and {maximum} {unit}.",
                "qc_passed": passed,
                "qc_failure_reason": (
                    "" if passed else f"{value} {unit} is outside {minimum} to {maximum}."
                ),
            }
        )
    elif isinstance(value, str) and value.upper() in {"PASS", "FAIL", "REVIEW"}:
        passed = value.upper() == "PASS"
        defaults.update(
            {
                "qc_rule": "Instrument QC status must be PASS.",
                "qc_passed": passed,
                "qc_failure_reason": "" if passed else f"Instrument reported {value.upper()}.",
            }
        )

    result, _ = Result.objects.update_or_create(
        work_item=work_item,
        key=key,
        defaults=clean_kwargs(Result, defaults),
    )
    return result


def link_demo_import_job(import_job, sample_codes, work_item_name, actor=None):
    """Attach seeded result work to its originating instrument import job.

    The explicit update keeps the demo upgrade-safe: running ``seed_demo`` on
    an older database adds v0.24 provenance to existing work items as well as
    newly seeded ones.
    """
    work_items = WorkItem.objects.filter(
        sample__sample_id__in=sample_codes,
        name=work_item_name,
    )
    linked_work_item_count = work_items.update(source_import_job=import_job)
    if actor:
        work_items.filter(created_by__isnull=True).update(created_by=actor)

    return {
        "linked_sample_count": work_items.values("sample_id").distinct().count(),
        "linked_work_item_count": linked_work_item_count,
        "linked_result_count": Result.objects.filter(work_item__in=work_items).count(),
    }


def create_or_update_instrument(instrument_config):
    """Create or update an instrument by code or name.

    This keeps seed_demo safe to run multiple times, even if an older
    demo database already has an instrument with the same unique name.
    """
    code = instrument_config["code"]
    name = instrument_config["name"]

    instrument = InstrumentProfile.objects.filter(code=code).first()

    if instrument is None:
        instrument = InstrumentProfile.objects.filter(name=name).first()

    defaults = {
        "code": code,
        "name": name,
        "delimiter": instrument_config["delimiter"],
        "has_header": instrument_config["has_header"],
        "header_row_index": instrument_config.get("header_row_index", 0),
        "auto_detect_header": instrument_config.get("auto_detect_header", True),
        "sample_id_column": instrument_config["sample_id_column"],
    }

    if instrument is None:
        instrument = InstrumentProfile.objects.create(
            **clean_kwargs(InstrumentProfile, defaults)
        )
    else:
        for field_name, value in clean_kwargs(InstrumentProfile, defaults).items():
            setattr(instrument, field_name, value)
        instrument.save()

    for source_column, target_key, value_type, min_value, max_value, allowed_values in instrument_config["mappings"]:
        InstrumentColumnMapping.objects.update_or_create(
            instrument=instrument,
            source_column=source_column,
            defaults=clean_kwargs(
                InstrumentColumnMapping,
                {
                    "target_key": target_key,
                    "value_type": value_type,
                    "min_value": min_value,
                    "max_value": max_value,
                    "allowed_values": allowed_values,
                },
            ),
        )

    return instrument



def build_demo_chromatogram(offset=0, scale=1.0):
    points = []

    for i in range(18):
        rt = 5.0 + i * 2.5
        peak_shape = max(0.05, 1 - abs(i - 9) / 10)
        total_intensity = round((1200 * peak_shape * scale) + offset + (i * 9), 2)

        points.append(
            {
                "rt": rt,
                "total_intensity": total_intensity,
                "ms_level": 1 if i % 5 != 0 else 2,
            }
        )

    return points


def build_demo_features(shared_base=150.0, unique_base=300.0, scale=1.0):
    return [
        {
            "mz": shared_base,
            "rt_min": 12.5,
            "rt_max": 24.5,
            "apex_rt": 17.5,
            "apex_intensity": round(950.0 * scale, 2),
            "total_intensity": round(3200.0 * scale, 2),
            "peak_count": 6,
            "ms_level": 1,
        },
        {
            "mz": 225.1,
            "rt_min": 20.0,
            "rt_max": 35.0,
            "apex_rt": 27.5,
            "apex_intensity": round(700.0 * scale, 2),
            "total_intensity": round(2600.0 * scale, 2),
            "peak_count": 5,
            "ms_level": 1,
        },
        {
            "mz": unique_base,
            "rt_min": 32.5,
            "rt_max": 45.0,
            "apex_rt": 37.5,
            "apex_intensity": round(520.0 * scale, 2),
            "total_intensity": round(1900.0 * scale, 2),
            "peak_count": 4,
            "ms_level": 1,
        },
    ]


def seed_mass_spec_demo(project_alpha, project_beta, sample_by_code, director, peter, maria, michael):
    demo_runs = [
        {
            "name": "Alpha LC-MS Demo Run 001",
            "project": project_alpha,
            "sample": sample_by_code.get("S-ALPHA-001"),
            "user": maria,
            "filename": "alpha_lcms_demo_run_001.mzML",
            "offset": 0,
            "scale": 1.00,
            "shared_mz": 150.02,
            "unique_mz": 301.10,
            "proteins": 4,
            "peptides": 11,
        },
        {
            "name": "Alpha LC-MS Demo Run 002",
            "project": project_alpha,
            "sample": sample_by_code.get("S-ALPHA-001"),
            "user": peter,
            "filename": "alpha_lcms_demo_run_002.mzML",
            "offset": 90,
            "scale": 1.12,
            "shared_mz": 150.04,
            "unique_mz": 315.25,
            "proteins": 5,
            "peptides": 13,
        },
        {
            "name": "Alpha LC-MS Demo Run 003 QC Review",
            "project": project_alpha,
            "sample": sample_by_code.get("S-ALPHA-003"),
            "user": michael,
            "filename": "alpha_lcms_demo_run_003_qc_review.mzML",
            "offset": -80,
            "scale": 0.72,
            "shared_mz": 150.01,
            "unique_mz": 330.40,
            "proteins": 2,
            "peptides": 6,
        },
        {
            "name": "Alpha OpenMS featureXML Demo",
            "project": project_alpha,
            "sample": sample_by_code.get("S-ALPHA-002"),
            "user": maria,
            "filename": "alpha_openms_features_demo.featureXML",
            "offset": 40,
            "scale": 0.95,
            "shared_mz": 150.03,
            "unique_mz": 410.75,
            "proteins": 0,
            "peptides": 0,
            "file_type": "featureXML",
        },
        {
            "name": "Beta mzIdentML Demo IDs",
            "project": project_beta,
            "sample": sample_by_code.get("S-BETA-001"),
            "user": director,
            "filename": "beta_identifications_demo.mzid",
            "offset": 20,
            "scale": 0.85,
            "shared_mz": 180.05,
            "unique_mz": 500.25,
            "proteins": 6,
            "peptides": 18,
            "file_type": "mzIdentML",
        },
    ]

    for item in demo_runs:
        chromatogram_data = build_demo_chromatogram(
            offset=item["offset"],
            scale=item["scale"],
        )
        detected_features = build_demo_features(
            shared_base=item["shared_mz"],
            unique_base=item["unique_mz"],
            scale=item["scale"],
        )

        total_intensities = [
            point["total_intensity"]
            for point in chromatogram_data
        ]

        top_peaks = [
            {
                "rt": feature["apex_rt"],
                "mz": feature["mz"],
                "intensity": feature["apex_intensity"],
                "ms_level": feature["ms_level"],
            }
            for feature in detected_features
        ]

        top_proteins = [
            {
                "accession": f"DEMO_PROT_{index + 1}",
                "description": f"Demo protein identification {index + 1}",
                "peptide_count": max(1, item["peptides"] // max(1, item["proteins"])),
                "score": round(95.0 - index * 4.5, 2),
            }
            for index in range(item["proteins"])
        ]

        top_peptides = [
            {
                "sequence": f"PEPTIDESEQ{index + 1}",
                "score": round(80.0 - index * 2.1, 2),
                "protein_accessions": [top_proteins[index % len(top_proteins)]["accession"]]
                if top_proteins
                else [],
                "charge": "2",
            }
            for index in range(item["peptides"])
        ]

        file_type = item.get("file_type", "mzML")

        run, _ = MassSpecRun.objects.update_or_create(
            name=item["name"],
            defaults={
                "project": item["project"],
                "sample": item["sample"],
                "uploaded_by": item["user"],
                "original_filename": item["filename"],
                "status": MassSpecRun.STATUS_COMPLETED,
                "error_message": "",
                "spectra_count": len(chromatogram_data),
                "ms1_count": len([p for p in chromatogram_data if p["ms_level"] == 1]),
                "ms2_count": len([p for p in chromatogram_data if p["ms_level"] == 2]),
                "rt_min": min(p["rt"] for p in chromatogram_data),
                "rt_max": max(p["rt"] for p in chromatogram_data),
                "mz_min": min(f["mz"] for f in detected_features) - 50,
                "mz_max": max(f["mz"] for f in detected_features) + 50,
                "chromatogram_data": chromatogram_data,
                "peak_count": sum(f["peak_count"] for f in detected_features),
                "base_peak_mz": detected_features[0]["mz"],
                "base_peak_intensity": detected_features[0]["apex_intensity"],
                "top_peaks": top_peaks,
                "feature_count": len(detected_features),
                "detected_features": detected_features,
                "featurexml_count": len(detected_features) if file_type == "featureXML" else 0,
                "consensusxml_count": 0,
                "openms_summary": {
                    "file_type": file_type,
                    "demo": True,
                    "source": "seed_demo",
                    "purpose": "mass_spec_comparison_demo",
                },
                "protein_count": item["proteins"],
                "peptide_count": item["peptides"],
                "top_proteins": top_proteins,
                "top_peptides": top_peptides,
                "identification_summary": {
                    "file_type": file_type,
                    "protein_count": item["proteins"],
                    "peptide_count": item["peptides"],
                    "top_proteins": top_proteins,
                    "top_peptides": top_peptides,
                    "note": "Seeded demo identification summary for mass spec comparison.",
                },
                "total_ion_current": round(sum(total_intensities), 2),
                "mean_total_intensity": round(sum(total_intensities) / len(total_intensities), 2),
                "max_total_intensity": round(max(total_intensities), 2),
                "mean_peak_intensity": round(
                    sum(peak["intensity"] for peak in top_peaks) / len(top_peaks),
                    2,
                ),
                "rt_span": round(
                    max(p["rt"] for p in chromatogram_data)
                    - min(p["rt"] for p in chromatogram_data),
                    2,
                ),
                "mz_span": round(
                    (max(f["mz"] for f in detected_features) + 50)
                    - (min(f["mz"] for f in detected_features) - 50),
                    2,
                ),
                "ms1_ratio": round(
                    len([p for p in chromatogram_data if p["ms_level"] == 1])
                    / len(chromatogram_data),
                    4,
                ),
                "ms2_ratio": round(
                    len([p for p in chromatogram_data if p["ms_level"] == 2])
                    / len(chromatogram_data),
                    4,
                ),
            },
        )

        run.uploaded_file.save(
            item["filename"],
            ContentFile(
                (
                    f"Seeded demo placeholder for {item['name']}.\n"
                    "This record is pre-processed for OpenLIMS demo comparison workflows.\n"
                ).encode("utf-8")
            ),
            save=True,
        )

        Event.objects.get_or_create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_DEMO_SEEDED",
            defaults={
                "actor": item["user"],
                "payload": {
                    "name": run.name,
                    "original_filename": run.original_filename,
                    "project": run.project_id,
                    "sample": run.sample_id,
                    "feature_count": run.feature_count,
                    "protein_count": run.protein_count,
                    "peptide_count": run.peptide_count,
                    "demo": True,
                },
            },
        )

    Notification.objects.get_or_create(
        user=director,
        title="Mass spec comparison demo ready",
        defaults={
            "message": "Seeded mass spec runs are ready for project, sample, and manual comparison.",
            "link": "/mass-spec/compare",
        },
    )


def ensure_sequence_revision(sequence_record, actor, change_summary):
    """Return a current immutable revision without creating duplicates on rerun."""
    from sequences.services import create_sequence_revision

    sequence_record.refresh_from_db()
    revision = sequence_record.current_revision or sequence_record.revisions.first()
    if revision:
        updates = []
        for field in ["sequence", "sequence_type", "topology", "source_metadata"]:
            value = getattr(revision, field)
            if getattr(sequence_record, field) != value:
                setattr(sequence_record, field, value)
                updates.append(field)
        if sequence_record.current_revision_id != revision.id:
            sequence_record.current_revision = revision
            updates.append("current_revision")
        if updates:
            sequence_record.save(update_fields=[*updates, "updated_at"])
        return revision
    return create_sequence_revision(
        sequence_record,
        actor=actor,
        change_summary=change_summary,
        audit_action="SEQUENCE_DEMO_REVISION_SEEDED",
    )


def seed_traceability_inventory_demo(project, director, maria, rack_a, rack_b):
    """Seed nested storage, reservations, lineage, barcodes, and custody history."""
    from assistant.models import BarcodeLabel, GeneratedArtifact
    from custom_fields.models import FieldDefinition, FieldValue

    shelf, _ = Container.objects.get_or_create(
        container_id="BOX-A1-SHELF-01",
        defaults={"kind": "shelf", "location": rack_a.location, "parent": rack_a},
    )
    tube_box, _ = Container.objects.get_or_create(
        container_id="BOX-A1-TUBES-01",
        defaults={"kind": "tube box", "location": rack_a.location, "parent": shelf},
    )

    reagent, _ = InventoryItem.objects.get_or_create(
        code="GIBSON-MIX",
        defaults={
            "name": "Gibson Assembly Master Mix",
            "category": InventoryItem.CATEGORY_REAGENT,
            "default_unit": "uL",
            "reorder_level": Decimal("100"),
        },
    )
    lot, _ = InventoryLot.objects.get_or_create(
        lot_code="GIBSON-DEMO-2026-01",
        defaults={
            "item": reagent,
            "quantity": Decimal("500"),
            "unit": "uL",
            "expiration_date": (timezone.now() + timedelta(days=120)).date(),
            "status": InventoryLot.STATUS_ACTIVE,
            "location": rack_a.location,
            "container": tube_box,
        },
    )
    InventoryReservation.objects.get_or_create(
        lot=lot,
        project=project,
        status=InventoryReservation.STATUS_ACTIVE,
        defaults={
            "quantity": Decimal("75"),
            "unit": "uL",
            "created_by": maria,
        },
    )
    InventoryReservation.objects.get_or_create(
        lot=lot,
        project=project,
        status=InventoryReservation.STATUS_CONSUMED,
        defaults={
            "quantity": Decimal("25"),
            "unit": "uL",
            "created_by": maria,
        },
    )

    sample_specs = [
        ("LIN-PARENT-001", "PRIMARY", rack_a),
        ("LIN-ALIQUOT-001", "ALIQUOT", tube_box),
        ("LIN-SPLIT-001", "ALIQUOT", tube_box),
        ("LIN-POOL-001", "POOLED", rack_b),
    ]
    lineage_samples = {}
    for sample_id, sample_type, container in sample_specs:
        sample, _ = Sample.objects.update_or_create(
            sample_id=sample_id,
            defaults={
                "sample_type": sample_type,
                "status": Sample.STATUS_IN_PROGRESS,
                "project": project,
                "container": container,
                "assigned_to": maria,
                "created_by": director,
            },
        )
        lineage_samples[sample_id] = sample
        BarcodeLabel.objects.update_or_create(
            sample=sample,
            template="STANDARD_SAMPLE",
            defaults={
                "barcode": sample.sample_id,
                "generation_count": 1,
                "last_generated_by": director,
                "last_generated_at": timezone.now(),
            },
        )

    label_content = (
        b"%PDF-1.4\n% OpenLIMS demo barcode labels\n"
        + "\n".join(lineage_samples).encode("utf-8")
        + b"\n%%EOF\n"
    )
    label_artifact = GeneratedArtifact.objects.filter(
        filename="openlims_demo_sample_labels.pdf"
    ).first()
    if not label_artifact:
        label_artifact = GeneratedArtifact.objects.create(
            kind=GeneratedArtifact.KIND_LABEL_PDF,
            filename="openlims_demo_sample_labels.pdf",
            content_type="application/pdf",
            checksum_sha256=hashlib.sha256(label_content).hexdigest(),
            parameters={
                "template": "STANDARD_SAMPLE",
                "sample_ids": list(lineage_samples),
                "demo": True,
            },
            project=project,
            created_by=director,
        )
        label_artifact.file.save(
            label_artifact.filename,
            ContentFile(label_content),
            save=True,
        )
    BarcodeLabel.objects.filter(sample__in=lineage_samples.values()).update(
        last_artifact=label_artifact,
        last_generated_by=director,
        last_generated_at=timezone.now(),
    )

    relationship_specs = [
        ("LIN-PARENT-001", "LIN-ALIQUOT-001", SampleRelationship.TYPE_ALIQUOT, "250", "uL"),
        ("LIN-PARENT-001", "LIN-SPLIT-001", SampleRelationship.TYPE_SPLIT, "250", "uL"),
        ("LIN-ALIQUOT-001", "LIN-POOL-001", SampleRelationship.TYPE_POOL_COMPONENT, "50", "uL"),
        ("LIN-SPLIT-001", "LIN-POOL-001", SampleRelationship.TYPE_POOL_COMPONENT, "50", "uL"),
    ]
    for source_id, derived_id, relationship_type, quantity, unit in relationship_specs:
        SampleRelationship.objects.get_or_create(
            source_sample=lineage_samples[source_id],
            derived_sample=lineage_samples[derived_id],
            relationship_type=relationship_type,
            defaults={
                "quantity": Decimal(quantity),
                "unit": unit,
                "reason": "Seeded demonstration of aliquoting, splitting, and pooling.",
                "created_by": maria,
            },
        )

    custody_sample = lineage_samples["LIN-ALIQUOT-001"]
    custody_specs = [
        (SampleCustodyEvent.ACTION_RECEIVE, None, tube_box, None, None, "Received and scanned into storage."),
        (SampleCustodyEvent.ACTION_CHECK_OUT, tube_box, tube_box, None, maria, "Checked out for plasmid preparation."),
        (SampleCustodyEvent.ACTION_PROCESS, tube_box, tube_box, maria, maria, "Processed at the molecular biology bench."),
        (SampleCustodyEvent.ACTION_CHECK_IN, tube_box, tube_box, maria, None, "Returned to controlled storage."),
    ]
    for action, from_container, to_container, from_custodian, to_custodian, reason in custody_specs:
        SampleCustodyEvent.objects.get_or_create(
            sample=custody_sample,
            action=action,
            scanned_code=custody_sample.sample_id,
            reason=reason,
            defaults={
                "from_container": from_container,
                "to_container": to_container,
                "from_custodian": from_custodian,
                "to_custodian": to_custodian,
                "performed_by": maria,
            },
        )
    custody_sample.container = tube_box
    custody_sample.custodian = None
    custody_sample.save(update_fields=["container", "custodian", "updated_at"])

    field_definition, _ = FieldDefinition.objects.get_or_create(
        entity_type="Sample",
        name="biosafety_level",
        defaults={
            "label": "Biosafety level",
            "data_type": "string",
            "required": True,
            "rules": {"allowed_values": ["BSL-1", "BSL-2"]},
        },
    )
    FieldValue.objects.update_or_create(
        field_definition=field_definition,
        entity_type="Sample",
        entity_id=str(custody_sample.id),
        defaults={"value": "BSL-1"},
    )
    return {"samples": lineage_samples, "lot": lot, "container": tube_box}


def seed_advanced_pipeline_demo(project, director, maria):
    """Seed configurable analyses and a live parallel/conditional pipeline."""
    from assistant.models import SOPDocument
    from pipelines.models import (
        AnalysisDefinition,
        PipelineRun,
        PipelineStepRun,
        PipelineTemplate,
        PipelineTemplateStep,
        ProcedureDefinition,
    )
    from pipelines.services import start_pipeline, sync_pipeline_step_from_work_item

    sop, _ = SOPDocument.objects.get_or_create(
        document_code="SOP-MOL-026",
        version="2",
        section="Complete procedure",
        defaults={
            "title": "Parallel plasmid characterization",
            "content": "Extract DNA, quantify it, amplify the insert, review QC, and interpret the construct.",
            "status": SOPDocument.STATUS_CURRENT,
            "approved": True,
            "project": project,
            "uploaded_by": director,
        },
    )

    definitions = [
        ("DEMO_DNA_EXTRACTION", "DNA Extraction", [{"key": "concentration", "value_type": "NUMBER", "required": True}], 45),
        ("DEMO_PCR", "PCR Amplification", [{"key": "amplification_status", "value_type": "STRING", "required": True}], 90),
        ("DEMO_SEQUENCE_QC", "Sequence QC", [{"key": "quality_score", "value_type": "NUMBER", "required": True}], 60),
        ("DEMO_INTERPRETATION", "Construct Interpretation", [{"key": "interpretation", "value_type": "STRING", "required": True}], 30),
        ("DEMO_CONFIRMATORY", "Optional Confirmatory Assay", [], 120),
    ]
    procedures = {}
    for code, name, required_fields, duration in definitions:
        analysis, _ = AnalysisDefinition.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": "Molecular Biology",
                "description": "Seeded configurable analysis for the advanced workflow demo.",
                "required_fields": required_fields,
                "active": True,
                "created_by": director,
            },
        )
        procedure, _ = ProcedureDefinition.objects.update_or_create(
            code=f"{code}_PROC",
            version="2",
            defaults={
                "name": f"{name} procedure",
                "analysis": analysis,
                "sop_document": sop,
                "instructions": f"Follow {sop.document_code} for {name.lower()}.",
                "estimated_duration_minutes": duration,
                "active": True,
                "created_by": director,
            },
        )
        procedures[code] = procedure

    template, _ = PipelineTemplate.objects.update_or_create(
        code="DEMO_PARALLEL_PLASMID",
        defaults={
            "name": "Parallel Plasmid Characterization",
            "description": "Demonstrates dependencies, parallel branches, QC gates, conditions, retries, and optional work.",
            "active": True,
            "is_default": True,
            "default_project": project,
            "default_sample_type": "PLASMID",
            "created_by": director,
        },
    )
    step_specs = [
        (1, "DEMO_DNA_EXTRACTION", [], {}, False, False, 0),
        (2, "DEMO_PCR", [1], {}, False, False, 2),
        (3, "DEMO_SEQUENCE_QC", [1], {}, True, False, 1),
        (4, "DEMO_INTERPRETATION", [2, 3], {"source_position": 3, "result_key": "quality_score", "operator": "GTE", "value": 80}, False, False, 0),
        (5, "DEMO_CONFIRMATORY", [2], {"source_position": 2, "result_key": "amplification_status", "operator": "EQ", "value": "REVIEW"}, False, True, 1),
    ]
    for position, code, dependencies, condition, requires_qc, optional, retries in step_specs:
        PipelineTemplateStep.objects.update_or_create(
            template=template,
            position=position,
            defaults={
                "procedure": procedures[code],
                "name": procedures[code].analysis.name,
                "requires_qc": requires_qc,
                "dependency_positions": dependencies,
                "activation_condition": condition,
                "optional": optional,
                "max_retries": retries,
            },
        )

    sample, _ = Sample.objects.update_or_create(
        sample_id="PIPE-DEMO-001",
        defaults={
            "sample_type": "PLASMID",
            "status": Sample.STATUS_IN_PROGRESS,
            "project": project,
            "assigned_to": maria,
            "created_by": director,
        },
    )
    run = PipelineRun.objects.filter(sample=sample, template=template).first()
    if not run:
        run = start_pipeline(sample=sample, template=template, actor=director)
        first_step = run.steps.get(position=1)
        set_result_value(first_step.work_item, "concentration", 42.5)
        first_step.work_item.status = WorkItem.STATUS_COMPLETED
        first_step.work_item.assigned_to = maria
        first_step.work_item.save(update_fields=["status", "assigned_to", "updated_at"])
        sync_pipeline_step_from_work_item(first_step.work_item, actor=maria)

        pcr_step = run.steps.get(position=2)
        pcr_step.work_item.status = WorkItem.STATUS_IN_PROGRESS
        pcr_step.work_item.assigned_to = maria
        pcr_step.work_item.save(update_fields=["status", "assigned_to", "updated_at"])
        sync_pipeline_step_from_work_item(pcr_step.work_item, actor=maria)

        qc_step = run.steps.get(position=3)
        set_result_value(qc_step.work_item, "quality_score", 92)
        qc_step.work_item.status = WorkItem.STATUS_COMPLETED
        qc_step.work_item.assigned_to = maria
        qc_step.work_item.save(update_fields=["status", "assigned_to", "updated_at"])
        sync_pipeline_step_from_work_item(qc_step.work_item, actor=maria)
    return run


def seed_registry_molecular_demo(project, director, maria, physical_sample):
    """Seed every Registry entity type plus representative immutable molecular records."""
    from registry.models import (
        RegistrationReview,
        RegistryAlias,
        RegistryRecord,
        RegistryRelationship,
        RegistrySchema,
    )
    from registry.services import create_record_version
    from sequences.services import create_sequence_revision

    schema_specs = {
        "plasmid": ("Plasmid", "PLS", {"backbone": {"type": "string"}, "resistance": {"type": "string"}}, ["backbone", "resistance"]),
        "oligo": ("Oligonucleotide", "OLG", {"purpose": {"type": "string"}}, ["purpose"]),
        "primer": ("Primer", "PRM", {"target": {"type": "string"}, "direction": {"type": "string"}}, ["target", "direction"]),
        "rna": ("RNA", "RNA", {"transcript": {"type": "string"}}, ["transcript"]),
        "protein": ("Protein", "PRO", {"gene": {"type": "string"}, "organism": {"type": "string"}}, ["gene", "organism"]),
        "antibody": ("Antibody", "AB", {"target": {"type": "string"}, "host": {"type": "string"}}, ["target", "host"]),
        "cell-line": ("Cell Line", "CL", {"species": {"type": "string"}, "tissue": {"type": "string"}}, ["species", "tissue"]),
        "strain": ("Strain", "STR", {"organism": {"type": "string"}}, ["organism"]),
        "organism": ("Organism", "ORG", {"taxonomy_id": {"type": "string"}}, ["taxonomy_id"]),
        "vector": ("Vector", "VEC", {"vector_class": {"type": "string"}}, ["vector_class"]),
        "construct": ("Construct", "CON", {"design": {"type": "string"}}, ["design"]),
        "custom-material": ("Custom Material", "MAT", {"material_type": {"type": "string"}}, ["material_type"]),
    }
    schemas = {}
    for code, (name, prefix, properties, matching_fields) in schema_specs.items():
        schema, _ = RegistrySchema.objects.get_or_create(
            code=code,
            version=1,
            defaults={
                "name": name,
                "entity_type": code,
                "id_prefix": prefix,
                "description": f"Demo schema for {name.lower()} registry records.",
                "schema": {"type": "object", "properties": properties},
                "matching_fields": matching_fields,
                "active": True,
                "created_by": director,
            },
        )
        schemas[code] = schema

    promoter_library, _ = SequenceFeatureLibrary.objects.get_or_create(
        project=project,
        name="T7 promoter",
        sequence_type="DNA",
        defaults={
            "feature_type": "ANNOTATION",
            "motif": "TAATACGACTCACTATAGGG",
            "color": "#2563eb",
            "qualifiers": {"function": "transcription promoter"},
            "created_by": director,
        },
    )
    primer_library, _ = SequenceFeatureLibrary.objects.get_or_create(
        project=project,
        name="GFP forward primer",
        sequence_type="DNA",
        defaults={
            "feature_type": "PRIMER",
            "motif": "ATGGTGAGCAAGGGCGAGGA",
            "color": "#9333ea",
            "qualifiers": {"target": "GFP"},
            "created_by": maria,
        },
    )

    plasmid_sequence, _ = Sequence.objects.update_or_create(
        name="Registry pOpenLIMS-GFP",
        project=project,
        defaults={
            "description": "Circular plasmid used to demonstrate immutable revisions, annotations, digest tools, and Registry links.",
            "sequence_type": "DNA",
            "topology": Sequence.TOPOLOGY_CIRCULAR,
            "sequence": "TAATACGACTCACTATAGGGGAATTCATGGTGAGCAAGGGCGAGGAGGGATCCTAA",
            "sample": physical_sample,
            "source_type": "GENBANK_IMPORT",
            "source_metadata": {"demo": True, "format": "genbank", "accession": "DEMO-PLASMID-001"},
            "enzymes": ["EcoRI", "BamHI"],
            "created_by": maria,
        },
    )
    plasmid_features = [
        ("ANNOTATION", "T7 promoter", 0, 20, 1, "#2563eb", promoter_library),
        ("ANNOTATION", "EcoRI", 23, 29, 1, "#f97316", None),
        ("PRIMER", "GFP forward", 29, 49, 1, "#9333ea", primer_library),
        ("ANNOTATION", "BamHI", 51, 57, 1, "#f97316", None),
    ]
    for feature_type, name, start, end, direction, color, library in plasmid_features:
        SequenceFeature.objects.update_or_create(
            sequence_record=plasmid_sequence,
            name=name,
            defaults={
                "feature_type": feature_type,
                "start": start,
                "end": end,
                "direction": direction,
                "color": color,
                "library_feature": library,
                "metadata": {"demo": True},
            },
        )
    first_revision = ensure_sequence_revision(
        plasmid_sequence, maria, "Imported circular plasmid with GenBank annotations"
    )
    if plasmid_sequence.revisions.count() < 2:
        plasmid_sequence.sequence = f"{first_revision.sequence}GCC"
        plasmid_sequence.save(update_fields=["sequence", "updated_at"])
        create_sequence_revision(
            plasmid_sequence,
            actor=maria,
            change_summary="Added assembly scar after virtual digest review",
        )

    primer_sequence, _ = Sequence.objects.update_or_create(
        name="Registry GFP Forward Primer",
        project=project,
        defaults={
            "description": "Linear primer sequence for Tm and GC demonstrations.",
            "sequence_type": "DNA",
            "topology": Sequence.TOPOLOGY_LINEAR,
            "sequence": "ATGGTGAGCAAGGGCGAGGA",
            "source_type": "FASTA_IMPORT",
            "source_metadata": {"demo": True, "format": "fasta"},
            "created_by": maria,
        },
    )
    primer_revision = ensure_sequence_revision(primer_sequence, maria, "Imported primer FASTA")

    protein_sequence, _ = Sequence.objects.update_or_create(
        name="Registry GFP Protein",
        project=project,
        defaults={
            "description": "Protein sequence for translation and molecular-weight demonstrations.",
            "sequence_type": "PROTEIN",
            "topology": Sequence.TOPOLOGY_LINEAR,
            "sequence": "MVSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLP",
            "source_type": "FASTA_IMPORT",
            "source_metadata": {"demo": True, "format": "fasta"},
            "created_by": maria,
        },
    )
    protein_revision = ensure_sequence_revision(protein_sequence, maria, "Imported protein FASTA")

    records = {}
    record_specs = [
        ("plasmid", "PLS-DEMO-0001", "pOpenLIMS-GFP", {"backbone": "pUC19", "resistance": "ampicillin"}, plasmid_sequence.current_revision, RegistryRecord.STATUS_REGISTERED),
        ("primer", "PRM-DEMO-0001", "GFP Forward Primer", {"target": "GFP", "direction": "forward"}, primer_revision, RegistryRecord.STATUS_REGISTERED),
        ("protein", "PRO-DEMO-0001", "Green Fluorescent Protein", {"gene": "gfp", "organism": "Aequorea victoria"}, protein_revision, RegistryRecord.STATUS_REGISTERED),
        ("antibody", "AB-DEMO-0001", "Anti-GFP monoclonal", {"target": "GFP", "host": "mouse"}, None, RegistryRecord.STATUS_IN_REVIEW),
        ("cell-line", "CL-DEMO-0001", "HEK293T Demo Bank", {"species": "human", "tissue": "kidney"}, None, RegistryRecord.STATUS_RETIRED),
    ]
    for entity_type, registry_id, name, data, revision, status in record_specs:
        record, _ = RegistryRecord.objects.get_or_create(
            registry_id=registry_id,
            defaults={
                "schema": schemas[entity_type],
                "name": name,
                "description": f"Seeded {entity_type} Registry demonstration record.",
                "catalog_number": f"CAT-{registry_id}",
                "external_identifiers": {"SISBI": f"LEGACY-{registry_id}"},
                "tags": ["demo", entity_type],
                "project": project,
                "owner": maria,
                "visibility": RegistryRecord.VISIBILITY_PROJECT,
                "lifecycle_status": status,
                "registered_at": timezone.now() if status == RegistryRecord.STATUS_REGISTERED else None,
                "retired_at": timezone.now() if status == RegistryRecord.STATUS_RETIRED else None,
            },
        )
        if not record.current_version_id:
            create_record_version(
                record,
                data=data,
                actor=maria,
                sequence_revision=revision,
                change_summary="Initial seeded registration snapshot",
                audit_action="REGISTRY_DEMO_RECORD_SEEDED",
            )
        RegistryAlias.objects.get_or_create(
            record=record,
            alias=f"{name} demo alias",
            defaults={"alias_type": "laboratory"},
        )
        records[entity_type] = record

    plasmid_record = records["plasmid"]
    if plasmid_record.versions.count() < 2:
        create_record_version(
            plasmid_record,
            data={"backbone": "pUC19", "resistance": "ampicillin", "verified": True},
            actor=director,
            sequence_revision=plasmid_record.current_version.sequence_revision,
            change_summary="Director verified construct identity",
        )
    RegistrationReview.objects.get_or_create(
        record=plasmid_record,
        version=plasmid_record.current_version,
        defaults={
            "requested_by": maria,
            "reviewer": director,
            "decision": RegistrationReview.DECISION_APPROVED,
            "comments": "Sequence, annotations, and metadata verified.",
            "reviewed_at": timezone.now(),
        },
    )
    RegistrationReview.objects.get_or_create(
        record=records["antibody"],
        version=records["antibody"].current_version,
        defaults={
            "requested_by": maria,
            "decision": RegistrationReview.DECISION_PENDING,
            "comments": "Awaiting director verification of vendor documentation.",
        },
    )

    relation_specs = [
        (plasmid_record, records["primer"], RegistryRelationship.RELATION_CONTAINS),
        (plasmid_record, records["protein"], RegistryRelationship.RELATION_EXPRESSES),
        (records["antibody"], records["protein"], RegistryRelationship.RELATION_BINDS),
        (records["primer"], plasmid_record, RegistryRelationship.RELATION_COMPONENT_OF),
    ]
    for source, target, relationship_type in relation_specs:
        RegistryRelationship.objects.get_or_create(
            source=source,
            target=target,
            relationship_type=relationship_type,
            custom_type="",
            defaults={"metadata": {"demo": True}, "created_by": maria},
        )

    plan, _ = ConstructAssemblyPlan.objects.get_or_create(
        name="pOpenLIMS GFP Gibson Assembly",
        target_sequence=plasmid_sequence,
        defaults={
            "method": "SIMPLE_FRAGMENT_ASSEMBLY",
            "cloning_notes": "Assemble backbone and GFP insert with 20 bp overlaps.",
            "status": ConstructAssemblyPlan.STATUS_DRAFT,
            "created_by": maria,
        },
    )
    AssemblyFragment.objects.get_or_create(
        plan=plan,
        order=1,
        defaults={
            "source_revision": plasmid_sequence.revisions.order_by("revision").first(),
            "start": 0,
            "end": 29,
            "left_overhang": "TAATACGACTCACTATAGGG",
            "right_overhang": "ATGGTGAGCAAGGGCGAGGA",
        },
    )
    AssemblyFragment.objects.get_or_create(
        plan=plan,
        order=2,
        defaults={
            "source_revision": primer_revision,
            "start": 0,
            "end": len(primer_revision.sequence),
            "left_overhang": "ATGGTGAGCAAGGGCGAGGA",
            "right_overhang": "GGATCCTAA",
        },
    )
    return {"records": records, "sequences": [plasmid_sequence, primer_sequence, protein_sequence], "plan": plan}


def seed_shared_links_and_attachments(project, director, registry_demo, traceability_demo, pipeline_run):
    """Demonstrate stable cross-module links and reusable file attachments."""
    from core.models import EntityLink, SharedAttachment

    plasmid = registry_demo["records"]["plasmid"]
    sequence = registry_demo["sequences"][0]
    sample = traceability_demo["samples"]["LIN-ALIQUOT-001"]
    lot = traceability_demo["lot"]
    targets = [
        (plasmid, sample, "represented_by", "Physical sample for this registered plasmid"),
        (plasmid, lot, "stored_as", "Inventory lot containing registered material"),
        (sequence, sample, "derived_from", "Sequence generated from the physical sample"),
        (pipeline_run, plasmid, "characterizes", "Workflow run characterizing the Registry record"),
    ]
    for source, target, relation_type, label in targets:
        EntityLink.objects.get_or_create(
            source_content_type=ContentType.objects.get_for_model(source),
            source_object_id=str(source.pk),
            target_content_type=ContentType.objects.get_for_model(target),
            target_object_id=str(target.pk),
            relation_type=relation_type,
            defaults={
                "label": label,
                "metadata": {"demo": True, "source": "seed_demo"},
                "project": project,
                "created_by": director,
            },
        )

    attachment_content = (
        b"OpenLIMS demo construct certificate\n"
        b"Registry: PLS-DEMO-0001\n"
        b"Status: sequence and physical material verified\n"
    )
    target_type = ContentType.objects.get_for_model(plasmid)
    attachment = SharedAttachment.objects.filter(
        target_content_type=target_type,
        target_object_id=str(plasmid.pk),
        display_name="pOpenLIMS construct certificate.txt",
    ).first()
    if not attachment:
        attachment = SharedAttachment.objects.create(
            target_content_type=target_type,
            target_object_id=str(plasmid.pk),
            project=project,
            display_name="pOpenLIMS construct certificate.txt",
            description="Reusable shared attachment linked through the common entity contract.",
            media_type="text/plain",
            size_bytes=len(attachment_content),
            sha256=hashlib.sha256(attachment_content).hexdigest(),
            uploaded_by=director,
        )
        attachment.file.save(
            "popenlims_construct_certificate.txt",
            ContentFile(attachment_content),
            save=True,
        )
    return attachment


def seed_migration_toolkit_demo(project, director, registry_record, sample):
    """Seed safe connection configuration, mappings, preview, reconciliation, and rollback examples."""
    from migration_toolkit.models import (
        MigrationDatabaseConnection,
        MigrationDataset,
        MigrationFieldMapping,
        MigrationJob,
        MigrationMappingTemplate,
        MigrationObjectChange,
        MigrationProfile,
        MigrationRowRecord,
        SampleExternalID,
    )

    connection, _ = MigrationDatabaseConnection.objects.get_or_create(
        name="SISBI Read-only Demo",
        defaults={
            "engine": MigrationDatabaseConnection.ENGINE_POSTGRESQL,
            "host": "sisbi.example.invalid",
            "port": 5432,
            "database_name": "sisbi_demo",
            "username": "openlims_readonly",
            "password_env_var": "SISBI_DEMO_PASSWORD",
            "ssl_mode": "require",
            "active": False,
            "created_by": director,
        },
    )
    profile, _ = MigrationProfile.objects.get_or_create(
        name="SISBI Comprehensive Migration Demo",
        defaults={
            "source_system": "SISBI",
            "source_type": MigrationProfile.SOURCE_TYPE_DATABASE,
            "description": "Read-only projects, users, samples, results, metadata, and Registry migration demo.",
            "created_by": director,
        },
    )
    datasets = {}
    for entity_type, table, key in [
        (MigrationDataset.ENTITY_PROJECT, "projects", "project_id"),
        (MigrationDataset.ENTITY_USER, "users", "user_id"),
        (MigrationDataset.ENTITY_SAMPLE, "samples", "sample_id"),
        (MigrationDataset.ENTITY_RESULT, "historical_results", "result_id"),
        (MigrationDataset.ENTITY_REGISTRY, "biological_registry", "registry_id"),
    ]:
        dataset, _ = MigrationDataset.objects.get_or_create(
            profile=profile,
            name=f"SISBI {entity_type.title()}",
            defaults={
                "connection": connection,
                "entity_type": entity_type,
                "source_schema": "public",
                "source_table": table,
                "source_key_column": key,
                "row_limit": 10000,
                "active": True,
            },
        )
        datasets[entity_type] = dataset

    mappings = [
        (MigrationDataset.ENTITY_PROJECT, "project_code", MigrationFieldMapping.TARGET_PROJECT_CODE, "", True),
        (MigrationDataset.ENTITY_PROJECT, "project_name", MigrationFieldMapping.TARGET_PROJECT_NAME, "", True),
        (MigrationDataset.ENTITY_USER, "username", MigrationFieldMapping.TARGET_USER_USERNAME, "", True),
        (MigrationDataset.ENTITY_USER, "email", MigrationFieldMapping.TARGET_USER_EMAIL, "", False),
        (MigrationDataset.ENTITY_SAMPLE, "sample_code", MigrationFieldMapping.TARGET_SAMPLE_ID, "", True),
        (MigrationDataset.ENTITY_SAMPLE, "legacy_barcode", MigrationFieldMapping.TARGET_EXTERNAL_ID, "barcode", False),
        (MigrationDataset.ENTITY_SAMPLE, "collection_site", MigrationFieldMapping.TARGET_CUSTOM_FIELD, "collection_site", False),
        (MigrationDataset.ENTITY_RESULT, "result_name", MigrationFieldMapping.TARGET_RESULT_KEY, "", True),
        (MigrationDataset.ENTITY_RESULT, "result_value", MigrationFieldMapping.TARGET_RESULT_VALUE, "", True),
        (MigrationDataset.ENTITY_RESULT, "recorded_at", MigrationFieldMapping.TARGET_RESULT_CREATED_AT, "", False),
        (MigrationDataset.ENTITY_REGISTRY, "registry_id", MigrationFieldMapping.TARGET_REGISTRY_ID, "", True),
        (MigrationDataset.ENTITY_REGISTRY, "entity_schema", MigrationFieldMapping.TARGET_REGISTRY_SCHEMA, "", True),
        (MigrationDataset.ENTITY_REGISTRY, "name", MigrationFieldMapping.TARGET_REGISTRY_NAME, "", True),
        (MigrationDataset.ENTITY_REGISTRY, "sequence", MigrationFieldMapping.TARGET_REGISTRY_SEQUENCE, "", False),
    ]
    for entity_type, source_column, target_type, target_field, required in mappings:
        MigrationFieldMapping.objects.get_or_create(
            profile=profile,
            dataset=datasets[entity_type],
            source_column=source_column,
            target_type=target_type,
            target_field=target_field,
            defaults={"required": required},
        )

    MigrationMappingTemplate.objects.get_or_create(
        name="SISBI Full Migration Template",
        defaults={
            "source_system": "SISBI",
            "source_type": MigrationProfile.SOURCE_TYPE_DATABASE,
            "description": "Reusable field mappings with skip, merge, overwrite, and create-new conflict policies.",
            "configuration": {
                "profile": profile.name,
                "entities": ["PROJECT", "USER", "SAMPLE", "RESULT", "REGISTRY"],
                "supported_conflict_policies": ["SKIP", "MERGE", "OVERWRITE", "CREATE_NEW"],
                "requires_frozen_preview": True,
            },
            "created_by": director,
        },
    )
    fingerprint = hashlib.sha256(b"openlims-sisbi-demo-preview-v1").hexdigest()
    job, _ = MigrationJob.objects.get_or_create(
        profile=profile,
        preview_fingerprint=fingerprint,
        defaults={
            "project": project,
            "source_connection": connection,
            "uploaded_by": director,
            "status": MigrationJob.STATUS_COMPLETED,
            "summary": {
                "source_rows": 5,
                "created": 2,
                "matched": 1,
                "skipped": 1,
                "errors": 1,
                "ready_to_commit": True,
                "reconciliation_report": True,
            },
            "source_snapshot": {"fingerprint": fingerprint, "tables": 5, "read_only": True},
            "conflict_policy": MigrationJob.CONFLICT_MERGE,
            "committed_by": director,
            "confirmed_at": timezone.now(),
        },
    )
    row_specs = [
        (1, MigrationRowRecord.STATUS_IMPORTED, MigrationRowRecord.ACTION_CREATE, "Created project and sample"),
        (2, MigrationRowRecord.STATUS_IMPORTED, MigrationRowRecord.ACTION_MERGE, "Merged blank metadata"),
        (3, MigrationRowRecord.STATUS_SKIPPED, MigrationRowRecord.ACTION_SKIP, "Existing registry checksum"),
        (4, MigrationRowRecord.STATUS_ERROR, MigrationRowRecord.ACTION_ERROR, "Missing required relationship"),
    ]
    for row_number, status, action, detail in row_specs:
        MigrationRowRecord.objects.get_or_create(
            migration_job=job,
            source_dataset=datasets[MigrationDataset.ENTITY_SAMPLE],
            row_number=row_number,
            defaults={
                "entity_type": "SAMPLE",
                "source_key": f"SISBI-{row_number:04d}",
                "project": project,
                "sample": sample if row_number == 2 else None,
                "project_code": project.code,
                "sample_code": sample.sample_id if row_number == 2 else f"LEGACY-{row_number:04d}",
                "raw_row": {"source": "SISBI", "row": row_number},
                "status": status,
                "action": action,
                "target_object_type": "sample" if status == MigrationRowRecord.STATUS_IMPORTED else "",
                "target_object_id": str(sample.id) if row_number == 2 else "",
                "errors": [detail] if status == MigrationRowRecord.STATUS_ERROR else [],
            },
        )
    MigrationObjectChange.objects.get_or_create(
        migration_job=job,
        object_type="registry_record",
        object_id=str(registry_record.id),
        action=MigrationObjectChange.ACTION_UPDATED,
        defaults={
            "identifier": registry_record.registry_id,
            "previous_values": {"description": ""},
            "metadata": {"rollback_supported": True, "demo": True},
        },
    )
    SampleExternalID.objects.get_or_create(
        sample=sample,
        source_system="SISBI",
        external_id="SISBI-SAMPLE-1042",
        label="legacy_sample_id",
        defaults={"metadata": {"migration_job": job.id}},
    )

    rollback_job, _ = MigrationJob.objects.get_or_create(
        profile=profile,
        preview_fingerprint=hashlib.sha256(b"openlims-sisbi-demo-rollback-v1").hexdigest(),
        defaults={
            "project": project,
            "source_connection": connection,
            "uploaded_by": director,
            "status": MigrationJob.STATUS_ROLLED_BACK,
            "summary": {"created": 1, "updated": 1},
            "source_snapshot": {"read_only": True},
            "conflict_policy": MigrationJob.CONFLICT_OVERWRITE,
            "committed_by": director,
            "confirmed_at": timezone.now(),
            "rolled_back_by": director,
            "rolled_back_at": timezone.now(),
            "rollback_summary": {"deleted": 1, "restored": 1, "errors": 0},
        },
    )
    return {"profile": profile, "job": job, "rollback_job": rollback_job}


def seed_analysis_assistant_demo(project, director, maria, registry_demo):
    """Seed completed analysis jobs, reports, assistant confirmations, and subscriptions."""
    from alignments.models import AlignmentJob
    from assistant.models import (
        AssistantAction,
        AssistantFeedback,
        AssistantInteraction,
        GeneratedArtifact,
        NotificationDelivery,
        NotificationSubscription,
    )
    from blast.models import BlastHit, BlastJob
    from settings_app.models import SystemSettings

    sequences = registry_demo["sequences"]
    alignment, _ = AlignmentJob.objects.update_or_create(
        name="Registry construct comparison demo",
        project=project,
        defaults={
            "tool": "CLUSTAL_OMEGA",
            "status": "COMPLETED",
            "input_fasta": "\n".join(f">{item.name}\n{item.sequence}" for item in sequences[:2]),
            "aligned_fasta": (
                f">{sequences[0].name}\n{sequences[0].sequence}\n"
                f">{sequences[1].name}\n{sequences[1].sequence}{'-' * max(0, len(sequences[0].sequence) - len(sequences[1].sequence))}\n"
            ),
            "summary": {"sequence_count": 2, "tool": "Clustal Omega", "demo": True},
            "error_message": "",
            "created_by": maria,
        },
    )
    alignment.sequences.set(sequences[:2])

    blast_database = BlastDatabase.objects.filter(name="Demo DNA BLAST DB").first()
    blast_query = Sequence.objects.filter(name="BLAST Demo Query").first()
    if blast_database and blast_query:
        blast_job, _ = BlastJob.objects.update_or_create(
            name="Demo construct identity search",
            project=project,
            defaults={
                "query_sequence": blast_query,
                "database": blast_database,
                "program": BlastJob.PROGRAM_BLASTN,
                "status": BlastJob.STATUS_COMPLETED,
                "max_target_seqs": 10,
                "evalue": "1e-20",
                "query_fasta": f">{blast_query.name}\n{blast_query.sequence}\n",
                "result_json": {"demo": True, "top_identity": 100.0},
                "hits_count": 2,
                "error_message": "",
                "created_by": maria,
            },
        )
        BlastHit.objects.update_or_create(
            job=blast_job,
            rank=1,
            defaults={
                "hit_id": "BLAST_REF_ALPHA",
                "hit_def": "perfect_match_alpha",
                "accession": "DEMO0001",
                "hit_length": len(blast_query.sequence),
                "bit_score": 120.0,
                "evalue": 1e-30,
                "identity_percent": 100.0,
                "alignment_length": len(blast_query.sequence),
                "query_from": 1,
                "query_to": len(blast_query.sequence),
                "hit_from": 1,
                "hit_to": len(blast_query.sequence),
                "query_aligned": blast_query.sequence,
                "hit_aligned": blast_query.sequence,
                "midline": "|" * len(blast_query.sequence),
            },
        )

    report_content = (
        b"%PDF-1.4\n% Seeded OpenLIMS demonstration report\n"
        b"Registry, lineage, workflow, QC, and inventory summary\n%%EOF\n"
    )
    report = GeneratedArtifact.objects.filter(filename="openlims_comprehensive_demo_report.pdf").first()
    if not report:
        report = GeneratedArtifact.objects.create(
            kind=GeneratedArtifact.KIND_REPORT_PDF,
            filename="openlims_comprehensive_demo_report.pdf",
            content_type="application/pdf",
            checksum_sha256=hashlib.sha256(report_content).hexdigest(),
            parameters={
                "project": project.code,
                "sections": ["samples", "workflows", "results", "qc", "registry", "inventory"],
                "demo": True,
            },
            project=project,
            created_by=director,
        )
        report.file.save(report.filename, ContentFile(report_content), save=True)

    AssistantAction.objects.get_or_create(
        requested_by=director,
        summary="Generate the comprehensive Alpha project compliance report",
        defaults={
            "action_type": AssistantAction.ACTION_COMPLIANCE_REPORT,
            "status": AssistantAction.STATUS_COMPLETED,
            "payload": {"project_id": project.id, "format": "PDF", "demo": True},
            "result": {"artifact_id": str(report.id), "filename": report.filename},
            "expires_at": timezone.now() + timedelta(days=7),
            "confirmed_at": timezone.now(),
            "executed_at": timezone.now(),
        },
    )
    AssistantAction.objects.get_or_create(
        requested_by=maria,
        summary="Archive the selected completed demo samples",
        defaults={
            "action_type": AssistantAction.ACTION_BULK_SAMPLE_UPDATE,
            "status": AssistantAction.STATUS_PROPOSED,
            "payload": {"project_id": project.id, "target_status": "ARCHIVED", "frozen_sample_ids": []},
            "expires_at": timezone.now() + timedelta(days=1),
        },
    )

    message_hash = hashlib.sha256(b"show alpha registry and qc status").hexdigest()
    interaction, _ = AssistantInteraction.objects.get_or_create(
        user=director,
        message_hash=message_hash,
        defaults={
            "route": "registry_project_summary",
            "routing_source": "rules",
            "confidence": 0.98,
            "response_type": "summary",
            "record_count": 5,
            "clarification_requested": False,
            "success": True,
            "latency_ms": 42,
            "context_keys": ["project", "registry", "qc"],
        },
    )
    AssistantFeedback.objects.get_or_create(
        interaction=interaction,
        user=director,
        defaults={"rating": AssistantFeedback.RATING_UP, "note": "Useful seeded assistant summary."},
    )

    subscription, _ = NotificationSubscription.objects.get_or_create(
        deduplication_key="demo-alpha-qc-failure-director",
        defaults={
            "trigger": "QC_FAILED",
            "recipient": director,
            "delivery_channel": NotificationSubscription.CHANNEL_IN_APP,
            "frequency": NotificationSubscription.FREQUENCY_IMMEDIATE,
            "project": project,
            "target_type": "project",
            "target_id": str(project.public_id),
            "active": True,
            "created_by": director,
        },
    )
    NotificationDelivery.objects.get_or_create(
        subscription=subscription,
        event_key="demo-qc-event-001",
        defaults={
            "status": NotificationDelivery.STATUS_DELIVERED,
            "permission_rechecked": True,
            "detail": {"channel": "IN_APP", "demo": True},
        },
    )

    settings_obj = SystemSettings.load()
    settings_obj.lab_name = "OpenLIMS Comprehensive Demo Lab"
    settings_obj.organization_name = "OpenLIMS Demo Organization"
    settings_obj.registry_enabled = True
    settings_obj.updated_by = director
    settings_obj.save()
    return {"alignment": alignment, "report": report, "subscription": subscription}

class Command(BaseCommand):
    help = "Seed OpenLIMS with realistic demo data"

    def handle(self, *args, **options):
        self.stdout.write("Seeding OpenLIMS demo data...")

        # --------------------------------------------------
        # Groups
        # --------------------------------------------------
        admin_group, _ = Group.objects.get_or_create(name="admin")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        qc_reviewer_group, _ = Group.objects.get_or_create(name="qc_reviewer")

        # --------------------------------------------------
        # Users
        # --------------------------------------------------
        configured_login_password = os.environ.get("OPENLIMS_DEMO_PASSWORD") or None
        director = create_demo_user(
            "director",
            admin_group,
            email="director@example.com",
            first_name="Dana",
            last_name="Director",
            is_admin=True,
            password=configured_login_password,
        )

        peter = create_demo_user(
            "peter",
            tech_group,
            email="peter.tech@example.com",
            first_name="Peter",
            last_name="Nguyen",
            password=configured_login_password,
        )

        maria = create_demo_user(
            "maria",
            tech_group,
            email="maria.tech@example.com",
            first_name="Maria",
            last_name="Chen",
            password=configured_login_password,
        )
        maria.groups.add(qc_reviewer_group)

        michael = create_demo_user(
            "michael",
            tech_group,
            email="michael.tech@example.com",
            first_name="Michael",
            last_name="Patel",
            password=configured_login_password,
        )

        viewer = create_demo_user(
            "viewer",
            viewer_group,
            email="viewer@example.com",
            first_name="Vivian",
            last_name="Reviewer",
            password=configured_login_password,
        )

        # --------------------------------------------------
        # Projects
        # --------------------------------------------------
        project_alpha, _ = get_or_create_safe(
            Project,
            {"code": "PRJ-ALPHA"},
            {
                "name": "Alpha Assay Validation",
                "description": (
                    "Demo validation project for instrument-imported assay results, "
                    "sequence workspaces, and Clustal Omega alignments."
                ),
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
                "name": "Gamma Sequencing Run",
                "description": "Demo sequencing project for MiSeq and Sanger QC review.",
                "status": "ACTIVE",
            },
        )

        if hasattr(project_alpha, "members"):
            project_alpha.members.add(director, peter, maria, michael, viewer)
            project_beta.members.add(director, peter, maria, michael, viewer)
            project_gamma.members.add(director, peter, maria, michael)

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

        sequencing_bench, _ = get_or_create_safe(
            Location,
            {"name": "Sequencing Bench"},
            {
                "description": "Bench used for sequencing prep and sample staging.",
                "room": "Lab 201",
            },
        )

        rack_a, _ = get_or_create_safe(
            Container,
            {"container_id": "BOX-A1"},
            {
                "kind": "96-well box",
                "location": freezer,
                "description": "Alpha validation sample box in Freezer A",
            },
        )

        rack_b, _ = get_or_create_safe(
            Container,
            {"container_id": "BOX-B1"},
            {
                "kind": "Tube rack",
                "location": fridge,
                "description": "Beta stability sample rack in Fridge B",
            },
        )

        rack_c, _ = get_or_create_safe(
            Container,
            {"container_id": "SEQ-RACK-1"},
            {
                "kind": "Sequencing prep rack",
                "location": sequencing_bench,
                "description": "Rack for sequencing prep samples.",
            },
        )

        freezer_f2, _ = get_or_create_safe(
            Location,
            {"name": "F2"},
            {"kind": "FREEZER"},
        )
        rack_r4, _ = get_or_create_safe(
            Container,
            {"container_id": "R4"},
            {"kind": "RACK", "location": freezer_f2},
        )
        box_b3, _ = get_or_create_safe(
            Container,
            {"container_id": "B3"},
            {"kind": "BOX", "location": freezer_f2, "parent": rack_r4},
        )
        reagent_r100, _ = get_or_create_safe(
            InventoryItem,
            {"code": "R-100"},
            {
                "name": "Sequencing reagent",
                "category": InventoryItem.CATEGORY_REAGENT,
                "default_unit": "mL",
                "reorder_level": Decimal("150"),
            },
        )
        get_or_create_safe(
            InventoryLot,
            {"lot_code": "L-204"},
            {
                "item": reagent_r100,
                "quantity": Decimal("100"),
                "unit": "mL",
                "expiration_date": timezone.localdate() + timedelta(days=20),
                "status": InventoryLot.STATUS_ACTIVE,
                "location": freezer_f2,
                "container": box_b3,
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
                    ("concentration", "concentration", "NUMBER", 0, 100, None),
                    ("purity", "purity", "NUMBER", 0, 100, None),
                    ("yield", "yield", "NUMBER", 0, 100, None),
                    ("qc_flag", "qc_flag", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "MISEQ",
                "name": "Illumina MiSeq Sequencer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("read_count", "read_count", "NUMBER", 0, 10000000, None),
                    ("mean_q_score", "mean_q_score", "NUMBER", 0, 50, None),
                    ("percent_q30", "percent_q30", "NUMBER", 0, 100, None),
                    ("sequencing_status", "sequencing_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "SANGER-3500",
                "name": "Applied Biosystems 3500 Sanger Sequencer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("read_length", "read_length", "NUMBER", 0, 1200, None),
                    ("quality_score", "quality_score", "NUMBER", 0, 100, None),
                    ("basecalling_status", "basecalling_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "ENDOSAFE",
                "name": "Charles River Endosafe Nexus",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("endotoxin_eu_ml", "endotoxin_eu_ml", "NUMBER", 0, 1000, None),
                    ("spike_recovery_percent", "spike_recovery_percent", "NUMBER", 0, 200, None),
                    ("lal_status", "lal_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "PLATEREADER",
                "name": "Molecular Devices SpectraMax Plate Reader",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("abs_450", "abs_450", "NUMBER", 0, 5, None),
                    ("abs_570", "abs_570", "NUMBER", 0, 5, None),
                    ("plate_qc_status", "plate_qc_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "QPCR-7500",
                "name": "Applied Biosystems 7500 qPCR System",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("ct_value", "ct_value", "NUMBER", 0, 45, None),
                    ("delta_ct", "delta_ct", "NUMBER", -50, 50, None),
                    ("qpcr_status", "qpcr_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "NANODROP",
                "name": "Thermo Fisher NanoDrop One",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("a260_a280", "a260_a280", "NUMBER", 0, 5, None),
                    ("a260_a230", "a260_a230", "NUMBER", 0, 5, None),
                    ("ng_ul", "ng_ul", "NUMBER", 0, 5000, None),
                    ("nanodrop_status", "nanodrop_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "BIOANALYZER",
                "name": "Agilent 2100 Bioanalyzer",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("rin", "rin", "NUMBER", 0, 10, None),
                    ("fragment_size_bp", "fragment_size_bp", "NUMBER", 0, 10000, None),
                    ("bioanalyzer_status", "bioanalyzer_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "HAMILTON-STAR",
                "name": "Hamilton STAR Liquid Handler",
                "delimiter": ",",
                "has_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("transfer_volume_ul", "transfer_volume_ul", "NUMBER", 0, 1000, None),
                    ("source_well", "source_well", "STRING", None, None, None),
                    ("destination_well", "destination_well", "STRING", None, None, None),
                    ("transfer_status", "transfer_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
                ],
            },
            {
                "code": "META-CSV",
                "name": "Metadata Header CSV Instrument",
                "delimiter": ",",
                "has_header": True,
                "header_row_index": 0,
                "auto_detect_header": True,
                "sample_id_column": "sample_id",
                "mappings": [
                    ("result", "result", "STRING", None, None, ["pass", "fail", "review", "PASS", "FAIL", "REVIEW"]),
                    ("operator", "operator", "STRING", None, None, None),
                    ("qc_status", "qc_status", "STRING", None, None, ["PASS", "FAIL", "REVIEW"]),
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
            instrument = create_or_update_instrument(instrument_config)
            instruments[instrument_config["code"]] = instrument

        novaflex = instruments["NOVAFLEX"]
        miseq = instruments["MISEQ"]
        sanger = instruments["SANGER-3500"]
        endosafe = instruments["ENDOSAFE"]
        platereader = instruments["PLATEREADER"]
        qpcr = instruments["QPCR-7500"]
        nanodrop = instruments["NANODROP"]
        bioanalyzer = instruments["BIOANALYZER"]
        hamilton = instruments["HAMILTON-STAR"]
        meta_csv = instruments["META-CSV"]

        # --------------------------------------------------
        # Sample batches + samples
        # --------------------------------------------------
        batch_data = [
            ("B-ALPHA-01", project_alpha),
            ("B-ALPHA-02", project_alpha),
            ("B-BETA-01", project_beta),
            ("B-GAMMA-01", project_gamma),
        ]
        batches = {}
        for batch_code, batch_project in batch_data:
            batch, _ = SampleBatch.objects.update_or_create(
                code=batch_code,
                defaults={
                    "project": batch_project,
                    "created_by": director,
                },
            )
            batches[batch_code] = batch

        sample_data = [
            {
                "sample_id": "S-ALPHA-001",
                "status": "RECEIVED",
                "project": project_alpha,
                "container": rack_a,
                "batch": batches["B-ALPHA-01"],
                "assigned_to": peter,
            },
            {
                "sample_id": "S-ALPHA-002",
                "status": "IN_PROGRESS",
                "project": project_alpha,
                "container": rack_a,
                "batch": batches["B-ALPHA-01"],
                "assigned_to": peter,
            },
            {
                "sample_id": "S-ALPHA-003",
                "status": "QC",
                "project": project_alpha,
                "container": rack_a,
                "batch": batches["B-ALPHA-02"],
                "assigned_to": maria,
            },
            {
                "sample_id": "S-ALPHA-004",
                "status": "IN_PROGRESS",
                "project": project_alpha,
                "container": rack_a,
                "batch": batches["B-ALPHA-02"],
                "assigned_to": michael,
            },
            {
                "sample_id": "S-BETA-001",
                "status": "REPORTED",
                "project": project_beta,
                "container": rack_b,
                "batch": batches["B-BETA-01"],
                "assigned_to": michael,
            },
            {
                "sample_id": "S-BETA-002",
                "status": "ARCHIVED",
                "project": project_beta,
                "container": rack_b,
                "batch": batches["B-BETA-01"],
                "assigned_to": maria,
            },
            {
                "sample_id": "S-BETA-003",
                "status": "QC",
                "project": project_beta,
                "container": rack_b,
                "batch": batches["B-BETA-01"],
                "assigned_to": peter,
            },
            {
                "sample_id": "S-GAMMA-001",
                "status": "RECEIVED",
                "project": project_gamma,
                "container": rack_c,
                "batch": batches["B-GAMMA-01"],
                "assigned_to": maria,
            },
            {
                "sample_id": "S-GAMMA-002",
                "status": "IN_PROGRESS",
                "project": project_gamma,
                "container": rack_c,
                "batch": batches["B-GAMMA-01"],
                "assigned_to": michael,
            },
        ]

        samples = []

        for row in sample_data:
            sample, created = get_or_create_safe(
                Sample,
                {"sample_id": row["sample_id"]},
                row,
            )
            sample.batch = row["batch"]
            sample.assigned_to = row["assigned_to"]
            sample.save(update_fields=["batch", "assigned_to", "updated_at"])
            samples.append(sample)

            if created:
                Event.objects.create(
                    entity_type="Sample",
                    entity_id=str(sample.id),
                    action="CREATED",
                    actor=director,
                    payload={
                        "sample_id": sample.id,
                        "sample_code": sample.sample_id,
                        "source": "demo_seed",
                        "project_id": getattr(sample, "project_id", None),
                        "container_id": getattr(sample, "container_id", None),
                    },
                )

        sample_by_code = {sample.sample_id: sample for sample in samples}

        # --------------------------------------------------
        # v0.15 demo: Cross-project sample linking
        # --------------------------------------------------
        alpha_shared_sample = sample_by_code.get("S-ALPHA-001")
        beta_review_sample = sample_by_code.get("S-BETA-001")

        if alpha_shared_sample and hasattr(alpha_shared_sample, "linked_projects"):
            alpha_shared_sample.linked_projects.add(project_beta, project_gamma)

            Event.objects.get_or_create(
                entity_type="Sample",
                entity_id=str(alpha_shared_sample.id),
                action="SAMPLE_PROJECT_LINKED",
                defaults={
                    "actor": director,
                    "payload": {
                        "sample_id": alpha_shared_sample.id,
                        "sample_code": alpha_shared_sample.sample_id,
                        "primary_project_id": project_alpha.id,
                        "primary_project_code": project_alpha.code,
                        "linked_project_id": project_beta.id,
                        "linked_project_code": project_beta.code,
                        "linked_project_name": project_beta.name,
                        "source": "demo_seed_v0_15",
                        "note": (
                            "v0.15 demo: sample is owned by PRJ-ALPHA but "
                            "shared with PRJ-BETA for visibility only."
                        ),
                    },
                },
            )

            Event.objects.get_or_create(
                entity_type="Sample",
                entity_id=str(alpha_shared_sample.id),
                action="SAMPLE_PROJECT_LINKED",
                defaults={
                    "actor": director,
                    "payload": {
                        "sample_id": alpha_shared_sample.id,
                        "sample_code": alpha_shared_sample.sample_id,
                        "primary_project_id": project_alpha.id,
                        "primary_project_code": project_alpha.code,
                        "linked_project_id": project_gamma.id,
                        "linked_project_code": project_gamma.code,
                        "linked_project_name": project_gamma.name,
                        "source": "demo_seed_v0_15",
                        "note": (
                            "v0.15 demo: sample is also shared with PRJ-GAMMA "
                            "to demonstrate multi-project visibility."
                        ),
                    },
                },
            )

        if beta_review_sample and hasattr(beta_review_sample, "linked_projects"):
            beta_review_sample.linked_projects.add(project_alpha)

            Event.objects.get_or_create(
                entity_type="Sample",
                entity_id=str(beta_review_sample.id),
                action="SAMPLE_PROJECT_LINKED",
                defaults={
                    "actor": director,
                    "payload": {
                        "sample_id": beta_review_sample.id,
                        "sample_code": beta_review_sample.sample_id,
                        "primary_project_id": project_beta.id,
                        "primary_project_code": project_beta.code,
                        "linked_project_id": project_alpha.id,
                        "linked_project_code": project_alpha.code,
                        "linked_project_name": project_alpha.name,
                        "source": "demo_seed_v0_15",
                        "note": (
                            "v0.15 demo: Beta sample is visible from Alpha, "
                            "but Alpha members only have linked-project visibility unless "
                            "they also belong to the primary project."
                        ),
                    },
                },
            )

        # --------------------------------------------------
        # Work items + results
        # --------------------------------------------------
        result_sets = {
            "S-ALPHA-001": {
                "NovaFlex Import Results": {
                    "concentration": 12.4,
                    "purity": 97.1,
                    "yield": 88.0,
                    "qc_flag": "PASS",
                },
                "Illumina MiSeq QC": {
                    "read_count": 185420,
                    "mean_q_score": 37.8,
                    "percent_q30": 92.4,
                    "sequencing_status": "PASS",
                },
                "Endosafe Endotoxin Test": {
                    "endotoxin_eu_ml": 0.03,
                    "spike_recovery_percent": 96.2,
                    "lal_status": "PASS",
                },
                "NanoDrop Purity Check": {
                    "a260_a280": 1.89,
                    "a260_a230": 2.11,
                    "ng_ul": 84.2,
                    "nanodrop_status": "PASS",
                },
                "Metadata Header CSV Import": {
                    "result": "pass",
                    "operator": "Peter",
                    "qc_status": "PASS",
                },
            },
            "S-ALPHA-002": {
                "NovaFlex Import Results": {
                    "concentration": 10.2,
                    "purity": 95.8,
                    "yield": 79.3,
                    "qc_flag": "PASS",
                },
                "Illumina MiSeq QC": {
                    "read_count": 163900,
                    "mean_q_score": 35.9,
                    "percent_q30": 88.7,
                    "sequencing_status": "PASS",
                },
                "qPCR Quantification": {
                    "ct_value": 23.8,
                    "delta_ct": 0.4,
                    "qpcr_status": "PASS",
                },
            },
            "S-ALPHA-003": {
                "NovaFlex Import Results": {
                    "concentration": 6.5,
                    "purity": 89.2,
                    "yield": 61.0,
                    "qc_flag": "REVIEW",
                },
                "Illumina MiSeq QC": {
                    "read_count": 78400,
                    "mean_q_score": 26.1,
                    "percent_q30": 61.8,
                    "sequencing_status": "REVIEW",
                },
                "Endosafe Endotoxin Test": {
                    "endotoxin_eu_ml": 0.42,
                    "spike_recovery_percent": 72.5,
                    "lal_status": "REVIEW",
                },
            },
            "S-ALPHA-004": {
                "NovaFlex Import Results": {
                    "concentration": 13.8,
                    "purity": 96.4,
                    "yield": 84.6,
                    "qc_flag": "PASS",
                },
                "Hamilton STAR Transfer Log": {
                    "transfer_volume_ul": 25.0,
                    "source_well": "A04",
                    "destination_well": "D04",
                    "transfer_status": "PASS",
                },
            },
            "S-BETA-001": {
                "SpectraMax Plate Reader": {
                    "abs_450": 1.42,
                    "abs_570": 0.18,
                    "plate_qc_status": "PASS",
                },
                "Sanger Sequencing QC": {
                    "read_length": 847,
                    "quality_score": 88.2,
                    "basecalling_status": "PASS",
                },
            },
            "S-BETA-002": {
                "SpectraMax Plate Reader": {
                    "abs_450": 0.37,
                    "abs_570": 0.28,
                    "plate_qc_status": "FAIL",
                },
                "Sanger Sequencing QC": {
                    "read_length": 312,
                    "quality_score": 48.5,
                    "basecalling_status": "REVIEW",
                },
            },
            "S-BETA-003": {
                "Bioanalyzer RNA QC": {
                    "rin": 7.8,
                    "fragment_size_bp": 1540,
                    "bioanalyzer_status": "PASS",
                },
            },
            "S-GAMMA-001": {
                "MiSeq Run QC": {
                    "read_count": 211004,
                    "mean_q_score": 38.6,
                    "percent_q30": 94.1,
                    "sequencing_status": "PASS",
                },
            },
            "S-GAMMA-002": {
                "MiSeq Run QC": {
                    "read_count": 99021,
                    "mean_q_score": 31.2,
                    "percent_q30": 78.6,
                    "sequencing_status": "REVIEW",
                },
            },
        }

        for sample_code, work_items in result_sets.items():
            sample = sample_by_code[sample_code]

            for work_item_name, values in work_items.items():
                work_item, _ = get_or_create_safe(
                    WorkItem,
                    {
                        "sample": sample,
                        "name": work_item_name,
                    },
                    {
                        "status": "COMPLETED",
                        "notes": "Demo result set from a lab instrument.",
                    },
                )

                for key, value in values.items():
                    set_result_value(work_item, key, value)

        # --------------------------------------------------
        # Assistant analytics demo: comparable metrics across every project
        # --------------------------------------------------
        comparison_metrics = {
            "S-ALPHA-001": [12.4, 97.1, 88.0, 37.8, 92.4, 95.0],
            "S-ALPHA-002": [10.2, 95.8, 79.3, 35.9, 88.7, 87.0],
            "S-ALPHA-003": [6.5, 89.2, 61.0, 26.1, 61.8, 54.0],
            "S-ALPHA-004": [13.8, 96.4, 84.6, 36.8, 90.2, 91.0],
            "S-BETA-001": [11.6, 96.2, 86.5, 36.7, 91.1, 89.0],
            "S-BETA-002": [4.9, 87.8, 52.0, 24.8, 58.2, 41.0],
            "S-BETA-003": [9.8, 94.1, 75.0, 34.2, 84.5, 82.0],
            "S-GAMMA-001": [14.1, 97.5, 92.1, 38.6, 94.1, 97.0],
            "S-GAMMA-002": [8.1, 91.3, 68.4, 31.2, 78.6, 69.0],
        }
        metric_keys = [
            "concentration",
            "purity",
            "yield",
            "mean_q_score",
            "percent_q30",
            "response_percent",
        ]
        for sample_code, metric_values in comparison_metrics.items():
            sample = sample_by_code[sample_code]
            work_item, _ = WorkItem.objects.update_or_create(
                sample=sample,
                name="Assistant Comparison Metrics",
                defaults={
                    "work_type": "ASSISTANT_DEMO_ANALYTICS",
                    "status": WorkItem.STATUS_COMPLETED,
                    "notes": (
                        "Seeded cross-project metrics for bar, line, dot, scatter, "
                        "trend, and outlier demonstrations."
                    ),
                    "created_by": director,
                },
            )
            for key, value in zip(metric_keys, metric_values):
                existing = Result.objects.filter(
                    work_item__sample=sample,
                    key=key,
                ).exclude(work_item=work_item)
                if existing.exists():
                    continue
                result = set_result_value(work_item, key, value)
                result.entered_by = peter
                if result.qc_passed is True:
                    result.qc_status = Result.QC_APPROVED
                    result.qc_reviewed_by = maria
                    result.qc_reviewed_at = result.qc_reviewed_at or timezone.now()
                    result.qc_review_note = "Approved demo result within its configured range."
                    result.qc_assigned_to = None
                elif result.qc_passed is False:
                    result.qc_status = Result.QC_PENDING_REVIEW
                    result.qc_assigned_to = maria
                    result.qc_reviewed_by = None
                    result.qc_reviewed_at = None
                    result.qc_review_note = ""
                result.save()

        # --------------------------------------------------
        # Assistant attention demo: active, overdue, and unassigned work
        # --------------------------------------------------
        operational_work = [
            (
                "S-ALPHA-002",
                "Library preparation follow-up",
                "LIBRARY_PREP",
                WorkItem.STATUS_IN_PROGRESS,
                peter,
                2,
            ),
            (
                "S-ALPHA-003",
                "QC failure investigation",
                "QC_INVESTIGATION",
                WorkItem.STATUS_PENDING,
                maria,
                -2,
            ),
            (
                "S-BETA-003",
                "RNA QC review",
                "RNA_QC_REVIEW",
                WorkItem.STATUS_PENDING,
                None,
                0,
            ),
            (
                "S-GAMMA-002",
                "Sequencing rerun review",
                "SEQUENCING_RERUN",
                WorkItem.STATUS_IN_PROGRESS,
                None,
                -1,
            ),
        ]
        for sample_code, name, work_type, status_value, assignee, due_offset in operational_work:
            WorkItem.objects.update_or_create(
                sample=sample_by_code[sample_code],
                name=name,
                defaults={
                    "work_type": work_type,
                    "status": status_value,
                    "assigned_to": assignee,
                    "created_by": director,
                    "due_at": timezone.now() + timedelta(days=due_offset),
                    "notes": (
                        "Seeded active work for assistant attention and "
                        "bottleneck demonstrations."
                    ),
                },
            )

        for sample_code, age_days in {"S-ALPHA-003": 14, "S-GAMMA-002": 10}.items():
            Sample.objects.filter(pk=sample_by_code[sample_code].pk).update(
                status_changed_at=timezone.now() - timedelta(days=age_days)
            )

        # --------------------------------------------------
        # Demo import jobs
        # --------------------------------------------------
        demo_import_jobs = [
            {
                "instrument": novaflex,
                "run_id": "DEMO-RUN-001",
                "project": project_alpha,
                "uploaded_by": peter,
                "rows_processed": 4,
                "results_created": 16,
                "message": "NovaFlex demo import completed",
                "sample_codes": ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003", "S-ALPHA-004"],
                "work_item_name": "NovaFlex Import Results",
            },
            {
                "instrument": miseq,
                "run_id": "MISEQ-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": maria,
                "rows_processed": 3,
                "results_created": 12,
                "message": "MiSeq sequencing QC import completed",
                "sample_codes": ["S-ALPHA-001", "S-ALPHA-002", "S-ALPHA-003"],
                "work_item_name": "Illumina MiSeq QC",
            },
            {
                "instrument": endosafe,
                "run_id": "ENDOSAFE-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": michael,
                "rows_processed": 2,
                "results_created": 6,
                "message": "Endotoxin import completed",
                "sample_codes": ["S-ALPHA-001", "S-ALPHA-003"],
                "work_item_name": "Endosafe Endotoxin Test",
            },
            {
                "instrument": qpcr,
                "run_id": "QPCR-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": maria,
                "rows_processed": 1,
                "results_created": 3,
                "message": "qPCR quantification import completed",
                "sample_codes": ["S-ALPHA-002"],
                "work_item_name": "qPCR Quantification",
            },
            {
                "instrument": nanodrop,
                "run_id": "NANODROP-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": peter,
                "rows_processed": 1,
                "results_created": 4,
                "message": "NanoDrop purity import completed",
                "sample_codes": ["S-ALPHA-001"],
                "work_item_name": "NanoDrop Purity Check",
            },
            {
                "instrument": platereader,
                "run_id": "PLATE-RUN-2026-001",
                "project": project_beta,
                "uploaded_by": michael,
                "rows_processed": 2,
                "results_created": 6,
                "message": "SpectraMax plate reader import completed",
                "sample_codes": ["S-BETA-001", "S-BETA-002"],
                "work_item_name": "SpectraMax Plate Reader",
            },
            {
                "instrument": sanger,
                "run_id": "SANGER-RUN-2026-001",
                "project": project_beta,
                "uploaded_by": maria,
                "rows_processed": 2,
                "results_created": 6,
                "message": "Sanger sequencing QC import completed",
                "sample_codes": ["S-BETA-001", "S-BETA-002"],
                "work_item_name": "Sanger Sequencing QC",
            },
            {
                "instrument": bioanalyzer,
                "run_id": "BIOANALYZER-RUN-2026-001",
                "project": project_beta,
                "uploaded_by": peter,
                "rows_processed": 1,
                "results_created": 3,
                "message": "Bioanalyzer RNA QC import completed",
                "sample_codes": ["S-BETA-003"],
                "work_item_name": "Bioanalyzer RNA QC",
            },
            {
                "instrument": hamilton,
                "run_id": "HAMILTON-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": michael,
                "rows_processed": 1,
                "results_created": 4,
                "message": "Hamilton STAR transfer log import completed",
                "sample_codes": ["S-ALPHA-004"],
                "work_item_name": "Hamilton STAR Transfer Log",
            },
            {
                "instrument": meta_csv,
                "run_id": "META-CSV-RUN-2026-001",
                "project": project_alpha,
                "uploaded_by": peter,
                "rows_processed": 1,
                "results_created": 3,
                "message": "Metadata-row CSV import completed using auto header detection",
                "sample_codes": ["S-ALPHA-001"],
                "work_item_name": "Metadata Header CSV Import",
                "csv_metadata": {
                    "detected_header_row": 3,
                    "skipped_metadata_rows": 3,
                    "fieldnames": ["sample_id", "result", "operator", "qc_status"],
                    "demo_file_preview": [
                        "Instrument,Example Analyzer",
                        "Run ID,META-CSV-RUN-2026-001",
                        "Operator,Peter",
                        "sample_id,result,operator,qc_status",
                        "S-ALPHA-001,pass,Peter,PASS",
                    ],
                },
            },
            {
                "instrument": miseq,
                "run_id": "MISEQ-RUN-2026-002",
                "project": project_gamma,
                "uploaded_by": maria,
                "rows_processed": 2,
                "results_created": 8,
                "message": "Gamma MiSeq sequencing QC import completed",
                "sample_codes": ["S-GAMMA-001", "S-GAMMA-002"],
                "work_item_name": "MiSeq Run QC",
            },
        ]

        for job_data in demo_import_jobs:
            sample_ids = [
                sample_by_code[code].id
                for code in job_data["sample_codes"]
                if code in sample_by_code
            ]

            import_job, _ = ImportJob.objects.update_or_create(
                instrument=job_data["instrument"],
                run_id=job_data["run_id"],
                defaults={
                    "project": job_data["project"],
                    "uploaded_by": job_data["uploaded_by"],
                    "source_type": "UPLOAD",
                    "status": "COMPLETED",
                    "progress_current": job_data["rows_processed"],
                    "progress_total": job_data["rows_processed"],
                    "progress_message": job_data["message"],
                    "summary": {
                        "rows_processed": job_data["rows_processed"],
                        "samples_created": 0,
                        "samples_matched": len(sample_ids),
                        "results_created": job_data["results_created"],
                        "skipped_rows": [],
                        "project_id": job_data["project"].id,
                        "created_sample_ids": [],
                        "matched_sample_ids": sample_ids,
                        "touched_sample_ids": sample_ids,
                        "csv_metadata": job_data.get("csv_metadata"),
                    },
                },
            )

            provenance_counts = link_demo_import_job(
                import_job,
                job_data["sample_codes"],
                job_data["work_item_name"],
                job_data["uploaded_by"],
            )
            import_job.summary = {
                **import_job.summary,
                "provenance": provenance_counts,
            }
            import_job.save(update_fields=["summary"])

            Event.objects.update_or_create(
                entity_type="ImportJob",
                entity_id=str(import_job.id),
                action="RESULTS_IMPORTED",
                defaults={
                    "actor": job_data["uploaded_by"],
                    "payload": {
                        "instrument_code": job_data["instrument"].code,
                        "instrument_name": job_data["instrument"].name,
                        "run_id": job_data["run_id"],
                        "rows_processed": job_data["rows_processed"],
                        "results_created": job_data["results_created"],
                        "touched_sample_ids": sample_ids,
                        "csv_metadata": job_data.get("csv_metadata"),
                        "provenance": provenance_counts,
                    },
                },
            )

        # --------------------------------------------------
        # Demo sequence workspaces
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
                "sample": sample_by_code.get("S-ALPHA-001"),
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
                "created_by": maria,
                "source_type": "MANUAL",
                "source_metadata": {"demo": True, "purpose": "seqviz_demo"},
            },
        )

        sequence_workspace.features.all().delete()

        demo_features = [
            ("ANNOTATION", "Promoter", 0, 35, 1, "#2563eb", {}),
            ("ANNOTATION", "BamHI", 37, 43, 1, "#f97316", {}),
            ("ANNOTATION", "GFP CDS", 43, 763, 1, "#22c55e", {}),
            ("PRIMER", "GFP Forward", 43, 63, 1, "#9333ea", {}),
            ("PRIMER", "GFP Reverse", 730, 760, -1, "#db2777", {}),
            ("TRANSLATION", "GFP Translation", 43, 763, 1, "#16a34a", {}),
            ("HIGHLIGHT", "QC Review Region", 120, 180, 1, "#fde047", {}),
        ]

        for feature_type, name, start, end, direction, color, metadata in demo_features:
            SequenceFeature.objects.create(
                sequence_record=sequence_workspace,
                feature_type=feature_type,
                name=name,
                start=start,
                end=end,
                direction=direction,
                color=color,
                metadata=metadata,
            )

        alignment_demo_sequences = [
            {
                "name": "S-ALPHA-001 GFP Reference",
                "sample": sample_by_code.get("S-ALPHA-001"),
                "sequence": (
                    "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAG"
                    "CTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGG"
                    "CGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCACCGGCAAG"
                ),
                "created_by": maria,
            },
            {
                "name": "S-ALPHA-002 GFP Variant A",
                "sample": sample_by_code.get("S-ALPHA-002"),
                "sequence": (
                    "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAG"
                    "CTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGG"
                    "CGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCACCGGCAA"
                ),
                "created_by": peter,
            },
            {
                "name": "S-ALPHA-003 GFP Variant B",
                "sample": sample_by_code.get("S-ALPHA-003"),
                "sequence": (
                    "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAG"
                    "CTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGG"
                    "CGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCGGCAAG"
                ),
                "created_by": michael,
            },
            {
                "name": "S-ALPHA-004 MiSeq Consensus Read",
                "sample": sample_by_code.get("S-ALPHA-004"),
                "sequence": (
                    "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAG"
                    "CTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAG"
                ),
                "created_by": maria,
            },
        ]

        for item in alignment_demo_sequences:
            sequence_record, _ = Sequence.objects.update_or_create(
                name=item["name"],
                defaults={
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
                    "bp_colors": {
                        "A": "#ef4444",
                        "T": "#3b82f6",
                        "G": "#22c55e",
                        "C": "#f59e0b",
                    },
                    "created_by": item["created_by"],
                    "source_type": "MANUAL",
                    "source_metadata": {
                        "demo": True,
                        "purpose": "alignment_demo",
                    },
                },
            )

            Event.objects.get_or_create(
                entity_type="Sequence",
                entity_id=str(sequence_record.id),
                action="SEQUENCE_WORKSPACE_SEEDED",
                defaults={
                    "actor": item["created_by"],
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
        # Demo BLAST database + query sequence
        # --------------------------------------------------
        seed_blast_demo(
            project=project_alpha,
            sample=sample_by_code.get("S-ALPHA-001"),
            director=director,
        )

        # --------------------------------------------------
        # Demo mass spectrometry runs for comparison
        # --------------------------------------------------
        seed_mass_spec_demo(
            project_alpha=project_alpha,
            project_beta=project_beta,
            sample_by_code=sample_by_code,
            director=director,
            peter=peter,
            maria=maria,
            michael=michael,
        )

        # --------------------------------------------------
        # Comprehensive current-capability demos
        # --------------------------------------------------
        traceability_demo = seed_traceability_inventory_demo(
            project=project_alpha,
            director=director,
            maria=maria,
            rack_a=rack_a,
            rack_b=rack_b,
        )
        pipeline_run = seed_advanced_pipeline_demo(
            project=project_alpha,
            director=director,
            maria=maria,
        )
        registry_demo = seed_registry_molecular_demo(
            project=project_alpha,
            director=director,
            maria=maria,
            physical_sample=traceability_demo["samples"]["LIN-ALIQUOT-001"],
        )
        seed_shared_links_and_attachments(
            project=project_alpha,
            director=director,
            registry_demo=registry_demo,
            traceability_demo=traceability_demo,
            pipeline_run=pipeline_run,
        )
        seed_migration_toolkit_demo(
            project=project_alpha,
            director=director,
            registry_record=registry_demo["records"]["plasmid"],
            sample=traceability_demo["samples"]["LIN-ALIQUOT-001"],
        )
        seed_analysis_assistant_demo(
            project=project_alpha,
            director=director,
            maria=maria,
            registry_demo=registry_demo,
        )

        # --------------------------------------------------
        # Demo project feed posts
        # --------------------------------------------------
        demo_project_posts = [
            {
                "project": project_alpha,
                "author": director,
                "note": (
                    "Alpha Assay Validation is ready for review. Please focus on "
                    "S-ALPHA-003 because the QC metrics are lower than expected."
                ),
            },
            {
                "project": project_alpha,
                "author": peter,
                "note": (
                    "NovaFlex import completed for the Alpha sample set. "
                    "Concentration, purity, yield, and QC flag values are available."
                ),
            },
            {
                "project": project_alpha,
                "author": maria,
                "note": (
                    "MiSeq sequencing QC was imported. S-ALPHA-001 and S-ALPHA-002 "
                    "look good, but S-ALPHA-003 should be reviewed before reporting."
                ),
            },
            {
                "project": project_alpha,
                "author": michael,
                "note": (
                    "Endosafe results are attached. S-ALPHA-003 has elevated endotoxin "
                    "and should stay in QC until reviewed."
                ),
            },
            {
                "project": project_alpha,
                "author": maria,
                "note": (
                    "FASTA sequence workspaces were linked to the Alpha samples. "
                    "I queued a Clustal Omega alignment for the GFP variants."
                ),
            },
            {
                "project": project_alpha,
                "author": viewer,
                "note": (
                    "Review note: I can view the linked sequence workspaces and results, "
                    "but I do not have write access to modify the records."
                ),
            },
            {
                "project": project_beta,
                "author": director,
                "note": (
                    "Beta Stability Study has been initialized. Samples are linked "
                    "to storage locations for tracking."
                ),
            },
            {
                "project": project_beta,
                "author": michael,
                "note": (
                    "Storage check completed. Beta samples are assigned to BOX-B1 "
                    "in Fridge B."
                ),
            },
            {
                "project": project_gamma,
                "author": maria,
                "note": (
                    "Gamma sequencing run is staged. MiSeq QC will be reviewed after "
                    "the next import completes."
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
        # v0.15 demo feed posts
        # --------------------------------------------------
        ProjectPost.objects.get_or_create(
            project=project_alpha,
            author=director,
            note=(
                "v0.15 demo: S-ALPHA-001 is still owned by PRJ-ALPHA, but it is "
                "linked to PRJ-BETA and PRJ-GAMMA so those teams can view it without "
                "taking ownership."
            ),
        )

        ProjectPost.objects.get_or_create(
            project=project_beta,
            author=director,
            note=(
                "v0.15 demo: linked samples now appear in project sample sections. "
                "PRJ-BETA can see S-ALPHA-001 as a linked sample, but primary-project "
                "permissions still control edits and imports."
            ),
        )

        ProjectPost.objects.get_or_create(
            project=project_alpha,
            author=peter,
            note=(
                "v0.15 demo: META-CSV shows flexible CSV import support. The import "
                "can skip metadata rows and auto-detect the real header using the "
                "sample_id column."
            ),
        )

        # --------------------------------------------------
        # Notifications
        # --------------------------------------------------
        Notification.objects.get_or_create(
            user=peter,
            title="NovaFlex import completed",
            defaults={
                "message": "NovaFlex demo import completed for Alpha samples.",
                "link": "/imports",
            },
        )

        Notification.objects.get_or_create(
            user=maria,
            title="Sequencing review needed",
            defaults={
                "message": "S-ALPHA-003 has sequencing QC values that need review.",
                "link": "/projects",
            },
        )

        Notification.objects.get_or_create(
            user=michael,
            title="Endotoxin review needed",
            defaults={
                "message": "S-ALPHA-003 has elevated endotoxin results.",
                "link": "/projects",
            },
        )

        Notification.objects.get_or_create(
            user=director,
            title="v0.15 demo features ready",
            defaults={
                "message": (
                    "Cross-project sample linking and flexible CSV header detection "
                    "demo data has been seeded."
                ),
                "link": "/samples",
            },
        )

        Notification.objects.update_or_create(
            user=director,
            title="Instrument provenance demo ready",
            defaults={
                "message": (
                    "Seeded instrument runs now link directly to their samples, "
                    "work items, and results for v0.24 provenance demonstrations."
                ),
                "link": "/imports",
            },
        )

        Notification.objects.get_or_create(
            user=director,
            title="Demo environment ready",
            defaults={
                "message": "OpenLIMS demo data has been seeded successfully.",
                "link": "/",
            },
        )

        Notification.objects.update_or_create(
            user=director,
            title="Comprehensive capability demo ready",
            defaults={
                "message": (
                    "Registry, Molecular Biology v2, lineage, custody scanning, "
                    "advanced workflows, shared links, attachments, migration controls, "
                    "reports, and assistant audit examples are ready."
                ),
                "link": "/registry",
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write("")
        self.stdout.write("Demo users:")
        self.stdout.write("  director (admin)")
        self.stdout.write("  peter (tech)")
        self.stdout.write("  maria (tech + QC reviewer)")
        self.stdout.write("  michael (tech)")
        self.stdout.write("  viewer (read only)")
        self.stdout.write("")
        self.stdout.write("Comprehensive demos:")
        self.stdout.write("  Registry + immutable Molecular Biology revisions")
        self.stdout.write("  Lineage, aliquots, pooling, barcodes, and custody history")
        self.stdout.write("  Parallel/conditional workflows, QC gates, and retries")
        self.stdout.write("  Inventory hierarchy, reservations, shared links, and attachments")
        self.stdout.write("  SISBI migration mapping, reconciliation, and rollback")
        self.stdout.write("  BLAST, alignment, reports, notifications, and assistant confirmation")
        if configured_login_password:
            self.stdout.write(
                "Passwords were set from OPENLIMS_DEMO_PASSWORD; the value is not displayed."
            )
        else:
            self.stdout.write(
                "Existing passwords were preserved. New demo users cannot sign in until "
                "OPENLIMS_DEMO_PASSWORD is set and seed_demo is run again."
            )
