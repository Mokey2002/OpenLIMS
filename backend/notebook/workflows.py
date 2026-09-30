"""Ordered notebook workflows: template definitions and per-experiment snapshots."""
import hashlib
import json
import math
from copy import deepcopy

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit_event
from core.permissions import is_admin
from .models import Experiment, ExperimentWorkflowStep
from .permissions import user_can_notebook


class WorkflowFieldDefinition(serializers.Serializer):
    key = serializers.RegexField(r"^[a-z][a-z0-9_]{0,63}$")
    label = serializers.CharField(max_length=120)
    type = serializers.ChoiceField(choices=["STRING", "NUMBER", "BOOLEAN"])
    required = serializers.BooleanField(default=True)
    minimum = serializers.FloatField(required=False, allow_null=True)
    maximum = serializers.FloatField(required=False, allow_null=True)
    equals = serializers.JSONField(required=False)

    def validate(self, attrs):
        for key in ("minimum", "maximum"):
            value = attrs.get(key)
            if value is not None and (attrs["type"] != "NUMBER" or not math.isfinite(value)):
                raise ValidationError({key: "Bounds require a finite numeric field."})
        if attrs.get("minimum") is not None and attrs.get("maximum") is not None and attrs["minimum"] > attrs["maximum"]:
            raise ValidationError("Minimum must not exceed maximum.")
        if "equals" in attrs:
            validate_value(attrs, attrs["equals"], criteria=True)
        return attrs


