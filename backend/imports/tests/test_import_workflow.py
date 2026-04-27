import io
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from imports.models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from samples.models import Sample

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    user = User.objects.create_user(username="admin1", password="pass123")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    return user


@pytest.fixture
def client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def instrument():
    profile = InstrumentProfile.objects.create(
        name="NovaFlex",
        code="NOVAFLEX",
        delimiter=",",
        has_header=True,
        sample_id_column="sample_id",
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="concentration",
        target_key="concentration",
        value_type="NUMBER",
    )

    return profile


def test_csv_import_workflow(client, instrument):
    csv_content = b"sample_id,concentration\nS-CSV-001,14.5\n"
    upload = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")

    response = client.post(
        "/api/import-jobs/",
        {
            "instrument": instrument.id,
            "uploaded_file": upload,
        },
        format="multipart",
    )

    assert response.status_code in (200, 201)

    job = ImportJob.objects.first()
    assert job.status in ("PENDING","COMPLETED")
    assert Sample.objects.filter(sample_id="S-CSV-001").exists()
