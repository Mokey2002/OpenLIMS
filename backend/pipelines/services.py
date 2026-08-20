from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from events.models import Event
from results.models import WorkItem

from .models import PipelineRun, PipelineStepRun, PipelineTemplate


ACTIVE_WORK_STATUSES = [WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS]


def resolve_default_template(sample):
    sample_type = str(sample.sample_type or "GENERAL").strip().upper()
    candidates = list(
        PipelineTemplate.objects.filter(active=True, is_default=True)
        .prefetch_related("steps__procedure__analysis")
        .order_by("id")
    )

    ranked = []
    for template in candidates:
        configured_type = str(template.default_sample_type or "").strip().upper()
        project_matches = template.default_project_id == sample.project_id
        global_project = template.default_project_id is None
        type_matches = bool(configured_type) and configured_type == sample_type
        global_type = not configured_type

        if project_matches and type_matches:
            score = 4
        elif project_matches and global_type:
            score = 3
        elif global_project and type_matches:
            score = 2
        elif global_project and global_type:
            score = 1
        else:
            continue

        ranked.append((score, template))

    if not ranked:
        return None

    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return ranked[0][1]


def start_default_pipeline_for_sample(sample, actor):
    template = resolve_default_template(sample)
    if not template:
        return None
    return start_pipeline(sample=sample, template=template, actor=actor)


def _event(entity_type, entity_id, action, actor, payload):
    Event.objects.create(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        actor=actor if actor and actor.is_authenticated else None,
        payload=payload,
    )


def _step_payload(step):
    return {
        "pipeline_run_id": step.pipeline_run_id,
        "pipeline_step_run_id": step.id,
        "sample_id": step.pipeline_run.sample_id,
        "sample_code": step.pipeline_run.sample.sample_id,
        "position": step.position,
        "name": step.name,
        "analysis_code": step.analysis_code,
        "procedure_code": step.procedure_code,
        "procedure_version": step.procedure_version,
        "work_item_id": step.work_item_id,
    }


def _activate_step(step, actor):
    active_conflict = WorkItem.objects.filter(
        sample=step.pipeline_run.sample,
        work_type=step.work_type,
        status__in=ACTIVE_WORK_STATUSES,
    ).exists()
    if active_conflict:
        raise ValidationError({
            "detail": (
                f"Cannot activate pipeline step {step.position}: an active "
                f"{step.work_type} work item already exists for this sample."
            )
        })

    due_at = timezone.now() + timedelta(minutes=step.estimated_duration_minutes)
    work_item = WorkItem.objects.create(
        sample=step.pipeline_run.sample,
        name=step.name,
        work_type=step.work_type,
        status=WorkItem.STATUS_PENDING,
        notes=(
            f"Pipeline {step.pipeline_run.template_code}, step {step.position}; "
            f"procedure {step.procedure_code} v{step.procedure_version}."
        ),
        created_by=actor if actor and actor.is_authenticated else None,
        due_at=due_at,
    )
    step.status = PipelineStepRun.STATUS_READY
    step.work_item = work_item
    step.failure_reason = ""
    step.save(update_fields=["status", "work_item", "failure_reason", "updated_at"])

    payload = _step_payload(step)
    payload["due_at"] = due_at.isoformat()
    _event("PipelineRun", step.pipeline_run_id, "PIPELINE_STEP_ACTIVATED", actor, payload)
    _event("Sample", step.pipeline_run.sample_id, "PIPELINE_STEP_ACTIVATED", actor, payload)


@transaction.atomic
def start_pipeline(*, sample, template, actor):
    from samples.models import Sample

    sample = Sample.objects.select_for_update().select_related("project").get(pk=sample.pk)
    if PipelineRun.objects.filter(
        sample=sample,
        status__in=[PipelineRun.STATUS_ACTIVE, PipelineRun.STATUS_BLOCKED],
    ).exists():
        raise ValidationError({"sample": "This sample already has an active or blocked pipeline run."})

    template = (
        PipelineTemplate.objects.select_for_update()
        .prefetch_related("steps__procedure__analysis")
        .get(pk=template.pk)
    )
    if not template.active:
        raise ValidationError({"template": "Only active pipeline templates can be started."})

    template_steps = list(template.steps.all())
    if not template_steps:
        raise ValidationError({"template": "A pipeline template must contain at least one step."})

    run = PipelineRun.objects.create(
        sample=sample,
        template=template,
        template_code=template.code,
        template_name=template.name,
        status=PipelineRun.STATUS_ACTIVE,
        started_by=actor if actor and actor.is_authenticated else None,
    )

    step_runs = []
    for template_step in template_steps:
        procedure = template_step.procedure
        analysis = procedure.analysis
        step_runs.append(
            PipelineStepRun.objects.create(
                pipeline_run=run,
                template_step=template_step,
                position=template_step.position,
                name=template_step.display_name,
                analysis_code=analysis.code,
                procedure_code=procedure.code,
                procedure_version=procedure.version,
                work_type=analysis.code,
                required_fields=analysis.required_fields,
                requires_qc=template_step.requires_qc,
                estimated_duration_minutes=procedure.estimated_duration_minutes,
                status=PipelineStepRun.STATUS_BLOCKED,
            )
        )

    payload = {
        "pipeline_run_id": run.id,
        "template_id": template.id,
        "template_code": template.code,
        "template_name": template.name,
        "sample_id": sample.id,
        "sample_code": sample.sample_id,
        "step_count": len(step_runs),
    }
    _event("PipelineRun", run.id, "PIPELINE_RUN_STARTED", actor, payload)
    _event("Sample", sample.id, "PIPELINE_RUN_STARTED", actor, payload)
    _activate_step(step_runs[0], actor)
    return run


