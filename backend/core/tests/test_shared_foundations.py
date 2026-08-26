import hashlib
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from core.audit import AUDIT_PAYLOAD_SCHEMA_VERSION, build_audit_payload
from core.entities import RESERVED_ENTITY_TYPES
from core.models import EntityLink, SharedAttachment
from events.models import Event
from inventory.models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from pipelines.models import PipelineRun, PipelineTemplate
from projects.models import Project
from samples.models import Sample
from sequences.models import Sequence


pytestmark = pytest.mark.django_db


def response_results(response):
    return response.data.get("results", response.data)


def test_public_ids_cover_current_and_reserved_module_entities(
    project,
    sample,
    admin_user,
):
    location = Location.objects.create(name="Freezer A", kind="freezer")
    container = Container.objects.create(
        container_id="BOX-FOUNDATION",
        kind="box",
        location=location,
    )
    item = InventoryItem.objects.create(
        code="FOUNDATION-REAGENT",
        name="Foundation reagent",
        default_unit="mL",
    )
    lot = InventoryLot.objects.create(
        item=item,
        lot_code="FOUNDATION-LOT",
        quantity=Decimal("10"),
        unit="mL",
        location=location,
        container=container,
    )
    reservation = InventoryReservation.objects.create(
        lot=lot,
        project=project,
        quantity=Decimal("1"),
        unit="mL",
        created_by=admin_user,
    )
    sequence = Sequence.objects.create(
        name="Foundation sequence",
        sequence_type="DNA",
        sequence="ATGC",
        project=project,
        sample=sample,
        created_by=admin_user,
    )
    template = PipelineTemplate.objects.create(
        code="FOUNDATION-PIPELINE",
        name="Foundation pipeline",
        created_by=admin_user,
    )
    run = PipelineRun.objects.create(
        sample=sample,
        template=template,
        template_code=template.code,
        template_name=template.name,
        started_by=admin_user,
    )

    records = [
        project,
        sample,
        sequence,
        location,
        container,
        item,
        lot,
        reservation,
        run,
    ]
    assert all(record.public_id for record in records)
    assert len({record.public_id for record in records}) == len(records)
    assert {"registry_record", "experiment", "study"} <= RESERVED_ENTITY_TYPES


def test_legacy_and_v1_sample_apis_return_the_same_stable_public_id(
    admin_client,
    sample,
):
    legacy = admin_client.get(f"/api/samples/{sample.id}/")
    versioned = admin_client.get(f"/api/v1/samples/{sample.id}/")

    assert legacy.status_code == 200
    assert versioned.status_code == 200
    assert legacy.data["id"] == versioned.data["id"] == sample.id
    assert legacy.data["public_id"] == versioned.data["public_id"] == str(sample.public_id)

    attempted_change = admin_client.patch(
        f"/api/v1/samples/{sample.id}/",
        {"public_id": "00000000-0000-0000-0000-000000000001"},
        format="json",
    )
    assert attempted_change.status_code == 200
    sample.refresh_from_db()
    assert str(sample.public_id) == versioned.data["public_id"]


def test_entity_reference_obeys_project_membership(
    member_client,
    other_client,
    sample,
):
    url = f"/api/v1/entity-references/sample/{sample.public_id}/"

    allowed = member_client.get(url)
    hidden = other_client.get(url)

    assert allowed.status_code == 200
    assert allowed.data["type"] == "sample"
    assert allowed.data["public_id"] == str(sample.public_id)
    assert allowed.data["project"]["public_id"] == str(sample.project.public_id)
    assert hidden.status_code == 404


def test_entity_links_use_common_permissions_and_audit_payload(
    tech_client,
    member_client,
    other_client,
    tech_user,
    project,
    sample,
):
    project.members.add(tech_user)
    sequence = Sequence.objects.create(
        name="Linked sequence",
        sequence_type="DNA",
        sequence="ATGC",
        project=project,
        sample=sample,
        created_by=tech_user,
    )
    payload = {
        "source_type": "sample",
        "source_public_id": str(sample.public_id),
        "target_type": "sequence",
        "target_public_id": str(sequence.public_id),
        "relation_type": "has-sequence",
        "label": "Primary sequence",
    }

    created = tech_client.post("/api/v1/entity-links/", payload, format="json")
    assert created.status_code == 201
    assert created.data["source"]["public_id"] == str(sample.public_id)
    assert created.data["target"]["public_id"] == str(sequence.public_id)

    duplicate = tech_client.post("/api/v1/entity-links/", payload, format="json")
    assert duplicate.status_code == 400

    member_list = member_client.get("/api/v1/entity-links/")
    other_list = other_client.get("/api/v1/entity-links/")
    assert len(response_results(member_list)) == 1
    assert response_results(other_list) == []

    event = Event.objects.get(action="ENTITY_LINK_CREATED")
    assert event.entity_type == "sample"
    assert event.entity_id == str(sample.public_id)
    assert event.payload["schema_version"] == AUDIT_PAYLOAD_SCHEMA_VERSION
    assert event.payload["project"]["public_id"] == str(project.public_id)
    assert event.payload["entity"]["public_id"] == str(sample.public_id)


