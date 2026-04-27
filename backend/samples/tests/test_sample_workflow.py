import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from samples.models import Sample
from events.models import Event

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="tech1", password="pass123")


@pytest.fixture
def client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_sample_lifecycle_workflow(tech_client):
    sample = Sample.objects.create(sample_id="S-LIFE-001", status="RECEIVED")

    r1 = tech_client.post(
        f"/api/samples/{sample.id}/transition/",
        {"new_status": "IN_PROGRESS"},
        format="json",
    )
    assert r1.status_code == 200

    r2 = tech_client.post(
        f"/api/samples/{sample.id}/transition/",
        {"new_status": "QC"},
        format="json",
    )
    assert r2.status_code == 200

    r3 = tech_client.post(
        f"/api/samples/{sample.id}/transition/",
        {"new_status": "REPORTED"},
        format="json",
    )
    assert r3.status_code == 200

    sample.refresh_from_db()
    assert sample.status == "REPORTED"

    events = Event.objects.filter(
        entity_type="Sample",
        entity_id=str(sample.id),
        action="STATUS_CHANGED",
    )
    assert events.count() == 3
