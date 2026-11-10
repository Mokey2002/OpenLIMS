"""Self-service requests with additive, administrator-reviewed access grants."""
from collections.abc import Mapping

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from events.models import Event
from notifications.models import Notification
from projects.models import Project
from .models import AccessRequest
from .permissions import application_roles, is_admin
from .user_safety import user_administration


class RequestConflict(APIException):
    status_code = 409
    default_detail = "This request changed. Refresh it before making a decision."


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ValidationError({"detail": "Unsupported request fields."})
        return super().to_internal_value(data)


class SubmitSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=[AccessRequest.PROJECT, AccessRequest.ROLE])
    project_code = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=["", *AccessRequest.REQUESTABLE_ROLES], required=False, default="")
    reason = serializers.CharField(min_length=10, max_length=2000)

    def validate(self, data):
        project = data["kind"] == AccessRequest.PROJECT
        if project and (not data["project_code"] or data["role"]):
            raise ValidationError("Project requests require only a project code.")
        if not project and (not data["role"] or data["project_code"]):
            raise ValidationError("Role requests require only a supported application role.")
        return data


class ReviewSerializer(StrictSerializer):
    decision = serializers.ChoiceField(choices=[AccessRequest.APPROVED, AccessRequest.REJECTED])
    decision_reason = serializers.CharField(min_length=10, max_length=2000)
    project_public_id = serializers.UUIDField(required=False)


class AccessRequestSerializer(serializers.ModelSerializer):
    can_withdraw = serializers.SerializerMethodField()
    can_review = serializers.SerializerMethodField()

    class Meta:
        model = AccessRequest
        fields = ["id", "requester_username", "kind", "project_code", "role", "reason", "status", "reviewer_username", "decision_reason", "access_changed", "created_at", "reviewed_at", "can_withdraw", "can_review"]
        read_only_fields = fields

    def get_can_withdraw(self, row) -> bool:
        request = self.context.get("request")
        return bool(request and row.requester_id == request.user.pk and row.status == AccessRequest.PENDING)

    def get_can_review(self, row) -> bool:
        request = self.context.get("request")
        return bool(request and self.context.get("administrator") and row.requester_id != request.user.pk and row.status == AccessRequest.PENDING)


class ProjectPreviewSerializer(serializers.Serializer):
    public_id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class PreviewSerializer(serializers.Serializer):
    request = AccessRequestSerializer(read_only=True)
    current_roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    requester_active = serializers.BooleanField(read_only=True)
    project = ProjectPreviewSerializer(read_only=True, allow_null=True)
    already_granted = serializers.BooleanField(read_only=True)
    can_approve = serializers.BooleanField(read_only=True)
    blockers = serializers.ListField(child=serializers.CharField(), read_only=True)


def _audit(row, actor, action):
    payload = {
        "requester_id": row.requester_id, "requester_username": row.requester_username,
        "kind": row.kind, "project_code": row.project_code, "role": row.role,
        "reason": row.reason, "status": row.status, "decision_reason": row.decision_reason,
        "access_changed": row.access_changed,
    }
    if row.project_id:
        payload["project_id"] = row.project_id
    Event.objects.create(entity_type="AccessRequest", entity_id=str(row.pk), actor=actor, action=action, payload=payload)


@user_administration()
@transaction.atomic
def submit(user, data):
    user = get_user_model().objects.select_for_update().filter(pk=user.pk).first()
    if not user or not user.is_active:
        raise PermissionDenied("An active account is required.")
    if is_admin(user):
        raise ValidationError("Administrators already have full application access.")
    if data["kind"] == AccessRequest.ROLE and user.groups.filter(name=data["role"]).exists():
        raise ValidationError("This role is already assigned to your account.")
    if data["kind"] == AccessRequest.PROJECT and Project.objects.filter(code__iexact=data["project_code"], members=user).exists():
        raise ValidationError("You already belong to this project.")
    target = data["project_code"].casefold() if data["kind"] == AccessRequest.PROJECT else data["role"]
    row, created = AccessRequest.objects.get_or_create(
        requester=user, target_key=f"{data['kind']}:{target}", status=AccessRequest.PENDING,
        defaults={**data, "requester_username": user.username},
    )
    if created:
        _audit(row, user, "ACCESS_REQUEST_SUBMITTED")
        administrators = get_user_model().objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__name="admin")).distinct()
        Notification.objects.bulk_create([
            Notification(user=admin, title="Access request awaiting review", message=f"{user.username} requested {data['project_code'] or data['role']}.", link="/access-requests")
            for admin in administrators
        ])
    return row, created


def _target_project(row, *, lock=False):
    projects = Project.objects.filter(code__iexact=row.project_code).order_by("pk")
    if lock:
        projects = projects.select_for_update()
    matches = list(projects[:2])
    return matches[0] if len(matches) == 1 else None


def preview(row, reviewer):
    user = row.requester
    project = _target_project(row) if row.kind == AccessRequest.PROJECT else None
    blockers = []
    if row.status != AccessRequest.PENDING:
        blockers.append("This request has already been decided.")
    if user is None or not user.is_active:
        blockers.append("The requester no longer has an active account.")
    if row.requester_id == reviewer.pk:
        blockers.append("Another administrator must review your request.")
    if row.kind == AccessRequest.PROJECT and project is None:
        blockers.append("The project code is missing or ambiguous. Reject the request and ask for clarification.")
    already = bool(user and (
        project.members.filter(pk=user.pk).exists() if project else user.groups.filter(name=row.role).exists()
    ))
    return {
        "request": AccessRequestSerializer(row).data,
        "current_roles": application_roles(user),
        "requester_active": bool(user and user.is_active),
        "project": {"public_id": str(project.public_id), "code": project.code, "name": project.name} if project else None,
        "already_granted": already, "can_approve": not blockers, "blockers": blockers,
    }


