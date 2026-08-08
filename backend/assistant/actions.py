from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from alignments.models import AlignmentJob
from alignments.serializers import AlignmentJobSerializer
from alignments.tasks import run_alignment_job
from blast.models import BlastJob
from blast.serializers import BlastJobSerializer
from blast.tasks import run_blast_job_task
from events.models import Event
from imports.models import ImportJob
from imports.tasks import process_import_job
from migration_toolkit.models import MigrationJob
from migration_toolkit.services import suggest_field_mappings
from samples.access import get_sample_access_queryset, validate_sample_project_assignment
from samples.models import Sample
from sequences.models import Sequence

from .models import AssistantAction
from .tasks import generate_assistant_report


ACTION_TYPES = {choice[0] for choice in AssistantAction.ACTION_CHOICES}


class AssistantActionError(Exception):
    pass


def serialize_action(action):
    return {
        "id": str(action.id),
        "type": action.action_type,
        "summary": action.summary,
        "status": action.status,
        "confirmation_token": str(action.confirmation_token),
        "expires_at": action.expires_at.isoformat(),
        "result": action.result,
        "error_message": action.error_message,
    }


def _audit(action, event_action, payload=None):
    Event.objects.create(
        entity_type="AssistantAction",
        entity_id=str(action.id),
        action=event_action,
        actor=action.requested_by,
        payload={
            "assistant_action_id": str(action.id),
            "action_type": action.action_type,
            "idempotency_key": str(action.idempotency_key),
            **(payload or {}),
        },
    )


def propose_action(user, action_type, summary, payload):
    if action_type not in ACTION_TYPES:
        raise AssistantActionError(f"Unsupported assistant action: {action_type}")

    action = AssistantAction.objects.create(
        requested_by=user,
        action_type=action_type,
        summary=str(summary or action_type)[:500],
        payload=payload or {},
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    _audit(action, "ASSISTANT_ACTION_PROPOSED")
    return action


def _user_can_execute(user):
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["admin", "tech"]).exists()


def _assert_sample_access(user, sample_id):
    if sample_id is None:
        return
    allowed = get_sample_access_queryset(
        Sample.objects.filter(id=sample_id),
        user,
    ).exists()
    if not allowed:
        raise AssistantActionError("You do not have access to the selected sample.")


def _run_blast(action):
    serializer = BlastJobSerializer(data=action.payload)
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError as exc:
        raise AssistantActionError(str(exc.detail)) from exc

    query_sequence = serializer.validated_data["query_sequence"]
    _assert_sample_access(action.requested_by, query_sequence.sample_id)

    if serializer.validated_data.get("project") is None:
        serializer.validated_data["project"] = query_sequence.project

    job = BlastJob.objects.create(
        **serializer.validated_data,
        created_by=action.requested_by,
        status=BlastJob.STATUS_PENDING,
    )
    transaction.on_commit(lambda: run_blast_job_task.delay(job.id))
    return AssistantAction.STATUS_QUEUED, {
        "blast_job_id": job.id,
        "url": "/blast",
    }


def _run_alignment(action):
    serializer = AlignmentJobSerializer(data=action.payload)
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError as exc:
        raise AssistantActionError(str(exc.detail)) from exc

    sequence_ids = serializer.validated_data.pop("sequence_ids")
    sequences = list(
        Sequence.objects.select_related("sample", "project")
        .filter(id__in=sequence_ids)
        .order_by("id")
    )

    sample_ids = {sequence.sample_id for sequence in sequences if sequence.sample_id}
    allowed_sample_ids = set(
        get_sample_access_queryset(
            Sample.objects.filter(id__in=sample_ids),
            action.requested_by,
        ).values_list("id", flat=True)
    )
    if sample_ids - allowed_sample_ids:
        raise AssistantActionError("You do not have access to every selected sequence.")

    if serializer.validated_data.get("project") is None:
        project_ids = {sequence.project_id for sequence in sequences if sequence.project_id}
        if len(project_ids) == 1:
            serializer.validated_data["project_id"] = next(iter(project_ids))

    job = AlignmentJob.objects.create(
        **serializer.validated_data,
        created_by=action.requested_by,
        status="PENDING",
        input_fasta="",
        aligned_fasta="",
        summary={},
        error_message="",
    )
    job.sequences.set(sequences)

    Event.objects.create(
        entity_type="AlignmentJob",
        entity_id=str(job.id),
        action="ALIGNMENT_QUEUED",
        actor=action.requested_by,
        payload={
            "alignment_job_id": job.id,
            "name": job.name,
            "tool": job.tool,
            "project_id": job.project_id,
            "sequence_ids": sequence_ids,
            "source": "assistant_confirmation",
        },
    )
    transaction.on_commit(lambda: run_alignment_job.delay(job.id))
    return AssistantAction.STATUS_QUEUED, {
        "alignment_job_id": job.id,
        "url": "/alignments",
    }


