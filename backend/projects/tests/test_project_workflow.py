import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from projects.models import Project, ProjectPost
from notifications.models import Notification

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
    return User.objects.create_user(username="member2", password="pass123")


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_project_post_workflow_creates_notification(admin_user, member_user, other_user):
    project = Project.objects.create(name="Project X", code="PX")
    project.members.add(admin_user, member_user, other_user)

    client = auth_client(admin_user)

    response = client.post(
        "/api/project-posts/",
        {
            "project": project.id,
            "note": "New lab update",
        },
        format="json",
    )

    assert response.status_code in (200, 201)
    assert ProjectPost.objects.filter(project=project, note="New lab update").exists()

    assert Notification.objects.filter(
        user=member_user,
        title="New project post",
    ).exists()

    assert Notification.objects.filter(
        user=other_user,
        title="New project post",
    ).exists()
