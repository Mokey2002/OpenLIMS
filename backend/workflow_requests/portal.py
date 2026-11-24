import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, Exists, OuterRef, Prefetch, Q, Value, When
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import record_audit_event
from core.demo_requester_access import (
    DEMO_PROJECT_CODE, DEMO_PROJECT_DESCRIPTION, can_use_requester_demo, is_requester_demo_session,
)
from core.permissions import is_admin, is_requester_only
from events.kafka import queue_requester_event
from pipelines.models import PipelineRun
from projects.models import Project

from .files import report_download, submission_labels
from .models import AssayRequestType, ClientTeamMembership, WorkflowRequest, WorkflowRequestItem, WorkflowRequestReport
from .services import portal_form_schema, validate_submission_form


def available_projects(user, *, demo=False):
    if demo:
        return Project.objects.filter(code=DEMO_PROJECT_CODE, description=DEMO_PROJECT_DESCRIPTION, members=user)
    if is_admin(user) and not is_requester_only(user):
        return Project.objects.all()
    return Project.objects.filter(members=user)


def available_tests(projects, *, demo=False):
    project_scope = Q(project__in=projects)
    if not demo:
        project_scope |= Q(project__isnull=True)
    return AssayRequestType.objects.filter(
        project_scope,
        active=True,
        portal_enabled=True,
        default_pipeline__active=True,
    )


def submission_team(user, project, team_id):
    memberships = ClientTeamMembership.objects.filter(user=user, team__project=project)
    if not is_requester_only(user):
        memberships = memberships.none()
    permitted = memberships.filter(can_submit=True)
    if team_id is not None:
        if not permitted.filter(team_id=team_id).exists():
            raise ValidationError({"client_team": "Choose a client team you can submit for in this project."})
        return team_id
    if permitted.exists():
        raise ValidationError({"client_team": "Choose a client team for this request."})
    if memberships.exists():
        raise PermissionDenied("Your client team access does not permit submissions in this project.")
    return None


