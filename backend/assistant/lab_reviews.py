"""Read-only impact and quality reviews, with explicit evidence and scan limits."""
import re
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.permissions import is_admin
from custom_fields.forms import validate_values
from custom_fields.models import FieldDefinition, FieldValue
from inventory.models import InventoryLot, InventoryReservation, InventoryTransaction
from inventory.units import units_compatible
from notebook.models import Experiment
from notebook.permissions import notebooks_for_user
from projects.models import Project
from results.models import Result, WorkItem
from .lab_helpers import enabled, response
from .sample_operations import _sample_queryset

SAMPLE_LIMIT = 250
RELATED_LIMIT = 1000
FINDING_LIMIT = 100
IMPACT_LIMIT = 25


def _projects(user):
    return Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)


def _table(title, rows, columns, notes):
    return {"title": title, "rows": rows,
            "columns": [{"key": key, "label": label} for key, label in columns], "notes": notes}


def quarantine_impact(code, user):
    lots = list(InventoryLot.objects.filter(lot_code__iexact=code)[:2])
    if len(lots) != 1:
        return response("Lot not found or ambiguous. Use its exact lot code.")
    lot = lots[0]
    samples = _sample_queryset(user)
    notebooks = notebooks_for_user(user) if enabled("notebook") else notebooks_for_user(user).none()
    # A row may link more than one domain: require access to every linked target.
    access = (Q(work_item__isnull=True) | Q(work_item__sample__in=samples)) & (
        Q(experiment__isnull=True) | Q(experiment__notebook__in=notebooks))
    reservations = InventoryReservation.objects.filter(
        lot=lot, status=InventoryReservation.STATUS_ACTIVE, project__in=_projects(user)
    ).filter(access).select_related("project", "work_item__sample", "experiment").order_by("pk")
    consumed = InventoryTransaction.objects.filter(lot=lot, operation=InventoryTransaction.OP_CONSUME).filter(
        access).exclude(work_item__isnull=True, experiment__isnull=True).select_related(
            "work_item__sample", "experiment").order_by("-occurred_at", "-pk")
    experiments = Experiment.objects.filter(notebook__in=notebooks,
        current_revision__links__entity_type="inventory_lot",
        current_revision__links__entity_public_id=lot.public_id).distinct().order_by("pk")
    rows, links, limited = [], {"/inventory": f"Inventory — {lot.lot_code}"}, False

    def target(row):
        labels = []
        if row.work_item_id:
            work = row.work_item
            sample = work.sample
            labels.append(f"{sample.sample_id} / {work.name} ({work.status})")
            links[f"/samples/{sample.pk}"] = sample.sample_id
        if row.experiment_id:
            labels.append(f"{row.experiment.title} ({row.experiment.status})")
            links[f"/notebook?experiment={row.experiment.public_id}"] = row.experiment.title
        return "; ".join(labels)

    for queryset, kind in [(reservations, "Active reservation"), (consumed, "Recorded past use")]:
        found = list(queryset[:IMPACT_LIMIT + 1])
        limited |= len(found) > IMPACT_LIMIT
        for row in found[:IMPACT_LIMIT]:
            label = target(row)
            if kind == "Active reservation":
                label = label or f"Project {row.project.code} (no specific work or experiment recorded)"
                links[f"/projects/{row.project_id}"] = f"Project {row.project.code}"
                detail = f"Reservation #{row.pk}: {row.quantity} {row.unit}. Review alternatives before using this lot."
            else:
                detail = f"Transaction #{row.pk}: {row.amount} {row.unit} at {row.occurred_at.isoformat()}. Review past use; this does not establish a failed result."
            rows.append({"kind": kind, "target": label, "evidence": detail})
    found = list(experiments[:IMPACT_LIMIT + 1])
    limited |= len(found) > IMPACT_LIMIT
    for experiment in found[:IMPACT_LIMIT]:
        rows.append({"kind": "Current notebook link", "target": f"{experiment.title} ({experiment.status})",
                     "evidence": "The current experiment revision links this lot. A link alone does not prove consumption or a blocked step."})
        links[f"/notebook?experiment={experiment.public_id}"] = experiment.title
    notes = ["Only accessible active reservations, consumption records and current notebook links are included. Unrecorded dependencies cannot be inferred.",
             "Evidence rows can refer to the same record more than once; row counts are not unique sample or experiment counts.",
             "This preview does not quarantine the lot, change work, or decide whether past results are valid."]
    if limited:
        notes.append(f"Partial preview: showing at most {IMPACT_LIMIT} rows per evidence category. Open the linked records for details.")
    if not enabled("notebook"):
        notes.append("Notebook checks are unavailable because that feature is disabled.")
    answer = f"Quarantine impact preview for {lot.lot_code} (current status: {lot.status}). {len(rows)} accessible evidence rows found."
    if not rows:
        answer += " No recorded accessible dependencies were found; this does not prove there is no impact."
    return response(answer, impact_preview={"lot_id": lot.pk, "truncated": limited},
        suggestions=[f"Preview quarantine impact for lot {lot.lot_code}"],
        comparison=_table("Lot quarantine impact", rows, [("kind", "Evidence type"), ("target", "Linked record"), ("evidence", "What to review")], notes),
        links=[{"label": label, "url": url} for url, label in links.items()][:100])


