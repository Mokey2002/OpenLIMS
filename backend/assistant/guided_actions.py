"""Small, explicit lab actions using server-owned previews and confirmation tokens."""
import json
import math
import re

from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from events.models import Event
from pipelines.models import PipelineRun, PipelineStepRun
from results.models import Result, WorkItem
from results.serializers import ResultSerializer
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample


TARGET = r"(?P<target>(?:the\s+)?next step|(?:el\s+)?siguiente paso|(?:step|paso)\s+\d+|work item\s*#?\d+)"
SAMPLE = r"(?:\s+(?:for sample|para muestra)\s+(?P<sample>[\w./-]+))?"
ASSIGN = re.compile(r"(?:assign|reassign|asigna|reasigna)\s+" + TARGET + SAMPLE + r"\s+(?:to|a)\s+(?P<person>[\w.@+-]+)[.!?]?", re.I)
ADD = re.compile(r"(?:add result|agrega resultado)\s+(?P<key>[\w.-]{1,64})\s*=\s*(?P<value>.+?)\s+(?:to|a)\s+" + TARGET + SAMPLE + r"(?:\s+unit\s+(?P<unit>\S{1,32}))?", re.I)
ACTIVE_WORK = {WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS}
ACTIVE_STEP = {PipelineStepRun.STATUS_READY, PipelineStepRun.STATUS_IN_PROGRESS}
ACTIVE_RUN = {PipelineRun.STATUS_ACTIVE, PipelineRun.STATUS_BLOCKED}


def _reply(answer, **extra):
    return {"answer": answer, "links": [], "skip_llm": True,
            "context": {}, "replace_context": True, **extra}


def _snapshot(work, sample, step):
    return {
        "work_updated": work.updated_at.isoformat(), "status": work.status,
        "assigned_to": work.assigned_to_id, "qc_status": work.qc_status,
        "sample_id": sample.pk, "project_id": sample.project_id,
        "sample_updated": sample.updated_at.isoformat(),
        "step_id": step.pk if step else None,
        "step_updated": step.updated_at.isoformat() if step else None,
        "run_id": step.pipeline_run_id if step else None,
        "step_status": step.status if step else None,
        "run_status": step.pipeline_run.status if step else None,
        "run_updated": step.pipeline_run.updated_at.isoformat() if step else None,
    }


def _eligible(work, step):
    return (work.status in ACTIVE_WORK and work.qc_status == WorkItem.QC_PENDING_REVIEW
            and (not step or (step.status in ACTIVE_STEP and step.pipeline_run.status in ACTIVE_RUN)))


def _assignee(username, sample):
    # Exact usernames prevent choosing between people with the same first name.
    users = list(get_user_model().objects.filter(username__iexact=username, is_active=True)[:2])
    if len(users) != 1 or not user_can_modify_sample(users[0], sample):
        raise ValueError("Use the exact username of an active Tech or Director who can modify this sample.")
    return users[0]


def _result_data(work, key, raw, unit):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('Use a number, true/false, or a quoted string, for example concentration = 43 or interpretation = "PASS".')
    if isinstance(value, bool):
        kind, field = "BOOLEAN", "value_boolean"
    elif type(value) in (int, float) and abs(value) <= 1.7976931348623157e308 and math.isfinite(value):
        kind, field = "NUMBER", "value_number"
    elif isinstance(value, str) and value.strip():
        kind, field = "STRING", "value_string"
    else:
        raise ValueError("A result must be a finite number, true/false, or a nonempty quoted string.")
    requirements = work.required_fields or []
    if requirements:
        requirement = next((r for r in requirements if r.get("key") == key), None)
        if not requirement:
            raise ValueError("Use a configured result key: " + ", ".join(r["key"] for r in requirements))
        if requirement.get("value_type", "STRING") != kind:
            raise ValueError(f"{key} requires {requirement.get('value_type', 'STRING')}; use the matching value type.")
    data = {"work_item": work.pk, "key": key, "value_type": kind, field: value, "unit": unit or ""}
    serializer = ResultSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return data