def test_viewer_cannot_create_entity_link(
    viewer_client,
    viewer_user,
    project,
    sample,
):
    project.members.add(viewer_user)
    response = viewer_client.post(
        "/api/v1/entity-links/",
        {
            "source_type": "project",
            "source_public_id": str(project.public_id),
            "target_type": "sample",
            "target_public_id": str(sample.public_id),
            "relation_type": "contains",
        },
        format="json",
    )
    assert response.status_code == 403


def test_cross_project_links_are_rejected(admin_client, admin_user, sample):
    other_project = Project.objects.create(code="OTHER", name="Other project")
    other_sequence = Sequence.objects.create(
        name="Other sequence",
        sequence_type="DNA",
        sequence="ATGC",
        project=other_project,
        created_by=admin_user,
    )
    response = admin_client.post(
        "/api/v1/entity-links/",
        {
            "source_type": "sample",
            "source_public_id": str(sample.public_id),
            "target_type": "sequence",
            "target_public_id": str(other_sequence.public_id),
            "relation_type": "derived-from",
        },
        format="json",
    )
    assert response.status_code == 400
    assert EntityLink.objects.count() == 0


def test_projectless_private_records_cannot_leak_through_shared_links(
    tech_client,
    tech_user,
):
    first = Sequence.objects.create(
        name="Private sequence one",
        sequence_type="DNA",
        sequence="ATGC",
        created_by=tech_user,
    )
    second = Sequence.objects.create(
        name="Private sequence two",
        sequence_type="DNA",
        sequence="ATGG",
        created_by=tech_user,
    )

    response = tech_client.post(
        "/api/v1/entity-links/",
        {
            "source_type": "sequence",
            "source_public_id": str(first.public_id),
            "target_type": "sequence",
            "target_public_id": str(second.public_id),
            "relation_type": "related-to",
        },
        format="json",
    )

    assert response.status_code == 400
    assert EntityLink.objects.count() == 0


def test_shared_attachment_hashes_file_and_reuses_entity_access(
    tmp_path,
    tech_client,
    member_client,
    other_client,
    tech_user,
    project,
    sample,
):
    project.members.add(tech_user)
    content = b"shared foundation attachment"
    upload = SimpleUploadedFile(
        "protocol.txt",
        content,
        content_type="text/plain",
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        created = tech_client.post(
            "/api/v1/shared-attachments/",
            {
                "target_type": "sample",
                "target_public_id": str(sample.public_id),
                "file": upload,
                "description": "Reusable protocol attachment",
            },
            format="multipart",
        )

        assert created.status_code == 201
        assert created.data["target"]["public_id"] == str(sample.public_id)
        assert created.data["sha256"] == hashlib.sha256(content).hexdigest()
        assert created.data["project_public_id"] == str(project.public_id)
        assert SharedAttachment.objects.get().file.name.startswith("shared_attachments/")

        member_list = member_client.get("/api/v1/shared-attachments/")
        other_list = other_client.get("/api/v1/shared-attachments/")
        assert len(response_results(member_list)) == 1
        assert response_results(other_list) == []

    event = Event.objects.get(action="SHARED_ATTACHMENT_UPLOADED")
    assert event.payload["details"]["sha256"] == hashlib.sha256(content).hexdigest()


def test_common_audit_payload_has_stable_shape(sample):
    payload = build_audit_payload(
        sample,
        reason="Foundation contract test",
        before={"status": "RECEIVED"},
        after={"status": "IN_PROGRESS"},
        details={"source": "test"},
    )

    assert set(payload) == {
        "schema_version",
        "entity",
        "project",
        "reason",
        "before",
        "after",
        "details",
    }
    assert payload["entity"]["type"] == "sample"
    assert payload["entity"]["public_id"] == str(sample.public_id)


def test_openapi_schema_only_publishes_versioned_paths(api_client):
    response = api_client.get("/api/schema/")

    assert response.status_code == 200
    schema_text = response.content.decode("utf-8")
    assert "/api/v1/samples/" in schema_text
    assert "/api/v1/entity-links/" in schema_text
    assert "\n  /api/samples/" not in schema_text
