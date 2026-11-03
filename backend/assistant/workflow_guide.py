"""A live, permission-filtered checklist for configured sample workflows."""
import re

from django.core import signing
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from core.permissions import is_qc_reviewer
from custom_fields.forms import validate_values
from pipelines.models import PipelineTemplate
from pipelines.services import missing_required_fields
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample
from settings_app.models import SystemSettings
from .lab_helpers import response
from .natural_requests import normalize_request
from .workflow_actions import FINAL_SAMPLES, MAX_STEPS, proposal, state

KEY = "workflow_guide"
SALT = "assistant.workflow-guide.v069"


def accessible_sample(pk, user):
    return get_object_or_404(get_sample_access_queryset(Sample.objects.select_related("project"), user), pk=pk)


def token(sample, user):
    return signing.dumps({"sample": sample.pk, "user": user.pk}, salt=SALT, compress=True)


def recall(context, user):
    raw = (context or {}).get(KEY)
    if not isinstance(raw, str) or len(raw) > 2000:
        return None
    try:
        data = signing.loads(raw, salt=SALT, max_age=1800)
        if data.get("user") == user.pk and type(data.get("sample")) is int:
            return get_sample_access_queryset(Sample.objects.select_related("project"), user).filter(pk=data["sample"]).first()
    except (signing.BadSignature, TypeError, ValueError):
        pass
    return None


