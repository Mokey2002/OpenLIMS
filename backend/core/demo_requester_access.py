from django.conf import settings


DEMO_REQUESTER_USERNAME = "demo-requester"
DEMO_REQUESTER_EMAIL = "demo-requester@example.invalid"
DEMO_PROJECT_CODE = "PRJ-REQUESTER-DEMO"
DEMO_PROJECT_DESCRIPTION = "Fictional requester submissions, sample receipt, and report release."
DEMO_REQUESTER_CLAIM = "requester_demo"


def is_requester_demo_session(token):
    return bool(token and token.get(DEMO_REQUESTER_CLAIM))


def can_use_requester_demo(user):
    if not settings.OPENLIMS_REQUESTER_DEMO_ENABLED or not user or (
        user.username != DEMO_REQUESTER_USERNAME or user.email != DEMO_REQUESTER_EMAIL
        or not user.is_active or user.is_staff or user.is_superuser
    ):
        return False
    return (
        set(user.groups.values_list("name", flat=True)) == {"requester"}
        and list(user.projects.values_list("code", "description")) == [(DEMO_PROJECT_CODE, DEMO_PROJECT_DESCRIPTION)]
        and not user.client_team_memberships.exists()
    )