class PortalSubmissionSerializer(serializers.Serializer):
    submission_id = serializers.UUIDField()
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.none())
    request_type = serializers.PrimaryKeyRelatedField(queryset=AssayRequestType.objects.none())
    client_team = serializers.IntegerField(min_value=1, required=False, allow_null=True)
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
            demo = is_requester_demo_session(request.auth)
            projects = available_projects(request.user, demo=demo)
            self.fields["project"].queryset = projects
            self.fields["request_type"].queryset = available_tests(projects, demo=demo)

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
    client_team_name = serializers.CharField(source="client_team.name", allow_null=True, read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowRequest
        fields = ("public_id", "request_number", "title", "project_name", "test_name", "client_team_name", "status", "submitted_at")

    def get_status(self, obj):
        if obj.status in (WorkflowRequest.STATUS_APPROVED, WorkflowRequest.STATUS_IN_PROGRESS) and obj.has_runs:
            return WorkflowRequest.STATUS_IN_PROGRESS if obj.has_unfinished_runs else WorkflowRequest.STATUS_COMPLETED
        return obj.status


class PortalSubmissionSampleSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(source="submission_reference")
    barcode = serializers.SerializerMethodField()
    received_at = serializers.DateTimeField(source="submission_received_at")

    class Meta:
        model = WorkflowRequestItem
        fields = ("public_id", "reference", "barcode", "received_at")

    def get_barcode(self, obj):
        if obj.request.requester_id == self.context["request"].user.pk:
            return obj.submission_barcode
        return None


class PortalReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowRequestReport
        fields = ("public_id", "title", "approved_at")


class PortalRequestDetailSerializer(PortalRequestSerializer):
    samples = PortalSubmissionSampleSerializer(source="submission_samples", many=True)
    reports = serializers.SerializerMethodField()
    can_view_reports = serializers.BooleanField(read_only=True)
    can_download_labels = serializers.SerializerMethodField()

    class Meta(PortalRequestSerializer.Meta):
        fields = PortalRequestSerializer.Meta.fields + ("samples", "reports", "can_view_reports", "can_download_labels")

    def get_reports(self, obj):
        if not obj.can_view_reports:
            return []
        return PortalReportSerializer(obj.released_reports, many=True).data

    def get_can_download_labels(self, obj):
        return obj.requester_id == self.context["request"].user.pk


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
        user = self.request.user
        demo = is_requester_demo_session(self.request.auth)
        queryset = (
            WorkflowRequest.objects.filter(project__in=available_projects(user, demo=demo))
            .exclude(status=WorkflowRequest.STATUS_DRAFT)
            .select_related("project", "request_type", "client_team")
            .order_by("-created_at", "-pk")
        )
        if demo:
            queryset = queryset.filter(requester=user, client_team__isnull=True).annotate(can_view_reports=Value(True))
        elif is_requester_only(user):
            team_results = Exists(ClientTeamMembership.objects.filter(
                team_id=OuterRef("client_team_id"), team__project_id=OuterRef("project_id"),
                user=user, can_view_results=True,
            ))
            queryset = queryset.filter(Q(requester=user) | team_results).annotate(
                can_view_reports=Case(When(client_team__isnull=True, then=Value(True)), default=team_results),
            )
        else:
            queryset = queryset.filter(requester=user).annotate(can_view_reports=Value(True))
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
        user = request.user
        demo = is_requester_demo_session(request.auth)
        accessible = available_projects(user, demo=demo)
        client_teams = []
        if not demo and is_requester_only(user):
            memberships = ClientTeamMembership.objects.filter(user=user)
            assigned = memberships.filter(team__project_id=OuterRef("pk"))
            projects_with_submit = accessible.filter(~Exists(assigned) | Exists(assigned.filter(can_submit=True)))
            client_teams = [
                {"id": row.team_id, "name": row.team.name, "project_id": row.team.project_id}
                for row in memberships.filter(can_submit=True, team__project__in=projects_with_submit)
                .select_related("team").order_by("team__name", "team_id")
            ]
        else:
            projects_with_submit = accessible
        projects = list(projects_with_submit.order_by("name").values("id", "code", "name"))
        types = available_tests([project["id"] for project in projects], demo=demo).values(
            "id", "project_id", "code", "name", "description", "form_schema",
        )
        return Response({"projects": projects, "tests": list(types) if projects else [], "client_teams": client_teams})

    @transaction.atomic
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        public_id = values["submission_id"]
        request_type = values["request_type"]
        submitted_at = timezone.now()
        demo = is_requester_demo_session(request.auth)
        if demo or is_requester_only(request.user):
            # Serialize new submissions with changes to this requester's team grants.
            requester = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if demo and not can_use_requester_demo(requester):
                raise PermissionDenied("The requester demo session is no longer available.")
        workflow_request = WorkflowRequest.objects.filter(public_id=public_id).first()
        created = False
        if workflow_request is None:
            team_id = submission_team(request.user, values["project"], values.get("client_team"))
            workflow_request, created = WorkflowRequest.objects.get_or_create(
                public_id=public_id,
                defaults={
                    "request_number": f"SUB-{public_id.hex}",
                    "requester": request.user,
                    "project": values["project"],
                    "client_team_id": team_id,
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
            or ("client_team" in values and workflow_request.client_team_id != values["client_team"])
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
        if (
            workflow_request.requester_id != request.user.pk or not items
            or workflow_request.status in (WorkflowRequest.STATUS_CANCELLED, WorkflowRequest.STATUS_REJECTED)
        ):
            raise NotFound("Submission labels are unavailable for this request.")
        return submission_labels(workflow_request, items)

    @action(detail=True, methods=["get"], url_path=r"reports/(?P<report_id>[0-9a-f-]{36})/download")
    def download_report(self, request, report_id, **kwargs):
        workflow_request = self.get_object()
        if not workflow_request.can_view_reports:
            raise NotFound("Released report unavailable.")
        report = get_object_or_404(workflow_request.reports.filter(approved=True), public_id=report_id)
        return report_download(report)
