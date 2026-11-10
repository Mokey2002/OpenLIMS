"""Reviewed account handovers; scientific authorship and approvals are retained."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .access_requests import StrictSerializer
from .audit import record_audit_event
from .models import AccessRequest, UserOffboarding
from .permissions import application_roles, is_admin, is_qc_reviewer, is_tech
from .project_access import user_can_access_project
from .session_revocation import revoke_user_sessions, session_generation
from .user_safety import (
    LAST_ADMIN_MESSAGE, last_administrator_id, lock_users, protect_user_deletion, user_administration,
)

NOTEBOOK_GRANTS = ("team_members", "readers", "editors", "commenters", "reviewers", "lockers")
EXPERIMENT_OPEN = ("DRAFT", "IN_PROGRESS", "COMPLETED")


class OffboardingConflict(APIException):
    status_code = 409
    default_code = "offboarding_changed"

    def __init__(self, detail="Responsibilities or access changed. Review a new offboarding preview."):
        super().__init__({"detail": detail, "code": "offboarding_changed"})


class OffboardingPreviewSerializer(StrictSerializer):
    successor_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    reason = serializers.CharField(min_length=10, max_length=2000)
    custody_confirmed = serializers.BooleanField(default=False)


class OffboardingConfirmSerializer(StrictSerializer):
    preview_id = serializers.UUIDField()
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise ValidationError("Confirm the reviewed offboarding changes.")
        return value


@dataclass
class Responsibility:
    category: str
    entity: object
    field: str
    label: str
    access_entity: object


def responsibilities(user):
    from notebook.models import Notebook, Experiment, ExperimentWorkflowStep, ExperimentComment
    from registry.models import RegistryRecord, RegistrationReview
    from results.models import WorkItem, Result
    from samples.models import Sample

    specs = [
        ("samples", Sample.objects.filter(assigned_to=user, status__in=["RECEIVED", "IN_PROGRESS", "QC"]).select_related("project"), "assigned_to", lambda x: x.sample_id, lambda x: x),
        ("custody", Sample.objects.filter(custodian=user).select_related("project", "container"), "custodian", lambda x: x.sample_id, lambda x: x),
        ("work_items", WorkItem.objects.filter(assigned_to=user, status__in=["PENDING", "IN_PROGRESS", "FAILED"]).select_related("sample__project"), "assigned_to", lambda x: f"{x.sample.sample_id}: {x.name}", lambda x: x.sample),
        ("qc_results", Result.objects.filter(qc_assigned_to=user, qc_status__in=["PENDING_REVIEW", "REOPENED"]).select_related("work_item__sample__project"), "qc_assigned_to", lambda x: f"{x.work_item.sample.sample_id}: {x.key}", lambda x: x.work_item.sample),
        ("notebooks", Notebook.objects.filter(owner=user).select_related("project"), "owner", lambda x: x.name, lambda x: x),
        ("experiments", Experiment.objects.filter(assignees=user, status__in=EXPERIMENT_OPEN).select_related("notebook__project"), "assignees", lambda x: x.title, lambda x: x.notebook),
        ("workflow_steps", ExperimentWorkflowStep.objects.filter(assignee=user, status="PENDING", experiment__status__in=["DRAFT", "IN_PROGRESS"]).select_related("experiment__notebook__project"), "assignee", lambda x: f"{x.experiment.title}: step {x.position}", lambda x: x.experiment.notebook),
        ("comments", ExperimentComment.objects.filter(assigned_to=user, resolved=False).select_related("experiment__notebook__project"), "assigned_to", lambda x: f"{x.experiment.title}: {x.body[:100]}", lambda x: x.experiment.notebook),
        ("registry_records", RegistryRecord.objects.filter(owner=user).select_related("project"), "owner", lambda x: f"{x.registry_id}: {x.name}", lambda x: x),
        ("registry_reviews", RegistrationReview.objects.filter(reviewer=user, decision="PENDING").select_related("record__project"), "reviewer", lambda x: f"{x.record.registry_id}: pending review", lambda x: x.record),
    ]
    return [Responsibility(category, row, field, label(row), access(row))
            for category, query, field, label, access in specs for row in query.order_by("pk")]


def _lock_responsibilities(user):
    # Use domain parent locks before child rows, matching notebook/work/custody
    # writes. Membership subqueries keep FOR UPDATE off DISTINCT/outer joins.
    from samples.models import Sample
    from results.models import WorkItem, Result
    from notebook.models import Notebook, Experiment, ExperimentWorkflowStep, ExperimentComment
    from registry.models import RegistryRecord, RegistrationReview
    samples = Sample.objects.filter(Q(assigned_to=user) | Q(custodian=user) | Q(work_items__assigned_to=user) | Q(work_items__results__qc_assigned_to=user))
    experiments = Experiment.objects.filter(Q(assignees=user) | Q(workflow_steps__assignee=user) | Q(comments__assigned_to=user))
    notebooks = Notebook.objects.filter(Q(owner=user) | Q(experiments__in=experiments))
    records = RegistryRecord.objects.filter(Q(owner=user) | Q(reviews__reviewer=user))
    queries = [Sample.objects.filter(pk__in=samples.values("pk")),
               WorkItem.objects.filter(Q(assigned_to=user) | Q(results__qc_assigned_to=user)),
               Result.objects.filter(qc_assigned_to=user), Notebook.objects.filter(pk__in=notebooks.values("pk")),
               Experiment.objects.filter(pk__in=experiments.values("pk")),
               ExperimentWorkflowStep.objects.filter(assignee=user), ExperimentComment.objects.filter(assigned_to=user),
               RegistryRecord.objects.filter(pk__in=records.values("pk")), RegistrationReview.objects.filter(reviewer=user)]
    for query in queries:
        model = query.model
        list(model.objects.filter(pk__in=query.values("pk")).order_by("pk").select_for_update())


def _person(user):
    if user is None:
        return None
    return {"id": user.pk, "username": user.username, "is_active": user.is_active,
            "roles": sorted(application_roles(user)), "is_staff": user.is_staff, "is_superuser": user.is_superuser,
            "permissions": sorted(user.user_permissions.values_list("pk", flat=True)),
            "session_generation": session_generation(user)}


def inventory(user, rows=None):
    from assistant.models import AssistantAction, AssistantChatRequest, NotificationSubscription
    from inventory.models import InstrumentBooking
    from notebook.models import Notebook
    from projects.models import Project
    from workflow_requests.models import WorkflowRequest
    from settings_app.models import SystemSettings

    rows = responsibilities(user) if rows is None else rows
    groups = {}
    for item in rows:
        row = item.entity
        groups.setdefault(item.category, []).append({
            "id": row.pk, "public_id": str(row.public_id) if hasattr(row, "public_id") else None,
            "label": item.label, "field": item.field,
            "status": getattr(row, "status", getattr(row, "qc_status", "")),
            "updated_at": str(getattr(row, "updated_at", "")), "version": getattr(row, "version", None),
        })
    grants = {field: list(Notebook.objects.filter(**{field: user}).order_by("pk").values("id", "name")) for field in NOTEBOOK_GRANTS}
    return {
        "user": _person(user), "responsibilities": groups,
        "policy": {"qc_separation_of_duties": SystemSettings.load().qc_separation_of_duties},
        "counts": {key: len(value) for key, value in groups.items()}, "total_responsibilities": len(rows),
        "projects": list(Project.objects.filter(members=user).order_by("pk").values("id", "code", "name")),
        "notebook_grants": grants,
        "pending_access_requests": list(AccessRequest.objects.filter(requester=user, status="PENDING").order_by("pk").values_list("pk", flat=True)),
        "proposed_actions": list(AssistantAction.objects.filter(requested_by=user, status="PROPOSED").order_by("pk").values_list("pk", flat=True)),
        "subscriptions": list(NotificationSubscription.objects.filter(recipient=user, active=True).order_by("pk").values_list("pk", flat=True)),
        "chat_requests": list(AssistantChatRequest.objects.filter(owner=user, status="RUNNING").order_by("pk").values_list("pk", flat=True)),
        "continuing_jobs": list(AssistantAction.objects.filter(requested_by=user, status="QUEUED").order_by("pk").values("id", "summary")),
        "open_requests": list(WorkflowRequest.objects.filter(requester=user).exclude(status__in=["COMPLETED", "CANCELLED", "REJECTED"]).order_by("pk").values("id", "request_number", "title")),
        "future_bookings": list(InstrumentBooking.objects.filter(created_by=user, status="ACTIVE", ends_at__gt=timezone.now()).order_by("pk").values("id", "starts_at", "ends_at")),
    }


def _json(value):
    return json.loads(json.dumps(value, default=str))


def _fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def blockers(target, actor, successor=None, rows=None, custody_confirmed=False, selecting=False):
    from notebook.models import Notebook
    from notebook.permissions import user_can_notebook
    from samples.access import user_can_access_sample, user_can_modify_sample
    from samples.models import Sample
    from settings_app.models import SystemSettings
    problems = []
    if target.pk == actor.pk:
        problems.append("Another administrator must offboard your account.")
    if target.pk == last_administrator_id():
        problems.append(LAST_ADMIN_MESSAGE)
    if not selecting:
        return problems
    rows = responsibilities(target) if rows is None else rows
    if rows and successor is None:
        problems.append("Choose a replacement for the outstanding responsibilities.")
    if successor is not None and (successor.pk == target.pk or not successor.is_active):
        problems.append("Choose a different active replacement.")
        return problems
    if any(item.category == "custody" for item in rows) and not custody_confirmed:
        problems.append("Confirm that the physical sample handoff has been verified.")
    if successor is None:
        return problems
    owned_notebooks = {row.entity.pk for row in rows if row.category == "notebooks"}
    independent_qc = SystemSettings.load().qc_separation_of_duties
    for item in rows:
        entity = item.access_entity
        if item.category in {"qc_results", "registry_reviews"}:
            if not is_qc_reviewer(successor):
                problems.append(f"{item.label}: the replacement needs a QC reviewer or administrator role.")
            independent = item.category == "registry_reviews" or independent_qc
            if independent and getattr(item.entity, "entered_by_id", getattr(item.entity, "requested_by_id", None)) == successor.pk:
                problems.append(f"{item.label}: choose an independent reviewer.")
        if item.category in {"samples", "work_items", "custody"} and not (is_admin(successor) or is_tech(successor)):
            problems.append(f"{item.label}: the replacement needs a technician or administrator role.")
        if isinstance(entity, Notebook):
            if entity.pk not in owned_notebooks and not user_can_notebook(successor, entity, "write"):
                problems.append(f"{item.label}: the replacement needs edit access to the notebook.")
        elif isinstance(entity, Sample):
            permitted = user_can_access_sample(successor, entity) if item.category == "qc_results" else user_can_modify_sample(successor, entity)
            if not permitted:
                problems.append(f"{item.label}: add the replacement to project {entity.project.code} first." if entity.project_id
                                else f"{item.label}: the replacement needs access to this unassigned sample; select an administrator or assign a project first.")
        elif entity.project_id and not user_can_access_project(successor, entity.project):
            problems.append(f"{item.label}: add the replacement to project {entity.project.code} first.")
    return list(dict.fromkeys(problems))


def review_offboarding(target, actor):
    snapshot = _json(inventory(target))
    successors = get_user_model().objects.filter(is_active=True).exclude(pk=target.pk).prefetch_related("groups").order_by("username")
    receipt = UserOffboarding.objects.filter(target=target, completed_at__isnull=False).order_by("-completed_at").values_list("receipt", flat=True).first()
    return {"snapshot": snapshot, "blockers": blockers(target, actor), "latest_receipt": receipt,
            "successors": [{"id": row.pk, "username": row.username, "roles": application_roles(row)} for row in successors]}


def _locked_people(actor, target, successor=None):
    people = lock_users(actor, [target, *([successor] if successor else [])])
    administrator = people.get(actor.pk)
    if not administrator or not administrator.is_active or not is_admin(administrator):
        raise PermissionDenied("Your administrator access changed. Refresh the page and sign in again if needed.")
    if target.pk not in people:
        raise NotFound("The account no longer exists.")
    if successor and successor.pk not in people:
        raise OffboardingConflict("The replacement account changed. Review a new preview.")
    return administrator, people.get(target.pk), people.get(successor.pk) if successor else None


def prepare_offboarding(target, actor, data):
    successor = get_object_or_404(get_user_model(), pk=data["successor_id"]) if data["successor_id"] else None
    with user_administration():
        actor, target, successor = _locked_people(actor, target, successor)
        rows = responsibilities(target)
        problems = blockers(target, actor, successor, rows, data["custody_confirmed"], selecting=True)
        if problems:
            raise ValidationError({"detail": "Resolve the offboarding blockers before continuing.", "blockers": problems})
        snapshot = _json({**inventory(target, rows), "successor": _person(successor)})
        plan = UserOffboarding.objects.create(target=target, administrator=actor, successor=successor,
            reason=data["reason"], custody_confirmed=data["custody_confirmed"], snapshot=snapshot,
            fingerprint=_fingerprint(snapshot), expires_at=timezone.now() + timedelta(minutes=15))
        return {"preview_id": str(plan.pk), "expires_at": plan.expires_at,
                "snapshot": snapshot, "successor": _person(successor), "reason": plan.reason}


def _transfer(item, target, successor, actor, plan):
    from notebook.models import ExperimentWorkflowStep, ExperimentComment
    from samples.models import SampleCustodyEvent
    row = item.entity
    before = {item.field: target.username}
    after = {item.field: successor.username}
    if item.field == "assignees":
        before[item.field] = list(row.assignees.order_by("username").values_list("username", flat=True))
        row.assignees.add(successor)
        row.assignees.remove(target)
        after[item.field] = list(row.assignees.order_by("username").values_list("username", flat=True))
    else:
        setattr(row, item.field, successor)
        fields = [item.field]
        if isinstance(row, ExperimentWorkflowStep):
            row.version += 1
            fields.append("version")
        if hasattr(row, "updated_at"):
            fields.append("updated_at")
        row.save(update_fields=fields)
    details = {"offboarding_id": str(plan.pk), "category": item.category}
    if item.category == "custody":
        event = SampleCustodyEvent.objects.create(sample=row, action="TRANSFER", scanned_code=row.sample_id,
            from_container=row.container, to_container=row.container, from_custodian=target, to_custodian=successor,
            reason="Verified physical handoff during account offboarding", performed_by=actor)
        details["custody_event_id"] = event.pk
    audit_entity = row.experiment if isinstance(row, (ExperimentWorkflowStep, ExperimentComment)) else (
        row.record if item.category == "registry_reviews" else row)
    details["record_id"] = str(row.pk)
    details["label"] = item.label
    record_audit_event(entity=audit_entity, action="RESPONSIBILITY_TRANSFERRED", actor=actor,
                       reason="Account offboarding handover", before=before, after=after, details=details, changed_fields=[item.field])


def confirm_offboarding(target, actor, preview_id):
    from assistant.models import AssistantAction, AssistantChatRequest, NotificationSubscription
    from events.models import Event
    from notebook.models import Notebook
    from notifications.models import Notification
    from projects.models import Project

    with user_administration():
        plan = get_object_or_404(UserOffboarding, pk=preview_id, target=target, administrator=actor)
        actor, target, successor = _locked_people(actor, target, plan.successor)
        plan = UserOffboarding.objects.select_for_update().get(pk=plan.pk)
        if plan.completed_at:
            return plan.receipt
        if plan.expires_at <= timezone.now():
            raise OffboardingConflict("This offboarding preview expired. Review a new preview.")
        protect_user_deletion([target.pk])
        _lock_responsibilities(target)
        rows = responsibilities(target)
        snapshot = _json({**inventory(target, rows), "successor": _person(successor)})
        if _fingerprint(snapshot) != plan.fingerprint:
            raise OffboardingConflict()
        problems = blockers(target, actor, successor, rows, plan.custody_confirmed, selecting=True)
        if problems:
            raise OffboardingConflict(" ".join(problems))
        for item in rows:
            _transfer(item, target, successor, actor, plan)
        Project.members.through.objects.filter(user_id=target.pk).delete()
        for field in NOTEBOOK_GRANTS:
            getattr(Notebook, field).through.objects.filter(user_id=target.pk).delete()
        now = timezone.now()
        requests = AccessRequest.objects.filter(requester=target, status="PENDING")
        for request in requests:
            request.status, request.reviewed_by, request.reviewer_username = "CANCELLED", actor, actor.username
            request.reviewed_at, request.decision_reason = now, "Cancelled during account offboarding."
            request.save()
            from .access_requests import _audit
            _audit(request, actor, "ACCESS_REQUEST_CANCELLED")
        actions = AssistantAction.objects.filter(requested_by=target, status="PROPOSED")
        for action in actions:
            action.status = "CANCELLED"
            action.save(update_fields=["status", "updated_at"])
            Event.objects.create(entity_type="AssistantAction", entity_id=str(action.pk), action="ASSISTANT_ACTION_CANCELLED", actor=actor,
                payload={"assistant_action_id": str(action.pk), "summary": action.summary, "offboarding_id": str(plan.pk), "reason": "Cancelled during account offboarding."})
        NotificationSubscription.objects.filter(recipient=target, active=True).update(active=False)
        AssistantChatRequest.objects.filter(owner=target, status="RUNNING").update(cancel_requested=True)
        target.groups.clear()
        target.user_permissions.clear()
        target.is_active = target.is_staff = target.is_superuser = False
        target.save(update_fields=["is_active", "is_staff", "is_superuser"])
        sessions = revoke_user_sessions(target)
        receipt = {"offboarding_id": str(plan.pk), "completed_at": now.isoformat(), "user": target.username,
            "successor": successor.username if successor else None, "reason": plan.reason,
            "transferred": snapshot["counts"], "total_transferred": len(rows), "projects_removed": len(snapshot["projects"]),
            "notebook_grants_removed": sum(map(len, snapshot["notebook_grants"].values())),
            "access_requests_cancelled": len(snapshot["pending_access_requests"]), "proposals_cancelled": len(snapshot["proposed_actions"]),
            "subscriptions_disabled": len(snapshot["subscriptions"]), "sessions": sessions,
            "continuing_jobs": snapshot["continuing_jobs"], "open_requests": snapshot["open_requests"], "future_bookings": snapshot["future_bookings"]}
        Event.objects.create(entity_type="User", entity_id=str(target.pk), action="USER_OFFBOARDED", actor=actor,
            payload={"username": target.username, "before": snapshot, "after": _person(target), "receipt": receipt,
                     "offboarding_id": str(plan.pk), "reason": plan.reason})
        if successor:
            Notification.objects.create(user=successor, title="Responsibilities transferred to you",
                message=f"{actor.username} transferred {len(rows)} responsibilities from {target.username} during account offboarding.", link="/dashboard")
        plan.completed_at, plan.receipt = now, receipt
        plan.save(update_fields=["completed_at", "receipt"])
        return receipt
