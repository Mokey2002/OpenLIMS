"""Fictional submissions shared by the requester portal and the lab workspace."""
from datetime import timedelta
from hashlib import sha256
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from assistant.models import BarcodeLabel
from notifications.models import Notification
from pipelines.models import AnalysisDefinition, PipelineTemplate, PipelineTemplateStep, ProcedureDefinition
from pipelines.services import sync_pipeline_step_from_work_item
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleAccession, SampleCustodyEvent
from workflow_requests.models import AssayRequestType, WorkflowRequest, WorkflowRequestItem, WorkflowRequestReport
from workflow_requests.services import approve_request


DEMO_REQUESTER_USERNAME = "demo-requester"
DEMO_REQUESTER_EMAIL = "demo-requester@example.invalid"
DEMO_PROJECT_CODE = "PRJ-REQUESTER-DEMO"
DEMO_PROJECT_DESCRIPTION = "Fictional requester submissions, sample receipt, and report release."
PENDING_REQUEST_NUMBER = "SUB-DEMO-0001"
COMPLETED_REQUEST_NUMBER = "SUB-DEMO-0002"
TEST_CODE = "DEMO_SAMPLE_CONDITION"
TEST_NAME = "Sample condition check"


def _prepare_test(project, director):
    analysis, _ = AnalysisDefinition.objects.get_or_create(
        code=TEST_CODE,
        defaults={
            "name": TEST_NAME,
            "required_fields": [{"key": "packaging_intact", "value_type": Result.VALUE_TYPE_BOOLEAN}],
            "created_by": director,
        },
    )
    procedure, _ = ProcedureDefinition.objects.get_or_create(
        code=TEST_CODE, version="1", defaults={"name": TEST_NAME, "analysis": analysis, "created_by": director},
    )
    template, _ = PipelineTemplate.objects.get_or_create(
        code=TEST_CODE, defaults={"name": TEST_NAME, "default_project": project, "created_by": director},
    )
    if template.default_project_id != project.pk:
        raise CommandError(f"{TEST_CODE} already belongs to another workflow template.")
    PipelineTemplateStep.objects.get_or_create(
        template=template, position=1, defaults={"procedure": procedure, "requires_qc": True},
    )
    request_type, _ = AssayRequestType.objects.get_or_create(
        code=TEST_CODE,
        defaults={
            "name": TEST_NAME,
            "description": "Demo test for documenting the condition of sample packaging.",
            "form_schema": {
                "properties": {"handling_notes": {"type": "string", "title": "Handling notes"}},
            },
            "default_pipeline": template,
            "project": project,
            "created_by": director,
            "portal_enabled": True,
        },
    )
    if request_type.project_id != project.pk or request_type.default_pipeline_id != template.pk:
        raise CommandError(f"{TEST_CODE} already belongs to another request type.")
    return request_type