def _create_migration_mappings(action):
    job_id = action.payload.get("migration_job_id")
    job = (
        MigrationJob.objects.select_related("profile", "project")
        .filter(id=job_id)
        .first()
    )
    if not job or not job.uploaded_file:
        raise AssistantActionError("The migration job or its uploaded file no longer exists.")

    if job.project_id:
        validate_sample_project_assignment(action.requested_by, job.project)

    with job.uploaded_file.open("rb") as uploaded_file:
        summary = suggest_field_mappings(
            profile=job.profile,
            uploaded_file=uploaded_file,
        )

    return AssistantAction.STATUS_COMPLETED, {
        "migration_job_id": job.id,
        "mapping_summary": summary,
        "url": f"/data-migration/jobs/{job.id}",
    }


def _queue_import(action):
    job_id = action.payload.get("import_job_id")
    job = (
        ImportJob.objects.select_related("project", "instrument")
        .filter(id=job_id)
        .first()
    )
    if not job:
        raise AssistantActionError("The import job no longer exists.")
    if job.status != "PENDING":
        raise AssistantActionError(
            f"Import job #{job.id} is {job.status}; only PENDING jobs can be queued."
        )
    if not job.uploaded_file:
        raise AssistantActionError("The import job has no uploaded file.")
    if job.project_id:
        validate_sample_project_assignment(action.requested_by, job.project)

    job.progress_message = "Queued after assistant confirmation"
    job.save(update_fields=["progress_message"])
    transaction.on_commit(lambda: process_import_job.delay(job.id))

    return AssistantAction.STATUS_QUEUED, {
        "import_job_id": job.id,
        "url": "/imports",
    }


def _queue_report(action):
    transaction.on_commit(lambda: generate_assistant_report.delay(str(action.id)))
    return AssistantAction.STATUS_QUEUED, {
        "report_type": action.payload.get("report_type", "OPERATIONS_SUMMARY"),
        "url": "/reports",
    }


EXECUTORS = {
    AssistantAction.ACTION_RUN_BLAST: _run_blast,
    AssistantAction.ACTION_RUN_ALIGNMENT: _run_alignment,
    AssistantAction.ACTION_CREATE_MIGRATION_MAPPINGS: _create_migration_mappings,
    AssistantAction.ACTION_QUEUE_REPORT: _queue_report,
    AssistantAction.ACTION_QUEUE_IMPORT: _queue_import,
}


def confirm_action(token, user):
    try:
        with transaction.atomic():
            action = (
                AssistantAction.objects.select_for_update()
                .get(confirmation_token=token, requested_by=user)
            )

            if action.status in [
                AssistantAction.STATUS_QUEUED,
                AssistantAction.STATUS_COMPLETED,
            ]:
                return action

            if action.status != AssistantAction.STATUS_PROPOSED:
                raise AssistantActionError(
                    f"This action cannot be confirmed because it is {action.status}."
                )

            if action.is_expired:
                action.status = AssistantAction.STATUS_EXPIRED
                action.save(update_fields=["status", "updated_at"])
                _audit(action, "ASSISTANT_ACTION_EXPIRED")
                raise AssistantActionError("This confirmation expired. Ask the assistant to propose it again.")

            if not _user_can_execute(user):
                raise AssistantActionError(
                    "Only users in the tech or admin role can confirm assistant actions."
                )

            action.confirmed_at = timezone.now()
            executor = EXECUTORS[action.action_type]
            next_status, result = executor(action)

            action.status = next_status
            action.result = result
            action.error_message = ""
            action.executed_at = timezone.now()
            action.save(update_fields=[
                "status",
                "result",
                "error_message",
                "confirmed_at",
                "executed_at",
                "updated_at",
            ])
            _audit(action, "ASSISTANT_ACTION_CONFIRMED", {"result": result})
            return action
    except AssistantAction.DoesNotExist as exc:
        raise AssistantActionError("Confirmation token not found.") from exc


def cancel_action(token, user):
    with transaction.atomic():
        try:
            action = (
                AssistantAction.objects.select_for_update()
                .get(confirmation_token=token, requested_by=user)
            )
        except AssistantAction.DoesNotExist as exc:
            raise AssistantActionError("Confirmation token not found.") from exc

        if action.status == AssistantAction.STATUS_PROPOSED:
            action.status = AssistantAction.STATUS_CANCELLED
            action.save(update_fields=["status", "updated_at"])
            _audit(action, "ASSISTANT_ACTION_CANCELLED")

        return action
