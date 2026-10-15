"""Deterministic lab helpers. Resolve permissions before collecting evidence."""
import re
from decimal import Decimal

from django.conf import settings
from django.db.models import CharField, Count, Prefetch, Q
from django.db.models.functions import Cast
from django.utils import timezone

from core.permissions import is_admin
from events.models import Event
from inventory.models import InventoryLot, InventoryReservation
from inventory.units import UnitConversionError, convert_quantity, units_compatible
from notebook.models import Experiment
from notebook.permissions import notebooks_for_user
from pipelines.models import ProcedureDefinition
from projects.models import Project
from results.models import Result, WorkItem
from settings_app.models import SystemSettings

from .sample_operations import _sample_queryset


def response(answer, **extra):
    return {"answer": answer, "skip_llm": True, "links": [], "suggestions": [],
            "context": {}, "replace_context": True, **extra}


def enabled(feature):
    return (not getattr(settings, "OPENLIMS_ENFORCE_FEATURE_FLAGS", True)
            or SystemSettings.load().feature_flags.get(feature, False))


def sample_history(code, user):
    sample = _sample_queryset(user).filter(sample_id__iexact=code).first()
    if not sample:
        return response("Sample not found or not accessible. Use its exact sample ID.")
    work = WorkItem.objects.filter(sample=sample)
    events = Event.objects.filter(
        Q(entity_type__iexact="sample", entity_id__in=[str(sample.pk), str(sample.public_id)])
        | Q(entity_type__iexact="workitem", entity_id__in=work.annotate(key=Cast("id", CharField())).values("key"))
        | Q(entity_type__iexact="workitem", entity_id__in=work.annotate(key=Cast("public_id", CharField())).values("key"))
    ).select_related("actor").order_by("-timestamp", "-pk")
    # Never include arbitrary audit payloads: they may contain former project details.
    rows = [{"at": event.timestamp.isoformat(), "action": event.action,
             "actor": event.actor.username if event.actor else "Unknown",
             "source": "audit"} for event in events[:51]]
    custody = sample.custody_events.select_related("performed_by").order_by("-occurred_at", "-pk")
    rows += [{"at": event.occurred_at.isoformat(), "action": event.action,
              "actor": event.performed_by.username, "source": "custody"} for event in custody[:51]]
    rows.sort(key=lambda row: row["at"], reverse=True)
    truncated = len(rows) > 50
    rows = rows[:50]
    lines = [f"{sample.sample_id}: current status {sample.status}.",
             "Recorded history (newest first):"]
    lines.extend(f"{row['at']} — {row['action']} — {row['actor']} ({row['source']})" for row in rows)
    if not rows:
        lines.append("No audit or custody events recorded.")
    if truncated:
        lines.append("Showing the latest 50 events. Open the sample for full history.")
    counts = work.values("status", "qc_status").annotate(total=Count("id"))
    lines.extend(f"Current work: {row['total']} {row['status']}, QC {row['qc_status']}." for row in counts)
    results = list(Result.objects.filter(work_item__in=work).order_by("-updated_at", "-pk")[:11])
    if results:
        lines.append("Current result values (not historical values):")
    lines.extend(f"{result.key}: {result.value} {result.unit} — QC {result.qc_status}; last updated {result.updated_at.isoformat()}." for result in results[:10])
    if len(results) > 10:
        lines.append("Showing the latest 10 results; open the sample for all results.")
    return response("\n".join(lines), history={"events": rows, "truncated": truncated},
                    links=[{"label": sample.sample_id, "url": f"/samples/{sample.pk}"}])


def similar_experiments(topic, user):
    if not enabled("notebook"):
        return response("The notebook feature is disabled.")
    words = list(dict.fromkeys(re.findall(r"[\w-]+", topic.lower())))
    if not words or len(words) > 12:
        return response("Give one short topic (up to 12 words), for example: Find similar experiments about plasma extraction.")
    # Search current content only. Template and linked-record permissions must not
    # be inherited from the experiment's notebook.
    experiments = Experiment.objects.filter(notebook__in=notebooks_for_user(user))
    for word in words:
        experiments = experiments.filter(Q(title__icontains=word) | Q(template__name__icontains=word, template__notebook__in=notebooks_for_user(user))
                                         | Q(current_revision__blocks__data__icontains=word))
    found = list(experiments.distinct().order_by("-updated_at", "-pk")[:21])
    lines = ["Related experiments by title, current content or accessible template keyword match; similarity is not a scientific equivalence assessment."]
    lines.extend(f"{row.title} — {row.status}" for row in found[:20])
    if not found:
        lines.append("No accessible experiments matched every keyword. Try fewer terms.")
    if len(found) > 20:
        lines.append("Showing the latest 20 matches; narrow the topic for more specific results.")
    return response("\n".join(lines), links=[{"label": row.title,
                    "url": f"/notebook?experiment={row.public_id}"} for row in found[:20]])


