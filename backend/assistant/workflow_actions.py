"""Confirmed workflow changes; plans are observations, never execution authority."""
import hashlib
import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.permissions import is_qc_reviewer
from custom_fields.forms import validate_values
from events.models import Event
from pipelines.models import PipelineRun, PipelineStepRun, PipelineTemplate
from pipelines.services import missing_required_fields, start_pipeline, validate_work_item_pipeline_completion
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample
from settings_app.models import SystemSettings

MAX_STEPS = 50
ACTIVE_RUNS = {"ACTIVE", "BLOCKED"}
FINAL_SAMPLES = {"REPORTED", "ARCHIVED", "CANCELLED"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def state(sample):
    run = sample.pipeline_runs.filter(status__in=ACTIVE_RUNS).order_by("-pk").first()
    steps = list(run.steps.select_related("work_item__assigned_to").prefetch_related("work_item__results").order_by("position")[:MAX_STEPS + 1]) if run else []
    frozen = {"sample": {key: getattr(sample, key) for key in ["id", "sample_id", "project_id", "status", "updated_at", "form_schema", "form_values"]},
              "run": {key: getattr(run, key) for key in ["id", "status", "updated_at"]} if run else None, "steps": []}
    for step in steps:
        work = step.work_item
        if work and work.sample_id != sample.pk:
            work = None
        frozen["steps"].append({"step": {key: getattr(step, key) for key in ["id", "position", "name", "work_type", "status", "updated_at", "work_item_id",
            "required_fields", "requires_qc", "dependency_positions", "activation_condition", "form_schema", "form_values", "retry_count"]},
            "work": {key: getattr(work, key) for key in ["id", "sample_id", "status", "qc_status", "assigned_to_id", "updated_at", "required_fields", "reviewed_by_id", "review_note"]} if work else None,
            "results": [{key: getattr(result, key) for key in ["id", "key", "value_type", "value_string", "value_number", "value_boolean", "unit", "qc_passed", "qc_status", "entered_by_id", "updated_at"]}
                        for result in work.results.all()] if work else []})
    return run, steps, digest(frozen)


def template_state(template):
    return digest({"template": {key: getattr(template, key) for key in ["id", "active", "updated_at"]},
        "steps": [{"step": row, "procedure": list(template.steps.filter(pk=row["id"]).values(
            "procedure__active", "procedure__updated_at", "procedure__analysis__active", "procedure__analysis__updated_at",
            "form__fields", "form__published", "form__archived"))[0]} for row in template.steps.order_by("position").values()]})


def require_access(user, sample, review=False):
    if not user.is_active or sample.status in FINAL_SAMPLES:
        raise ValueError("This sample is inactive or final; no workflow change is available.")
    if review:
        if not is_qc_reviewer(user) or not get_sample_access_queryset(Sample.objects.filter(pk=sample.pk), user, for_write=True).exists():
            raise ValueError("An authorized QC reviewer with current sample access is required.")
    elif not user_can_modify_sample(user, sample):
        raise ValueError("You have read-only access; an active Tech or Admin with sample write access is required.")
    validate_values(sample.form_schema, sample.form_values)


def validate_operation(sample, user, data, run, steps):
    operation = data["operation"]
    require_access(user, sample, review=operation == "WORKFLOW_REVIEW")
    if len(steps) > MAX_STEPS:
        raise ValueError("This run exceeds the guided workflow limit. Review it in the sample page.")
    if operation == "WORKFLOW_START":
        if run:
            raise ValueError("This sample already has an active or blocked run. Refresh its workflow.")
        template = PipelineTemplate.objects.filter(pk=data.get("template_id"), active=True).first()
        if not template or not 1 <= template.steps.count() <= MAX_STEPS:
            raise ValueError("Choose an active template containing 1–50 steps.")
        if template.steps.filter(procedure__active=False).exists() or template.steps.filter(procedure__analysis__active=False).exists():
            raise ValueError("This template contains an inactive procedure or analysis.")
        for item in template.steps.select_related("form"):
            if item.form_id and (not item.form.published or item.form.archived):
                raise ValueError("This template contains an unpublished or archived step form.")
        return template
    step = next((step for step in steps if step.pk == data.get("step_id")), None)
    work = step.work_item if step else None
    if not step or not work or work.sample_id != sample.pk:
        raise ValueError("Select a current step with work in this sample's active workflow.")
    positions = {row.position: row for row in steps}
    if any(position not in positions or positions[position].status not in {"COMPLETED", "SKIPPED"} for position in step.dependency_positions):
        raise ValueError("Required dependency steps are unfinished. Complete their work and QC first.")
    if operation == "WORKFLOW_REVIEW":
        if step.status != "AWAITING_QC" or not step.requires_qc or work.status != "COMPLETED" or work.qc_status != "PENDING_REVIEW":
            raise ValueError("Only completed work currently awaiting its workflow QC gate can be reviewed here.")
        if missing_required_fields(work, step):
            raise ValueError("Required measurements are missing or invalid; review the workflow before approving QC.")
        if data.get("decision") not in {"APPROVED", "REJECTED", "RERUN_REQUIRED"}:
            raise ValueError("Choose an explicit QC decision.")
        if not str(data.get("reason", "")).strip():
            raise ValueError("Provide the reviewer's explicit QC reason.")
        if data["decision"] == "APPROVED" and SystemSettings.load().qc_separation_of_duties and work.results.filter(entered_by=user).exists():
            raise ValueError("Separation of duties prevents the result entrant from approving this work.")
    else:
        if step.status not in {"READY", "IN_PROGRESS"} or work.status not in {"PENDING", "IN_PROGRESS"} or work.qc_status != "PENDING_REVIEW":
            raise ValueError("Only available, unfinished work awaiting review can be changed here.")
        if operation == "WORKFLOW_COMPLETE":
            validate_work_item_pipeline_completion(work, "COMPLETED")
        elif operation == "WORKFLOW_FORM":
            if not step.form_schema or len(str(data.get("reason", "")).strip()) < 10:
                raise ValueError("Choose an attached step form and provide a reason of at least 10 characters.")
            validate_values(step.form_schema, data.get("values"))
        else:
            raise ValueError("Unsupported guided workflow action.")
    return step


def proposal(sample, user, data):
    run, steps, fingerprint = state(sample)
    if data.get("plan_digest") != fingerprint:
        raise ValueError("The workflow changed. Refresh the checklist and request a fresh preview.")
    target = validate_operation(sample, user, data, run, steps)
    frozen = {**data, "sample_id": sample.pk, "run_id": run.pk if run else None}
    if data["operation"] == "WORKFLOW_START":
        frozen["template_digest"] = template_state(target)
        label, before, after = target.code, {"active_run": None}, {"template": target.code, "steps": target.steps.count()}
        warnings = ["Starts the selected configured pipeline, including its configured automation. This does not start a physical sequencer."]
    else:
        label = f"Step {target.position}: {target.name} · Work #{target.work_item_id}"
        before = {"status": target.work_item.status, "qc_status": target.work_item.qc_status, "form_values": target.form_values}
        after = {"status": "COMPLETED"} if data["operation"] == "WORKFLOW_COMPLETE" else {"qc_status": data["decision"], "reason": data["reason"]} if data["operation"] == "WORKFLOW_REVIEW" else {"form_values": data["values"], "reason": data["reason"]}
        warnings = ["Confirm only work you have actually finished. Completing work does not approve its QC gate."] if data["operation"] == "WORKFLOW_COMPLETE" else ["This is a human QC decision for the work-item gate; individual result reviews remain separate."] if data["operation"] == "WORKFLOW_REVIEW" else []
        if data["operation"] == "WORKFLOW_REVIEW" and target.work_item.results.filter(qc_passed=False).exists():
            warnings.append("Recorded results include failed automated QC. Review the evidence before deciding.")
    preview = {"title": "Review workflow action", "operation": data["operation"], "records_affected": 1,
        "project": {"id": sample.project_id, "label": sample.project.code if sample.project_id else "Unassigned"},
        "current_values": before, "proposed_values": after, "records": [{"label": f"{sample.sample_id} · {label}", "current": before, "proposed": after}], "warnings": warnings}
    frozen["preview"] = preview
    return {"type": "WORK_ITEM_OPERATION", "summary": f"{data['operation']}: {sample.sample_id} · {label}", "payload": frozen}


@transaction.atomic
def execute_workflow_action(action):
    data, user = action.payload, action.requested_by
    sample = Sample.objects.select_for_update().get(pk=data["sample_id"])
    if data.get("run_id"):
        run = PipelineRun.objects.select_for_update().get(pk=data["run_id"], sample=sample)
        list(PipelineStepRun.objects.select_for_update().filter(pipeline_run=run).order_by("pk"))
        list(WorkItem.objects.select_for_update().filter(pipeline_step_run__pipeline_run=run).order_by("pk"))
        list(Result.objects.select_for_update().filter(work_item__pipeline_step_run__pipeline_run=run).order_by("pk"))
    run, steps, fingerprint = state(sample)
    if fingerprint != data["plan_digest"] or (run.pk if run else None) != data["run_id"]:
        raise ValueError("The workflow changed after preview. Refresh it and request a fresh preview.")
    target = validate_operation(sample, user, data, run, steps)
    entity_type = "PipelineRun"
    entity_id = run.pk if run else None
    if data["operation"] == "WORKFLOW_START":
        target = PipelineTemplate.objects.select_for_update().get(pk=target.pk)
        if template_state(target) != data["template_digest"]:
            raise ValueError("The template changed after preview. Request a fresh preview.")
        run = start_pipeline(sample=sample, template=target, actor=user)
        entity_id = run.pk
        event, change = "WORKFLOW_STARTED_ASSISTANT", {"pipeline_run_id": run.pk, "template_id": target.pk}
    elif data["operation"] == "WORKFLOW_FORM":
        before = target.form_values
        target.form_values = data["values"]
        target.save(update_fields=["form_values", "updated_at"])
        event, change = "STEP_FORM_SAVED", {"step_id": target.pk, "work_item_id": target.work_item_id, "before": before,
            "after": data["values"], "reason": data["reason"], "form_version": target.form_schema.get("version"), "retry_count": target.retry_count}
    else:
        work = target.work_item
        entity_type, entity_id = "WorkItem", work.pk
        before = {"status": work.status, "qc_status": work.qc_status}
        work._pipeline_actor = user
        if data["operation"] == "WORKFLOW_COMPLETE":
            work.status = "COMPLETED"
            work.save(update_fields=["status", "updated_at"])
            event = "WORK_ITEM_COMPLETED"
        else:
            work.qc_status, work.review_note, work.reviewed_by, work.reviewed_at = data["decision"], data["reason"], user, timezone.now()
            work.save(update_fields=["qc_status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
            event = "QC_" + data["decision"]
        change = {"step_id": target.pk, "work_item_id": work.pk, "before": before,
            "after": {"status": work.status, "qc_status": work.qc_status}, "reason": data.get("reason", "")}
    Event.objects.create(entity_type=entity_type, entity_id=str(entity_id), action=event, actor=user,
        payload={"assistant_action_id": str(action.pk), "sample_id": sample.pk, "project_id": sample.project_id, **change})
    return {"operation": data["operation"], "succeeded_count": 1, "failed_count": 0,
        "message": "Workflow action completed. Refresh the checklist to review current requirements and QC.",
        "succeeded": [{"id": sample.pk, "label": sample.sample_id}], "failed": []}
