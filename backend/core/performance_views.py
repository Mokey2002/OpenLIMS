from django.db.models import F, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import InventoryAlert
from notebook.models import Experiment
from notebook.permissions import notebooks_for_user
from notifications.models import Notification
from results.models import WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample
from settings_app.models import SystemSettings
from workflow_requests.models import WorkflowRequest
from workflow_requests.permissions import workflow_requests_for_user

from .serializers import MeSerializer


ACTIVE_WORK_STATUSES = [
    WorkItem.STATUS_PENDING,
    WorkItem.STATUS_IN_PROGRESS,
    WorkItem.STATUS_FAILED,
]
ACTIVE_REQUEST_STATUSES = [
    WorkflowRequest.STATUS_DRAFT,
    WorkflowRequest.STATUS_SUBMITTED,
    WorkflowRequest.STATUS_TRIAGE,
    WorkflowRequest.STATUS_APPROVED,
    WorkflowRequest.STATUS_IN_PROGRESS,
]
ACTIVE_EXPERIMENT_STATUSES = [
    Experiment.STATUS_DRAFT,
    Experiment.STATUS_IN_PROGRESS,
    Experiment.STATUS_COMPLETED,
]
ATTENTION_QC_STATUSES = [
    WorkItem.QC_PENDING_REVIEW,
    WorkItem.QC_RERUN_REQUIRED,
]


class SessionBootstrapView(APIView):
    """Return the small, stable payload needed by the application shell.

    This replaces three separate startup requests for the current user,
    feature flags, and notification state.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings_obj = SystemSettings.load()
        return Response(
            {
                "user": MeSerializer(request.user).data,
                "feature_flags": settings_obj.feature_flags,
                "unread_notification_count": Notification.objects.filter(
                    user=request.user,
                    is_read=False,
                ).count(),
            }
        )


class MyWorkSummaryView(APIView):
    """Server-side aggregation for the My Work landing page.

    The previous implementation paged through every visible work item,
    workflow request, notification, inventory alert, and experiment, then
    filtered those records in React. This endpoint keeps response size and
    request count bounded as the laboratory database grows.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        user = request.user
        settings_obj = SystemSettings.load()

        allowed_samples = get_sample_access_queryset(
            Sample.objects.only("id"),
            user,
        )
        visible_work = WorkItem.objects.filter(sample__in=allowed_samples)

        assigned_work = visible_work.filter(
            assigned_to=user,
            status__in=ACTIVE_WORK_STATUSES,
        )
        active_requests = workflow_requests_for_user(user).filter(
            status__in=ACTIVE_REQUEST_STATUSES,
        )

        assigned_rows = list(
            assigned_work.order_by("due_at", "-created_at").values(
                "id",
                "name",
                "status",
                "qc_status",
                "due_at",
                sample_code=F("sample__sample_id"),
                project_code=F("sample__project__code"),
            )[:12]
        )

        overdue_work = list(
            assigned_work.filter(due_at__lt=now)
            .order_by("due_at")
            .values(
                "id",
                "name",
                "due_at",
                sample_code=F("sample__sample_id"),
                project_code=F("sample__project__code"),
            )[:8]
        )
        overdue_requests = list(
            active_requests.filter(due_at__lt=now)
            .order_by("due_at")
            .values("id", "request_number", "title", "due_at")[:8]
        )

        overdue = [
            {
                "key": f"work-{item['id']}",
                "type": "Work item",
                "name": item["name"],
                "context": f"{item['sample_code'] or 'Sample'} · {item['project_code'] or 'No project'}",
                "due_at": item["due_at"],
                "to": "/work-queue",
            }
            for item in overdue_work
        ] + [
            {
                "key": f"request-{item['id']}",
                "type": "Request",
                "name": item["title"] or item["request_number"],
                "context": item["request_number"],
                "due_at": item["due_at"],
                "to": "/workflow-requests",
            }
            for item in overdue_requests
        ]
        overdue.sort(key=lambda item: item["due_at"])
        overdue = overdue[:8]

        experiment_count = 0
        if settings_obj.notebook_enabled:
            experiment_count = (
                Experiment.objects.filter(
                    notebook__in=notebooks_for_user(user),
                    status__in=ACTIVE_EXPERIMENT_STATUSES,
                )
                .filter(Q(assignees=user) | Q(created_by=user))
                .distinct()
                .count()
            )

        notifications = list(
            Notification.objects.filter(user=user, is_read=False)
            .order_by("-created_at")
            .values("id", "title", "message", "link", "created_at")[:5]
        )

        summary = {
            "assigned": assigned_work.count(),
            "requests": active_requests.count(),
            "experiments": experiment_count,
            "qc": visible_work.filter(qc_status__in=ATTENTION_QC_STATUSES).count(),
            "inventory_alerts": InventoryAlert.objects.filter(
                status=InventoryAlert.STATUS_OPEN
            ).count(),
            "unread_notifications": Notification.objects.filter(
                user=user,
                is_read=False,
            ).count(),
            "overdue": len(overdue),
        }

        return Response(
            {
                "summary": summary,
                "assigned_work": assigned_rows,
                "overdue": overdue,
                "notifications": notifications,
                "notebook_enabled": settings_obj.notebook_enabled,
            }
        )
