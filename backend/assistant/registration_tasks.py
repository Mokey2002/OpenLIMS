"""A bounded registration conversation and one atomic, confirmed lab task."""
import copy
import re

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from custom_fields.forms import schema_for, validate_values
from custom_fields.models import FieldDefinition, FieldValue
from projects.models import Project
from samples.access import validate_sample_project_assignment
from samples.models import Sample
from .lab_helpers import enabled, response
from .natural_requests import normalize_request
from .registration_input import _validate_json, parse_registration_fields
from .sample_operations import (
    _event_for_sample, _generated_sample_codes, _preview, _proposal_result,
    _resolve_project, _validate_custom_field_payload, _write_user, assistant_bulk_max_records,
)

KEY = "registration_task"
SALT = "assistant.registration-task.v1"
MAX_AGE = 1800
MAX_TOKEN = 24000
REFERENCE = r'(?:"[^"\n]{1,128}"|[\w.:/@+-]{1,128})'
START = re.compile(
    r"(?:register|create)(?: (?P<count>\d+))?(?: (?P<sample_type>[A-Za-z][A-Za-z0-9_-]{0,63}))? samples?"
    rf"(?: (?:in|for) (?:project )?(?P<project>{REFERENCE}))?"
    r"(?P<assignment> and assign(?: (?:them|it|these samples|the samples))?(?: to (?P<assignee>[\w.@+-]{1,150}))?)?"
    r"(?: with (?P<values>.+))?", re.I,
)
def _recall(context, user):
    token = context.get(KEY)
    if not isinstance(token, str) or len(token) > MAX_TOKEN:
        return None
    try:
        saved = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, TypeError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get("user") != user.pk or not isinstance(saved.get("draft"), dict):
        return None
    draft = saved["draft"]
    if (set(draft) != {"count", "sample_type", "project_id", "assign_requested", "assignee", "assignee_id", "values", "awaiting"}
            or type(draft["assign_requested"]) is not bool or not isinstance(draft["values"], dict)
            or draft["count"] is not None and type(draft["count"]) is not int
            or any(value is not None and (type(value) is not int or not 0 < value < 2**63) for value in [draft["project_id"], draft["assignee_id"]])
            or draft["sample_type"] is not None and (not isinstance(draft["sample_type"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", draft["sample_type"]))
            or draft["assignee"] is not None and (not isinstance(draft["assignee"], str) or not re.fullmatch(r"[\w.@+-]{1,150}", draft["assignee"]))
            or not isinstance(draft["awaiting"], str) or not re.fullmatch(r"count|project|sample_type|assignee|values|(?:custom_fields|form_values):[^\x00\n]{1,64}", draft["awaiting"])):
        return None
    return copy.deepcopy(draft)


def _ask(draft, user, slot, question):
    draft["awaiting"] = slot
    token = signing.dumps({"user": user.pk, "draft": draft}, salt=SALT, compress=True)
    if len(token) > MAX_TOKEN:
        return response("This draft is too large. Start again with a smaller set of shared field values.", clarification={"required": True})
    return response(question, context={KEY: token}, clarification={"required": True, "fields": [slot]})


def _project(pk, user):
    projects = Project.objects.all() if user.is_superuser or user.groups.filter(name="admin").exists() else Project.objects.filter(members=user)
    return projects.filter(pk=pk).first()


def _person(reference, project):
    people = list(get_user_model().objects.filter(username__iexact=reference, is_active=True)[:2])
    if len(people) != 1 or not _write_user(people[0]):
        raise ValueError("Use the exact username of one active Tech or Admin.")
    person = people[0]
    try:
        validate_sample_project_assignment(person, project)
    except ValidationError:
        raise ValueError("The assignee must be able to modify samples in this project.")
    return person


def _values(draft, schema, definitions):
    custom, intake = {}, {}
    intake_keys = {field["key"] for field in schema.get("fields", [])}
    for key, value in draft["values"].items():
        if key in {"custom_fields", "form_values"}:
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object of field names and values.")
            (custom if key == "custom_fields" else intake).update(value)
        elif key in definitions and key in intake_keys:
            raise ValueError(f"{key} exists in both field systems. Use custom_fields={{\"{key}\": value}} or form_values={{\"{key}\": value}} explicitly.")
        elif key in definitions:
            custom[key] = value
        elif key in intake_keys:
            intake[key] = value
        else:
            raise ValueError(f"Unknown field: {key}. Use configured field names; no samples were proposed.")
    if set(custom) - set(definitions) or set(intake) - intake_keys:
        raise ValueError("Unknown field in custom_fields or form_values; use configured field names.")
    return custom, intake


def _progress(draft, user):
    count = draft.get("count")
    if type(count) is not int or not 1 <= count <= assistant_bulk_max_records():
        return _ask(draft, user, "count", f"How many samples? Reply with a whole number from 1 to {assistant_bulk_max_records()}.")
    if not draft.get("project_id"):
        return _ask(draft, user, "project", "Which project? Reply with its exact code, or a quoted exact name.")
    project = _project(draft["project_id"], user)
    if not project:
        return response("The selected project is unavailable or your write access changed. Start a new task with an accessible project.", clarification={"required": True})
    if not draft.get("sample_type"):
        return _ask(draft, user, "sample_type", "What sample type should I use? Reply with its code, for example DNA, PLASMA or GENERAL.")
    person = None
    if draft["assign_requested"]:
        if not draft.get("assignee_id"):
            reference = draft.get("assignee")
            if not reference:
                return _ask(draft, user, "assignee", "Who should receive the samples? Reply with an exact username, or me.")
            try:
                person = _person(user.username if reference.lower() == "me" else reference, project)
            except ValueError as exc:
                return _ask(draft, user, "assignee", str(exc))
            draft["assignee_id"] = person.pk
        else:
            person = get_user_model().objects.filter(pk=draft["assignee_id"], is_active=True).first()
            if not person or not _write_user(person):
                return response("The assignee is no longer available. Start a fresh task.", clarification={"required": True})
            try:
                validate_sample_project_assignment(person, project)
            except ValidationError:
                return response("The assignee can no longer modify samples in this project. Start a fresh task.", clarification={"required": True})
    try:
        schema = schema_for(draft["sample_type"])
    except ValidationError:
        draft["sample_type"] = None
        return _ask(draft, user, "sample_type", "That sample type is archived or unavailable. Reply with an available sample type code.")
    definitions = {field.name: field for field in FieldDefinition.objects.filter(entity_type="Sample").order_by("name")}
    try:
        custom, intake = _values(draft, schema, definitions)
    except ValueError as exc:
        return _ask(draft, user, "values", str(exc) + " Correct values with: with field_name=value.")
    draft["values"] = {"custom_fields": custom, "form_values": intake}
    for key, definition in definitions.items():
        missing = definition.required and (key not in custom or custom[key] is None or isinstance(custom[key], str) and not custom[key].strip())
        _, errors = _validate_custom_field_payload({key: custom[key]}, require_all=False) if key in custom else ({}, [])
        if missing or errors:
            detail = " ".join(errors)
            return _ask(draft, user, "custom_fields:" + key,
                        f"What is {definition.label or key} ({key}, {definition.data_type}) for all {count} samples? {detail} Reply with the value, or with {key}=value.")
    try:
        validate_values(schema, intake)
    except ValidationError as exc:
        errors = exc.detail.get("form_values", {})
        key = next((field["key"] for field in schema.get("fields", []) if field["key"] in errors), None)
        if not key:
            return _ask(draft, user, "values", "Check the intake fields and correct them with: with field_name=value.")
        field = next(field for field in schema["fields"] if field["key"] == key)
        choices = f" Choices: {', '.join(field['choices'])}." if field.get("choices") else ""
        return _ask(draft, user, "form_values:" + key,
                    f"What is {field.get('en', key)} ({key}, {field['type']}) for all {count} samples? {errors[key]}{choices} Reply with the value, or with {key}=value.")
    codes = _generated_sample_codes(project, count)
    if any(len(code) > 64 for code in codes):
        return response("Generated sample IDs exceed 64 characters. Use a shorter project code and start again.", clarification={"required": True})
    proposed = {"status": Sample.STATUS_RECEIVED, "project": project.code, "sample_type": draft["sample_type"],
                "assigned_to": person.username if person else None, "custom_fields": custom, "form_values": intake}
    rows = [{"id": None, "sample_id": code, "current": {"record": "Does not exist"}, "proposed": proposed} for code in codes]
    preview = _preview(operation="Register and assign samples" if person else "Register samples", user=user, project=project,
                       samples=rows, current_values={"record": "Does not exist"}, proposed_values=proposed,
                       warnings=["Assignment sets the sample assignee. Pipeline steps and work items have separate assignments."] if person else [])
    summary = f"Register {count} {draft['sample_type']} samples in {project.code}" + (f" and assign them to {person.username}" if person else "")
    result = _proposal_result(summary, preview, {"action_type": "CREATE_SAMPLES", "registration_task": True,
        "sample_type": draft["sample_type"], "project_id": project.pk, "sample_codes": codes,
        "custom_fields": custom, "form_values": intake, "intake_schema": schema,
        "target_user_id": person.pk if person else None, "target_username": person.username if person else None},
        context={"project_id": project.pk})
    result["replace_context"] = True
    return result


def route_registration_task(message, user, context=None):
    text = normalize_request(message)
    context = context or {}
    match = START.fullmatch(text)
    # Complete, single registration requests retain their established parser.
    started = match and (match["assignment"] or not match["count"] or not match["project"])
    draft = None if started else _recall(context, user)
    if not started and not draft:
        if KEY in context and re.match(r"^(?:with\b|\d+$)", text, re.I):
            return response("This registration draft expired or could not be verified. Start a fresh registration task.", clarification={"required": True})
        return None
    if not user.is_active or not _write_user(user):
        return response("Only an active Tech or Admin can register and assign samples.")
    if not enabled("samples"):
        return response("Sample management is disabled. No registration task was started.")
    if not started and text.lower() in {"cancel", "never mind", "start over", "reset conversation", "forget this conversation"}:
        return response("Registration draft discarded. No samples were created.")
    if started:
        if match["count"] and len(match["count"]) > 6:
            return response("The count exceeds the assistant limit. Start with a smaller number.", clarification={"required": True})
        draft = {"count": int(match["count"]) if match["count"] else None,
                 "sample_type": match["sample_type"].upper() if match["sample_type"] else None,
                 "project_id": None, "assign_requested": bool(match["assignment"]),
                 "assignee": match["assignee"], "assignee_id": None, "values": {}}
        project_error = None
        if match["project"]:
            project, error = _resolve_project(match["project"], user, write=True)
            if error:
                project_error = "Project not found, ambiguous, or inaccessible. Reply with an exact accessible project code."
            else:
                draft["project_id"] = project.pk
        if match["values"]:
            try:
                draft["values"] = parse_registration_fields(match["values"])
            except ValueError as exc:
                return _ask(draft, user, "values", str(exc))
        if project_error:
            return _ask(draft, user, "project", project_error)
    else:
        slot = draft.get("awaiting")
        if text.lower() in {"thanks", "thank you", "okay", "ok", "got it"}:
            return None
        if re.match(r"^(?:show|find|list|summarize|explain|what|where|why|approve|reject|archive|delete|assign|register|create)\b", text, re.I):
            return None
        try:
            if re.match(r"^with\s+", text, re.I):
                values = parse_registration_fields(text[5:])
                if slot == "values":
                    draft["values"] = {}
                for key, value in values.items():
                    if key in {"custom_fields", "form_values"} and isinstance(value, dict):
                        previous = draft["values"].get(key, {})
                        draft["values"][key] = {**(previous if isinstance(previous, dict) else {}), **value}
                    else:
                        draft["values"][key] = value
            elif slot == "count":
                if not re.fullmatch(r"\d{1,6}(?: samples?)?", text, re.I):
                    return _ask(draft, user, slot, "Reply with one whole-number sample count, for example 10.")
                draft["count"] = int(text.split()[0])
            elif slot == "project":
                if not re.fullmatch(REFERENCE, text):
                    return None
                project, error = _resolve_project(text, user, write=True)
                if error:
                    return _ask(draft, user, slot, "Project not found, ambiguous, or inaccessible. Use an exact accessible project code.")
                draft["project_id"] = project.pk
            elif slot == "sample_type":
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", text):
                    return _ask(draft, user, slot, "Reply with one sample type code, for example DNA or GENERAL.")
                draft["sample_type"] = text.upper()
            elif slot == "assignee":
                if not re.fullmatch(r"[\w.@+-]{1,150}", text):
                    return _ask(draft, user, slot, "Reply with one exact assignee username, or me.")
                draft["assignee"], draft["assignee_id"] = text, None
            elif isinstance(slot, str) and ":" in slot:
                group, key = slot.split(":", 1)
                value = parse_registration_fields(f"value={text}")["value"]
                draft["values"].setdefault(group, {})[key] = value
            else:
                return _ask(draft, user, "values", "Correct the draft using: with field_name=value. Or cancel and start again.")
        except (ValueError, TypeError) as exc:
            return _ask(draft, user, slot or "values", str(exc))
    return _progress(draft, user)


def execute_registration_task(action):
    """All samples, values, assignees and audit rows commit together."""
    payload, user = action.payload, action.requested_by
    if not user.is_active or not _write_user(user):
        raise ValueError("Your write permission changed. Request a fresh preview.")
    if not enabled("samples"):
        raise ValueError("Sample management is disabled. No samples were created.")
    project = _project(payload.get("project_id"), user)
    if not project:
        raise ValueError("Project unavailable or write access changed. Request a fresh preview.")
    sample_type, codes = payload.get("sample_type"), payload.get("sample_codes")
    if (not isinstance(sample_type, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", sample_type)
            or not isinstance(codes, list) or not 1 <= len(codes) <= assistant_bulk_max_records()
            or any(not isinstance(code, str) or not code.strip() or len(code) > 64 for code in codes)
            or len(set(code.casefold() for code in codes)) != len(codes)):
        raise ValueError("Invalid frozen sample selection. Request a fresh preview.")
    schema = schema_for(sample_type)
    if schema != payload.get("intake_schema"):
        raise ValueError("The intake form changed. Request a fresh preview.")
    intake = payload.get("form_values")
    _validate_json(intake)
    validate_values(schema, intake)
    custom = payload.get("custom_fields")
    if not isinstance(custom, dict):
        raise ValueError("Invalid frozen custom fields.")
    _validate_json(custom)
    custom, errors = _validate_custom_field_payload(custom, require_all=True)
    if errors:
        raise ValueError("; ".join(errors))
    person = None
    target_id, target_name = payload.get("target_user_id"), payload.get("target_username")
    if ((target_id is None) != (target_name is None)
            or target_id is not None and (type(target_id) is not int or not 0 < target_id < 2**63 or not isinstance(target_name, str))):
        raise ValueError("Invalid frozen assignee. Request a fresh preview.")
    if payload.get("target_user_id") is not None:
        person = _person(payload.get("target_username"), project)
        if person.pk != payload["target_user_id"]:
            raise ValueError("The assignee changed. Request a fresh preview.")
    definitions = {field.name: field for field in FieldDefinition.objects.filter(entity_type="Sample", name__in=custom)}
    if any(field.required and (custom[key] is None or isinstance(custom[key], str) and not custom[key].strip()) for key, field in definitions.items()):
        raise ValueError("A required custom field is empty. Request a fresh preview.")
    succeeded = []
    try:
        with transaction.atomic():
            for code in codes:
                if Sample.objects.filter(sample_id__iexact=code).exists():
                    raise ValueError("A previewed sample ID already exists. No samples were created; request a fresh preview.")
                sample = Sample.objects.create(sample_id=code, sample_type=sample_type, project=project,
                    status=Sample.STATUS_RECEIVED, created_by=user, assigned_to=person, form_values=intake)
                if sample.form_schema != schema:
                    raise ValueError("The intake form changed during confirmation. No samples were created; request a fresh preview.")
                for key, value in custom.items():
                    FieldValue.objects.create(field_definition=definitions[key], entity_type="Sample", entity_id=str(sample.pk), value=value)
                after = {"project_id": project.pk, "sample_type": sample_type, "status": sample.status,
                         "assigned_to_id": person.pk if person else None, "custom_fields": custom, "form_values": intake}
                _event_for_sample(action, sample, "SAMPLE_CREATED_BY_ASSISTANT", {}, after, list(after))
                succeeded.append({"id": sample.pk, "sample_id": code, "assigned_to": person.username if person else None})
    except IntegrityError as exc:
        raise ValueError("A sample conflict occurred. No samples were created; request a fresh preview.") from exc
    return {"operation": "REGISTER_AND_ASSIGN_SAMPLES", "requested_count": len(codes), "succeeded_count": len(codes),
            "failed_count": 0, "succeeded": succeeded, "failed": [],
            "message": f"Registered {len(codes)} {sample_type} samples in {project.code}" + (f" and assigned them to {person.username}." if person else "."),
            "context": {"sample_ids": [row["id"] for row in succeeded], "sample_codes": codes, "project_id": project.pk}}
