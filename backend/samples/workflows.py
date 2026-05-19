ALLOWED_TRANSITIONS = {
    "RECEIVED": ["IN_PROGRESS"],
    "IN_PROGRESS": ["QC"],
    "QC": ["REPORTED"],
    "REPORTED": ["ARCHIVED"],
    "ARCHIVED": [],
}


def get_allowed_transitions(current_status: str) -> list[str]:
    return ALLOWED_TRANSITIONS.get(current_status, [])


def can_transition(current_status: str, new_status: str) -> bool:
    return new_status in get_allowed_transitions(current_status)
