import pytest
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from projects.models import Project

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    user = User.objects.create_user(username="admin1", password="pass123")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    return user


@pytest.fixture
def member_user():
    return User.objects.create_user(username="member1", password="pass123")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other1", password="pass123")


@pytest.fixture
def project(member_user):
    p = Project.objects.create(name="Project A", code="PA")
    p.members.add(member_user)
    return p


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_admin_can_see_all_projects(admin_user, project):
    client = auth_client(admin_user)
    response = client.get("/api/projects/")
    assert response.status_code == 200
    data = response.json()
    results = data["results"] if "results" in data else data
    assert len(results) >= 1


def test_member_sees_only_assigned_projects(member_user, project):
    client = auth_client(member_user)
    response = client.get("/api/projects/")
    assert response.status_code == 200
    data = response.json()
    results = data["results"] if "results" in data else data
    assert any(p["id"] == project.id for p in results)


def test_non_member_cannot_see_unassigned_project(other_user, project):
    client = auth_client(other_user)
    response = client.get("/api/projects/")
    assert response.status_code == 200
    data = response.json()
    results = data["results"] if "results" in data else data
    assert all(p["id"] != project.id for p in results)
