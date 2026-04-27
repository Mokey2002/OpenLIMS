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


@pytest.fixture
def sample():
    return Sample.objects.create(sample_id="S-100", status="RECEIVED")


def test_valid_sample_transition_creates_event(tech_client, sample):
    response = tech_client.post(
        f"/api/samples/{sample.id}/transition/",
        {"new_status": "IN_PROGRESS"},
        format="json",
    )

    assert response.status_code == 200

    sample.refresh_from_db()
    assert sample.status == "IN_PROGRESS"

    assert Event.objects.filter(
        entity_type="Sample",
        entity_id=str(sample.id),
        action="STATUS_CHANGED",
    ).exists()
