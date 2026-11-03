"""Chat upload controls; uploaded contents never enter a model prompt."""
import hashlib
import io
import os
import re
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite, is_admin, is_tech
from core.upload_validators import validate_text_file, validate_uploaded_file
from imports.assistant_uploads import MARKER, digest, inspect_upload, read_file, report_csv, require_writer, validate_prepared
from imports.models import ImportJob, InstrumentProfile
from projects.models import Project
from .actions import propose_action, serialize_action
from .lab_helpers import response
from .models import AssistantAction
from .natural_requests import normalize_request
from .sample_operations import _project_label, _resolve_project


def accessible_job(pk, user):
    job = get_object_or_404(ImportJob.objects.select_related("project", "instrument"), pk=pk)
    if (not job.summary.get(MARKER) or not (is_admin(user) or job.uploaded_by_id == user.pk)
            or not job.project_id or not (is_admin(user) or job.project.members.filter(pk=user.pk).exists())):
        raise NotFound("Import unavailable.")
    return job


def latest_action(job, user):
    actions = AssistantAction.objects.filter(requested_by=user, action_type="QUEUE_IMPORT", payload__import_job_id=job.pk)
    action_id = job.summary.get("queued_by_action_id") or job.summary.get("prepared_action_id")
    return actions.filter(pk=action_id).first() if action_id else actions.order_by("-created_at").first()


def public_job(job, user):
    frozen = job.summary[MARKER]
    action = latest_action(job, user)
    pending = bool(job.summary.get("awaiting_assistant_confirmation"))
    return {"id": job.pk, "instrument": frozen["config"]["code"], "project": job.project.code, "run_id": job.run_id,
            "filename": frozen.get("filename", os.path.basename(job.uploaded_file.name)), "status": job.status,
            "state": "awaiting_confirmation" if pending else "queued_or_running" if job.status == "PENDING" else job.status.lower(),
            "counts": job.summary.get("receipt", frozen["counts"]), "planned_counts": frozen["counts"],
            "mappings": frozen["config"]["mappings"], "unmapped_columns": frozen["unmapped_columns"],
            "sample_id_column": frozen["config"]["sample_id_column"], "delimiter": frozen["config"]["delimiter"],
            "row_report": job.summary.get("row_report", [])[:50], "report_total": frozen["counts"]["rows_received"],
            "download_url": f"/api/assistant/instrument-imports/{job.pk}/report/",
            "error": job.summary.get("error") or job.summary.get("queue_error", ""), "action": serialize_action(action) if action else None,
            "can_revalidate": bool(job.uploaded_by_id == user.pk and user.is_active and (is_admin(user) or is_tech(user)) and job.status in {"FAILED", "PENDING"}),
            "can_resume": bool(job.uploaded_by_id == user.pk and user.is_active and (is_admin(user) or is_tech(user)) and
                (job.status == "PENDING" and not pending or job.status == "COMPLETED" and action and action.status == "QUEUED"))}


def job_reply(job, user):
    data = public_job(job, user)
    result = response(f"Instrument import #{job.pk}: {data['state'].replace('_', ' ')}. Review the mapping and row receipt in chat.",
                      context={"instrument_import_job_id": job.pk}, instrument_import_job=data)
    action = latest_action(job, user)
    if action and not action.is_expired and action.status == "PROPOSED":
        result["pending_action"] = serialize_action(action)
    return result