def missing_required_fields(work_item, step=None):
    if step is None:
        step = PipelineStepRun.objects.filter(work_item=work_item).first()
    if not step:
        return []

    result_map = {
        result.key.strip().lower(): result
        for result in work_item.results.all()
    }
    missing = []
    for definition in step.required_fields or []:
        if not definition.get("required", True):
            continue
        key = str(definition.get("key") or "").strip()
        result = result_map.get(key.lower())
        if not result:
            missing.append(key)
            continue
        expected_type = definition.get("value_type")
        if expected_type and result.value_type != expected_type:
            missing.append(key)
            continue
        if result.value is None or (isinstance(result.value, str) and not result.value.strip()):
            missing.append(key)
    return missing


def validate_work_item_pipeline_completion(work_item, next_status):
    step = PipelineStepRun.objects.filter(work_item=work_item).first()
    if not step:
        return
    terminal_statuses = [
        WorkItem.STATUS_COMPLETED,
        WorkItem.STATUS_FAILED,
        WorkItem.STATUS_CANCELLED,
    ]
    if work_item.status in terminal_statuses and next_status != work_item.status:
        raise ValidationError({
            "status": "A final pipeline work item cannot be reopened or changed to another final state."
        })
    if next_status != WorkItem.STATUS_COMPLETED:
        return
    missing = missing_required_fields(work_item, step)
    if missing:
        raise ValidationError({
            "status": (
                "Pipeline work cannot be completed until these required result "
                f"fields are recorded: {', '.join(missing)}."
            ),
            "missing_required_fields": missing,
        })


def _complete_step(step, actor):
    now = timezone.now()
    step.status = PipelineStepRun.STATUS_COMPLETED
    step.completed_at = now
    step.failure_reason = ""
    step.save(update_fields=["status", "completed_at", "failure_reason", "updated_at"])
    _event("PipelineRun", step.pipeline_run_id, "PIPELINE_STEP_COMPLETED", actor, _step_payload(step))

    next_step = (
        step.pipeline_run.steps.filter(position__gt=step.position)
        .order_by("position")
        .first()
    )
    if next_step:
        _activate_step(next_step, actor)
        return

    run = step.pipeline_run
    run.status = PipelineRun.STATUS_COMPLETED
    run.completed_at = now
    run.save(update_fields=["status", "completed_at", "updated_at"])
    payload = {
        "pipeline_run_id": run.id,
        "sample_id": run.sample_id,
        "sample_code": run.sample.sample_id,
        "template_code": run.template_code,
        "completed_at": now.isoformat(),
    }
    _event("PipelineRun", run.id, "PIPELINE_RUN_COMPLETED", actor, payload)
    _event("Sample", run.sample_id, "PIPELINE_RUN_COMPLETED", actor, payload)


