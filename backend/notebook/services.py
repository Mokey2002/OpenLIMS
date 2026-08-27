import hashlib
import json
from io import BytesIO
from xml.sax.saxutils import escape

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit_event
from core.entities import entity_reference, get_entity_project, resolve_entity
from notifications.models import Notification

from .models import (
    Experiment,
    ExperimentBlock,
    ExperimentComment,
    ExperimentLink,
    ExperimentRevision,
    ExperimentReview,
)
from .permissions import user_can_notebook


BLOCK_TYPES = {choice[0] for choice in ExperimentBlock.TYPE_CHOICES}


def canonical_content(blocks, links):
    return json.dumps(
        {"blocks": blocks, "links": links},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def content_checksum(blocks, links):
    return hashlib.sha256(canonical_content(blocks, links).encode("utf-8")).hexdigest()


def validate_blocks(blocks):
    if not isinstance(blocks, list):
        raise ValidationError({"blocks": "Blocks must be a list."})
    cleaned = []
    for position, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValidationError({"blocks": f"Block {position + 1} must be an object."})
        block_type = str(block.get("block_type") or "").upper()
        if block_type not in BLOCK_TYPES:
            raise ValidationError({"blocks": f"Unsupported block type '{block_type}'."})
        data = block.get("data", {})
        if not isinstance(data, dict):
            raise ValidationError({"blocks": f"Block {position + 1} data must be an object."})
        cleaned.append({"position": position, "block_type": block_type, "data": data})
    return cleaned


def entity_version_snapshot(entity_type, obj):
    # The ExperimentLink row already records when the snapshot was captured.
    # Keep only stable version identity here so an unchanged autosave has the
    # same checksum and does not manufacture another revision.
    snapshot = {}
    if entity_type == "registry_record":
        version = obj.current_version
        snapshot.update(
            registry_id=obj.registry_id,
            record_version=version.version if version else None,
            record_version_public_id=str(version.public_id) if version else None,
            sequence_revision=(
                version.sequence_revision.revision if version and version.sequence_revision else None
            ),
            sequence_checksum=version.sequence_checksum if version else "",
        )
    elif entity_type == "sequence":
        revision = obj.current_revision
        snapshot.update(
            revision=revision.revision if revision else None,
            revision_public_id=str(revision.public_id) if revision else None,
            checksum=revision.checksum if revision else "",
        )
    elif entity_type == "sop_document":
        snapshot.update(document_code=obj.document_code, version=obj.version, section=obj.section)
    elif entity_type == "inventory_lot":
        snapshot.update(lot_code=obj.lot_code, quantity=str(obj.quantity), unit=obj.unit)
    elif entity_type == "sample":
        snapshot.update(sample_id=obj.sample_id, status=obj.status)
    elif entity_type == "pipeline_run":
        snapshot.update(
            template_code=obj.template_code,
            template_name=obj.template_name,
            started_at=obj.started_at.isoformat(),
        )
    elif entity_type == "work_item":
        snapshot.update(status=obj.status, updated_at=obj.updated_at.isoformat())
    elif entity_type == "result":
        snapshot.update(key=obj.key, value=obj.value, updated_at=obj.updated_at.isoformat())
    else:
        snapshot.update(model=obj._meta.label_lower)
    return snapshot


def resolve_links(links, actor, project=None, *, preserve_versions=False):
    if not isinstance(links, list):
        raise ValidationError({"links": "Links must be a list."})
    cleaned = []
    for link in links:
        entity_type = str(link.get("entity_type") or link.get("type") or "").lower()
        public_id = link.get("entity_public_id") or link.get("public_id")
        try:
            obj = resolve_entity(entity_type, public_id, actor, write=False)
        except (ValueError, LookupError, PermissionError) as exc:
            raise ValidationError({"links": str(exc)}) from exc
        reference = entity_reference(obj)
        target_project = get_entity_project(obj)
        if project is not None and target_project is not None and target_project.pk != project.pk:
            raise ValidationError({"links": f"{reference['label']} belongs to another project."})
        supplied_version = link.get("version")
        cleaned.append(
            {
                "entity_type": entity_type,
                "entity_public_id": obj.public_id,
                "relation_type": str(link.get("relation_type") or "used").lower(),
                "label": str(link.get("label") or reference["label"]),
                "version": (
                    supplied_version
                    if preserve_versions and isinstance(supplied_version, dict)
                    else entity_version_snapshot(entity_type, obj)
                ),
            }
        )
    return cleaned


def revision_payload(revision):
    return {
        "number": revision.number,
        "public_id": str(revision.public_id),
        "checksum": revision.checksum,
        "blocks": [
            {"position": block.position, "block_type": block.block_type, "data": block.data}
            for block in revision.blocks.all()
        ],
        "links": [
            {
                "entity_type": link.entity_type,
                "entity_public_id": str(link.entity_public_id),
                "relation_type": link.relation_type,
                "label": link.label,
                "version": link.version,
            }
            for link in revision.links.all()
        ],
    }


@transaction.atomic
def create_revision(
    *, experiment, actor, blocks, links, reason="Autosave", restored_from=None,
    preserve_link_versions=False,
):
    experiment = Experiment.objects.select_for_update().select_related("notebook").get(pk=experiment.pk)
    if not user_can_notebook(actor, experiment.notebook, "write"):
        raise PermissionDenied("You cannot edit this experiment.")
    if experiment.status in {Experiment.STATUS_REVIEWED, Experiment.STATUS_LOCKED}:
        raise ValidationError({"status": "Reviewed or locked experiments cannot be modified; clone the experiment instead."})

    cleaned_blocks = validate_blocks(blocks)
    cleaned_links = resolve_links(
        links,
        actor,
        experiment.project,
        preserve_versions=preserve_link_versions,
    )
    checksum_links = [
        {**link, "entity_public_id": str(link["entity_public_id"])} for link in cleaned_links
    ]
    checksum = content_checksum(cleaned_blocks, checksum_links)
    if experiment.current_revision and experiment.current_revision.checksum == checksum:
        return experiment.current_revision, False

    previous = experiment.current_revision
    number = (previous.number if previous else 0) + 1
    revision = ExperimentRevision.objects.create(
        experiment=experiment,
        number=number,
        checksum=checksum,
        change_summary=str(reason or "Autosave"),
        parent_revision=previous,
        restored_from=restored_from,
        created_by=actor,
    )
    ExperimentBlock.objects.bulk_create(
        [
            ExperimentBlock(
                revision=revision,
                position=block["position"],
                block_type=block["block_type"],
                data=block["data"],
            )
            for block in cleaned_blocks
        ]
    )
    ExperimentLink.objects.bulk_create(
        [
            ExperimentLink(
                revision=revision,
                entity_type=link["entity_type"],
                entity_public_id=link["entity_public_id"],
                relation_type=link["relation_type"],
                label=link["label"],
                version=link["version"],
                created_by=actor,
            )
            for link in cleaned_links
        ]
    )
    updates = {"current_revision": revision, "updated_at": timezone.now()}
    if experiment.status == Experiment.STATUS_DRAFT:
        updates["status"] = Experiment.STATUS_IN_PROGRESS
    Experiment.objects.filter(pk=experiment.pk).update(**updates)
    experiment.refresh_from_db()
    record_audit_event(
        entity=experiment,
        action="EXPERIMENT_REVISION_CREATED",
        actor=actor,
        reason=reason,
        before={"revision": previous.number if previous else None},
        after={"revision": revision.number, "checksum": checksum},
        details={"block_count": len(cleaned_blocks), "link_count": len(cleaned_links)},
    )
    return revision, True


@transaction.atomic
def restore_revision(*, experiment, revision, actor, reason):
    if revision.experiment_id != experiment.pk:
        raise ValidationError({"revision": "The revision does not belong to this experiment."})
    payload = revision_payload(revision)
    return create_revision(
        experiment=experiment,
        actor=actor,
        blocks=payload["blocks"],
        links=payload["links"],
        reason=reason or f"Restored revision {revision.number}",
        restored_from=revision,
        preserve_link_versions=True,
    )


@transaction.atomic
def review_experiment(*, experiment, actor, decision, comment="", signed_name=""):
    experiment = Experiment.objects.select_for_update().select_related("notebook", "current_revision").get(pk=experiment.pk)
    if not user_can_notebook(actor, experiment.notebook, "review"):
        raise PermissionDenied("You cannot review this experiment.")
    if experiment.status != Experiment.STATUS_COMPLETED or not experiment.current_revision:
        raise ValidationError({"status": "Only completed experiments can be reviewed."})
    decision = str(decision or "").upper()
    if decision not in {ExperimentReview.DECISION_APPROVED, ExperimentReview.DECISION_CHANGES}:
        raise ValidationError({"decision": "Choose APPROVED or CHANGES_REQUESTED."})
    review = ExperimentReview.objects.create(
        experiment=experiment,
        revision=experiment.current_revision,
        reviewer=actor,
        decision=decision,
        comment=comment,
        signed_name=signed_name or actor.get_full_name() or actor.username,
        content_checksum=experiment.current_revision.checksum,
    )
    if decision == ExperimentReview.DECISION_APPROVED:
        experiment.status = Experiment.STATUS_REVIEWED
        experiment.reviewed_at = review.reviewed_at
        fields = ["status", "reviewed_at", "updated_at"]
    else:
        experiment.status = Experiment.STATUS_IN_PROGRESS
        fields = ["status", "updated_at"]
    experiment.save(update_fields=fields)
    record_audit_event(
        entity=experiment,
        action="EXPERIMENT_REVIEWED",
        actor=actor,
        reason=comment,
        after={"decision": decision, "revision": experiment.current_revision.number, "checksum": review.content_checksum},
    )
    return review


@transaction.atomic
def lock_experiment(*, experiment, actor, reason=""):
    experiment = Experiment.objects.select_for_update().select_related("notebook", "current_revision").get(pk=experiment.pk)
    if not user_can_notebook(actor, experiment.notebook, "lock"):
        raise PermissionDenied("You cannot lock this experiment.")
    if experiment.status != Experiment.STATUS_REVIEWED:
        raise ValidationError({"status": "Only reviewed experiments can be locked."})
    if not experiment.reviews.filter(
        revision=experiment.current_revision,
        decision=ExperimentReview.DECISION_APPROVED,
        content_checksum=experiment.current_revision.checksum,
    ).exists():
        raise ValidationError({"review": "The current revision has no valid approval."})
    experiment.status = Experiment.STATUS_LOCKED
    experiment.locked_at = timezone.now()
    experiment.locked_by = actor
    experiment.save(update_fields=["status", "locked_at", "locked_by", "updated_at"])
    record_audit_event(
        entity=experiment,
        action="EXPERIMENT_LOCKED",
        actor=actor,
        reason=reason,
        after={"revision": experiment.current_revision.number, "checksum": experiment.current_revision.checksum},
    )
    return experiment


def notify_comment(comment):
    recipients = set(comment.mentions.all())
    if comment.assigned_to_id:
        recipients.add(comment.assigned_to)
    recipients.discard(comment.author)
    for user in recipients:
        Notification.objects.create(
            user=user,
            title=f"Experiment comment: {comment.experiment.title}",
            message=comment.body[:500],
            link=f"/notebook?experiment={comment.experiment.public_id}",
        )


def render_experiment_pdf(experiment):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=experiment.title,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(experiment.title), styles["Title"]), Spacer(1, 8)]
    current = experiment.current_revision
    metadata = [
        ["Status", experiment.status],
        ["Notebook", experiment.notebook.name],
        ["Project", experiment.project.code if experiment.project else "Private/team"],
        ["Author", experiment.created_by.get_full_name() or experiment.created_by.username],
        ["Created", experiment.created_at.isoformat()],
        ["Revision", str(current.number if current else "-")],
        ["Checksum", current.checksum if current else "-"],
    ]
    table = Table(metadata, colWidths=[1.2 * inch, 5.8 * inch])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([table, Spacer(1, 14)])

    if current:
        for block in current.blocks.all():
            data = block.data or {}
            if block.block_type == ExperimentBlock.TYPE_HEADING:
                story.append(Paragraph(escape(str(data.get("text") or "")), styles["Heading2"]))
            elif block.block_type == ExperimentBlock.TYPE_TABLE:
                rows = data.get("rows") or []
                if rows:
                    block_table = Table([[str(cell) for cell in row] for row in rows], repeatRows=1)
                    block_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
                    story.append(block_table)
            else:
                text = data.get("text") or data.get("expression") or data.get("name") or json.dumps(data, default=str)
                story.append(Paragraph(f"<b>{escape(block.get_block_type_display())}:</b> {escape(str(text))}", styles["BodyText"]))
            story.append(Spacer(1, 6))

        story.extend([Spacer(1, 10), Paragraph("Linked records and version provenance", styles["Heading2"])])
        link_rows = [["Type", "Record", "Captured version"]]
        for link in current.links.all():
            link_rows.append([link.entity_type, link.label, json.dumps(link.version, sort_keys=True, default=str)])
        if len(link_rows) > 1:
            link_table = Table(link_rows, colWidths=[1.1 * inch, 2.2 * inch, 3.7 * inch], repeatRows=1)
            link_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(link_table)

    story.extend([PageBreak(), Paragraph("Revision and review history", styles["Heading2"])])
    history_rows = [["Revision", "Author", "Timestamp", "Change", "Checksum"]]
    for revision in experiment.revisions.select_related("created_by").order_by("number"):
        history_rows.append([
            str(revision.number),
            revision.created_by.username if revision.created_by else "System",
            revision.created_at.isoformat(),
            revision.change_summary,
            revision.checksum,
        ])
    history = Table(history_rows, colWidths=[0.55 * inch, 0.9 * inch, 1.35 * inch, 1.8 * inch, 2.4 * inch], repeatRows=1)
    history.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([history, Spacer(1, 12), Paragraph("Review sign-off", styles["Heading2"])])
    review_rows = [["Reviewer", "Decision", "Timestamp", "Signed name", "Revision checksum"]]
    for review in experiment.reviews.select_related("reviewer", "revision").all():
        review_rows.append([
            review.reviewer.username,
            review.decision,
            review.reviewed_at.isoformat(),
            review.signed_name,
            review.content_checksum,
        ])
    if len(review_rows) == 1:
        review_rows.append(["-", "Not reviewed", "-", "-", "-"])
    reviews = Table(review_rows, colWidths=[1 * inch, 1 * inch, 1.4 * inch, 1.5 * inch, 2.1 * inch], repeatRows=1)
    reviews.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(reviews)
    document.build(story)
    return buffer.getvalue()
