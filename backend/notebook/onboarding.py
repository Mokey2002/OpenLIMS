"""Permission-aware, resumable first experiment using a lab's saved workflow."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from settings_app.models import SystemSettings
from .models import ExperimentOnboarding, ExperimentTemplate
from .permissions import notebooks_for_user, user_can_notebook
from .services import instantiate_template


def notebook_enabled():
    return not getattr(settings, "OPENLIMS_ENFORCE_FEATURE_FLAGS", True) or SystemSettings.load().feature_flags.get("notebook", False)


def progress(user):
    if not notebook_enabled():
        return {"enabled": False, "experiment": None}
    record = ExperimentOnboarding.objects.select_related("experiment__notebook").filter(user=user).first()
    experiment = record.experiment if record else None
    if not experiment or not user_can_notebook(user, experiment.notebook, "read"):
        return {"enabled": True, "experiment": None}
    steps = list(experiment.workflow_steps.order_by("position"))
    return {"enabled": True, "experiment": {
        "public_id": str(experiment.public_id), "title": experiment.title,
        "status": experiment.status, "can_write": user_can_notebook(user, experiment.notebook, "write"),
        "steps": [{"position": step.position, "name": step.definition.get("name", ""),
                   "status": step.status} for step in steps],
    }}


class StartSerializer(serializers.Serializer):
    template = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=255)


class OnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(progress(request.user))

    @transaction.atomic
    def post(self, request):
        if not notebook_enabled():
            raise NotFound("The notebook module is disabled.")
        # Serialize retries across tabs/requests, including first creation of the record.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        current = progress(request.user)
        if current["experiment"]:
            return Response(current)
        data = StartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        template = ExperimentTemplate.objects.select_for_update().filter(
            pk=data.validated_data["template"], active=True,
            notebook__in=notebooks_for_user(request.user, "write"),
        ).exclude(workflow_steps=[]).first()
        if not template:
            raise NotFound("Choose an available workflow you have permission to use.")
        experiment = instantiate_template(template, request.user, title=data.validated_data["title"], assignees=[request.user.pk])
        ExperimentOnboarding.objects.update_or_create(user=request.user, defaults={"experiment": experiment})
        return Response(progress(request.user), status=201)
