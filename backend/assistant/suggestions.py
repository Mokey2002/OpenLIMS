"""Permission-filtered assistant suggestions backed by current records."""

from core.permissions import is_admin
from django.db.models import Count
from projects.models import Project
from results.models import Result
from samples.access import get_sample_access_queryset
from samples.models import Sample, SampleBatch


def _authenticated(user):
    return bool(user and getattr(user, "is_authenticated", False))


def accessible_sample_ids(user, limit=3):
    if not _authenticated(user):
        return []
    queryset = get_sample_access_queryset(
        Sample.objects.order_by("sample_id"),
        user,
    )
    return list(queryset.values_list("sample_id", flat=True)[:limit])


def accessible_project_codes(user, limit=3):
    if not _authenticated(user):
        return []
    queryset = Project.objects.order_by("code")
    if not is_admin(user):
        queryset = queryset.filter(members=user).distinct()
    return list(queryset.values_list("code", flat=True)[:limit])


def accessible_batch_codes(user, limit=3):
    if not _authenticated(user):
        return []
    queryset = SampleBatch.objects.select_related("project").order_by("code")
    if not is_admin(user):
        queryset = queryset.filter(project__members=user).distinct()
    return list(queryset.values_list("code", flat=True)[:limit])


def accessible_result_references(user, limit=3, failed_only=False):
    if not _authenticated(user):
        return []
    samples = get_sample_access_queryset(Sample.objects.all(), user)
    queryset = Result.objects.filter(work_item__sample__in=samples).order_by("id")
    if failed_only:
        queryset = queryset.filter(qc_passed=False)
    return [f"R-{value}" for value in queryset.values_list("id", flat=True)[:limit]]


def accessible_failed_sample_ids(user, limit=3):
    if not _authenticated(user):
        return []
    samples = get_sample_access_queryset(Sample.objects.all(), user)
    return list(
        samples.filter(work_items__results__qc_passed=False)
        .order_by("sample_id")
        .values_list("sample_id", flat=True)
        .distinct()[:limit]
    )


def sample_prompt(user, action="Find sample"):
    identifiers = accessible_sample_ids(user, limit=1)
    return f"{action} {identifiers[0]}" if identifiers else None


def project_prompt(user, action="Summarize project"):
    identifiers = accessible_project_codes(user, limit=1)
    return f"{action} {identifiers[0]}" if identifiers else None


def batch_prompt(user, action="Create barcode labels for batch"):
    identifiers = accessible_batch_codes(user, limit=1)
    return f"{action} {identifiers[0]}" if identifiers else None


def comparison_prompt(user, kind="project", chart_type=None):
    if kind == "sample":
        identifiers = accessible_sample_ids(user, limit=2)
        plural = "samples"
    elif kind == "batch":
        identifiers = accessible_batch_codes(user, limit=2)
        plural = "batches"
    else:
        identifiers = accessible_project_codes(user, limit=2)
        plural = "projects"
    if len(identifiers) < 2:
        return None
    prompt = f"Compare {plural} {identifiers[0]} and {identifiers[1]}"
    if chart_type:
        prompt += f" using a {chart_type} chart"
    return prompt


def sample_scatter_prompt(user):
    identifiers = accessible_sample_ids(user, limit=2)
    if len(identifiers) < 2:
        return None
    result_keys = list(
        Result.objects.filter(
            work_item__sample__sample_id__in=identifiers,
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number__isnull=False,
        )
        .values("key")
        .annotate(sample_count=Count("work_item__sample_id", distinct=True))
        .filter(sample_count=2)
        .order_by("key")
        .values_list("key", flat=True)[:2]
    )
    if len(result_keys) < 2:
        return None
    return (
        f"Plot {result_keys[0]} versus {result_keys[1]} for samples "
        f"{identifiers[0]} and {identifiers[1]} as a scatter plot"
    )


def without_empty(*suggestions):
    return list(dict.fromkeys(value for value in suggestions if value))


def assistant_starter_suggestions(user):
    failed_samples = accessible_failed_sample_ids(user, limit=1)
    failed_sample_prompt = (
        f"Investigate why sample {failed_samples[0]} failed QC"
        if failed_samples
        else None
    )
    return without_empty(
        "What needs attention?",
        failed_sample_prompt,
        comparison_prompt(user, "sample", chart_type="bar"),
        comparison_prompt(user, "sample", chart_type="dot"),
        sample_scatter_prompt(user),
        comparison_prompt(user, "project"),
        comparison_prompt(user, "batch"),
        sample_prompt(user),
        "Show samples needing QC review",
        project_prompt(user, "Find unusual results in project"),
        project_prompt(user, "Where are samples getting stuck in project"),
        "Which reagents expire in the next 30 days?",
        "Show inventory below its reorder level",
        "Find sample sequences",
        "Chart samples by status",
        "Show system status",
    )
