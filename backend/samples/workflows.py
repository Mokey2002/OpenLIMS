ALLOWED_TRANSITIONS = {
    "RECEIVED": ["IN_PROGRESS", "CANCELLED"],
    "IN_PROGRESS": ["QC", "CANCELLED"],
    "QC": ["REPORTED", "CANCELLED"],
    "REPORTED": ["ARCHIVED"],
    "CANCELLED": ["ARCHIVED"],
    "ARCHIVED": [],
}


def get_status_transitions() -> dict:
    from settings_app.models import SampleStatusPolicy
    policy = SampleStatusPolicy.objects.filter(pk=1).first()
    return policy.transitions if policy and policy.transitions else ALLOWED_TRANSITIONS


def get_allowed_transitions(current_status: str, transitions=None) -> list[str]:
    if transitions is None:
        transitions = get_status_transitions()
    return transitions.get(current_status, [])


def can_transition(current_status: str, new_status: str) -> bool:
    return new_status in get_allowed_transitions(current_status)
