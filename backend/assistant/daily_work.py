"""Grounded work priorities and one-record, explicitly confirmed work actions."""
import re
import math
from datetime import datetime

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import is_qc_reviewer
from custom_fields.forms import validate_values
from events.models import Event
from pipelines.models import PipelineRun, PipelineStepRun
from pipelines.services import missing_required_fields, validate_work_item_pipeline_completion
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample
from settings_app.models import SystemSettings
from .guided_actions import _assignee, _snapshot
from .lab_helpers import response
from .natural_requests import normalize_request
from .workflow_actions import FINAL_SAMPLES, digest, require_access
from .workflow_dates import deadline_windows

KEY = "daily_work"
SCAN_LIMIT = 250
PAGE_SIZE = 25


def finite_or_text(value):
    return str(value) if isinstance(value, float) and not math.isfinite(value) else value


class DailyScopeSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["mine", "unassigned", "team"], default="mine")
    focus = serializers.ChoiceField(choices=["all", "actionable", "overdue", "today", "qc", "blocked"], default="all")
    project = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    offset = serializers.IntegerField(min_value=0, max_value=SCAN_LIMIT, default=0)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"detail": "Use only the displayed daily-work filters."})
        return super().to_internal_value(data)


def scoped_work(user):
    return WorkItem.objects.filter(sample__in=get_sample_access_queryset(Sample.objects.all(), user)).select_related(
        "sample__project", "assigned_to", "pipeline_step_run__pipeline_run").prefetch_related(
        "results", "pipeline_step_run__pipeline_run__steps")


