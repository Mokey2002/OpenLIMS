"""Validated, pinned actions applied once per activated work item."""
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from core.permissions import is_admin, is_tech
from notifications.models import Notification
from samples.access import user_can_access_sample, user_can_modify_sample


def validate_automation(value):
    if not isinstance(value, dict) or set(value) - {"assigned_to", "notify_assignee", "notify_users"}:
        raise ValidationError("Invalid step actions. / Acciones del paso inválidas.")
    assigned = value.get("assigned_to")
    recipients = value.get("notify_users", [])
    notify = value.get("notify_assignee", False)
    if (assigned is not None and (type(assigned) is not int or assigned < 1)) or type(notify) is not bool:
        raise ValidationError("Invalid assignee or notification setting. / Asignación o notificación inválida.")
    if not isinstance(recipients, list) or len(recipients) > 50 or any(type(pk) is not int or pk < 1 for pk in recipients):
        raise ValidationError("Select at most 50 recipients. / Seleccione hasta 50 destinatarios.")
    ids = set(recipients) | ({assigned} if assigned else set())
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=ids, is_active=True).prefetch_related("groups")}
    if ids != set(users):
        raise ValidationError("Select active users. / Seleccione usuarios activos.")
    if assigned and not (is_admin(users[assigned]) or is_tech(users[assigned])):
        raise ValidationError("Assign work to an administrator or technician. / Asigne el trabajo a un administrador o técnico.")
    if notify and not assigned:
        raise ValidationError("Select an assignee to notify. / Seleccione una persona asignada para notificar.")
    return {"assigned_to": assigned, "notify_assignee": notify, "notify_users": sorted(set(recipients))} if value else {}


def apply_step_actions(step, actor):
    from .services import _event, _step_payload

    config = step.automation or {}
    if not config:
        return
    sample = step.pipeline_run.sample
    assigned = config.get("assigned_to")
    ids = set(config.get("notify_users", []))
    if assigned:
        ids.add(assigned)
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=ids, is_active=True).prefetch_related("groups")}
    assignee = users.get(assigned)
    assignment_applied = bool(assignee and user_can_modify_sample(assignee, sample))
    if assignment_applied:
        step.work_item.assigned_to = assignee
        step.work_item.save(update_fields=["assigned_to", "updated_at"])
    recipients = set(config.get("notify_users", []))
    if config.get("notify_assignee") and assignment_applied:
        recipients.add(assigned)
    notified, skipped = [], []
    for pk in sorted(recipients):
        user = users.get(pk)
        if not user or not user_can_access_sample(user, sample):
            skipped.append(pk)
            continue
        Notification.objects.create(
            user=user,
            title="Workflow step ready / Paso del flujo listo",
            message=f"{sample.sample_id}: {step.name}",
            link=f"/samples/{sample.pk}",
        )
        notified.append(pk)
    payload = _step_payload(step)
    payload.update({"configured_actions": config, "assigned_to": assigned if assignment_applied else None,
                    "assignment_skipped": bool(assigned and not assignment_applied),
                    "notified_users": notified, "skipped_recipients": skipped, "attempt": step.retry_count})
    _event("PipelineRun", step.pipeline_run_id, "WORKFLOW_ACTIONS_APPLIED", actor, payload)