@transaction.atomic
def sync_pipeline_step_from_work_item(work_item, actor=None):
    step = (
        PipelineStepRun.objects.select_for_update()
        .select_related("pipeline_run__sample", "work_item")
        .filter(work_item_id=work_item.id)
        .first()
    )
    if not step:
        return None

    work_item = WorkItem.objects.select_for_update().get(pk=work_item.pk)
    run = step.pipeline_run
    if run.status not in [PipelineRun.STATUS_ACTIVE, PipelineRun.STATUS_BLOCKED]:
        return step

    if work_item.status == WorkItem.STATUS_IN_PROGRESS:
        changed = step.status != PipelineStepRun.STATUS_IN_PROGRESS
        step.status = PipelineStepRun.STATUS_IN_PROGRESS
        if not step.started_at:
            step.started_at = timezone.now()
        step.failure_reason = ""
        step.save(update_fields=["status", "started_at", "failure_reason", "updated_at"])
        if changed:
            _event("PipelineRun", run.id, "PIPELINE_STEP_STARTED", actor, _step_payload(step))
        return step

    if work_item.status in [WorkItem.STATUS_FAILED, WorkItem.STATUS_CANCELLED]:
        target_step_status = (
            PipelineStepRun.STATUS_FAILED
            if work_item.status == WorkItem.STATUS_FAILED
            else PipelineStepRun.STATUS_CANCELLED
        )
        target_run_status = (
            PipelineRun.STATUS_BLOCKED
            if work_item.status == WorkItem.STATUS_FAILED
            else PipelineRun.STATUS_CANCELLED
        )
        already_synchronized = (
            step.status == target_step_status and run.status == target_run_status
        )
        step.status = target_step_status
        step.failure_reason = work_item.notes if work_item.status == WorkItem.STATUS_FAILED else ""
        step.completed_at = timezone.now()
        step.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])
        run.status = target_run_status
        run.completed_at = timezone.now() if run.status == PipelineRun.STATUS_CANCELLED else None
        run.save(update_fields=["status", "completed_at", "updated_at"])
        if already_synchronized:
            return step
        action = "PIPELINE_STEP_BLOCKED" if run.status == PipelineRun.STATUS_BLOCKED else "PIPELINE_RUN_CANCELLED"
        payload = _step_payload(step)
        payload["failure_reason"] = step.failure_reason
        _event("PipelineRun", run.id, action, actor, payload)
        _event("Sample", run.sample_id, action, actor, payload)
        return step

    if work_item.status != WorkItem.STATUS_COMPLETED:
        return step

    missing = missing_required_fields(work_item, step)
    if missing:
        step.status = PipelineStepRun.STATUS_FAILED
        step.failure_reason = f"Missing required result fields: {', '.join(missing)}."
        step.save(update_fields=["status", "failure_reason", "updated_at"])
        run.status = PipelineRun.STATUS_BLOCKED
        run.save(update_fields=["status", "updated_at"])
        payload = _step_payload(step)
        payload["failure_reason"] = step.failure_reason
        _event("PipelineRun", run.id, "PIPELINE_STEP_BLOCKED", actor, payload)
        _event("Sample", run.sample_id, "PIPELINE_STEP_BLOCKED", actor, payload)
        return step

    if step.requires_qc:
        if work_item.qc_status == WorkItem.QC_PENDING_REVIEW:
            step.status = PipelineStepRun.STATUS_AWAITING_QC
            step.save(update_fields=["status", "updated_at"])
            return step
        if work_item.qc_status in [WorkItem.QC_REJECTED, WorkItem.QC_RERUN_REQUIRED]:
            step.status = PipelineStepRun.STATUS_FAILED
            step.failure_reason = work_item.review_note or "QC review did not approve this step."
            step.save(update_fields=["status", "failure_reason", "updated_at"])
            run.status = PipelineRun.STATUS_BLOCKED
            run.save(update_fields=["status", "updated_at"])
            payload = _step_payload(step)
            payload["failure_reason"] = step.failure_reason
            _event("PipelineRun", run.id, "PIPELINE_STEP_BLOCKED", actor, payload)
            _event("Sample", run.sample_id, "PIPELINE_STEP_BLOCKED", actor, payload)
            return step

    _complete_step(step, actor)
    return step


@transaction.atomic
def cancel_pipeline(*, run, actor, reason):
    run = (
        PipelineRun.objects.select_for_update()
        .select_related("sample")
        .prefetch_related("steps__work_item")
        .get(pk=run.pk)
    )
    if run.status in [PipelineRun.STATUS_COMPLETED, PipelineRun.STATUS_CANCELLED]:
        raise ValidationError({"detail": f"Pipeline run is already {run.status.lower()}."})

    now = timezone.now()
    current_step = run.steps.exclude(
        status__in=[PipelineStepRun.STATUS_COMPLETED, PipelineStepRun.STATUS_CANCELLED]
    ).order_by("position").first()
    run.steps.exclude(status=PipelineStepRun.STATUS_COMPLETED).update(
        status=PipelineStepRun.STATUS_CANCELLED,
        completed_at=now,
        failure_reason=reason,
    )
    if current_step and current_step.work_item_id and current_step.work_item.status not in [
        WorkItem.STATUS_COMPLETED,
        WorkItem.STATUS_FAILED,
        WorkItem.STATUS_CANCELLED,
    ]:
        notes = f"{current_step.work_item.notes}\nCancelled: {reason}".strip()
        WorkItem.objects.filter(pk=current_step.work_item_id).update(
            status=WorkItem.STATUS_CANCELLED,
            notes=notes,
            updated_at=now,
        )

    run.status = PipelineRun.STATUS_CANCELLED
    run.completed_at = now
    run.save(update_fields=["status", "completed_at", "updated_at"])
    payload = {
        "pipeline_run_id": run.id,
        "sample_id": run.sample_id,
        "sample_code": run.sample.sample_id,
        "reason": reason,
    }
    _event("PipelineRun", run.id, "PIPELINE_RUN_CANCELLED", actor, payload)
    _event("Sample", run.sample_id, "PIPELINE_RUN_CANCELLED", actor, payload)
    return run