def inspect_work(work, user, now=None, separation=None):
    now = now or timezone.now()
    step = getattr(work, "pipeline_step_run", None)
    run = step.pipeline_run if step else None
    siblings = list(run.steps.all()) if run else []
    positions = {row.position: row for row in siblings}
    results = list(work.results.all())
    waiting = [position for position in step.dependency_positions if position not in positions or positions[position].status not in {"COMPLETED", "SKIPPED"}] if step else []
    consistent = not run or run.sample_id == work.sample_id
    pipeline_available = not step or consistent and run.status in {"ACTIVE", "BLOCKED"} and step.status in {"READY", "IN_PROGRESS"} and not waiting
    missing = missing_required_fields(work, step) if consistent else []
    invalid_numbers = [result.key for result in results if result.value_type == "NUMBER" and isinstance(result.value, float) and not math.isfinite(result.value)]
    intake = True
    try:
        validate_values(work.sample.form_schema, work.sample.form_values)
    except ValidationError:
        intake = False
    live = user.is_active and work.sample.status not in FINAL_SAMPLES and intake
    writable = live and user_can_modify_sample(user, work.sample)
    available = pipeline_available and work.status in {"PENDING", "IN_PROGRESS"} and work.qc_status == "PENDING_REVIEW"
    awaiting = bool(step and consistent and run.status in {"ACTIVE", "BLOCKED"} and not waiting and step.requires_qc and
                    step.status == "AWAITING_QC" and work.status == "COMPLETED" and work.qc_status == "PENDING_REVIEW")
    failed = sum(result.qc_passed is False or result.qc_status == "REJECTED" for result in results)
    separation = SystemSettings.load().qc_separation_of_duties if separation is None else separation
    own_results = separation and any(result.entered_by_id == user.pk for result in results)
    overdue = bool(work.due_at and work.due_at < now and work.status in {"PENDING", "IN_PROGRESS"})
    today_start, today_end = deadline_windows(now, ["due_today"])["due_today"]
    due_today = bool(work.due_at and today_start <= work.due_at < today_end)
    if not consistent:
        rank, review, reason = 7, "Link needs repair", "The pipeline/work sample link is inconsistent; ask an administrator to repair it."
    elif not live:
        rank, review, reason = 7, "Record needs attention", "The sample is final, intake is invalid, or your account is inactive."
    elif work.status == "FAILED" or work.qc_status in {"REJECTED", "RERUN_REQUIRED"}:
        rank, review, reason = 0, "Needs review", "Review recorded work failures or rejected/rerun QC; these gates are not bypassed."
    elif awaiting:
        rank, review, reason = 1, "Awaiting workflow QC", "Work is complete; an authorized reviewer must decide the work-item QC gate."
    elif not pipeline_available:
        rank, review, reason = 6, "Blocked", "Waiting for steps: " + ", ".join(map(str, waiting)) if waiting else "The pipeline or activation gate is not available."
    elif overdue:
        rank, review, reason = 2, "Overdue", "Available unfinished work has passed its recorded deadline."
    elif due_today:
        rank, review, reason = 3, "Due today", "Available unfinished work is due in the current application calendar day."
    elif failed:
        rank, review, reason = 3, "QC evidence to review", "Recorded results include failed checks/rejected reviews; inspect the evidence before completing work."
    elif not work.due_at:
        rank, review, reason = 4, "No deadline", "Available work has no recorded deadline; coordinate its priority with the team."
    else:
        rank, review, reason = 5, "Upcoming", "Available unfinished work has a future recorded deadline."
    if missing:
        reason += " Required fields: " + ", ".join(missing) + "."
    if invalid_numbers:
        reason += " Correct non-finite numeric results: " + ", ".join(invalid_numbers) + "."
    frozen = {"work": _snapshot(work, work.sample, step), "sample_status": work.sample.status,
        "sample_form": [work.sample.form_schema, work.sample.form_values], "due_at": work.due_at, "required": work.required_fields,
        "form": [step.form_schema, step.form_values] if step else None,
        "steps": [(row.pk, row.status, row.updated_at, row.dependency_positions) for row in siblings],
        "results": [{key: finite_or_text(getattr(result, key)) for key in ["id", "key", "value_type", "value_string", "value_number", "value_boolean", "qc_status", "qc_passed", "entered_by_id", "updated_at"]} for result in results]}
    can_review = bool(live and awaiting and not missing and not invalid_numbers and is_qc_reviewer(user))
    return {"id": work.pk, "sample_id": work.sample_id, "sample": work.sample.sample_id, "project": work.sample.project.code if work.sample.project_id else "",
        "work": work.name, "status": work.status, "qc_status": work.qc_status, "assigned_to": work.assigned_to.username if work.assigned_to else None,
        "due": work.due_at.isoformat() if work.due_at else None, "overdue": overdue, "due_today": due_today,
        "review": review, "reason": reason, "priority": rank, "missing_fields": missing, "failed_results": failed,
        "step_id": step.pk if step and consistent else None, "run_id": run.pk if run and consistent else None,
        "can_assign": bool(writable and available), "can_start": bool(writable and available and work.status == "PENDING"),
        "can_complete": bool(writable and available and not missing and not invalid_numbers), "can_schedule": bool(writable and consistent and work.status in {"PENDING", "IN_PROGRESS"}),
        "can_review": can_review, "can_approve": can_review and not own_results,
        "approval_blocker": "Separation of duties prevents self-approval." if own_results else "",
        "actionable": bool(writable and available or can_review), "blocked": not available and not awaiting or not live or not consistent,
        "evidence": [{"id": result.pk, "key": result.key, "value": None if result.key in invalid_numbers else result.value, "value_warning": "Non-finite numeric value" if result.key in invalid_numbers else "", "unit": result.unit, "qc_passed": result.qc_passed, "qc_status": result.qc_status} for result in results[:20]],
        "evidence_count": len(results), "digest": digest(frozen)}