def _locked_people(row, actor):
    ids = {actor.pk, row.requester_id} - {None}
    users = {user.pk: user for user in get_user_model().objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    reviewer = users.get(actor.pk)
    if reviewer:
        # Serialize group-based administrator revocation with a review as well
        # as superuser/active flag changes on the locked User row.
        list(get_user_model().groups.through.objects.select_for_update(of=("self",)).filter(user_id=reviewer.pk, group__name="admin"))
    if not reviewer or not reviewer.is_active or not is_admin(reviewer):
        raise PermissionDenied("A current active administrator must review access requests.")
    return reviewer, users.get(row.requester_id)


@user_administration()
@transaction.atomic
def review(request_id, actor, data):
    row = AccessRequest.objects.select_for_update().get(pk=request_id)
    reviewer, user = _locked_people(row, actor)
    if row.requester_id == reviewer.pk:
        raise PermissionDenied("Another administrator must review your request.")
    if row.status != AccessRequest.PENDING:
        if row.status == data["decision"]:
            return row
        raise RequestConflict()
    if data["decision"] == AccessRequest.APPROVED:
        if not user or not user.is_active:
            raise ValidationError("The requester no longer has an active account.")
        if row.kind == AccessRequest.PROJECT:
            project = _target_project(row, lock=True)
            if not project or project.public_id != data.get("project_public_id"):
                raise RequestConflict("The project changed or the preview is missing. Refresh the review preview.")
            row.project = project
            row.access_changed = not project.members.filter(pk=user.pk).exists()
            project.members.add(user)
        else:
            if row.role not in AccessRequest.REQUESTABLE_ROLES:
                raise ValidationError("This application role cannot be requested.")
            row.access_changed = not user.groups.filter(name=row.role).exists()
            group, _ = Group.objects.get_or_create(name=row.role)
            user.groups.add(group)
    row.status = data["decision"]
    row.decision_reason = data["decision_reason"]
    row.reviewed_by = reviewer
    row.reviewer_username = reviewer.username
    row.reviewed_at = timezone.now()
    row.save()
    _audit(row, reviewer, "ACCESS_REQUEST_APPROVED" if row.status == AccessRequest.APPROVED else "ACCESS_REQUEST_REJECTED")
    if user:
        Notification.objects.create(user=user, title="Access request reviewed", message=f"Your request for {row.project_code or row.role} was {row.status.lower()}.", link="/access-requests?status=ALL")
    return row


@user_administration()
@transaction.atomic
def withdraw(request_id, user):
    row = AccessRequest.objects.select_for_update().get(pk=request_id)
    if row.requester_id != user.pk:
        raise PermissionDenied("Only the requester can withdraw this request.")
    if row.status == AccessRequest.CANCELLED:
        return row
    if row.status != AccessRequest.PENDING:
        raise RequestConflict()
    row.status = AccessRequest.CANCELLED
    row.decision_reason = "Withdrawn by requester."
    row.reviewed_by = user
    row.reviewer_username = user.username
    row.reviewed_at = timezone.now()
    row.save()
    _audit(row, user, "ACCESS_REQUEST_CANCELLED")
    return row


class SubmissionThrottle(SimpleRateThrottle):
    rate = "20/hour"
    scope = "access_requests"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class AccessRequestViewSet(viewsets.GenericViewSet):
    queryset = AccessRequest.objects.none()
    permission_classes = [IsAuthenticated]
    serializer_class = AccessRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        from .permissions import IsAdminOnly
        return [IsAdminOnly()] if self.action in {"preview", "review"} else [IsAuthenticated()]

    def get_throttles(self):
        return [SubmissionThrottle()] if self.action == "create" else super().get_throttles()

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "administrator": is_admin(self.request.user)}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AccessRequest.objects.none()
        rows = AccessRequest.objects.select_related("requester", "reviewed_by").all()
        if not is_admin(self.request.user):
            rows = rows.filter(requester=self.request.user)
        elif self.request.query_params.get("mine") == "1":
            rows = rows.filter(requester=self.request.user)
        state = self.request.query_params.get("status")
        if state:
            if state not in {AccessRequest.PENDING, AccessRequest.APPROVED, AccessRequest.REJECTED, AccessRequest.CANCELLED}:
                raise ValidationError({"status": "Choose a valid request status."})
            rows = rows.filter(status=state)
        return rows

    def list(self, request, *args, **kwargs):
        rows = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(rows)
        if page is None:
            return Response(self.get_serializer(rows, many=True).data)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request, pk=None, **kwargs):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=SubmitSerializer, responses={200: AccessRequestSerializer, 201: AccessRequestSerializer})
    def create(self, request, *args, **kwargs):
        data = SubmitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row, created = submit(request.user, data.validated_data)
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(responses=PreviewSerializer)
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None, **kwargs):
        row = self.get_object()
        data = preview(row, request.user)
        data["request"] = self.get_serializer(row).data
        return Response(data)

    @extend_schema(request=ReviewSerializer, responses=AccessRequestSerializer)
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None, **kwargs):
        row = self.get_object()
        data = ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(self.get_serializer(review(row.pk, request.user, data.validated_data)).data)

    @extend_schema(request=None, responses=AccessRequestSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None, **kwargs):
        row = self.get_object()
        if request.data:
            raise ValidationError("Withdrawal does not accept changes to the request.")
        return Response(self.get_serializer(withdraw(row.pk, request.user)).data)