def project_quality(code, user):
    matches = list(_projects(user).filter(code__iexact=code).distinct()[:2])
    if len(matches) != 1:
        return response("Project not found, ambiguous or not accessible. Use its exact project code.")
    project = matches[0]
    cohort = list(_sample_queryset(user).filter(project=project).order_by("pk")[:SAMPLE_LIMIT + 1])
    samples = cohort[:SAMPLE_LIMIT]
    sample_by_id = {sample.pk: sample for sample in samples}
    required = list(FieldDefinition.objects.filter(entity_type="Sample", required=True).order_by("name"))
    metadata = {(value.entity_id, value.field_definition_id): value.value for value in FieldValue.objects.filter(
        entity_type="Sample", entity_id__in=[str(sample.pk) for sample in samples], field_definition__in=required)}
    rows, links, finding_count = [], {}, 0

    def finding(sample, kind, detail):
        nonlocal finding_count
        finding_count += 1
        if len(rows) < FINDING_LIMIT:
            rows.append({"sample": sample.sample_id, "kind": kind, "evidence": detail})
            links[f"/samples/{sample.pk}"] = sample.sample_id

    now = timezone.now()
    tolerance = timedelta(minutes=5)
    identifiers = defaultdict(list)
    for sample in samples:
        normalized = re.sub(r"[^\w]", "", sample.sample_id.casefold()).replace("_", "")
        if normalized:
            identifiers[normalized].append(sample)
        for definition in required:
            value = metadata.get((str(sample.pk), definition.pk))
            if value is None or value == "" or value == {} or (isinstance(value, str) and not value.strip()):
                finding(sample, "Missing required metadata", f"Required custom field {definition.name} is absent or empty.")
        try:
            validate_values(sample.form_schema, sample.form_values)
        except ValidationError as exc:
            finding(sample, "Invalid intake form", str(exc.detail))
        except (TypeError, KeyError, AttributeError, ValueError):
            finding(sample, "Invalid intake form", "The saved form schema or values are malformed. Review the sample form.")
        if sample.created_at > now + tolerance or sample.status_changed_at > now + tolerance:
            finding(sample, "Unusual date", f"Future sample timestamp: created {sample.created_at.isoformat()}, status changed {sample.status_changed_at.isoformat()}.")
        if sample.status_changed_at < sample.created_at - tolerance:
            finding(sample, "Unusual date", f"Status change {sample.status_changed_at.isoformat()} predates creation {sample.created_at.isoformat()} by more than five minutes.")
    for group in identifiers.values():
        if len(group) > 1:
            codes = ", ".join(sample.sample_id for sample in group[:10])
            for sample in group:
                finding(sample, "Possible duplicate identifier", f"Ignoring case and punctuation, {len(group)} sample IDs match: {codes}. Verify whether these are intentionally distinct.")
    work = list(WorkItem.objects.filter(sample_id__in=sample_by_id).order_by("pk")[:RELATED_LIMIT + 1])
    for item in work[:RELATED_LIMIT]:
        sample = sample_by_id[item.sample_id]
        if item.due_at and item.due_at < sample.created_at - tolerance:
            finding(sample, "Unusual deadline", f"Work #{item.pk} ({item.name}) is due {item.due_at.isoformat()}, before sample creation {sample.created_at.isoformat()}. Historical imports may explain this.")
    results = list(Result.objects.filter(work_item__sample_id__in=sample_by_id).select_related("work_item").order_by("pk")[:RELATED_LIMIT + 1])
    groups = defaultdict(list)
    for result in results[:RELATED_LIMIT]:
        groups[(result.work_item.analysis_code or result.work_item.work_type, result.key)].append(result)
    for (analysis, key), group in groups.items():
        units = sorted({result.unit.strip() for result in group})
        if len(units) > 1 and not all(units_compatible(units[0], unit) for unit in units[1:]):
            labels = ", ".join(unit or "<missing>" for unit in units[:10])
            if len(units) > 10:
                labels += f", … ({len(units)} distinct labels)"
            for result in group:
                finding(sample_by_id[result.work_item.sample_id], "Review result units",
                         f"Result #{result.pk}: {analysis} / {key} uses differing or missing unit labels ({labels}). Conversion equivalence is not established; verify the intended units.")
    partial = len(cohort) > SAMPLE_LIMIT or len(work) > RELATED_LIMIT or len(results) > RELATED_LIMIT
    notes = [f"Scanned {len(samples)} primary-project samples, {min(len(work), RELATED_LIMIT)} work items and {min(len(results), RELATED_LIMIT)} results in ID order.",
             "Findings are review prompts, not proof of duplicate specimens or invalid scientific results. No records were modified.",
             "Duplicate candidates use sample-ID similarity only. Unit checks compare the same analysis/work type and result key; compatible known units are allowed."]
    if partial:
        notes.append(f"Partial scan: limited to {SAMPLE_LIMIT} samples and {RELATED_LIMIT} work items/results each. Unscanned records may contain additional issues.")
    if finding_count > FINDING_LIMIT:
        notes.append(f"Showing the first {FINDING_LIMIT} of {finding_count} findings within the scanned records.")
    answer = f"Data-quality review for {project.code}: {finding_count} potential issues in the scanned records."
    if not finding_count:
        answer += " These checks found no issues in the scanned records; this is not a completeness or accuracy certification."
    return response(answer, context={"project_id": project.pk}, quality_review={"project_id": project.pk, "scanned_samples": len(samples),
        "finding_count": finding_count, "partial_scan": partial, "truncated": finding_count > FINDING_LIMIT},
        suggestions=[f"Review data quality for project {project.code}"],
        comparison=_table("Project data-quality review", rows, [("sample", "Sample"), ("kind", "Check"), ("evidence", "Evidence / review")], notes),
        links=[{"label": f"Project {project.code}", "url": f"/projects/{project.pk}"}] +
              [{"label": label, "url": url} for url, label in list(links.items())[:99]])


def route_lab_reviews(message, user):
    if not user or not user.is_authenticated:
        return None
    text = str(message).strip().rstrip(".?!")
    match = re.fullmatch(r"(?:what would be affected if (?:we|I) quarantine lot|preview (?:quarantine )?impact (?:for|of) lot) (.+)", text, re.I)
    if match:
        return quarantine_impact(match[1], user)
    match = re.fullmatch(r"(?:check project (.+?) for (?:suspicious records|data quality)|(?:review|check) data quality (?:for|in) project (.+))", text, re.I)
    if match:
        return project_quality(match[1] or match[2], user)
    return None
