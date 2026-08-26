from core.entities import entity_reference, get_entity_project


AUDIT_PAYLOAD_SCHEMA_VERSION = 1


def build_audit_payload(
    entity,
    *,
    reason="",
    before=None,
    after=None,
    details=None,
):
    """Create the common audit payload used by new OpenLIMS modules."""
    project = get_entity_project(entity)
    payload = {
        "schema_version": AUDIT_PAYLOAD_SCHEMA_VERSION,
        "entity": entity_reference(entity),
        "project": (
            {
                "public_id": str(project.public_id),
                "code": project.code,
                "name": project.name,
            }
            if project is not None
            else None
        ),
        "reason": str(reason or ""),
        "before": before if before is not None else {},
        "after": after if after is not None else {},
        "details": details if details is not None else {},
    }
    return payload


def record_audit_event(
    *,
    entity,
    action,
    actor=None,
    reason="",
    before=None,
    after=None,
    details=None,
):
    from events.models import Event

    reference = entity_reference(entity)
    return Event.objects.create(
        entity_type=reference["type"],
        entity_id=reference["public_id"],
        action=action,
        actor=actor if actor and actor.is_authenticated else None,
        payload=build_audit_payload(
            entity,
            reason=reason,
            before=before,
            after=after,
            details=details,
        ),
    )