class WorkflowStepDefinition(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    instructions = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    completion_criteria = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    assignee = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    fields = WorkflowFieldDefinition(many=True, max_length=30)

    def validate_fields(self, fields):
        keys = [field["key"] for field in fields]
        if len(keys) != len(set(keys)):
            raise ValidationError("Field keys must be unique within a step.")
        return fields


def validate_definition(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValidationError("Use at most 50 ordered workflow steps.")
    serializer = WorkflowStepDefinition(data=value, many=True)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def validate_assignee(user_id, notebook):
    if user_id is None:
        return None
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user or not user_can_notebook(user, notebook, "write"):
        raise ValidationError({"assignee": "Choose an active user with edit access to this notebook. Assignment does not grant access."})
    return user


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_value(field, value, *, criteria=False):
    kind = field["type"]
    valid = ((kind == "STRING" and isinstance(value, str) and len(value) <= 10000)
             or (kind == "BOOLEAN" and type(value) is bool)
             or (kind == "NUMBER" and finite_number(value)))
    if not valid:
        raise ValidationError({field["key"]: f"Enter a valid {kind.lower()} value."})
    if kind == "NUMBER":
        if field.get("minimum") is not None and value < field["minimum"]:
            raise ValidationError({field["key"]: f"Minimum: {field['minimum']}."})
        if field.get("maximum") is not None and value > field["maximum"]:
            raise ValidationError({field["key"]: f"Maximum: {field['maximum']}."})
    if not criteria and "equals" in field and value != field["equals"]:
        raise ValidationError({field["key"]: f"Required value: {field['equals']}."})


def validate_values(definition, values, *, complete):
    if not isinstance(values, dict):
        raise ValidationError({"values": "Expected an object of field values."})
    fields = {field["key"]: field for field in definition["fields"]}
    if set(values) - fields.keys():
        raise ValidationError({"values": "Unknown field. Reload the workflow before saving."})
    for key, field in fields.items():
        value = values.get(key)
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            if complete and (field.get("required", True) or "equals" in field or field.get("minimum") is not None or field.get("maximum") is not None):
                raise ValidationError({key: "This field is required before completion."})
            continue
        # Drafts retain measured values even if they fail acceptance criteria.
        check = field if complete else {k: v for k, v in field.items() if k not in {"minimum", "maximum", "equals"}}
        validate_value(check, value)
    return values


def create_steps(experiment, definitions, actor, *, cloning=False):
    definitions = validate_definition(deepcopy(definitions))
    for position, definition in enumerate(definitions, 1):
        user_id = definition.pop("assignee", None)
        try:
            assignee = validate_assignee(user_id, experiment.notebook)
        except ValidationError:
            if not cloning:
                raise
            assignee = None
        ExperimentWorkflowStep.objects.create(experiment=experiment, position=position, definition=definition, assignee=assignee)
        if assignee:
            experiment.assignees.add(assignee)
    if definitions:
        record_audit_event(entity=experiment, action="EXPERIMENT_WORKFLOW_STARTED", actor=actor,
                           after={"steps": workflow_snapshot(experiment)})


def workflow_snapshot(experiment):
    rows = list(experiment.workflow_steps.order_by("position").values(
        "position", "definition", "assignee_id", "values", "status", "version", "completed_by_id", "completed_at", "completion_note"
    ))
    for row in rows:
        row["completed_at"] = row["completed_at"].isoformat() if row["completed_at"] else None
    return rows


def workflow_checksum(experiment):
    return hashlib.sha256(json.dumps(workflow_snapshot(experiment), sort_keys=True).encode()).hexdigest()


class WorkflowStepUpdate(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["save", "complete", "assign"])
    expected_version = serializers.IntegerField(min_value=1)
    values = serializers.JSONField(required=False)
    assignee = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    note = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    confirmed = serializers.BooleanField(required=False, default=False)


@transaction.atomic
def update_step(*, experiment, position, actor, data):
    # Every workflow mutation and experiment transition locks this same row first.
    experiment = Experiment.objects.select_for_update().get(pk=experiment.pk)
    if not user_can_notebook(actor, experiment.notebook, "write"):
        raise PermissionDenied("You cannot edit this experiment workflow.")
    if experiment.status not in {Experiment.STATUS_DRAFT, Experiment.STATUS_IN_PROGRESS}:
        raise ValidationError("Only draft or in-progress experiments can change workflow steps.")
    step = experiment.workflow_steps.filter(position=position).first()
    if not step:
        raise ValidationError("Workflow step not found.")
    if step.status == "COMPLETED":
        raise ValidationError("Completed workflow steps are immutable. Clone the experiment to repeat or correct the workflow.")
    if data["expected_version"] != step.version:
        raise ValidationError("This step changed. Reload the experiment before saving; your input has not been applied.")
    before = workflow_snapshot(experiment)[position - 1]
    operation = data["operation"]
    if operation == "assign":
        if "assignee" not in data or not data["note"].strip():
            raise ValidationError("Select an assignee and provide a reason for the assignment change.")
        step.assignee = validate_assignee(data["assignee"], experiment.notebook)
        if step.assignee:
            experiment.assignees.add(step.assignee)
    else:
        if experiment.workflow_steps.filter(position__lt=position).exclude(status="COMPLETED").exists():
            raise ValidationError("Complete the preceding steps first.")
        if step.assignee_id and actor.pk != step.assignee_id and actor.pk != experiment.notebook.owner_id and not is_admin(actor):
            raise PermissionDenied("Only the assigned person, notebook owner, or administrator can record this step.")
        step.values = validate_values(step.definition, data.get("values", step.values), complete=operation == "complete")
        if operation == "complete":
            if step.assignee_id is None:
                raise ValidationError("Assign a responsible person before completing the step.")
            validate_assignee(step.assignee_id, experiment.notebook)
            if not data["confirmed"] or not data["note"].strip():
                raise ValidationError("Confirm the completion criteria and enter a completion note.")
            step.status = "COMPLETED"
            step.completed_by = actor
            step.completed_at = timezone.now()
            step.completion_note = data["note"]
        if experiment.status == Experiment.STATUS_DRAFT:
            experiment.status = Experiment.STATUS_IN_PROGRESS
    step.version += 1
    step.save()
    experiment.save(update_fields=["status", "updated_at"])
    record_audit_event(entity=experiment, action=f"EXPERIMENT_WORKFLOW_{operation.upper()}", actor=actor,
                       reason=data["note"], before=before, after=workflow_snapshot(experiment)[position - 1])
    if operation == "complete":
        following = experiment.workflow_steps.filter(position=position + 1).select_related("assignee").first()
        if following and following.assignee:
            from .services import notify_experiment
            notify_experiment(experiment, actor, [following.assignee], f"Workflow step ready: {following.definition['name']}", experiment.title)
    if operation == "assign" and step.assignee:
        from .services import notify_experiment
        notify_experiment(experiment, actor, [step.assignee], f"Workflow step assigned: {step.definition['name']}", experiment.title)
    return step