def checklist(sample, user):
    run, steps, fingerprint = state(sample)
    writable = bool(user.is_active and sample.status not in FINAL_SAMPLES and user_can_modify_sample(user, sample))
    reviewer = bool(user.is_active and sample.status not in FINAL_SAMPLES and is_qc_reviewer(user))
    truncated = len(steps) > MAX_STEPS
    separation = SystemSettings.load().qc_separation_of_duties
    intake_errors = {}
    try:
        validate_values(sample.form_schema, sample.form_values)
    except ValidationError as exc:
        intake_errors = exc.detail
    positions = {step.position: step for step in steps}
    rows = []
    for step in steps[:MAX_STEPS]:
        work = step.work_item
        link_error = bool(work and work.sample_id != sample.pk)
        if link_error:
            work = None
        waiting = [position for position in step.dependency_positions if position not in positions or positions[position].status not in {"COMPLETED", "SKIPPED"}]
        missing = missing_required_fields(work, step) if work else []
        results = list(work.results.all()) if work else []
        available = bool(work and not waiting and step.status in {"READY", "IN_PROGRESS"} and work.status in {"PENDING", "IN_PROGRESS"} and work.qc_status == "PENDING_REVIEW")
        awaiting_qc = bool(work and not waiting and step.status == "AWAITING_QC" and step.requires_qc and work.status == "COMPLETED" and work.qc_status == "PENDING_REVIEW")
        self_approval = bool(work and separation and any(result.entered_by_id == user.pk for result in results))
        if link_error:
            reason = "The linked work no longer belongs to this sample. An administrator must repair the link."
        elif step.status in {"COMPLETED", "SKIPPED"}:
            reason = "Recorded as " + step.status.lower() + "."
        elif waiting:
            reason = "Waiting for dependency steps: " + ", ".join(map(str, waiting)) + "."
        elif step.status in {"FAILED", "CANCELLED"}:
            reason = step.failure_reason or "Review the recorded failure and retry controls with the project team."
        elif step.status == "BLOCKED":
            reason = "The activation gate has not opened. Review its configured condition; it cannot be skipped here."
        elif missing:
            reason = "Record or correct required fields: " + ", ".join(missing) + "."
        elif awaiting_qc:
            reason = "Work is completed; an authorized human reviewer must decide its workflow QC gate."
        elif available:
            reason = "Work is available. Record actual measurements and complete it only when finished."
        else:
            reason = "Review the recorded execution state; no automatic next action is available."
        rows.append({"id": step.pk, "position": step.position, "name": step.name, "status": step.status,
            "work_item_id": work.pk if work else None, "work_status": work.status if work else None,
            "assigned_to": work.assigned_to.username if work and work.assigned_to else None,
            "requires_qc": step.requires_qc, "qc_status": work.qc_status if work else None, "reason": reason,
            "waiting_for": waiting, "missing_fields": missing, "required_fields": work.required_fields if work else step.required_fields,
            "form_schema": step.form_schema, "form_values": step.form_values,
            "results": [{"id": result.pk, "key": result.key, "value": result.value, "value_type": result.value_type,
                "unit": result.unit, "qc_status": result.qc_status, "qc_passed": result.qc_passed} for result in results[:100]],
            "results_truncated": len(results) > 100,
            "can_assign": writable and available and not truncated,
            "can_record": writable and available and not truncated,
            "can_complete": writable and available and not missing and not truncated,
            "can_review": reviewer and awaiting_qc and not missing and not truncated,
            "can_approve": reviewer and awaiting_qc and not missing and not self_approval and not truncated,
            "approval_blocker": "Separation of duties prevents self-approval." if self_approval else "",
            "is_sequencing": step.work_type.upper() == "SEQUENCING", "link_error": link_error})
    sequence = [row for row in rows if row["is_sequencing"]]
    if truncated:
        readiness, summary = "unknown", "This run exceeds the 50-step guide limit. Open the sample for its complete workflow."
    elif any(row["link_error"] for row in rows):
        readiness, summary = "unknown", "A workflow work-item link is inconsistent. Ask an administrator to repair it before relying on this checklist."
    elif sample.status in FINAL_SAMPLES:
        readiness, summary = "final_sample", "This sample has a final status. The checklist is read-only."
    elif intake_errors:
        readiness, summary = "blocked", "The sample's configured intake fields are incomplete or invalid. Correct the intake record before preparing it for sequencing."
    elif not run:
        readiness, summary = "needs_workflow", "No active or blocked pipeline is linked. Select the appropriate configured template and preview its start."
    elif not sequence:
        readiness, summary = "unknown", "This workflow has no step with the exact SEQUENCING analysis code. Review its configured requirements; sequencing readiness cannot be inferred from names."
    elif len(sequence) != 1:
        readiness, summary = "unknown", "This workflow contains multiple sequencing steps. Review each step explicitly; no single sequencing target was selected."
    elif sequence[0]["status"] == "READY" and not sequence[0]["waiting_for"] and run.status == "ACTIVE":
        readiness, summary = "available", "The configured sequencing step is available and its dependency gates are satisfied. Its output/form requirements are listed below and may still be incomplete. This is not a scientific suitability assessment or an instrument start."
    elif sequence[0]["status"] == "IN_PROGRESS":
        readiness, summary = "in_progress", "The sequencing step is already in progress. Review its remaining measurements and QC."
    elif sequence[0]["status"] in {"COMPLETED", "SKIPPED"}:
        readiness, summary = "finished", "The sequencing step is recorded as finished or skipped. Review the remaining workflow; no new run is started."
    else:
        readiness, summary = "blocked", "Sequencing is not currently available in this workflow. Review the recorded prerequisites and QC gates below."
    templates = list(PipelineTemplate.objects.filter(active=True).order_by("code")[:51]) if not run and writable else []
    last = sample.pipeline_runs.order_by("-pk").first() if not run else None
    if not run and last and last.status == "COMPLETED" and readiness == "needs_workflow":
        readiness, summary = "finished_workflow", "The most recent configured workflow is completed. Review its history before explicitly choosing whether to start another run."
    return {"sample_id": sample.pk, "sample_code": sample.sample_id, "sample_status": sample.status,
        "run": {"id": run.pk, "code": run.template_code, "status": run.status} if run else None,
        "last_run": {"id": last.pk, "code": last.template_code, "status": last.status} if last else None,
        "as_of": timezone.now().isoformat(), "plan_digest": fingerprint, "readiness": readiness, "summary": summary,
        "read_only": not writable, "steps": rows, "truncated": truncated, "intake_errors": intake_errors,
        "templates": [{"id": item.pk, "code": item.code, "name": item.name} for item in templates[:50]],
        "templates_truncated": len(templates) > 50,
        "notes": ["Current records are reread after confirmation or refresh. Every change requires a separate preview and confirmation.",
                  "Work-item QC gates and individual result QC reviews are separate. The assistant does not invent measurements or approve QC automatically."]}


def guide_reply(sample, user, **extra):
    plan = checklist(sample, user)
    return response(f"Preparing {sample.sample_id} for sequencing: {plan['summary']}",
        context={KEY: token(sample, user), "sample_id": sample.pk, "sample_code": sample.sample_id},
        workflow_plan=plan, suggestions=["What should I do next?", "Why is preparation blocked?", "Refresh preparation"],
        links=[{"label": sample.sample_id, "url": f"/samples/{sample.pk}"}], **extra)


class WorkflowActionSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["WORKFLOW_START", "WORKFLOW_FORM", "WORKFLOW_COMPLETE", "WORKFLOW_REVIEW"])
    plan_digest = serializers.RegexField(r"^[a-f0-9]{64}$")
    step_id = serializers.IntegerField(min_value=1, required=False)
    template_id = serializers.IntegerField(min_value=1, required=False)
    decision = serializers.ChoiceField(choices=["APPROVED", "REJECTED", "RERUN_REQUIRED"], required=False)
    values = serializers.JSONField(required=False)
    reason = serializers.CharField(max_length=2000, required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"detail": "Use only the displayed workflow action fields."})
        return super().to_internal_value(data)

    def validate(self, data):
        allowed = {"WORKFLOW_START": {"template_id"}, "WORKFLOW_FORM": {"step_id", "values", "reason"},
            "WORKFLOW_COMPLETE": {"step_id"}, "WORKFLOW_REVIEW": {"step_id", "decision", "reason"}}[data["operation"]]
        if set(data) != allowed | {"operation", "plan_digest"}:
            raise ValidationError({"detail": "Supply exactly the fields required for this workflow action."})
        return data


class WorkflowGuideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        return Response(checklist(accessible_sample(pk, request.user), request.user))


class WorkflowActionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=WorkflowActionSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        sample = accessible_sample(pk, request.user)
        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            pending = proposal(sample, request.user, serializer.validated_data)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        from .actions import propose_action, serialize_action
        action = propose_action(request.user, pending["type"], pending["summary"], pending["payload"])
        return Response(guide_reply(sample, request.user, pending_action=serialize_action(action)), status=201)


def route_workflow_guide(message, user, context=None):
    context = context or {}
    text = normalize_request(message)
    start = re.fullmatch(r'(?:help me |can you help me |please )?(?:prepare|prep|get) (?:sample ([\w./-]{1,64})|(?:a |the )?sample)(?: ready)? for sequencing', text, re.I)
    if start:
        if not start[1]:
            return response("Which sample should we prepare? Reply with its exact sample ID.",
                context={KEY: {"awaiting_sample": True}}, clarification={"required": True})
        samples = list(get_sample_access_queryset(Sample.objects.select_related("project"), user).filter(sample_id__iexact=start[1])[:2])
        if len(samples) != 1:
            return response("That sample is unavailable. Provide one exact accessible sample ID.", clarification={"required": True})
        return guide_reply(samples[0], user)
    if isinstance(context.get(KEY), dict) and context[KEY] == {"awaiting_sample": True}:
        from .conversation import is_courtesy_reply
        if is_courtesy_reply(text):
            return None
        if re.fullmatch(r"[\w./-]{1,64}", text) and text.lower() not in {"cancel", "thanks", "stop"}:
            return route_workflow_guide(f"Prepare sample {text} for sequencing", user)
    if KEY not in context:
        return None
    if re.fullmatch(r"(?:cancel|stop|stop preparation|cancel preparation|never mind|start over|reset conversation)", text, re.I):
        return response("Preparation guide closed. No queued or proposed action was confirmed; use its Cancel button to cancel an existing proposal.")
    followup = re.fullmatch(r"(?:what (?:should i do|comes|is) next|what next|what should i do next|continue(?: preparing(?: for sequencing)?)?|refresh(?: preparation| workflow)?|check (?:requirements|preparation|qc)|why is (?:it|preparation|this) blocked|what(?:'s| is) (?:blocking|missing)|am i ready(?: for sequencing)?)", text, re.I)
    sample = recall(context, user)
    if followup:
        if not sample:
            return response("This preparation guide expired or access changed. Start again with the exact sample ID.")
        return guide_reply(sample, user)
    if sample:
        from .guided_actions import ADD, ASSIGN, route_guided_action
        guided = route_guided_action(message, user, context)
        if guided:
            target = ((guided.get("pending_action") or {}).get("payload") or {}).get("snapshot", {}).get("sample_id")
            parsed = ADD.fullmatch(text) or ASSIGN.fullmatch(text)
            same_sample = parsed and parsed["sample"] and parsed["sample"].casefold() == sample.sample_id.casefold()
            if target == sample.pk or target is None and same_sample:
                plan = checklist(sample, user)
                if target == sample.pk:
                    payload = guided["pending_action"]["payload"]
                    row = next((row for row in plan["steps"] if row["work_item_id"] == payload.get("work_item_id")), None)
                    if not row or not row["can_record" if payload["operation"] == "GUIDED_RESULT" else "can_assign"]:
                        return guide_reply(sample, user, clarification={"required": True})
                    payload["workflow_digest"] = plan["plan_digest"]
                guided["workflow_plan"] = plan
                guided["context"] = {**guided.get("context", {}), KEY: token(sample, user), "sample_id": sample.pk, "sample_code": sample.sample_id}
            return guided
    return None