def route_guided_action(message, user, context=None):
    text = str(message or "").strip()
    assignment = ASSIGN.fullmatch(text)
    addition = ADD.fullmatch(text)
    interested = bool(re.search(r"\b(?:assign|reassign|asigna|reasigna)\b.*\b(?:step|paso|work item)\b|\b(?:add result|agrega resultado)\b", text, re.I))
    if not interested:
        return None
    match = assignment or addition
    if not match:
        return _reply('Specify one action, for example: Assign step 1 for sample DEMO-360-001 to maria; or Add result concentration = 43 to step 1 for sample DEMO-360-001.', clarification={"required": True})
    context = context or {}
    code = match["sample"] or context.get("sample_code")
    target = match["target"].lower()
    step = None
    if target.startswith("work item"):
        work_id = int(re.search(r"\d+", target)[0])
        work = WorkItem.objects.filter(pk=work_id, sample__in=get_sample_access_queryset(Sample.objects.all(), user)).first()
        if not work or (code and work.sample.sample_id.casefold() != str(code).casefold()):
            return _reply("Work item not found, inaccessible, or does not match the selected sample.")
        sample = work.sample
        step = PipelineStepRun.objects.select_related("pipeline_run").filter(work_item=work).first()
    else:
        if not isinstance(code, str) or not code:
            return _reply("Include the exact sample ID in your request, or first ask what comes next for that sample.", clarification={"required": True})
        samples = list(get_sample_access_queryset(Sample.objects.all(), user).filter(sample_id__iexact=code)[:2])
        if len(samples) != 1:
            return _reply("Sample not found, ambiguous, or inaccessible.")
        sample = samples[0]
        steps = PipelineStepRun.objects.select_related("pipeline_run", "work_item").filter(pipeline_run__sample=sample, pipeline_run__status__in=ACTIVE_RUN)
        number = re.search(r"\d+", target)
        if number:
            steps = steps.filter(position=int(number[0]))
        else:
            steps = steps.filter(status__in=ACTIVE_STEP, work_item__status__in=ACTIVE_WORK)
        candidates = list(steps[:2])
        if len(candidates) != 1:
            return _reply("No unique available step. Specify its step number or exact work item ID; parallel steps are not selected automatically.", clarification={"required": True})
        step = candidates[0]
        work = step.work_item
    if not user.is_active or not user_can_modify_sample(user, sample):
        return _reply("You do not have permission to modify this sample.")
    if not work or not _eligible(work, step):
        return _reply("Only active, available work awaiting QC review can be changed here. Open the sample to inspect blocked, completed, or reviewed work.")
    try:
        if assignment:
            person = _assignee(match["person"], sample)
            if person.pk == work.assigned_to_id:
                return _reply("This work is already assigned to that user.")
            operation = "GUIDED_ASSIGN"
            proposed = {"assigned_to": person.username}
            detail = {"target_user_id": person.pk}
        else:
            operation = "GUIDED_RESULT"
            detail = {"result_data": _result_data(work, match["key"], match["value"], match["unit"])}
            proposed = {**detail["result_data"], "qc_status": Result.QC_PENDING_REVIEW}
    except (ValueError, ValidationError) as exc:
        return _reply(str(exc), clarification={"required": True})
    label = f"{sample.sample_id} · {work.name} · Work #{work.pk}"
    if step:
        label += f" · Step {step.position} · Run #{step.pipeline_run_id}"
    current = {"status": work.status, "qc_status": work.qc_status, "assigned_to": work.assigned_to.username if work.assigned_to else None}
    preview = {"title": "Review lab action", "operation": operation,
               "project": {"id": sample.project_id, "label": sample.project.code if sample.project_id else "Unassigned"},
               "records_affected": 1, "current_values": current, "proposed_values": proposed,
               "records": [{"id": work.pk, "label": label, "current": current, "proposed": proposed}],
               "warnings": ["A new result remains unreviewed. This does not complete work or approve QC."] if addition else []}
    return _reply(f"Review the proposed change to {label}, then confirm. Nothing has been changed yet.",
                  links=[{"label": sample.sample_id, "url": f"/samples/{sample.pk}"}],
                  context={"sample_code": sample.sample_id, "guidance": {"step": step.position} if step else {}},
                  pending_action={"type": "WORK_ITEM_OPERATION", "summary": f"{operation}: {label}",
                                  "payload": {"operation": operation, "work_item_id": work.pk,
                                              "snapshot": _snapshot(work, sample, step), "preview": preview, **detail}})


def execute_guided_action(action):
    """Called inside confirm_action's transaction; never trust client context here."""
    payload = action.payload
    expected = payload["snapshot"]
    sample = Sample.objects.select_for_update().get(pk=expected["sample_id"])
    run = PipelineRun.objects.select_for_update().get(pk=expected["run_id"]) if expected["run_id"] else None
    step = PipelineStepRun.objects.select_for_update().get(pk=expected["step_id"], pipeline_run=run) if expected["step_id"] else None
    if step:
        step.pipeline_run = run
    work = WorkItem.objects.select_for_update().get(pk=payload["work_item_id"])
    if not action.requested_by.is_active or not user_can_modify_sample(action.requested_by, sample):
        raise ValueError("Sample modification access is no longer permitted.")
    if (work.sample_id != sample.pk or (step and (step.work_item_id != work.pk or step.pipeline_run_id != run.pk or run.sample_id != sample.pk))
            or _snapshot(work, sample, step) != expected or not _eligible(work, step)):
        raise ValueError("The work, sample, or pipeline changed after preview. Request a fresh preview.")
    operation = payload["operation"]
    if operation == "GUIDED_ASSIGN":
        person = get_user_model().objects.get(pk=payload["target_user_id"])
        if not person.is_active or not user_can_modify_sample(person, sample):
            raise ValueError("The assignee can no longer modify this sample.")
        before = work.assigned_to_id
        work.assigned_to = person
        work.save(update_fields=["assigned_to", "updated_at"])
        entity_type, entity_id, event = "WorkItem", work.pk, "WORK_ITEM_REASSIGNED" if before else "WORK_ITEM_ASSIGNED"
        change = {"before": {"assigned_to": before}, "after": {"assigned_to": person.pk}}
    elif operation == "GUIDED_RESULT":
        data = payload["result_data"]
        # Validate the current schema and uniqueness again after obtaining locks.
        value = data.get("value_" + data["value_type"].lower())
        validated = _result_data(work, data["key"], json.dumps(value), data["unit"])
        serializer = ResultSerializer(data=validated)
        serializer.is_valid(raise_exception=True)
        result = serializer.save(entered_by=action.requested_by)
        entity_type, entity_id, event = "Result", result.pk, "RESULT_CREATED"
        change = {"after": {"key": result.key, "value": result.value, "value_type": result.value_type, "unit": result.unit, "qc_status": result.qc_status}}
    else:
        raise ValueError("Unsupported guided action.")
    Event.objects.create(entity_type=entity_type, entity_id=str(entity_id), action=event, actor=action.requested_by,
                         payload={"assistant_action_id": str(action.pk), "sample_id": sample.pk,
                                  "project_id": sample.project_id, "work_item_id": work.pk, **change})
    return {"operation": operation, "succeeded_count": 1, "failed_count": 0,
            "succeeded": [{"id": entity_id, "sample_id": sample.sample_id}], "failed": []}
