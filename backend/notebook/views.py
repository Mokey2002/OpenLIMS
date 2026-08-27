from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import record_audit_event
from core.permissions import is_admin

from .models import Experiment, ExperimentComment, ExperimentRevision, ExperimentTemplate, Notebook
from .permissions import notebooks_for_user, user_can_notebook
from .serializers import (
    ExperimentCommentSerializer,
    ExperimentRevisionSerializer,
    ExperimentSerializer,
    ExperimentTemplateSerializer,
    NotebookCollaboratorSerializer,
    NotebookSerializer,
)
from .services import (
    create_revision,
    lock_experiment,
    notify_comment,
    render_experiment_pdf,
    restore_revision,
    review_experiment,
    revision_payload,
)


User = get_user_model()


class NotebookViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NotebookSerializer

    def get_queryset(self):
        action_name = "write" if self.request.method not in {"GET", "HEAD", "OPTIONS"} else "read"
        return notebooks_for_user(self.request.user, action_name).select_related("owner", "project").prefetch_related("team_members", "readers", "editors", "commenters", "reviewers", "lockers")

    def perform_create(self, serializer):
        project = serializer.validated_data.get("project")
        if project and not (is_admin(self.request.user) or project.members.filter(pk=self.request.user.pk).exists()):
            raise PermissionDenied("You must belong to the selected project.")
        notebook = serializer.save(owner=self.request.user)
        record_audit_event(entity=notebook, action="NOTEBOOK_CREATED", actor=self.request.user, after={"scope": notebook.scope})

    def perform_update(self, serializer):
        notebook = self.get_object()
        if not user_can_notebook(self.request.user, notebook, "write"):
            raise PermissionDenied("You cannot update this notebook.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Notebooks with immutable experiment history cannot be deleted."})

    @action(detail=False, methods=["get"])
    def collaborators(self, request):
        """Return the minimal internal directory used by notebook sharing controls."""
        users = User.objects.filter(is_active=True).order_by("username")
        return Response(NotebookCollaboratorSerializer(users, many=True).data)


class ExperimentTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentTemplateSerializer

    def get_queryset(self):
        return ExperimentTemplate.objects.filter(notebook__in=notebooks_for_user(self.request.user)).select_related("notebook", "created_by")

    def perform_create(self, serializer):
        notebook = serializer.validated_data["notebook"]
        if not user_can_notebook(self.request.user, notebook, "write"):
            raise PermissionDenied("You cannot create templates in this notebook.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if not user_can_notebook(self.request.user, self.get_object().notebook, "write"):
            raise PermissionDenied("You cannot update this template.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        if template.experiments.exists():
            template.active = False
            template.save(update_fields=["active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def instantiate(self, request, pk=None):
        template = self.get_object()
        if not user_can_notebook(request.user, template.notebook, "write"):
            raise PermissionDenied("You cannot create experiments in this notebook.")
        experiment = Experiment.objects.create(
            notebook=template.notebook,
            template=template,
            title=request.data.get("title") or template.name,
            created_by=request.user,
        )
        experiment.assignees.set(request.data.get("assignees", []))
        create_revision(
            experiment=experiment,
            actor=request.user,
            blocks=template.blocks or [],
            links=request.data.get("links", []),
            reason="Created from template",
        )
        return Response(ExperimentSerializer(experiment, context={"request": request}).data, status=status.HTTP_201_CREATED)


class ExperimentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentSerializer

    def get_queryset(self):
        return (
            Experiment.objects.filter(notebook__in=notebooks_for_user(self.request.user))
            .select_related("notebook", "notebook__project", "template", "created_by", "current_revision", "locked_by")
            .prefetch_related("assignees", "current_revision__blocks", "current_revision__links", "revisions__blocks", "revisions__links", "comments__mentions", "reviews")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notebook = serializer.validated_data["notebook"]
        if not user_can_notebook(request.user, notebook, "write"):
            raise PermissionDenied("You cannot create experiments in this notebook.")
        initial_blocks = serializer.validated_data.pop("initial_blocks", None)
        initial_links = serializer.validated_data.pop("initial_links", [])
        template = serializer.validated_data.get("template")
        experiment = serializer.save(created_by=request.user)
        create_revision(
            experiment=experiment,
            actor=request.user,
            blocks=initial_blocks if initial_blocks is not None else (template.blocks if template else []),
            links=initial_links,
            reason="Experiment created",
        )
        experiment.refresh_from_db()
        return Response(self.get_serializer(experiment).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        experiment = self.get_object()
        if not user_can_notebook(self.request.user, experiment.notebook, "write"):
            raise PermissionDenied("You cannot edit this experiment.")
        if experiment.status in {Experiment.STATUS_REVIEWED, Experiment.STATUS_LOCKED}:
            raise ValidationError({"status": "Reviewed or locked experiments cannot be changed."})
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Experiments with immutable revision history cannot be deleted."})

    @action(detail=True, methods=["post"])
    def autosave(self, request, pk=None):
        revision, created = create_revision(
            experiment=self.get_object(),
            actor=request.user,
            blocks=request.data.get("blocks", []),
            links=request.data.get("links", []),
            reason=request.data.get("reason", "Autosave"),
        )
        return Response({"created": created, "revision": ExperimentRevisionSerializer(revision).data})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        experiment = self.get_object()
        revision = experiment.revisions.filter(public_id=request.data.get("revision_public_id")).first()
        if not revision:
            raise ValidationError({"revision_public_id": "Revision not found."})
        restored, _created = restore_revision(
            experiment=experiment,
            revision=revision,
            actor=request.user,
            reason=request.data.get("reason", ""),
        )
        return Response(ExperimentRevisionSerializer(restored).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        experiment = self.get_object()
        if not user_can_notebook(request.user, experiment.notebook, "write"):
            raise PermissionDenied("You cannot change this experiment state.")
        target = str(request.data.get("status") or "").upper()
        allowed = {
            Experiment.STATUS_DRAFT: {Experiment.STATUS_IN_PROGRESS},
            Experiment.STATUS_IN_PROGRESS: {Experiment.STATUS_COMPLETED},
            Experiment.STATUS_COMPLETED: {Experiment.STATUS_IN_PROGRESS},
        }
        if target not in allowed.get(experiment.status, set()):
            raise ValidationError({"status": f"Cannot transition from {experiment.status} to {target}."})
        before = experiment.status
        experiment.status = target
        if target == Experiment.STATUS_COMPLETED:
            if not experiment.current_revision:
                raise ValidationError({"revision": "An experiment needs content before completion."})
            experiment.completed_at = timezone.now()
        experiment.save(update_fields=["status", "completed_at", "updated_at"])
        record_audit_event(entity=experiment, action="EXPERIMENT_STATUS_CHANGED", actor=request.user, reason=request.data.get("reason", ""), before={"status": before}, after={"status": target})
        return Response(self.get_serializer(experiment).data)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        review = review_experiment(
            experiment=self.get_object(),
            actor=request.user,
            decision=request.data.get("decision"),
            comment=request.data.get("comment", ""),
            signed_name=request.data.get("signed_name", ""),
        )
        return Response({"review": review.public_id, "decision": review.decision}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        experiment = lock_experiment(experiment=self.get_object(), actor=request.user, reason=request.data.get("reason", ""))
        return Response(self.get_serializer(experiment).data)

    @action(detail=True, methods=["post"])
    def clone(self, request, pk=None):
        source = self.get_object()
        if not user_can_notebook(request.user, source.notebook, "write"):
            raise PermissionDenied("You cannot clone into this notebook.")
        clone = Experiment.objects.create(
            notebook=source.notebook,
            template=source.template,
            cloned_from=source,
            title=request.data.get("title") or f"Copy of {source.title}",
            created_by=request.user,
        )
        clone.assignees.set(request.data.get("assignees", []))
        payload = revision_payload(source.current_revision) if source.current_revision else {"blocks": [], "links": []}
        create_revision(
            experiment=clone,
            actor=request.user,
            blocks=payload["blocks"],
            links=payload["links"],
            reason="Cloned from existing experiment",
            preserve_link_versions=True,
        )
        clone.refresh_from_db()
        return Response(self.get_serializer(clone).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        experiment = self.get_object()
        content = render_experiment_pdf(experiment)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="experiment-{experiment.public_id}.pdf"'
        return response


class ExperimentRevisionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentRevisionSerializer

    def get_queryset(self):
        return ExperimentRevision.objects.filter(experiment__notebook__in=notebooks_for_user(self.request.user)).select_related("experiment", "created_by", "restored_from").prefetch_related("blocks", "links", "reviews")


class ExperimentCommentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExperimentCommentSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return ExperimentComment.objects.filter(experiment__notebook__in=notebooks_for_user(self.request.user, "comment")).select_related("experiment", "revision", "author", "assigned_to", "resolved_by").prefetch_related("mentions")

    def perform_create(self, serializer):
        experiment = serializer.validated_data["experiment"]
        if not user_can_notebook(self.request.user, experiment.notebook, "comment"):
            raise PermissionDenied("You cannot comment on this experiment.")
        comment = serializer.save(author=self.request.user)
        notify_comment(comment)
        record_audit_event(entity=experiment, action="EXPERIMENT_COMMENT_ADDED", actor=self.request.user, details={"comment_public_id": str(comment.public_id), "revision": comment.revision.number if comment.revision else None})

    def partial_update(self, request, *args, **kwargs):
        comment = self.get_object()
        if not user_can_notebook(request.user, comment.experiment.notebook, "comment"):
            raise PermissionDenied("You cannot resolve this comment.")
        resolved = bool(request.data.get("resolved"))
        comment.resolved = resolved
        comment.resolved_by = request.user if resolved else None
        comment.resolved_at = timezone.now() if resolved else None
        comment.save(update_fields=["resolved", "resolved_by", "resolved_at"])
        return Response(self.get_serializer(comment).data)