def prepare(job, analysis, user, skip_duplicates):
    if not analysis["accepted"]:
        raise ValidationError({"detail": "No rows are importable. Correct the rejected rows and validate again.", "validation": {
            "counts": analysis["counts"], "row_report": analysis["report"][:50]}})
    # Callers lock associated actions before the job, matching confirmation order.
    AssistantAction.objects.filter(requested_by=user, action_type="QUEUE_IMPORT", payload__import_job_id=job.pk,
        status__in=["PROPOSED", "QUEUED"]).update(status="CANCELLED", error_message="Replaced by a freshly validated preview.")
    frozen = {key: analysis[key] for key in ["config", "file_sha256", "plan_digest", "counts", "unmapped_columns", "csv_metadata"]}
    frozen.update(owner_id=user.pk, project_id=job.project_id, instrument_id=job.instrument_id, run_id=job.run_id, skip_duplicates=skip_duplicates)
    frozen["filename"] = getattr(job, "source_filename", job.summary.get(MARKER, {}).get("filename", os.path.basename(job.uploaded_file.name)))
    job.summary = {MARKER: frozen, "awaiting_assistant_confirmation": True, "row_report": analysis["report"]}
    job.status, job.progress_current, job.progress_total = "PENDING", 0, analysis["counts"]["rows_received"]
    job.progress_message = "Validated; awaiting confirmation in chat"
    job.save()
    counts = analysis["counts"]
    preview = {"title": "Validated instrument import", "operation": "Import measurement rows", "instrument_import": True,
        "import_job_id": job.pk, "project": _project_label(job.project), "requested_user": {"username": user.username},
        "records_affected": counts["rows_to_import"], "current_values": {"Measurements": "Not imported yet"},
        "proposed_values": {"Instrument": job.instrument.code, "Run ID": job.run_id, "Rows received": counts["rows_received"],
            "Rows to import": counts["rows_to_import"], "Rows rejected": counts["rows_rejected"], "Exact repeats skipped": counts["duplicates_skipped"],
            "Expected results": counts["expected_results"]},
        "records": [{"label": f"Data row {row['row']}: {row['sample_id']}", "current": {"Validation": row["status"]},
                     "proposed": {"Results": row["result_cells"], "Note": row["reason"]}} for row in analysis["report"][:20]],
        "warnings": ["Preview shows the first 20 rows; the downloadable report accounts for every data row.",
                     "Unmapped columns are ignored: " + ", ".join(analysis["unmapped_columns"])] if analysis["unmapped_columns"] else ["Preview shows the first 20 rows; the downloadable report accounts for every data row."]}
    action = propose_action(user, "QUEUE_IMPORT", f"Import {counts['rows_to_import']} validated rows from {job.instrument.code}, run {job.run_id}",
                            {"import_job_id": job.pk, "prepared_digest": digest(frozen), "preview": preview})
    job.summary["prepared_action_id"] = str(action.pk)
    job.save(update_fields=["summary"])
    return job_reply(job, user)


class UploadSerializer(serializers.Serializer):
    instrument = serializers.IntegerField(min_value=1, max_value=2**63-1)
    project = serializers.IntegerField(min_value=1, max_value=2**63-1)
    run_id = serializers.CharField(max_length=128)
    uploaded_file = serializers.FileField(max_length=255)
    skip_duplicates = serializers.BooleanField(default=True)

    def to_internal_value(self, data):
        if set(data) - set(self.fields):
            raise ValidationError({"detail": "Only the displayed import fields are supported."})
        if hasattr(data, "getlist") and any(len(data.getlist(key)) != 1 for key in data):
            raise ValidationError({"detail": "Supply each import field and file exactly once."})
        return super().to_internal_value(data)

    def validate_run_id(self, value):
        if any(ord(char) < 32 for char in value):
            raise ValidationError("Use a run ID without control characters.")
        return value