def inventory_plan(count, code, version, user):
    if count < 1 or count > 100000:
        return response("Choose a sample count between 1 and 100000.")
    procedures = ProcedureDefinition.objects.filter(code__iexact=code, active=True)
    if version:
        procedures = procedures.filter(version=version)
    matches = list(procedures[:2])
    if len(matches) != 1:
        return response("Procedure not found or multiple active versions exist. Specify its exact code and version, e.g. Plan reagents for 30 samples using procedure EXTRACT version 1.")
    procedure = matches[0]
    requirements = list(procedure.reagent_requirements.select_related("item").order_by("item__code"))
    if not requirements:
        return response(f"No per-sample reagent quantities are configured for {procedure.code} version {procedure.version}. An administrator must configure these before stock sufficiency can be calculated.")
    rows = []
    for requirement in requirements:
        if (not requirement.quantity_per_sample.is_finite() or requirement.quantity_per_sample <= 0
                or not units_compatible(requirement.unit, requirement.item.default_unit)):
            return response(f"Invalid reagent configuration for {requirement.item.code}. An administrator must correct the positive per-sample quantity and compatible unit before planning.")
        needed = requirement.quantity_per_sample * count
        available = Decimal("0")
        invalid = False
        lots = InventoryLot.objects.filter(item=requirement.item, status=InventoryLot.STATUS_ACTIVE).filter(
            Q(expiration_date__isnull=True) | Q(expiration_date__gte=timezone.localdate())).prefetch_related(
                Prefetch("reservations", queryset=InventoryReservation.objects.filter(status=InventoryReservation.STATUS_ACTIVE), to_attr="planning_reservations"))
        for lot in lots:
            try:
                if not lot.quantity.is_finite() or lot.quantity < 0:
                    raise ValueError("Invalid stock quantity")
                reserved = Decimal("0")
                for reservation in lot.planning_reservations:
                    if not reservation.quantity.is_finite() or reservation.quantity <= 0:
                        raise ValueError("Invalid reservation quantity")
                    reserved += convert_quantity(reservation.quantity, reservation.unit, lot.unit)
                if reserved > lot.quantity:
                    raise ValueError("Reservations exceed stock")
                available += convert_quantity(lot.quantity - reserved, lot.unit, requirement.unit)
            except (UnitConversionError, ValueError, ArithmeticError):
                invalid = True
        rows.append({"reagent": requirement.item.code, "required": str(needed),
                     "available": None if invalid else str(available), "unit": requirement.unit,
                     "shortfall": None if invalid else str(max(Decimal("0"), needed - available)),
                     "status": "Unknown: invalid stock, reservations or units" if invalid else ("Enough" if available >= needed else "Short")})
    lines = [f"Reagent plan: {count} samples, {procedure.code} version {procedure.version}."]
    lines.extend(f"{r['reagent']}: need {r['required']} {r['unit']}; available {r['available'] if r['available'] is not None else 'unknown'}; {r['status']}." for r in rows)
    lines.append("Available stock excludes active reservations, expired and non-active lots. Quantities cover configured reagents only; no allowance for controls, repeats or waste. This is a live estimate, not a reservation.")
    return response("\n".join(lines), inventory_plan={"rows": rows}, links=[{"label": "Inventory", "url": "/inventory"}])


def project_update(code, user):
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    project = projects.filter(code__iexact=code).first()
    if not project:
        return response("Project not found or not accessible. Use its exact project code.")
    samples = _sample_queryset(user).filter(project=project)
    work = WorkItem.objects.filter(sample__in=samples)
    active = work.exclude(status__in=[WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED])
    statuses = list(samples.values("status").annotate(total=Count("id")).order_by("status"))
    total = sum(row["total"] for row in statuses)
    text = (f"Project {project.code} — progress snapshot as of {timezone.now().isoformat()}.\n"
            f"{total} samples: " + (", ".join(f"{r['total']} {r['status']}" for r in statuses) or "none") + ".\n"
            f"{work.filter(status=WorkItem.STATUS_COMPLETED).count()} completed work items; "
            f"{active.count()} open, including {active.filter(due_at__lt=timezone.now()).count()} overdue "
            f"and {active.filter(assigned_to__isnull=True).count()} unassigned.\n"
            f"{work.filter(qc_status=WorkItem.QC_REJECTED).count()} work items have rejected QC.\n"
            "Counts cover samples owned by this project and reflect current records, not changes over a reporting period.")
    return response("Review and edit this project update before sharing.", draft={"text": text},
                    links=[{"label": f"Project {project.code}", "url": f"/projects/{project.pk}"}])


def route_lab_helpers(message, user):
    text = str(message).strip().rstrip(".?!")
    if not user or not user.is_authenticated:
        return None
    match = re.fullmatch(r"(?:what happened to|(?:show |summarize )?(?:the )?history (?:of|for)) sample ([\w-]+)", text, re.I)
    if match:
        return sample_history(match[1], user)
    match = re.fullmatch(r"(?:find|show) (?:similar|related) experiments (?:about|for|on) (.+)", text, re.I)
    if match:
        return similar_experiments(match[1], user)
    match = re.fullmatch(r"(?:plan reagents|do we have enough reagents) for (\d+) samples (?:using|with) (?:procedure|protocol) ([\w-]+)(?: version ([\w.-]+))?", text, re.I)
    if match:
        return inventory_plan(int(match[1]), match[2], match[3], user)
    match = re.fullmatch(r"(?:draft|write) (?:a )?(?:short )?(?:progress |project )?update for project ([\w-]+)", text, re.I)
    if match:
        return project_update(match[1], user)
    return None