def daily_reply(user, scope=None):
    serializer = DailyScopeSerializer(data=scope or {})
    serializer.is_valid(raise_exception=True)
    scope = serializer.validated_data
    now = timezone.now()
    work = scoped_work(user).exclude(sample__status__in=FINAL_SAMPLES).exclude(status="CANCELLED").filter(
        ~Q(status="COMPLETED") | Q(pipeline_step_run__status="AWAITING_QC", qc_status="PENDING_REVIEW"))
    if scope["scope"] == "mine":
        work = work.filter(assigned_to=user)
    elif scope["scope"] == "unassigned":
        work = work.filter(assigned_to__isnull=True)
    if scope["project"]:
        from .lab_reviews import _projects
        projects = list(_projects(user).filter(code__iexact=scope["project"])[:2])
        if len(projects) != 1:
            return response("Project unavailable. Use one exact accessible project code.")
        from .project_conversation import project_samples
        scope["project"] = projects[0].code
        work = work.filter(sample__in=project_samples(projects[0], user))
    total = work.count()
    records = list(work.order_by(F("due_at").asc(nulls_last=True), "pk")[:SCAN_LIMIT + 1])
    truncated = len(records) > SCAN_LIMIT
    separation = SystemSettings.load().qc_separation_of_duties
    rows = [inspect_work(item, user, now, separation) for item in records[:SCAN_LIMIT]]
    focus = scope["focus"]
    rows = [row for row in rows if focus == "all" or focus == "actionable" and row["actionable"] or focus == "overdue" and row["overdue"] or
            focus == "today" and row["due_today"] or focus == "qc" and (row["failed_results"] or row["qc_status"] in {"REJECTED", "RERUN_REQUIRED"} or row["review"] == "Awaiting workflow QC") or focus == "blocked" and row["blocked"]]
    rows.sort(key=lambda row: (row["priority"], row["due"] or "9999", row["id"]))
    page = rows[scope["offset"]:scope["offset"] + PAGE_SIZE]
    answer = f"Here are {len(page)} of {len(rows)} matching priorities assessed from {min(total, SCAN_LIMIT)} work items. "
    answer += "Scope: work assigned to you. " if scope["scope"] == "mine" else f"Scope: {scope['scope']} accessible work. "
    if not rows:
        answer += "No matching work was found in this assessment; this is not a team-wide all-clear. "
    if truncated:
        answer += f"Only the earliest-due {SCAN_LIMIT} of {total} candidates were assessed. Narrow the project/filter; this is not a complete priority ranking."
    panel = {"scope": scope, "as_of": now.isoformat(), "timezone": timezone.get_current_timezone_name(), "rows": page,
        "total_candidates": total, "assessed": min(total, SCAN_LIMIT), "matched_assessed": len(rows), "truncated": truncated,
        "next_offset": scope["offset"] + PAGE_SIZE if scope["offset"] + PAGE_SIZE < len(rows) else None,
        "day": {key: value.isoformat() for key, value in zip(["start", "end_exclusive"], deadline_windows(now, ["due_today"])["due_today"])},
        "notes": ["Priorities use recorded failures, workflow QC, availability and deadlines, not a prediction of scientific importance.",
            "Today is the application calendar day. Future and undated work remain visible unless filtered. Pages reread live records.",
            "Completed work appears only when a pipeline QC gate is waiting. Result QC reviews remain separate."]}
    return response(answer, daily_work=panel, personal_work={"username": user.username, "truncated": truncated},
        comparison={"title": "Your work priorities", "rows": page, "columns": [{"key": key, "label": key.title()} for key in ["sample", "work", "review", "due"]], "notes": panel["notes"]},
        context={KEY: scope}, suggestions=["Only actionable", "Only overdue", "Show daily team work", "Show daily unassigned work", "Refresh my work"])


class DailyActionSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["DAILY_ASSIGN", "DAILY_START", "DAILY_COMPLETE", "DAILY_DUE", "WORKFLOW_REVIEW"])
    work_item_id = serializers.IntegerField(min_value=1, max_value=2**63-1)
    digest = serializers.RegexField(r"^[a-f0-9]{64}$")
    assignee = serializers.CharField(max_length=150, required=False)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    decision = serializers.ChoiceField(choices=["APPROVED", "REJECTED", "RERUN_REQUIRED"], required=False)
    reason = serializers.CharField(max_length=2000, required=False)
    scope = DailyScopeSerializer(required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"detail": "Use only the displayed work action fields."})
        value = data.get("due_at")
        if isinstance(value, str) and not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value, re.I):
            raise ValidationError({"due_at": "Supply an explicit UTC/offset timestamp, or null to clear the deadline."})
        return super().to_internal_value(data)

    def validate(self, data):
        extra = {"DAILY_ASSIGN": {"assignee"}, "DAILY_DUE": {"due_at"}, "WORKFLOW_REVIEW": {"decision", "reason"}}.get(data["operation"], set())
        if set(data) - {"scope"} != {"operation", "work_item_id", "digest"} | extra:
            raise ValidationError({"detail": "Supply exactly the fields required for this work action."})
        return data


