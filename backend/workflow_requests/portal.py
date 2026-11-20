import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import record_audit_event
from core.permissions import is_admin, is_requester_only
from events.kafka import queue_requester_event
from pipelines.models import PipelineRun
from projects.models import Project

from .files import report_download, submission_labels
from .models import AssayRequestType, WorkflowRequest, WorkflowRequestItem, WorkflowRequestReport
from .services import portal_form_schema, validate_submission_form


def available_projects(user):
    if is_admin(user) and not is_requester_only(user):
        return Project.objects.all()
    return Project.objects.filter(members=user)


def available_tests(projects):
    return AssayRequestType.objects.filter(
        Q(project__isnull=True) | Q(project__in=projects),
        active=True,
        portal_enabled=True,
        default_pipeline__active=True,
    )


class PortalSubmissionSerializer(serializers.Serializer):
    submission_id = serializers.UUIDField()
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    request_type = serializers.PrimaryKeyRelatedField(queryset=AssayRequestType.objects.none())
    title = serializers.CharField(max_length=255)
    sample_references = serializers.ListField(
        child=serializers.CharField(max_length=64),
        min_length=1,
        max_length=50,
    )
    form_data = serializers.DictField(required=False, default=dict)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            projects = available_projects(request.user)
            self.fields["project"].queryset = projects
            self.fields["request_type"].queryset = available_tests(projects)

    def validate_sample_references(self, references):
        if any(not reference.isprintable() for reference in references):
            raise serializers.ValidationError("Use printable characters in sample references.")
        if len({ref.casefold() for ref in references}) != len(references):
            raise serializers.ValidationError("Use a different reference for each sample.")
        return references

    def validate(self, attrs):
        request_type = attrs["request_type"]
        if request_type.project_id not in (None, attrs["project"].pk):
            raise serializers.ValidationError({"request_type": "Choose a test available for this project."})
        schema = request_type.form_schema
        properties, required = portal_form_schema(schema)
        data = attrs["form_data"]
        if len(json.dumps(data)) > 32000:
            raise serializers.ValidationError({"form_data": "Shorten the test details before submitting."})
        if data.keys() - (properties.keys() | set(required)):
            raise serializers.ValidationError({"form_data": "Use the fields configured for this test."})
        validate_submission_form(schema, data)
        for name, value in data.items():
            definition = properties.get(name, {})
            choices = definition.get("enum")
            if choices is not None and value not in choices:
                raise serializers.ValidationError({"form_data": {name: "Choose one of the available values."}})
            if definition.get("type") in {"number", "integer"} and isinstance(value, bool):
                raise serializers.ValidationError({"form_data": {name: "Enter a number."}})
        return attrs


class PortalRequestSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name")
    test_name = serializers.CharField(source="request_type.name")
    status = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowRequest
        fields = ("public_id", "request_number", "title", "project_name", "test_name", "status", "submitted_at")

    def get_status(self, obj):
        if obj.status in (WorkflowRequest.STATUS_APPROVED, WorkflowRequest.STATUS_IN_PROGRESS) and obj.has_runs:
            return WorkflowRequest.STATUS_IN_PROGRESS if obj.has_unfinished_runs else WorkflowRequest.STATUS_COMPLETED
        return obj.status


class PortalSubmissionSampleSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(source="submission_reference")
    barcode = serializers.CharField(source="submission_barcode")
    received_at = serializers.DateTimeField(source="submission_received_at")

    class Meta:
        model = WorkflowRequestItem
        fields = ("reference", "barcode", "received_at")


class PortalReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRequestReport
        fields = ("public_id", "title", "approved_at")


class PortalRequestDetailSerializer(PortalRequestSerializer):
    samples = PortalSubmissionSampleSerializer(source="submission_samples", many=True)
    reports = PortalReportSerializer(source="released_reports", many=True)

    class Meta(PortalRequestSerializer.Meta):
        fields = PortalRequestSerializer.Meta.fields + ("samples", "reports")