def _release_sample_report(workflow_request, item, director, technician):
    barcode = item.submission_barcode
    sample = Sample.objects.create(
        sample_id=barcode,
        project=workflow_request.project,
        sample_type="DEMO_SUBMISSION",
        created_by=technician,
    )
    BarcodeLabel.objects.create(sample=sample, template="ACCESSION_SAMPLE", barcode=barcode)
    receipt = SampleCustodyEvent.objects.create(
        sample=sample,
        action=SampleCustodyEvent.ACTION_RECEIVE,
        scanned_code=barcode,
        performed_by=technician,
        reason="Received the sealed example container for the requester portal demo.",
    )
    SampleAccession.objects.create(sample=sample, receipt=receipt)
    item.sample = sample
    item.save(update_fields=["sample", "updated_at"])

    workflow_request, _, runs = approve_request(
        workflow_request=workflow_request,
        actor=director,
        reason="Approved the fictional sample inspection.",
    )
    work = runs[0].steps.get().work_item
    Result.objects.create(
        work_item=work, key="packaging_intact", value_type=Result.VALUE_TYPE_BOOLEAN,
        value_boolean=True, entered_by=technician, qc_passed=True, qc_status=Result.QC_APPROVED,
    )
    reviewed_at = timezone.now()
    work.status = WorkItem.STATUS_COMPLETED
    work.qc_status = WorkItem.QC_APPROVED
    work.reviewed_by = director
    work.reviewed_at = reviewed_at
    work.review_note = "Approved the demo packaging inspection."
    work.save(update_fields=["status", "qc_status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    sync_pipeline_step_from_work_item(work, actor=director)
    item.status = "COMPLETED"
    item.save(update_fields=["status", "updated_at"])
    sample.status = Sample.STATUS_REPORTED
    sample.status_changed_at = reviewed_at
    sample.save(update_fields=["status", "status_changed_at", "updated_at"])
    workflow_request.status = WorkflowRequest.STATUS_COMPLETED
    workflow_request.completed_at = timezone.now()
    workflow_request.save(update_fields=["status", "completed_at", "updated_at"])

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("OpenLIMS demo sample condition report")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, 780, "Sample condition report")
    text = pdf.beginText(48, 746)
    text.setFont("Helvetica", 11)
    text.setLeading(18)
    for line in (
        "OpenLIMS demonstration data",
        f"Request: {workflow_request.request_number}",
        f"Sample reference: {item.submission_reference}",
        "Inspection result: Packaging intact",
        "Report released by the lab director",
    ):
        text.textLine(line)
    pdf.drawText(text)
    pdf.save()
    content = buffer.getvalue()
    report = WorkflowRequestReport(
        request=workflow_request, title="Sample condition report", checksum_sha256=sha256(content).hexdigest(),
        uploaded_by=technician, approved=True, approved_by=director, approved_at=workflow_request.completed_at,
    )
    report.file.save(f"{workflow_request.request_number}-report.pdf", ContentFile(content))


@transaction.atomic
def seed_requester_demo(*, director, technician):
    requester, created = get_user_model().objects.get_or_create(
        username=DEMO_REQUESTER_USERNAME,
        defaults={
            "email": DEMO_REQUESTER_EMAIL,
            "first_name": "Riley",
            "last_name": "Requester",
            "password": make_password(None),
        },
    )
    if created:
        requester.groups.add(Group.objects.get_or_create(name="requester")[0])
    elif (requester.email != DEMO_REQUESTER_EMAIL or requester.is_staff or requester.is_superuser
          or set(requester.groups.values_list("name", flat=True)) != {"requester"}):
        raise CommandError(f"{DEMO_REQUESTER_USERNAME} already belongs to another account.")

    project, _ = Project.objects.get_or_create(
        code=DEMO_PROJECT_CODE,
        defaults={"name": "Requester Portal Demo", "description": DEMO_PROJECT_DESCRIPTION},
    )
    if project.description != DEMO_PROJECT_DESCRIPTION:
        raise CommandError(f"{DEMO_PROJECT_CODE} already belongs to another project.")
    project.members.add(requester, director, technician)
    request_type = _prepare_test(project, director)
    now = timezone.now()
    defaults = {
        "requester": requester,
        "project": project,
        "request_type": request_type,
        "status": WorkflowRequest.STATUS_SUBMITTED,
        "assigned_pipeline": request_type.default_pipeline,
        "submitted_at": now,
        "due_at": now + timedelta(hours=request_type.sla_hours),
    }
    for number, title, reference in (
        (PENDING_REQUEST_NUMBER, "Inspect incoming sample packaging", "Delivery A"),
        (COMPLETED_REQUEST_NUMBER, "Completed sample condition check", "Delivery B"),
    ):
        workflow_request, created = WorkflowRequest.objects.get_or_create(
            request_number=number,
            defaults={**defaults, "title": title, "form_data": {"handling_notes": "Fictional demo sample."}},
        )
        if workflow_request.requester_id != requester.pk or workflow_request.project_id != project.pk:
            raise CommandError(f"{number} already belongs to another workflow request.")
        if created:
            item = WorkflowRequestItem.objects.create(request=workflow_request, submission_reference=reference)
            if number == COMPLETED_REQUEST_NUMBER:
                _release_sample_report(workflow_request, item, director, technician)
        if number == PENDING_REQUEST_NUMBER:
            Notification.objects.get_or_create(
                user=director,
                title="Requester portal demo ready",
                defaults={
                    "message": f"{PENDING_REQUEST_NUMBER} is ready for receipt. {COMPLETED_REQUEST_NUMBER} has a released report.",
                    "link": f"/workflow-requests?request={workflow_request.public_id}",
                },
            )
