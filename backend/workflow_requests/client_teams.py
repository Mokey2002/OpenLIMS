from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from core.audit import record_audit_event
from core.permissions import IsAdminOnly
from projects.models import Project

from .models import ClientTeam, ClientTeamMembership


def eligible_requesters(project):
    return project.members.filter(groups__name="requester", is_superuser=False).order_by("username")


class ClientTeamMembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ClientTeamMembership
        fields = ("user", "username", "can_submit", "can_view_results")


class ClientTeamSerializer(serializers.ModelSerializer):
    memberships = ClientTeamMembershipSerializer(many=True, read_only=True)

    class Meta:
        model = ClientTeam
        fields = ("id", "project", "name", "memberships")


class ClientTeamAccessInput(serializers.Serializer):
    user = serializers.IntegerField(min_value=1)
    can_submit = serializers.BooleanField()
    can_view_results = serializers.BooleanField()


class ClientTeamAssignmentInput(serializers.Serializer):
    client_team = serializers.PrimaryKeyRelatedField(queryset=ClientTeam.objects.none(), allow_null=True)

    def __init__(self, *args, teams, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client_team"].queryset = teams


class ClientTeamViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = ClientTeamSerializer
    queryset = ClientTeam.objects.select_related("project")

    def list(self, request):
        project = get_object_or_404(Project, pk=request.query_params.get("project"))
        teams = self.get_queryset().filter(project=project).prefetch_related(
            Prefetch("memberships", queryset=ClientTeamMembership.objects.select_related("user").order_by("user__username")),
        )
        return Response({
            "teams": self.get_serializer(teams, many=True).data,
            "requesters": list(eligible_requesters(project).values("id", "username")),
        })

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                team = serializer.save()
                record_audit_event(
                    entity=team.project, action="CLIENT_TEAM_CREATED", actor=self.request.user,
                    details={"team_public_id": str(team.public_id), "name": team.name},
                )
        except IntegrityError as error:
            if ClientTeam.objects.filter(
                project=serializer.validated_data["project"], name=serializer.validated_data["name"],
            ).exists():
                raise ValidationError({"name": "This project already has a team with this name."}) from error
            raise

    @transaction.atomic
    @action(detail=True, methods=["post"], url_path="member-access")
    def member_access(self, request, pk=None):
        team = self.get_object()
        form = ClientTeamAccessInput(data=request.data)
        form.is_valid(raise_exception=True)
        permissions = dict(form.validated_data)
        user = get_object_or_404(get_user_model().objects.select_for_update(), pk=permissions.pop("user"))
        previous = team.memberships.filter(user=user).values("can_submit", "can_view_results").first()
        if (previous is None or any(permissions.values())) and not eligible_requesters(team.project).filter(pk=user.pk).exists():
            raise ValidationError({"user": "Choose a requester account in this project."})

        membership, _ = team.memberships.update_or_create(user=user, defaults=permissions)
        if previous != permissions:
            record_audit_event(
                entity=team.project, action="CLIENT_TEAM_ACCESS_UPDATED", actor=request.user,
                before=previous, after=permissions,
                details={"team_public_id": str(team.public_id), "user_id": user.pk},
            )
        return Response(ClientTeamMembershipSerializer(membership).data)


def report_recipient_ids(workflow_request):
    if not workflow_request.client_team_id:
        return [workflow_request.requester_id]
    return ClientTeamMembership.objects.filter(
        team_id=workflow_request.client_team_id,
        team__project_id=workflow_request.project_id,
        can_view_results=True,
        user__in=eligible_requesters(workflow_request.project).filter(is_active=True),
    ).values_list("user_id", flat=True)