@method_decorator(never_cache, name="dispatch")
class RequesterPortalViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    requester_access = True
    lookup_field = "public_id"
    lookup_value_regex = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"

    def get_serializer_class(self):
        if self.action == "create":
            return PortalSubmissionSerializer
        if self.action == "retrieve":
            return PortalRequestDetailSerializer
        return PortalRequestSerializer

    def get_queryset(self):
        queryset = (
            WorkflowRequest.objects.filter(requester=self.request.user, project__in=available_projects(self.request.user))
            .exclude(status=WorkflowRequest.STATUS_DRAFT)
            .select_related("project", "request_type")
            .order_by("-created_at", "-pk")
        )
        if self.action in ("list", "retrieve"):
            runs = WorkflowRequestItem.objects.filter(request_id=OuterRef("pk"), pipeline_run__isnull=False)
            queryset = queryset.annotate(
                has_runs=Exists(runs),
                has_unfinished_runs=Exists(runs.exclude(pipeline_run__status=PipelineRun.STATUS_COMPLETED)),
            )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "items",
                    queryset=WorkflowRequestItem.objects.exclude(submission_reference="").select_related("sample__accession__receipt"),
                    to_attr="submission_samples",
                ),
                Prefetch("reports", queryset=WorkflowRequestReport.objects.filter(approved=True), to_attr="released_reports"),
            )
        return queryset

    @action(detail=False, methods=["get"])
    def catalog(self, request):
        projects = list(available_projects(request.user).order_by("name").values("id", "code", "name"))
        types = available_tests([project["id"] for project in projects]).values(
            "id", "project_id", "code", "name", "description", "form_schema",
        )
        return Response({"projects": projects, "tests": list(types) if projects else []})

    @transaction.atomic
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        public_id = values["submission_id"]
        request_type = values["request_type"]
        submitted_at = timezone.now()
        workflow_request, created = WorkflowRequest.objects.get_or_create(
            public_id=public_id,
            defaults={
                "request_number": f"SUB-{public_id.hex}",
                "requester": request.user,
                "project": values["project"],
                "request_type": request_type,
                "title": values["title"],
                "form_data": values["form_data"],
                "status": WorkflowRequest.STATUS_SUBMITTED,
                "priority": request_type.default_priority,
                "due_at": submitted_at + timedelta(hours=request_type.sla_hours),
                "assigned_pipeline": request_type.default_pipeline,
                "submitted_at": submitted_at,
            },
        )
        references = values["sample_references"]
        if created:
            workflow_request.request_number = f"SUB-{submitted_at:%Y}-{workflow_request.pk:05d}"
            workflow_request.save(update_fields=["request_number"])
            WorkflowRequestItem.objects.bulk_create([
                WorkflowRequestItem(request=workflow_request, submission_reference=ref) for ref in references
            ])
            record_audit_event(
                entity=workflow_request,
                action="WORKFLOW_REQUEST_SUBMITTED",
                actor=request.user,
                after={"status": workflow_request.status, "item_count": len(references)},
                details={"source": "requester_portal"},
            )
            queue_requester_event("request.submitted", workflow_request, occurred_at=submitted_at)
        elif (
            workflow_request.requester_id != request.user.pk
            or workflow_request.project_id != values["project"].pk
            or workflow_request.request_type_id != request_type.pk
            or workflow_request.title != values["title"]
            or workflow_request.form_data != values["form_data"]
            or list(workflow_request.items.values_list("submission_reference", flat=True)) != references
        ):
            return Response(
                {"detail": "This submission was already used. Check your saved requests before starting a new request."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"public_id": workflow_request.public_id, "request_number": workflow_request.request_number},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def labels(self, request, **kwargs):
        workflow_request = self.get_object()
        items = list(workflow_request.items.exclude(submission_reference=""))
        if not items or workflow_request.status in (WorkflowRequest.STATUS_CANCELLED, WorkflowRequest.STATUS_REJECTED):
            raise NotFound("Submission labels are unavailable for this request.")
        return submission_labels(workflow_request, items)

    @action(detail=True, methods=["get"], url_path=r"reports/(?P<report_id>[0-9a-f-]{36})/download")
    def download_report(self, request, report_id, **kwargs):
        report = get_object_or_404(self.get_object().reports.filter(approved=True), public_id=report_id)
        return report_download(report)
