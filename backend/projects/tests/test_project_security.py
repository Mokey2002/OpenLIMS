import pytest

pytestmark = pytest.mark.django_db


def test_user_cannot_access_other_project(other_client, project):
    response = other_client.get(f"/api/projects/{project.id}/")
    assert response.status_code in (403, 404)


def test_member_can_access_project(member_client, project):
    response = member_client.get(f"/api/projects/{project.id}/")
    assert response.status_code == 200
