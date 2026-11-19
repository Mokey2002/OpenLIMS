import re
from uuid import UUID

from rest_framework.exceptions import NotFound

from .models import WorkflowRequest, WorkflowRequestItem
from .permissions import user_can_operate_request


SUBMISSION_BARCODE = re.compile(
    rf"{WorkflowRequestItem.SUBMISSION_BARCODE_PREFIX}([0-9a-f]{{32}})", re.IGNORECASE,
)


def submission_for_barcode(code, user, *, lock=False):
    match = SUBMISSION_BARCODE.fullmatch(code)
    if not match:
        return None
    submissions = WorkflowRequestItem.objects.exclude(submission_reference="").select_related("request__project")
    item = submissions.filter(public_id=UUID(hex=match[1])).first()
    if item and lock:
        # Registering a tube and approving or closing its request must be serialized.
        workflow_request = WorkflowRequest.objects.select_for_update().get(pk=item.request_id)
        item = submissions.get(pk=item.pk)
        item.request = workflow_request
    if (
        not item
        or not user_can_operate_request(user, item.request)
        or item.request.status not in (WorkflowRequest.STATUS_SUBMITTED, WorkflowRequest.STATUS_TRIAGE)
    ):
        raise NotFound("Submission barcode unavailable. Check the code or contact the project owner.")
    return item


def submission_context(item):
    return {
        "reference": item.submission_reference,
        "request_number": item.request.request_number,
        "request_public_id": str(item.request.public_id),
        "project": item.request.project_id,
        "project_name": item.request.project.name,
    }


def registered_submission(sample, barcode, user):
    if not SUBMISSION_BARCODE.fullmatch(barcode):
        return None
    item = (
        sample.workflow_request_items.exclude(submission_reference="")
        .select_related("request__project").first()
    )
    return submission_context(item) if item and user_can_operate_request(user, item.request) else None
