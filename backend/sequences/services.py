import difflib

from django.db import transaction

from core.audit import record_audit_event

from .molecular import (
    gc_content,
    melting_temperature,
    reverse_complement,
    sequence_checksum,
    validate_alphabet,
)
from .models import Sequence, SequenceFeature, SequenceRevision, SequenceRevisionFeature


@transaction.atomic
def create_sequence_revision(
    sequence_record,
    *,
    actor,
    change_summary="",
    registry_record=None,
    audit_action="SEQUENCE_REVISION_CREATED",
):
    locked = Sequence.objects.select_for_update().get(pk=sequence_record.pk)
    cleaned = validate_alphabet(locked.sequence, locked.sequence_type)
    next_revision = (
        locked.revisions.order_by("-revision").values_list("revision", flat=True).first()
        or 0
    ) + 1
    revision = SequenceRevision.objects.create(
        sequence_record=locked,
        revision=next_revision,
        sequence_type=locked.sequence_type,
        topology=locked.topology,
        sequence=cleaned,
        checksum=sequence_checksum(cleaned, locked.sequence_type),
        change_summary=change_summary,
        registry_record=registry_record,
        source_metadata=locked.source_metadata,
        created_by=actor,
    )
    snapshots = []
    for feature in locked.features.all():
        primer_sequence = feature.primer_sequence
        primer_tm = feature.melting_temperature
        primer_gc = feature.gc_content
        if feature.feature_type == "PRIMER":
            primer_sequence = cleaned[feature.start:feature.end]
            if feature.direction == -1 and locked.sequence_type == "DNA":
                primer_sequence = reverse_complement(primer_sequence)
            if locked.sequence_type == "DNA":
                try:
                    primer_tm = melting_temperature(primer_sequence)
                except ValueError:
                    primer_tm = None
            primer_gc = gc_content(primer_sequence)
        snapshots.append(
            SequenceRevisionFeature(
                revision=revision,
                library_feature=feature.library_feature,
                feature_type=feature.feature_type,
                name=feature.name,
                start=feature.start,
                end=feature.end,
                direction=feature.direction,
                color=feature.color,
                metadata=feature.metadata,
                primer_sequence=primer_sequence,
                melting_temperature=primer_tm,
                gc_content=primer_gc,
            )
        )
    SequenceRevisionFeature.objects.bulk_create(snapshots)
    Sequence.objects.filter(pk=locked.pk).update(current_revision=revision)
    sequence_record.current_revision = revision
    record_audit_event(
        entity=sequence_record,
        action=audit_action,
        actor=actor,
        after={
            "revision": revision.revision,
            "checksum": revision.checksum,
            "topology": revision.topology,
            "registry_record": str(registry_record.public_id) if registry_record else None,
        },
        details={"change_summary": change_summary},
    )
    return revision


@transaction.atomic
def restore_sequence_revision(sequence_record, source_revision, *, actor, change_summary=""):
    if source_revision.sequence_record_id != sequence_record.id:
        raise ValueError("The revision does not belong to this sequence.")
    sequence_record.sequence_type = source_revision.sequence_type
    sequence_record.topology = source_revision.topology
    sequence_record.sequence = source_revision.sequence
    sequence_record.source_metadata = source_revision.source_metadata
    sequence_record.save(
        update_fields=["sequence_type", "topology", "sequence", "source_metadata", "updated_at"]
    )
    sequence_record.features.all().delete()
    SequenceFeature.objects.bulk_create([
        SequenceFeature(
            sequence_record=sequence_record,
            library_feature=feature.library_feature,
            feature_type=feature.feature_type,
            name=feature.name,
            start=feature.start,
            end=feature.end,
            direction=feature.direction,
            color=feature.color,
            metadata=feature.metadata,
            primer_sequence=feature.primer_sequence,
            melting_temperature=feature.melting_temperature,
            gc_content=feature.gc_content,
        )
        for feature in source_revision.features.all()
    ])
    return create_sequence_revision(
        sequence_record,
        actor=actor,
        change_summary=change_summary or f"Restored revision {source_revision.revision}",
        registry_record=source_revision.registry_record,
        audit_action="SEQUENCE_REVISION_RESTORED",
    )


@transaction.atomic
def link_revision_to_registry(source_revision, registry_record, *, actor):
    """Create a linked immutable revision without changing the source snapshot."""
    if source_revision.registry_record_id == registry_record.id:
        return source_revision
    if source_revision.registry_record_id:
        raise ValueError("This sequence revision is already linked to another registry record.")
    sequence_record = Sequence.objects.select_for_update().get(pk=source_revision.sequence_record_id)
    next_revision = (
        sequence_record.revisions.order_by("-revision").values_list("revision", flat=True).first()
        or 0
    ) + 1
    linked = SequenceRevision.objects.create(
        sequence_record=sequence_record,
        revision=next_revision,
        sequence_type=source_revision.sequence_type,
        topology=source_revision.topology,
        sequence=source_revision.sequence,
        checksum=source_revision.checksum,
        change_summary=f"Linked to registry record {registry_record.registry_id}",
        registry_record=registry_record,
        source_metadata=source_revision.source_metadata,
        created_by=actor,
    )
    SequenceRevisionFeature.objects.bulk_create([
        SequenceRevisionFeature(
            revision=linked,
            library_feature=feature.library_feature,
            feature_type=feature.feature_type,
            name=feature.name,
            start=feature.start,
            end=feature.end,
            direction=feature.direction,
            color=feature.color,
            metadata=feature.metadata,
            primer_sequence=feature.primer_sequence,
            melting_temperature=feature.melting_temperature,
            gc_content=feature.gc_content,
        )
        for feature in source_revision.features.all()
    ])
    Sequence.objects.filter(pk=sequence_record.pk).update(current_revision=linked)
    record_audit_event(
        entity=sequence_record,
        action="SEQUENCE_REGISTRY_LINKED",
        actor=actor,
        after={
            "revision": linked.revision,
            "registry_record": str(registry_record.public_id),
        },
    )
    return linked


def sequence_revision_diff(left, right):
    matcher = difflib.SequenceMatcher(a=left.sequence, b=right.sequence, autojunk=False)
    changes = []
    for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        changes.append({
            "operation": operation,
            "left": {"start": left_start, "end": left_end, "sequence": left.sequence[left_start:left_end]},
            "right": {"start": right_start, "end": right_end, "sequence": right.sequence[right_start:right_end]},
        })
    return {
        "left_revision": left.revision,
        "right_revision": right.revision,
        "left_checksum": left.checksum,
        "right_checksum": right.checksum,
        "identical": not changes,
        "changes": changes,
    }
