"""Audit scopes shared by sample history and assistant readers."""
from django.db.models import CharField, Q
from django.db.models.functions import Cast

from pipelines.models import PipelineRun
from results.models import WorkItem


def _entity_events(entity_type, queryset):
    return Q(entity_type__iexact=entity_type) & (
        Q(entity_id__in=queryset.annotate(audit_key=Cast("pk", CharField())).values("audit_key"))
        | Q(entity_id__in=queryset.annotate(audit_key=Cast("public_id", CharField())).values("audit_key"))
    )


def sample_event_filter(sample, *, include_work_items=False):
    """Call after resolving sample access; verify related events by real ownership.

    New canonical workflow/analysis events carry an explicit sample relation.
    Older pipeline events had a separate Sample mirror, so those unmarked rows
    stay out of sample history to avoid introducing historical duplicates.
    """
    direct = Q(entity_type__iexact="sample", entity_id__in=[str(sample.pk), str(sample.public_id)])
    related = Q(payload__related_sample_id=sample.pk)
    pipelines = _entity_events("PipelineRun", PipelineRun.objects.filter(sample=sample))
    work = _entity_events("WorkItem", WorkItem.objects.filter(sample=sample))
    work_scope = work if include_work_items else related & work & Q(action="ANALYSIS_ASSIGNED")
    return direct | (related & pipelines) | work_scope
