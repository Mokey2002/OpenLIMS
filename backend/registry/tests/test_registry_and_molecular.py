import io

import pytest
from Bio import SeqIO
from django.core.files.uploadedfile import SimpleUploadedFile

from events.models import Event
from inventory.models import InventoryItem, InventoryLot, Location
from migration_toolkit.models import (
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
)
from registry.imports import apply_registry_migration, prepare_registry_preview
from registry.models import RegistryRecord, RegistryRecordVersion, RegistrySchema
from sequences.models import Sequence, SequenceRevision


pytestmark = pytest.mark.django_db


def results(response):
    return response.data.get("results", response.data)


@pytest.fixture
def plasmid_schema(admin_client):
    response = admin_client.post(
        "/api/v1/registry-schemas/",
        {
            "code": "plasmid",
            "name": "Plasmid",
            "entity_type": "plasmid",
            "version": 1,
            "id_prefix": "PLS",
            "schema": {
                "type": "object",
                "required": ["backbone"],
                "properties": {
                    "backbone": {"type": "string"},
                    "resistance": {"type": "string"},
                },
            },
            "matching_fields": ["backbone", "resistance"],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return RegistrySchema.objects.get(pk=response.data["id"])


def test_director_configures_versioned_plasmid_schema(admin_client, plasmid_schema):
    blocked = admin_client.patch(
        f"/api/v1/registry-schemas/{plasmid_schema.id}/",
        {"name": "Plasmid changed"},
        format="json",
    )
    assert blocked.status_code == 200

    newer = admin_client.post(
        f"/api/v1/registry-schemas/{plasmid_schema.id}/new-version/",
        {
            "schema": {
                **plasmid_schema.schema,
                "properties": {
                    **plasmid_schema.schema["properties"],
                    "host": {"type": "string"},
                },
            }
        },
        format="json",
    )
    assert newer.status_code == 201, newer.data
    assert newer.data["version"] == 2


def test_sequence_revision_validation_tools_diff_restore_and_primer_metrics(
    tech_client, tech_user, project
):
    project.members.add(tech_user)
    invalid = tech_client.post(
        "/api/v1/sequences/",
        {"name": "Invalid", "sequence_type": "DNA", "sequence": "ATGU", "project": project.id},
        format="json",
    )
    assert invalid.status_code == 400

    created = tech_client.post(
        "/api/v1/sequences/",
        {
            "name": "Circular plasmid",
            "sequence_type": "DNA",
            "topology": "CIRCULAR",
            "sequence": "GAATTCATGGGATCCTAA",
            "project": project.id,
            "features": [
                {"feature_type": "PRIMER", "name": "Forward", "start": 6, "end": 14, "direction": 1}
            ],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    sequence = Sequence.objects.get(pk=created.data["id"])
    assert sequence.revisions.count() == 1
    first = sequence.current_revision
    primer = first.features.get(feature_type="PRIMER")
    assert primer.primer_sequence == "ATGGGATC"
    assert primer.gc_content == 50.0
    assert primer.melting_temperature is not None

    updated = tech_client.patch(
        f"/api/v1/sequences/{sequence.id}/",
        {"sequence": "GAATTCATGGGATCCTAAGG", "change_summary": "Added cloning overhang"},
        format="json",
    )
    assert updated.status_code == 200, updated.data
    sequence.refresh_from_db()
    assert sequence.revisions.count() == 2
    assert first.sequence == "GAATTCATGGGATCCTAA"

    diff = tech_client.get(
        f"/api/v1/sequences/{sequence.id}/revision-diff/?left=1&right=2"
    )
    assert diff.status_code == 200
    assert diff.data["identical"] is False
    assert diff.data["changes"]

    analysis = tech_client.post(
        f"/api/v1/sequences/{sequence.id}/molecular-tools/",
        {"operation": "ANALYZE", "minimum_codons": 2},
        format="json",
    )
    assert analysis.status_code == 200
    assert analysis.data["length"] == 20
    assert "molecular_weight" in analysis.data

    digest = tech_client.post(
        f"/api/v1/sequences/{sequence.id}/virtual-digest/",
        {"enzymes": ["EcoRI", "BamHI"]},
        format="json",
    )
    assert digest.status_code == 200
    assert {site["enzyme"] for site in digest.data["sites"]} == {"EcoRI", "BamHI"}

    restored = tech_client.post(
        f"/api/v1/sequences/{sequence.id}/restore-revision/",
        {"revision": 1},
        format="json",
    )
    assert restored.status_code == 201
    sequence.refresh_from_db()
    assert sequence.current_revision.revision == 3
    assert sequence.sequence == first.sequence


def test_plasmid_registration_versions_duplicates_links_permissions_and_audit(
    admin_client,
    tech_client,
    viewer_client,
    tech_user,
    project,
    sample,
    plasmid_schema,
):
    project.members.add(tech_user)
    sequence_response = tech_client.post(
        "/api/v1/sequences/",
        {
            "name": "pOpenLIMS",
            "sequence_type": "DNA",
            "topology": "CIRCULAR",
            "sequence": "GAATTCATGAAATAGGGATCC",
            "project": project.id,
            "features": [
                {"feature_type": "ANNOTATION", "name": "CDS", "start": 6, "end": 15, "direction": 1}
            ],
        },
        format="json",
    )
    assert sequence_response.status_code == 201, sequence_response.data
    sequence = Sequence.objects.get(pk=sequence_response.data["id"])

    record_response = tech_client.post(
        "/api/v1/registry-records/",
        {
            "schema": plasmid_schema.id,
            "name": "pOpenLIMS",
            "catalog_number": "CAT-100",
            "project": project.id,
            "visibility": "PROJECT",
            "data": {"backbone": "pUC19", "resistance": "ampicillin"},
            "sequence_revision": sequence.current_revision_id,
            "aliases": [{"alias": "pOL-1", "alias_type": "laboratory"}],
            "tags": ["demo", "cloning"],
        },
        format="json",
    )
    assert record_response.status_code == 201, record_response.data
    record = RegistryRecord.objects.get(pk=record_response.data["id"])
    assert record.registry_id.startswith("PLS-")
    assert record.current_version.version == 1
    assert record.current_version.sequence_revision.registry_record == record
    assert sequence.revisions.count() == 2
    assert viewer_client.get(f"/api/v1/registry-records/{record.id}/").status_code == 404

    version_response = tech_client.post(
        f"/api/v1/registry-records/{record.id}/new-version/",
        {
            "data": {"backbone": "pUC19", "resistance": "kanamycin"},
            "change_summary": "Changed selection marker",
        },
        format="json",
    )
    assert version_response.status_code == 201, version_response.data
    record.refresh_from_db()
    assert record.versions.count() == 2
    assert record.versions.get(version=1).data["resistance"] == "ampicillin"

    location = Location.objects.create(name="Registry freezer", kind="freezer")
    item = InventoryItem.objects.create(code="PLASMID", name="Plasmid stock", default_unit="uL")
    lot = InventoryLot.objects.create(
        item=item, lot_code="LOT-POL-1", quantity=10, unit="uL", location=location
    )
    for target_type, target_id, relation in [
        ("sample", sample.public_id, "represented_by"),
        ("inventory_lot", lot.public_id, "stored_as"),
    ]:
        linked = tech_client.post(
            "/api/v1/entity-links/",
            {
                "source_type": "registry_record",
                "source_public_id": str(record.public_id),
                "target_type": target_type,
                "target_public_id": str(target_id),
                "relation_type": relation,
            },
            format="json",
        )
        assert linked.status_code == 201, linked.data

    submitted = tech_client.post(
        f"/api/v1/registry-records/{record.id}/submit-review/", {}, format="json"
    )
    assert submitted.status_code == 200, submitted.data
    approved = admin_client.post(
        f"/api/v1/registry-records/{record.id}/review/",
        {"decision": "APPROVED", "comments": "Sequence and metadata verified."},
        format="json",
    )
    assert approved.status_code == 200, approved.data
    record.refresh_from_db()
    assert record.lifecycle_status == RegistryRecord.STATUS_REGISTERED
    event = Event.objects.filter(action="REGISTRATION_REVIEWED").latest("id")
    assert event.entity_type == "registry_record"
    assert event.entity_id == str(record.public_id)
    assert event.payload["schema_version"] == 1

    duplicate_sequence = tech_client.post(
        "/api/v1/sequences/",
        {
            "name": "Duplicate",
            "sequence_type": "DNA",
            "topology": "CIRCULAR",
            "sequence": "GAATTCATGAAATAGGGATCC",
            "project": project.id,
        },
        format="json",
    )
    duplicate = tech_client.post(
        "/api/v1/registry-records/duplicate-check/",
        {
            "schema": plasmid_schema.id,
            "name": "Duplicate",
            "sequence_revision": duplicate_sequence.data["current_revision"],
            "data": {"backbone": "other", "resistance": "chloramphenicol"},
        },
        format="json",
    )
    assert duplicate.status_code == 200
    assert duplicate.data["duplicate"] is True
    assert "sequence_checksum" in duplicate.data["matches"][0]["reasons"]


def test_genbank_round_trip_preserves_annotations(tech_client, tech_user, project):
    project.members.add(tech_user)
    genbank = """LOCUS       TESTSEQ                   18 bp    DNA     circular SYN 01-JAN-2000
DEFINITION  Example plasmid.
ACCESSION   TESTSEQ
VERSION     TESTSEQ.1
FEATURES             Location/Qualifiers
     misc_feature    1..6
                     /label="promoter"
ORIGIN
        1 gaattcatgg gatcctaa
//
"""
    imported = tech_client.post(
        "/api/v1/sequences/import-file/",
        {
            "file": SimpleUploadedFile("example.gb", genbank.encode(), content_type="text/plain"),
            "project": str(project.id),
            "format": "genbank",
        },
        format="multipart",
    )
    assert imported.status_code == 201, imported.data
    sequence_id = imported.data[0]["id"]
    exported = tech_client.get(f"/api/v1/sequences/{sequence_id}/export/?file_format=genbank")
    assert exported.status_code == 200
    parsed = SeqIO.read(io.StringIO(exported.content.decode()), "genbank")
    assert parsed.annotations["topology"] == "circular"
    labels = [feature.qualifiers.get("label", []) for feature in parsed.features]
    assert ["promoter"] in labels


def test_registry_csv_import_reuses_migration_preview_fingerprint(
    admin_user, project, plasmid_schema
):
    profile = MigrationProfile.objects.create(
        name="Registry CSV", source_system="Legacy Registry", source_type="CSV", created_by=admin_user
    )
    mappings = [
        ("registry_id", MigrationFieldMapping.TARGET_REGISTRY_ID, "", True),
        ("schema", MigrationFieldMapping.TARGET_REGISTRY_SCHEMA, "", True),
        ("name", MigrationFieldMapping.TARGET_REGISTRY_NAME, "", True),
        ("backbone", MigrationFieldMapping.TARGET_REGISTRY_DATA, "backbone", True),
        ("resistance", MigrationFieldMapping.TARGET_REGISTRY_DATA, "resistance", False),
        ("sequence", MigrationFieldMapping.TARGET_REGISTRY_SEQUENCE, "", False),
        ("alias", MigrationFieldMapping.TARGET_REGISTRY_ALIAS, "", False),
    ]
    for source, target, field, required in mappings:
        MigrationFieldMapping.objects.create(
            profile=profile, source_column=source, target_type=target,
            target_field=field, required=required,
        )
    content = (
        "registry_id,schema,name,backbone,resistance,sequence,alias\n"
        "PLS-LEGACY-1,plasmid,Legacy plasmid,pBR322,ampicillin,GAATTCATGGGATCC,pLegacy\n"
    ).encode()
    upload = SimpleUploadedFile("registry.csv", content, content_type="text/csv")
    summary, _ = prepare_registry_preview(
        profile, uploaded_file=upload, default_project=project
    )
    assert summary["ready_to_commit"] is True
    job = MigrationJob.objects.create(
        profile=profile,
        project=project,
        uploaded_file=SimpleUploadedFile("registry.csv", content, content_type="text/csv"),
        uploaded_by=admin_user,
        committed_by=admin_user,
        status=MigrationJob.STATUS_RUNNING,
        summary=summary,
        source_snapshot=summary["source_snapshot"],
        preview_fingerprint=summary["preview_fingerprint"],
    )
    applied = apply_registry_migration(job, admin_user)
    record = RegistryRecord.objects.get(registry_id="PLS-LEGACY-1")
    assert applied["records_created"] == 1
    assert record.current_version.data["backbone"] == "pBR322"
    assert record.current_version.sequence_checksum
    assert job.row_records.get().target_object_id == str(record.public_id)


def test_registry_record_versions_cannot_be_mutated(plasmid_schema, admin_user, project):
    record = RegistryRecord.objects.create(
        registry_id="PLS-IMMUTABLE", schema=plasmid_schema, name="Immutable",
        project=project, owner=admin_user,
    )
    version = RegistryRecordVersion.objects.create(
        record=record, schema=plasmid_schema, version=1,
        data={"backbone": "pUC"}, created_by=admin_user,
    )
    version.data = {"backbone": "changed"}
    with pytest.raises(Exception, match="immutable"):
        version.save()
