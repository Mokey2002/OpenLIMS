from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alignments.models import AlignmentJob
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from projects.models import Project
from samples.models import Sample
from sequences.models import Sequence

User = get_user_model()


def limited(queryset, limit=8):
    return list(queryset[:limit])


class GlobalSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()

        empty_response = {
            "query": q,
            "total": 0,
            "results": {
                "samples": [],
                "projects": [],
                "sequences": [],
                "alignments": [],
                "imports": [],
                "instruments": [],
                "events": [],
                "users": [],
            },
        }

        if len(q) < 2:
            return Response(empty_response)

        user = request.user
        user_is_admin = (
            user.is_superuser
            or user.groups.filter(name="admin").exists()
        )

        project_queryset = Project.objects.all()

        if not user_is_admin:
            project_queryset = project_queryset.filter(members=user)

        allowed_project_ids = list(project_queryset.values_list("id", flat=True))

        samples = (
            Sample.objects
            .select_related(
                "project",
                "container",
                "container__location",
            )
            .filter(
                Q(sample_id__icontains=q)
                | Q(status__icontains=q)
                | Q(project__code__icontains=q)
                | Q(project__name__icontains=q)
                | Q(container__container_id__icontains=q)
                | Q(container__location__name__icontains=q)
            )
        )

        if not user_is_admin:
            samples = samples.filter(project_id__in=allowed_project_ids)

        projects = project_queryset.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(description__icontains=q)
        )

        sequences = (
            Sequence.objects
            .select_related("sample", "project")
            .filter(
                Q(name__icontains=q)
                | Q(sequence_type__icontains=q)
                | Q(sample__sample_id__icontains=q)
                | Q(project__code__icontains=q)
                | Q(project__name__icontains=q)
            )
        )

        if not user_is_admin:
            sequences = sequences.filter(project_id__in=allowed_project_ids)

        alignments = (
            AlignmentJob.objects
            .select_related("project", "created_by")
            .filter(
                Q(name__icontains=q)
                | Q(status__icontains=q)
                | Q(tool__icontains=q)
                | Q(project__code__icontains=q)
                | Q(project__name__icontains=q)
                | Q(created_by__username__icontains=q)
            )
        )

        if not user_is_admin:
            alignments = alignments.filter(project_id__in=allowed_project_ids)

        imports = (
            ImportJob.objects
            .select_related(
                "instrument",
                "project",
                "uploaded_by",
            )
            .filter(
                Q(status__icontains=q)
                | Q(source_type__icontains=q)
                | Q(run_id__icontains=q)
                | Q(instrument__code__icontains=q)
                | Q(instrument__name__icontains=q)
                | Q(project__code__icontains=q)
                | Q(project__name__icontains=q)
                | Q(uploaded_by__username__icontains=q)
            )
        )

        if not user_is_admin:
            imports = imports.filter(project_id__in=allowed_project_ids)

        instruments = InstrumentProfile.objects.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
        )

        events = (
            Event.objects
            .select_related("actor")
            .filter(
                Q(action__icontains=q)
                | Q(entity_type__icontains=q)
                | Q(entity_id__icontains=q)
                | Q(actor__username__icontains=q)
            )
        )

        if not user_is_admin:
            events = events.filter(actor=user)

        users = User.objects.none()

        if user_is_admin:
            users = User.objects.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )

        sample_results = [
            {
                "id": sample.id,
                "title": sample.sample_id,
                "subtitle": (
                    f"{sample.status} · "
                    f"{sample.project.code if sample.project else 'No project'}"
                ),
                "type": "Sample",
                "url": f"/samples/{sample.id}",
            }
            for sample in limited(samples.order_by("-created_at"))
        ]

        project_results = [
            {
                "id": project.id,
                "title": project.code,
                "subtitle": project.name,
                "type": "Project",
                "url": f"/projects/{project.id}",
            }
            for project in limited(projects.order_by("code"))
        ]

        sequence_results = [
            {
                "id": sequence.id,
                "title": sequence.name,
                "subtitle": (
                    f"{sequence.sequence_type} · "
                    f"{sequence.project.code if sequence.project else 'No project'}"
                ),
                "type": "Sequence",
                "url": f"/sequences?workspace={sequence.id}",
            }
            for sequence in limited(sequences.order_by("-updated_at"))
        ]

        alignment_results = [
            {
                "id": alignment.id,
                "title": alignment.name,
                "subtitle": (
                    f"{alignment.status} · "
                    f"{alignment.project.code if alignment.project else 'No project'}"
                ),
                "type": "Alignment",
                "url": "/alignments",
            }
            for alignment in limited(alignments.order_by("-created_at"))
        ]

        import_results = [
            {
                "id": job.id,
                "title": job.run_id or f"Import #{job.id}",
                "subtitle": (
                    f"{job.status} · "
                    f"{job.instrument.code if job.instrument else 'No instrument'}"
                ),
                "type": "Import",
                "url": f"/imports/{job.id}",
            }
            for job in limited(imports.order_by("-created_at"))
        ]

        instrument_results = [
            {
                "id": instrument.id,
                "title": instrument.code,
                "subtitle": instrument.name,
                "type": "Instrument",
                "url": "/imports",
            }
            for instrument in limited(instruments.order_by("code"))
        ]

        event_results = [
            {
                "id": event.id,
                "title": event.action,
                "subtitle": f"{event.entity_type} #{event.entity_id}",
                "type": "Event",
                "url": "/events",
            }
            for event in limited(events.order_by("-timestamp"))
        ]

        user_results = [
            {
                "id": found_user.id,
                "title": found_user.username,
                "subtitle": (
                    found_user.email
                    or found_user.get_full_name()
                    or "User"
                ),
                "type": "User",
                "url": "/users",
            }
            for found_user in limited(users.order_by("username"))
        ]

        total = (
            len(sample_results)
            + len(project_results)
            + len(sequence_results)
            + len(alignment_results)
            + len(import_results)
            + len(instrument_results)
            + len(event_results)
            + len(user_results)
        )

        return Response(
            {
                "query": q,
                "total": total,
                "results": {
                    "samples": sample_results,
                    "projects": project_results,
                    "sequences": sequence_results,
                    "alignments": alignment_results,
                    "imports": import_results,
                    "instruments": instrument_results,
                    "events": event_results,
                    "users": user_results,
                },
            }
        )