def prepare_daily_action(user, data):
    work = scoped_work(user).filter(pk=data["work_item_id"]).first()
    if not work:
        raise ValueError("Work item unavailable.")
    row = inspect_work(work, user)
    if row["digest"] != data["digest"]:
        raise ValueError("Work or evidence changed. Refresh your priorities and request a fresh preview.")
    operation = data["operation"]
    if operation == "WORKFLOW_REVIEW":
        from .workflow_actions import proposal, state
        _, _, fingerprint = state(work.sample)
        return proposal(work.sample, user, {"operation": operation, "step_id": row["step_id"], "plan_digest": fingerprint,
            "decision": data["decision"], "reason": data["reason"]})
    require_access(user, work.sample)
    eligibility = {"DAILY_ASSIGN": "can_assign", "DAILY_START": "can_start", "DAILY_COMPLETE": "can_complete", "DAILY_DUE": "can_schedule"}
    if not row[eligibility[operation]]:
        raise ValueError(row["reason"] + " This action is not currently available.")
    details = {key: value for key, value in data.items() if key not in {"scope"}}
    after = {"status": "IN_PROGRESS" if operation == "DAILY_START" else "COMPLETED"}
    if operation == "DAILY_ASSIGN":
        person = _assignee(data["assignee"], work.sample)
        details["target_user_id"] = person.pk
        after = {"assigned_to": person.username}
    elif operation == "DAILY_DUE":
        details["due_at"] = data["due_at"].isoformat() if data["due_at"] else None
        after = {"due_at": details["due_at"]}
    details["sample_id"] = work.sample_id
    preview = {"title": "Review daily work action", "operation": operation, "records_affected": 1,
        "project": {"label": row["project"] or "Unassigned"}, "current_values": {key: row[key] for key in ["status", "assigned_to", "due"]},
        "proposed_values": after, "records": [{"id": work.pk, "label": f"{row['sample']} · {row['work']} · Work #{work.pk}", "current": {"status": work.status}, "proposed": after}],
        "warnings": ["Confirm only work actually performed. Completing work does not approve QC."] if operation == "DAILY_COMPLETE" else []}
    if row["failed_results"]:
        preview["warnings"].append("Recorded results contain failed checks or rejected reviews. Inspect the evidence before proceeding.")
    details["preview"] = preview
    return {"type": "WORK_ITEM_OPERATION", "summary": f"{operation}: {row['sample']} · Work #{work.pk}", "payload": details}


@transaction.atomic
def execute_daily_action(action):
    data, user = action.payload, action.requested_by
    sample = Sample.objects.select_for_update().get(pk=data["sample_id"])
    step = PipelineStepRun.objects.filter(work_item_id=data["work_item_id"]).first()
    if step:
        PipelineRun.objects.select_for_update().get(pk=step.pipeline_run_id)
        list(PipelineStepRun.objects.select_for_update().filter(pipeline_run_id=step.pipeline_run_id).order_by("pk"))
    WorkItem.objects.select_for_update().get(pk=data["work_item_id"])
    list(Result.objects.select_for_update().filter(work_item_id=data["work_item_id"]).order_by("pk"))
    require_access(user, sample)
    clean = {key: value for key, value in data.items() if key in DailyActionSerializer().fields and key != "scope"}
    if clean.get("due_at"):
        clean["due_at"] = datetime.fromisoformat(clean["due_at"])
    pending = prepare_daily_action(user, clean)
    work = scoped_work(user).get(pk=data["work_item_id"], sample=sample)
    operation = data["operation"]
    before = {"status": work.status, "assigned_to_id": work.assigned_to_id, "due_at": work.due_at.isoformat() if work.due_at else None}
    work._pipeline_actor = user
    if operation == "DAILY_ASSIGN":
        if pending["payload"]["target_user_id"] != data["target_user_id"]:
            raise ValueError("The assignee identity changed. Request a fresh preview.")
        work.assigned_to_id = data["target_user_id"]
        fields, event = ["assigned_to", "updated_at"], "WORK_ITEM_REASSIGNED" if before["assigned_to_id"] else "WORK_ITEM_ASSIGNED"
    elif operation == "DAILY_DUE":
        work.due_at = clean["due_at"]
        fields, event = ["due_at", "updated_at"], "WORK_ITEM_DEADLINE_UPDATED"
    else:
        work.status = "IN_PROGRESS" if operation == "DAILY_START" else "COMPLETED"
        validate_work_item_pipeline_completion(work, work.status)
        fields, event = ["status", "updated_at"], "WORK_ITEM_STARTED" if operation == "DAILY_START" else "WORK_ITEM_COMPLETED"
    work.save(update_fields=fields)
    Event.objects.create(entity_type="WorkItem", entity_id=str(work.pk), action=event, actor=user,
        payload={"assistant_action_id": str(action.pk), "sample_id": sample.pk, "project_id": sample.project_id, "before": before,
            "after": {"status": work.status, "assigned_to_id": work.assigned_to_id, "due_at": work.due_at.isoformat() if work.due_at else None}})
    return {"operation": operation, "succeeded_count": 1, "failed_count": 0,
        "message": "Work updated. Priorities will be refreshed from current records.", "succeeded": [{"id": work.pk, "label": work.name}], "failed": []}


class DailyWorkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            raise ValidationError({"detail": "Supply each work filter once."})
        return Response(daily_reply(request.user, request.query_params.dict()))


class DailyWorkActionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=DailyActionSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = DailyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pending = prepare_daily_action(request.user, serializer.validated_data)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        from .actions import propose_action, serialize_action
        action = propose_action(request.user, pending["type"], pending["summary"], pending["payload"])
        reply = daily_reply(request.user, serializer.validated_data.get("scope"))
        reply["pending_action"] = serialize_action(action)
        return Response(reply, status=201)


def route_daily_work(message, user, context=None, page_context=None):
    context = context or {}
    text = normalize_request(message)
    sample_selected = page_context or any(context.get(key) for key in ["sample_code", "sample_codes", "sample_id", "sample_ids", "workflow_guide"])
    if text.lower() != "what should i do next" or not sample_selected or KEY in context:
        from .workitem_operations import personal_work_summary
        personal = personal_work_summary(text, user)
        if personal:
            return personal
    match = re.fullmatch(r"(?:show |list )?(?:my|daily|my daily) work in project ([\w.:/-]{1,64})", text, re.I)
    if match:
        return daily_reply(user, {"project": match[1]})
    if text.lower() in {"show daily team work", "show daily unassigned work"}:
        return daily_reply(user, {"scope": "team" if "team" in text.lower() else "unassigned"})
    if KEY not in context:
        return None
    followup = {"only actionable": "actionable", "only overdue": "overdue", "only due today": "today", "only qc": "qc", "only blocked": "blocked", "show all work": "all"}
    serializer = DailyScopeSerializer(data=context[KEY])
    recognized = text.lower() in {*followup, "refresh my work", "next work page", "show my work"}
    if not recognized:
        from .guided_actions import route_guided_action
        guided = route_guided_action(message, user, context)
        if not guided:
            return None
        if not serializer.is_valid():
            return response("The work filters are unavailable. Ask for your daily work again.")
        pending = guided.get("pending_action")
        if pending:
            work = scoped_work(user).filter(pk=pending["payload"]["work_item_id"]).first()
            if not work:
                return response("Work item unavailable.")
            row = inspect_work(work, user)
            if not row["can_assign"]:
                reply = daily_reply(user, serializer.validated_data)
                reply["answer"] = row["reason"] + " This work is not available for that action."
                return reply
            pending["payload"]["daily_digest"] = row["digest"]
        reply = daily_reply(user, serializer.validated_data)
        reply.update({key: value for key, value in guided.items() if key not in {"context", "replace_context"}})
        return reply
    if not serializer.is_valid():
        return response("The work filters are unavailable. Ask for your daily work again.")
    scope = serializer.validated_data
    if text.lower() in followup:
        scope.update(focus=followup[text.lower()], offset=0)
    elif text.lower() == "next work page":
        scope["offset"] = min(SCAN_LIMIT, scope["offset"] + PAGE_SIZE)
    else:
        scope["offset"] = 0
    return daily_reply(user, scope)