class InstrumentImportUploadView(APIView):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=UploadSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        instrument = get_object_or_404(InstrumentProfile, pk=data["instrument"])
        project = Project.objects.filter(pk=data["project"]).first()
        upload = data["uploaded_file"]
        saved_file = None
        try:
            require_writer(request.user, project)
            validate_uploaded_file(upload, [".csv", ".tsv", ".txt"])
            validate_text_file(upload)
            raw = upload.read()
            upload.seek(0)
            previous = ImportJob.objects.filter(instrument=instrument, run_id=data["run_id"]).first()
            if previous and (previous.status in {"COMPLETED", "RUNNING"} or previous.status == "PENDING" and previous.summary.get("queued_by_action_id")):
                frozen = previous.summary.get(MARKER, {})
                if (previous.uploaded_by_id != request.user.pk or previous.project_id != project.pk
                        or frozen.get("file_sha256") != hashlib.sha256(raw).hexdigest() or frozen.get("skip_duplicates") != data["skip_duplicates"]):
                    return Response({"detail": "This instrument/run ID is already reserved for a different import. Use a different run ID."}, status=409)
                return Response(job_reply(previous, request.user))
            analysis = inspect_upload(raw, instrument, project, request.user, data["skip_duplicates"])
            if not analysis["accepted"]:
                raise ValidationError({"detail": "No rows are importable. Correct the file and validate again.",
                                       "validation": {"counts": analysis["counts"], "row_report": analysis["report"][:50]}})
            with transaction.atomic():
                job, created = ImportJob.objects.get_or_create(instrument=instrument, run_id=data["run_id"],
                    defaults={"project": project, "uploaded_by": request.user, "source_type": "UPLOAD"})
                list(AssistantAction.objects.select_for_update().filter(requested_by=request.user,
                     action_type="QUEUE_IMPORT", payload__import_job_id=job.pk).order_by("pk"))
                job = ImportJob.objects.select_for_update(of=("self",)).select_related("project", "instrument").get(pk=job.pk)
                if not created:
                    frozen = job.summary.get(MARKER, {})
                    if (job.uploaded_by_id != request.user.pk or job.project_id != project.pk or frozen.get("file_sha256") != analysis["file_sha256"]
                            or frozen.get("skip_duplicates") != data["skip_duplicates"]):
                        return Response({"detail": "This instrument/run ID is already reserved for a different import. Use a different run ID."}, status=409)
                    if job.status == "COMPLETED" or not job.summary.get("awaiting_assistant_confirmation") and job.status == "PENDING":
                        return Response(job_reply(job, request.user))
                    action = latest_action(job, request.user)
                    if (job.status == "PENDING" and action and action.status == "PROPOSED" and not action.is_expired
                            and frozen["config"] == analysis["config"] and frozen["plan_digest"] == analysis["plan_digest"]):
                        return Response(job_reply(job, request.user))
                else:
                    job.source_filename = os.path.basename(upload.name)
                    job.uploaded_file.save(f"assistant-{uuid.uuid4().hex}{os.path.splitext(upload.name)[1].lower()}", ContentFile(raw), save=False)
                    saved_file = (job.uploaded_file.storage, job.uploaded_file.name)
                result = prepare(job, analysis, request.user, data["skip_duplicates"])
            return Response(result, status=201 if created else 200)
        except (ValueError, DjangoValidationError) as exc:
            if saved_file:
                saved_file[0].delete(saved_file[1])
            raise ValidationError({"detail": str(exc)}) from exc
        except Exception:
            if saved_file:
                saved_file[0].delete(saved_file[1])
            raise


class InstrumentImportStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        return Response(public_job(accessible_job(pk, request.user), request.user))


class InstrumentImportReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.BINARY)
    def get(self, request, pk):
        job = accessible_job(pk, request.user)
        return FileResponse(io.BytesIO(report_csv(job)), as_attachment=True, filename=f"instrument-import-{pk}.csv", content_type="text/csv")


