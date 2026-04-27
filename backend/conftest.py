import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from imports.models import InstrumentProfile, InstrumentColumnMapping
from projects.models import Project
from samples.models import Sample

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_group():
    group, _ = Group.objects.get_or_create(name="admin")
    return group


@pytest.fixture
def tech_group():
    group, _ = Group.objects.get_or_create(name="tech")
    return group


@pytest.fixture
def viewer_group():
    group, _ = Group.objects.get_or_create(name="viewer")
    return group


@pytest.fixture
def admin_user(admin_group):
    user = User.objects.create_user(
        username="admin1",
        email="admin1@test.com",
        password="pass123",
    )
    user.groups.add(admin_group)
    return user


@pytest.fixture
def tech_user(tech_group):
    user = User.objects.create_user(
        username="tech1",
        email="tech1@test.com",
        password="pass123",
    )
    user.groups.add(tech_group)
    return user


@pytest.fixture
def viewer_user(viewer_group):
    user = User.objects.create_user(
        username="viewer1",
        email="viewer1@test.com",
        password="pass123",
    )
    user.groups.add(viewer_group)
    return user


@pytest.fixture
def member_user():
    return User.objects.create_user(
        username="member1",
        email="member1@test.com",
        password="pass123",
    )


@pytest.fixture
def other_user():
    return User.objects.create_user(
        username="other1",
        email="other1@test.com",
        password="pass123",
    )


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def tech_client(tech_user):
    client = APIClient()
    client.force_authenticate(user=tech_user)
    return client


@pytest.fixture
def viewer_client(viewer_user):
    client = APIClient()
    client.force_authenticate(user=viewer_user)
    return client


@pytest.fixture
def member_client(member_user):
    client = APIClient()
    client.force_authenticate(user=member_user)
    return client


@pytest.fixture
def other_client(other_user):
    client = APIClient()
    client.force_authenticate(user=other_user)
    return client


@pytest.fixture
def instrument_profile():
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
        min_value=0,
        max_value=1000,
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="purity",
        target_key="purity",
        value_type="NUMBER",
        min_value=0,
        max_value=100,
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="qc_flag",
        target_key="qc_flag",
        value_type="STRING",
        allowed_values=["PASS", "FAIL"],
    )

    return profile


@pytest.fixture
def instrument_headers():
    return {
        "HTTP_X_INSTRUMENT_API_KEY": settings.INSTRUMENT_API_KEY,
    }


@pytest.fixture
def project(admin_user, member_user):
    p = Project.objects.create(
        name="Project Alpha",
        code="PA-001",
        description="Test project",
    )
    p.members.add(admin_user, member_user)
    return p


@pytest.fixture
def sample(project):
    return Sample.objects.create(
        sample_id="S-001",
        status="RECEIVED",
        project=project,
    )


@pytest.fixture
def second_sample(project):
    return Sample.objects.create(
        sample_id="S-002",
        status="RECEIVED",
        project=project,
    )


@pytest.fixture
def ingest_payload():
    return {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-001",
        "rows": [
            {
                "sample_id": "S-INGEST-001",
                "concentration": 12.4,
                "purity": 97.1,
                "qc_flag": "PASS",
            }
        ],
    }
