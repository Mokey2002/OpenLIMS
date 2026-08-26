import pytest

from events.models import Event
from settings_app.models import SystemSettings


@pytest.mark.django_db
def test_ui_language_is_available_before_login(api_client):
    settings_obj = SystemSettings.load()
    settings_obj.ui_language = "es"
    settings_obj.save()

    response = api_client.get("/api/ui-settings/")

    assert response.status_code == 200
    assert response.data == {"ui_language": "es"}


@pytest.mark.django_db
def test_director_can_change_ui_language_to_spanish(admin_client):
    response = admin_client.patch(
        "/api/system-settings/1/",
        {"ui_language": "es"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["ui_language"] == "es"
    assert SystemSettings.load().ui_language == "es"

    event = Event.objects.get(action="SETTINGS_UPDATED")
    assert event.payload["before"]["ui_language"] == "en"
    assert event.payload["after"]["ui_language"] == "es"


@pytest.mark.django_db
@pytest.mark.parametrize("client_fixture", ["tech_client", "viewer_client"])
def test_non_directors_cannot_change_ui_language(client_fixture, request):
    client = request.getfixturevalue(client_fixture)

    response = client.patch(
        "/api/system-settings/1/",
        {"ui_language": "es"},
        format="json",
    )

    assert response.status_code == 403
    assert SystemSettings.load().ui_language == "en"


@pytest.mark.django_db
def test_ui_language_rejects_unsupported_values(admin_client):
    response = admin_client.patch(
        "/api/system-settings/1/",
        {"ui_language": "fr"},
        format="json",
    )

    assert response.status_code == 400
    assert "ui_language" in response.data
    assert SystemSettings.load().ui_language == "en"


@pytest.mark.django_db
def test_reset_defaults_restores_english(admin_client):
    settings_obj = SystemSettings.load()
    settings_obj.ui_language = "es"
    settings_obj.save()

    response = admin_client.post(
        "/api/system-settings/reset-defaults/",
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["ui_language"] == "en"
    assert SystemSettings.load().ui_language == "en"


@pytest.mark.django_db
def test_feature_flags_default_off_and_require_authentication(api_client, admin_client):
    unauthenticated = api_client.get("/api/v1/feature-flags/")
    authenticated = admin_client.get("/api/v1/feature-flags/")

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.data == {
        "notebook": False,
        "registry": False,
        "studies": False,
        "insight": False,
    }


@pytest.mark.django_db
def test_director_can_enable_foundation_feature_flags(admin_client):
    response = admin_client.patch(
        "/api/v1/system-settings/1/",
        {
            "notebook_enabled": True,
            "registry_enabled": True,
            "studies_enabled": True,
            "insight_enabled": True,
        },
        format="json",
    )

    assert response.status_code == 200
    flags = admin_client.get("/api/v1/feature-flags/")
    assert flags.data == {
        "notebook": True,
        "registry": True,
        "studies": True,
        "insight": True,
    }


@pytest.mark.django_db
def test_reset_defaults_disables_foundation_feature_flags(admin_client):
    settings_obj = SystemSettings.load()
    settings_obj.notebook_enabled = True
    settings_obj.registry_enabled = True
    settings_obj.studies_enabled = True
    settings_obj.insight_enabled = True
    settings_obj.save()

    response = admin_client.post(
        "/api/v1/system-settings/reset-defaults/",
        {},
        format="json",
    )

    assert response.status_code == 200
    assert SystemSettings.load().feature_flags == {
        "notebook": False,
        "registry": False,
        "studies": False,
        "insight": False,
    }