class InstrumentImportControlView(APIView):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk, operation):
        if not isinstance(request.data, dict) or request.data:
            raise ValidationError({"detail": "This control accepts no additional fields. Revalidate the stored file and policy."})
        job = accessible_job(pk, request.user)
        try:
            require_writer(request.user, job.project)
            if job.uploaded_by_id != request.user.pk:
                raise ValueError("Only the original uploader can revalidate or resume this import.")
            with transaction.atomic():
                list(AssistantAction.objects.select_for_update().filter(requested_by=request.user,
                     action_type="QUEUE_IMPORT", payload__import_job_id=job.pk).order_by("pk"))
                job = ImportJob.objects.select_for_update(nowait=True).get(pk=pk)
                if operation == "resume":
                    action = latest_action(job, request.user)
                    if job.status == "COMPLETED":
                        if action and action.status == "QUEUED":
                            from imports.assistant_uploads import deliver_import
                            transaction.on_commit(lambda: deliver_import(job.pk, str(action.pk)))
                        return Response(job_reply(job, request.user))
                    if (job.status != "PENDING" or job.summary.get("awaiting_assistant_confirmation") or not action
                            or action.status != "QUEUED" or job.summary.get("queued_by_action_id") != str(action.pk)):
                        raise ValueError("Only a previously confirmed queued import can be resumed.")
                    validate_prepared(job, request.user)
                    from imports.assistant_uploads import deliver_import
                    transaction.on_commit(lambda: deliver_import(job.pk, str(action.pk)))
                    result = job_reply(job, request.user)
                elif operation == "revalidate":
                    if job.status not in {"PENDING", "FAILED"}:
                        raise ValueError("This import is already running or completed. Check its receipt instead.")
                    analysis = inspect_upload(read_file(job), job.instrument, job.project, request.user, job.summary[MARKER]["skip_duplicates"])
                    result = prepare(job, analysis, request.user, job.summary[MARKER]["skip_duplicates"])
                else:
                    raise NotFound()
            return Response(result)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        except DatabaseError as exc:
            cause = exc.__cause__
            if getattr(cause, "sqlstate", None) == "55P03" or getattr(cause, "pgcode", None) == "55P03":
                return Response({"detail": "The import is being processed. Check its status again shortly."}, status=409)
            return Response({"detail": "Import controls are temporarily unavailable. Refresh the status or try again shortly."}, status=503)


def route_instrument_import(message, user, context=None):
    text = normalize_request(message)
    start = re.fullmatch(r'(?:import (?:instrument data|(?:this |a |an )?(?:sequencer|instrument) file)|upload (?:an? )?instrument file)(?: (?:into|in|to) project ("[^"\n]{1,128}"|[\w.:/-]{1,128}))?', text, re.I)
    if start:
        if not user.is_active or not (is_admin(user) or is_tech(user)):
            return response("Only an active Tech or Admin can prepare instrument imports.")
        project_id = None
        if start[1]:
            project, error = _resolve_project(start[1], user, write=True)
            if error:
                return response("Use an exact accessible project code to start the instrument upload.", clarification={"required": True})
            project_id = project.pk
        return response("Attach a CSV/TSV instrument export, choose its instrument and project, and enter the instrument run ID. Validate the file to review its mapping and row counts before confirming.", instrument_import_form={"project_id": project_id})
    explicit = re.fullmatch(r"(?:show|check) (?:instrument )?import(?: job)? #?([1-9]\d{0,17})(?: status)?", text, re.I)
    followup = re.fullmatch(r"(?:show|check) (?:the )?import status|how did the import go", text, re.I)
    if explicit or followup:
        pk = int(explicit[1]) if explicit else (context or {}).get("instrument_import_job_id")
        if type(pk) is not int or not 0 < pk < 2**63:
            return response("Which instrument import? Give its job number, or ask 'Show my instrument imports'.", clarification={"required": True})
        try:
            return job_reply(accessible_job(pk, user), user)
        except NotFound:
            return response("Import unavailable or no longer accessible.")
    if re.fullmatch(r"(?:show|list) my instrument imports", text, re.I):
        jobs = ImportJob.objects.filter(uploaded_by=user, summary__has_key=MARKER)
        if not is_admin(user):
            jobs = jobs.filter(project__members=user)
        jobs = list(jobs.select_related("instrument").order_by("-pk")[:8])
        return response("\n".join(f"#{job.pk}: {job.instrument.code}, run {job.run_id} — {job.status}" for job in jobs) or "No accessible instrument imports were found.",
                        suggestions=[f"Show instrument import #{job.pk}" for job in jobs])
    return None
