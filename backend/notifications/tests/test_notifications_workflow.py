import pytest
from notifications.models import Notification
from projects.models import Project

pytestmark = pytest.mark.django_db


def test_project_post_creates_notifications(
    admin_client,
    member_user,
    other_user,
):
    project = Project.objects.create(name="Test", code="T1")
    project.members.add(member_user, other_user)

    response = admin_client.post(
        "/api/project-posts/",
        {
            "project": project.id,
            "note": "Important update",
        },
        format="json",
    )

    assert response.status_code in (200, 201)

    assert Notification.objects.filter(user=member_user).exists()
    assert Notification.objects.filter(user=other_user).exists()
