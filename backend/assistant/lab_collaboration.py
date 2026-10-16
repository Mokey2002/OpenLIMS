"""Reviewable collaboration drafts and evidence-based run comparisons."""
import json
import re
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core.permissions import is_admin
from inventory.models import InventoryLot
from notebook.models import Experiment
from notebook.permissions import notebooks_for_user
from pipelines.models import ProcedureDefinition
from results.models import WorkItem
from .lab_helpers import enabled, response
from .lab_reviews import _table
from .sample_operations import _sample_queryset


def workflow_draft(spec, user):
    if not is_admin(user):
        return response("Director/admin access is required to draft workflows in the workflow designer.")
    tokens = [part.strip() for part in re.split(r",\s*(?:and\s+)?|\s+then\s+|\s+and\s+", spec) if part.strip()]
    if not 1 <= len(tokens) <= 30:
        return response("Choose 1–30 active procedures, separated by commas. Use CODE@VERSION when a code has multiple versions.")
    steps = []
    for token in tokens:
        code, separator, version = token.partition("@")
        candidates = ProcedureDefinition.objects.filter(active=True, analysis__active=True).filter(Q(code__iexact=code) | Q(name__iexact=code))
        if separator:
            candidates = candidates.filter(version=version)
        matches = list(candidates[:2])
        if len(matches) != 1:
            return response(f"Procedure '{token}' was not found or is ambiguous. Use an exact active procedure code and version (CODE@VERSION). No draft was saved.")
        procedure = matches[0]
        steps.append({"procedure": procedure.pk, "name": procedure.name,
                      "code": procedure.code, "version": procedure.version})
    text = "Sequential workflow draft:\n" + "\n".join(f"{i}. {step['code']}@{step['version']} — {step['name']}" for i, step in enumerate(steps, 1))
    text += "\nReview dependencies, QC gates, conditions and automation in the designer. These are not inferred. Nothing has been saved."
    return response("Open this draft in the workflow designer, review it, choose a code/name, then save explicitly.",
                    draft={"text": text, "workflow": {"steps": steps}})


def handover(source, recipient, user):
    people = []
    for name in (source, recipient):
        matches = list(get_user_model().objects.filter(username__iexact=name, is_active=True)[:2])
        if len(matches) != 1:
            return response("Use exact active usernames for both people. A user was not found or is ambiguous.")
        people.append(matches[0])
    owner, receiver = people
    # Assignment does not grant access; all three participants must see a sample.
    samples = _sample_queryset(user).filter(pk__in=_sample_queryset(receiver).values("pk"),
                                           public_id__in=_sample_queryset(owner).values("public_id"))
    work = WorkItem.objects.filter(sample__in=samples, assigned_to=owner).exclude(status__in=["COMPLETED", "CANCELLED"])
    records = list(work.select_related("sample").order_by("due_at", "pk")[:101])
    now = timezone.now()
    lines = [f"Handover: {owner.username} → {receiver.username}", f"Snapshot: {now.isoformat()}",
             "Unfinished assigned work visible to you and both participants. Access is checked now; review again before sharing."]
    for item in records[:100]:
        due = item.due_at.isoformat() if item.due_at else "not recorded"
        flags = []
        if item.due_at and item.due_at < now:
            flags.append("OVERDUE")
        if item.status == "FAILED" or item.qc_status in {"REJECTED", "RERUN_REQUIRED"}:
            flags.append("REVIEW BLOCKER")
        lines.append(f"{item.sample.sample_id} / {item.name}: {item.status}; QC {item.qc_status}; due {due}" + (" — " + ", ".join(flags) if flags else ""))
    if not records:
        lines.append("No matching unfinished assigned work in this shared scope.")
    if len(records) > 100:
        lines.append("Partial summary: first 100 work items only.")
    lines.append("Blocker flags cover failed work and rejected/rerun QC only; dependencies and unrecorded blockers need manual review. No work was reassigned and no message was sent.")
    return response("Review this editable handover before sharing.", draft={"text": "\n".join(lines)},
                    links=[{"label": item.sample.sample_id, "url": f"/samples/{item.sample_id}"} for item in records[:100]])


