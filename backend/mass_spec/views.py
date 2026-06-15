from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response

from core.permissions import is_admin, is_tech
from events.models import Event

from .models import MassSpecRun
from .serializers import MassSpecRunSerializer
from .tasks import process_mass_spec_run_task



def _round_or_none(value, digits=4):
    if value is None:
        return None

    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _feature_mz_set(run, tolerance_digits=1):
    values = set()

    for feature in run.detected_features or []:
        mz = feature.get("mz")

        if mz is None:
            continue

        try:
            values.add(round(float(mz), tolerance_digits))
        except (TypeError, ValueError):
            continue

    return values


def _comparison_row(run):
    return {
        "id": run.id,
        "name": run.name,
        "status": run.status,
        "original_filename": run.original_filename,
        "project": run.project_id,
        "project_code": run.project.code if run.project else None,
        "sample": run.sample_id,
        "sample_id_value": run.sample.sample_id if run.sample else None,
        "spectra_count": run.spectra_count,
        "peak_count": run.peak_count,
        "feature_count": run.feature_count,
        "protein_count": run.protein_count,
        "peptide_count": run.peptide_count,
        "base_peak_mz": run.base_peak_mz,
        "base_peak_intensity": run.base_peak_intensity,
        "total_ion_current": run.total_ion_current,
        "mean_total_intensity": run.mean_total_intensity,
        "max_total_intensity": run.max_total_intensity,
        "rt_span": run.rt_span,
        "mz_span": run.mz_span,
        "created_at": run.created_at,
        "processed_at": run.processed_at,
    }


class MassSpecRunPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return is_admin(request.user) or is_tech(request.user)


class MassSpecRunViewSet(viewsets.ModelViewSet):
    serializer_class = MassSpecRunSerializer
    permission_classes = [MassSpecRunPermission]

    def get_queryset(self):
        queryset = (
            MassSpecRun.objects
            .select_related("project", "sample", "uploaded_by")
            .all()
            .order_by("-created_at")
        )

        project = self.request.query_params.get("project")
        sample = self.request.query_params.get("sample")
        status = self.request.query_params.get("status")
        search = self.request.query_params.get("search")

        if project:
            queryset = queryset.filter(project_id=project)

        if sample:
            queryset = queryset.filter(sample_id=sample)

        if status:
            queryset = queryset.filter(status__iexact=status)

        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset

    def perform_create(self, serializer):
        uploaded_file = self.request.FILES.get("uploaded_file")

        run = serializer.save(
            uploaded_by=self.request.user,
            original_filename=uploaded_file.name if uploaded_file else "",
            status=MassSpecRun.STATUS_PENDING,
        )

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_UPLOADED",
            actor=self.request.user,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
                "project": run.project_id,
                "sample": run.sample_id,
            },
        )

        process_mass_spec_run_task.delay(run.id)

    @action(detail=False, methods=["get"], url_path="compare")
    def compare(self, request):
        project = request.query_params.get("project")
        sample = request.query_params.get("sample")

        queryset = self.get_queryset().filter(status=MassSpecRun.STATUS_COMPLETED)

        if project:
            queryset = queryset.filter(project_id=project)

        if sample:
            queryset = queryset.filter(sample_id=sample)

        runs = list(queryset[:25])

        if not runs:
            return Response(
                {
                    "count": 0,
                    "filters": {
                        "project": project,
                        "sample": sample,
                    },
                    "runs": [],
                    "summary": {},
                    "feature_overlap": {},
                }
            )

        run_rows = [_comparison_row(run) for run in runs]

        feature_sets = {
            str(run.id): _feature_mz_set(run)
            for run in runs
        }

        shared_feature_mz = set.intersection(*feature_sets.values()) if feature_sets else set()
        all_feature_mz = set.union(*feature_sets.values()) if feature_sets else set()

        unique_feature_mz_by_run = {}

        for run in runs:
            current = feature_sets[str(run.id)]
            others = set()

            for other_run in runs:
                if other_run.id == run.id:
                    continue

                others.update(feature_sets[str(other_run.id)])

            unique_feature_mz_by_run[str(run.id)] = sorted(current - others)

        summary = {
            "run_count": len(runs),
            "spectra_count_min": min(run.spectra_count for run in runs),
            "spectra_count_max": max(run.spectra_count for run in runs),
            "peak_count_min": min(run.peak_count for run in runs),
            "peak_count_max": max(run.peak_count for run in runs),
            "feature_count_min": min(run.feature_count for run in runs),
            "feature_count_max": max(run.feature_count for run in runs),
            "protein_count_max": max(run.protein_count for run in runs),
            "peptide_count_max": max(run.peptide_count for run in runs),
            "total_ion_current_min": _round_or_none(
                min(
                    [run.total_ion_current for run in runs if run.total_ion_current is not None],
                    default=None,
                )
            ),
            "total_ion_current_max": _round_or_none(
                max(
                    [run.total_ion_current for run in runs if run.total_ion_current is not None],
                    default=None,
                )
            ),
        }

        return Response(
            {
                "count": len(runs),
                "filters": {
                    "project": project,
                    "sample": sample,
                },
                "runs": run_rows,
                "summary": summary,
                "feature_overlap": {
                    "mz_rounding_digits": 1,
                    "shared_feature_mz": sorted(shared_feature_mz),
                    "shared_feature_count": len(shared_feature_mz),
                    "all_feature_count": len(all_feature_mz),
                    "unique_feature_mz_by_run": unique_feature_mz_by_run,
                },
            }
        )

    @action(detail=True, methods=["post"], url_path="reprocess")
    def reprocess(self, request, pk=None):
        run = self.get_object()
        run.status = MassSpecRun.STATUS_PENDING
        run.error_message = ""
        run.save(update_fields=["status", "error_message"])

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_REPROCESS_QUEUED",
            actor=request.user,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
            },
        )

        process_mass_spec_run_task.delay(run.id)

        return Response(self.get_serializer(run).data)