def compare_runs(left, right, user):
    if not enabled("notebook"):
        return response("The notebook feature is disabled.")
    experiments = []
    for token in (left, right):
        query = Experiment.objects.filter(notebook__in=notebooks_for_user(user))
        try:
            query = query.filter(public_id=UUID(token))
        except ValueError:
            query = query.filter(title__iexact=token.strip('"'))
        matches = list(query[:2])
        if len(matches) != 1:
            return response("Experiment not found, not accessible, or title is ambiguous. Use two exact experiment public IDs.")
        experiments.append(matches[0])
    if experiments[0].pk == experiments[1].pk:
        return response("Choose two different experiments to compare.")
    snapshots = []
    partial = False
    for experiment in experiments:
        snapshot = {"Status": experiment.status}
        steps = list(experiment.workflow_steps.order_by("position")[:51])
        partial |= len(steps) > 50
        for step in steps[:50]:
            prefix = f"Step {step.position}"
            snapshot[f"{prefix}: protocol definition"] = step.definition
            snapshot[f"{prefix}: recorded parameters"] = step.values
            snapshot[f"{prefix}: completion status"] = step.status
        if experiment.current_revision_id:
            lot_ids = experiment.current_revision.links.filter(entity_type="inventory_lot").values("entity_public_id")
            lots = list(InventoryLot.objects.filter(public_id__in=lot_ids).order_by("public_id")[:101])
            partial |= len(lots) > 100
            if lots:
                snapshot["Current linked lots (not proof of use)"] = [{"id": str(lot.public_id), "code": lot.lot_code} for lot in lots[:100]]
            blocks = list(experiment.current_revision.blocks.filter(block_type="STRUCTURED_RESULT").order_by("position")[:51])
            partial |= len(blocks) > 50
            for block in blocks[:50]:
                snapshot[f"Result block {block.position} (recorded data)"] = block.data
        snapshots.append(snapshot)
    rows = []
    for key in dict.fromkeys([*snapshots[0], *snapshots[1]]):
        present = [key in snapshot for snapshot in snapshots]
        values = [json.dumps(snapshot[key], ensure_ascii=True, sort_keys=True) if found else "Not recorded" for snapshot, found in zip(snapshots, present)]
        rows.append({"field": key, "left": values[0][:4000], "right": values[1][:4000],
                     "finding": "Unknown (missing record)" if not all(present) else "Same" if values[0] == values[1] else "Different"})
        partial |= any(len(value) > 4000 for value in values)
    notes = ["Compared current workflow step definitions, recorded step parameters/status, current linked lots and structured result blocks. Steps/blocks align by position; review alignment if their order changed.",
             "Missing records are unknown. Linked lots do not prove consumption. Free text, historical revisions and external QC are not compared. Differences do not establish causes."]
    if partial:
        notes.append("Partial comparison: at most 50 steps, 100 lots and 50 result blocks per run; displayed values limited to 4000 characters.")
    return response("Recorded differences between accessible runs; no causal explanation is inferred.",
                    comparison=_table("Experiment run comparison", rows, [("field", "Recorded field"), ("left", experiments[0].title), ("right", experiments[1].title), ("finding", "Finding")], notes),
                    links=[{"label": exp.title, "url": f"/notebook?experiment={exp.public_id}"} for exp in experiments])


def route_lab_collaboration(message, user):
    text = message.strip().rstrip(".?!")
    match = re.fullmatch(r"(?:create|draft|build) (?:a )?workflow (?:with|using) (.+)", text, re.I)
    if match:
        return workflow_draft(match[1], user)
    match = re.fullmatch(r"(?:prepare|draft) ([\w.@+-]+)(?:'s|’s) handover for ([\w.@+-]+)", text, re.I)
    if match:
        return handover(match[1], match[2], user)
    match = re.fullmatch(r"(?:compare|explain differences between) (?:runs|experiments) (.+?) (?:and|vs\.?|versus) (.+)", text, re.I)
    if match:
        return compare_runs(match[1], match[2], user)
    return None
