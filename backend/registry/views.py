from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.audit import record_audit_event
from core.entities import user_can_access_entity
from core.permissions import (
    IsAuthenticatedReadOnlyAdminWrite,
    IsAuthenticatedReadOnlyOrTechAdminWrite,
    is_admin,
)

from .models import (
    RegistrationReview,
    RegistryRecord,
    RegistryRelationship,
    RegistrySchema,
)
from .serializers import (
    RegistryRecordSerializer,
    RegistryRecordVersionSerializer,
    RegistryRelationshipSerializer,
    RegistrySchemaSerializer,
)
from .services import (
    create_record_version,
    duplicate_matches,
    registry_records_for_user,
    user_can_write_record,
)


class RegistrySchemaViewSet(viewsets.ModelViewSet):
    serializer_class = RegistrySchemaSerializer
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]

    def get_queryset(self):
        queryset = RegistrySchema.objects.select_related("created_by").all()
        entity_type = self.request.query_params.get("entity_type")
        active = self.request.query_params.get("active")
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)
        if active in {"true", "false"}:
            queryset = queryset.filter(active=active == "true")
        return queryset

    def perform_destroy(self, instance):
        if instance.records.exists() or instance.record_versions.exists():
            raise serializers.ValidationError(
                "Schemas referenced by registry history cannot be deleted; deactivate them instead."
            )
        instance.delete()

    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, pk=None):
        source = self.get_object()
        next_version = (
            RegistrySchema.objects.filter(code=source.code)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        ) + 1
        payload = {
            "code": source.code,
            "name": request.data.get("name", source.name),
            "entity_type": source.entity_type,
            "version": next_version,
            "id_prefix": request.data.get("id_prefix", source.id_prefix),
            "description": request.data.get("description", source.description),
            "schema": request.data.get("schema", source.schema),
            "matching_fields": request.data.get("matching_fields", source.matching_fields),
            "active": request.data.get("active", True),
        }
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        schema = serializer.save()
        return Response(self.get_serializer(schema).data, status=status.HTTP_201_CREATED)


class RegistryRecordViewSet(viewsets.ModelViewSet):
    serializer_class = RegistryRecordSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    def get_queryset(self):
        queryset = (
            registry_records_for_user(self.request.user)
            .select_related("schema", "project", "owner", "current_version")
            .prefetch_related("aliases", "versions__created_by", "reviews__reviewer")
        )
        schema = self.request.query_params.get("schema")
        entity_type = self.request.query_params.get("entity_type")
        lifecycle_status = self.request.query_params.get("status")
        project = self.request.query_params.get("project")
        search = self.request.query_params.get("search")
        if schema:
            queryset = queryset.filter(schema_id=schema)
        if entity_type:
            queryset = queryset.filter(schema__entity_type=entity_type)
        if lifecycle_status:
            queryset = queryset.filter(lifecycle_status=lifecycle_status)
        if project:
            queryset = queryset.filter(project_id=project)
        if search:
            queryset = queryset.filter(
                Q(registry_id__icontains=search)
                | Q(name__icontains=search)
                | Q(catalog_number__icontains=search)
                | Q(aliases__alias__icontains=search)
            ).distinct()
        return queryset

    def _require_write(self, record):
        if not user_can_write_record(self.request.user, record):
            raise PermissionDenied("You cannot modify this registry record.")

    def perform_update(self, serializer):
        self._require_write(serializer.instance)
        before = {
            "name": serializer.instance.name,
            "description": serializer.instance.description,
            "tags": serializer.instance.tags,
        }
        record = serializer.save()
        record_audit_event(
            entity=record,
            action="REGISTRY_RECORD_UPDATED",
            actor=self.request.user,
            before=before,
            after={"name": record.name, "description": record.description, "tags": record.tags},
        )

    def perform_destroy(self, instance):
        raise serializers.ValidationError(
            "Registry records preserve history and cannot be deleted. Retire the record instead."
        )

    @action(detail=False, methods=["post"], url_path="duplicate-check")
    def duplicate_check(self, request):
        schema = RegistrySchema.objects.filter(pk=request.data.get("schema")).first()
        if not schema:
            return Response({"schema": "Registry schema not found."}, status=400)
        sequence_revision = request.data.get("sequence_revision")
        checksum = ""
        if sequence_revision:
            from sequences.models import SequenceRevision

            revision = SequenceRevision.objects.filter(pk=sequence_revision).first()
            if revision and not user_can_access_entity(request.user, revision.sequence_record):
                revision = None
            checksum = revision.checksum if revision else ""
        matches = duplicate_matches(
            user=request.user,
            schema=schema,
            registry_id=request.data.get("registry_id", ""),
            aliases=request.data.get("aliases", []),
            catalog_number=request.data.get("catalog_number", ""),
            sequence_checksum=checksum,
            data=request.data.get("data", {}),
        )
        return Response({"duplicate": bool(matches), "matches": matches})

    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, pk=None):
        record = self.get_object()
        self._require_write(record)
        if record.lifecycle_status == RegistryRecord.STATUS_RETIRED:
            raise serializers.ValidationError("Retired records cannot receive new versions.")
        schema = RegistrySchema.objects.filter(
            pk=request.data.get("schema", record.schema_id)
        ).first()
        if not schema or schema.code != record.schema.code:
            raise serializers.ValidationError({"schema": "Choose a version of the same registry schema."})
        sequence_revision = None
        if request.data.get("sequence_revision"):
            from sequences.models import SequenceRevision

            sequence_revision = SequenceRevision.objects.filter(
                pk=request.data["sequence_revision"]
            ).first()
            if not sequence_revision:
                raise serializers.ValidationError({"sequence_revision": "Sequence revision not found."})
            if not user_can_access_entity(request.user, sequence_revision.sequence_record, write=True):
                raise PermissionDenied("You cannot link this sequence revision.")
        version = create_record_version(
            record,
            data=request.data.get("data", record.current_version.data if record.current_version else {}),
            actor=request.user,
            schema=schema,
            sequence_revision=sequence_revision or (
                record.current_version.sequence_revision if record.current_version else None
            ),
            change_summary=request.data.get("change_summary", ""),
        )
        return Response(RegistryRecordVersionSerializer(version).data, status=201)

    @action(detail=True, methods=["get"], url_path="duplicates")
    def duplicates(self, request, pk=None):
        record = self.get_object()
        version = record.current_version
        matches = duplicate_matches(
            user=request.user,
            schema=record.schema,
            registry_id=record.registry_id,
            aliases=record.aliases.values_list("alias", flat=True),
            catalog_number=record.catalog_number,
            sequence_checksum=version.sequence_checksum if version else "",
            data=version.data if version else {},
            exclude_record=record,
        )
        return Response({"duplicate": bool(matches), "matches": matches})

    @action(detail=True, methods=["post"], url_path="submit-review")
    def submit_review(self, request, pk=None):
        record = self.get_object()
        self._require_write(record)
        if record.lifecycle_status != RegistryRecord.STATUS_DRAFT:
            raise serializers.ValidationError("Only draft records can be submitted for review.")
        if not record.current_version:
            raise serializers.ValidationError("Create a record version before review.")
        matches = duplicate_matches(
            user=request.user,
            schema=record.schema,
            registry_id=record.registry_id,
            aliases=record.aliases.values_list("alias", flat=True),
            catalog_number=record.catalog_number,
            sequence_checksum=record.current_version.sequence_checksum,
            data=record.current_version.data,
            exclude_record=record,
        )
        if matches:
            return Response(
                {"detail": "Resolve potential duplicates before registration.", "duplicates": matches},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            review = RegistrationReview.objects.create(
                record=record,
                version=record.current_version,
                requested_by=request.user,
                comments=request.data.get("comments", ""),
            )
            record.lifecycle_status = RegistryRecord.STATUS_IN_REVIEW
            record.save(update_fields=["lifecycle_status", "updated_at"])
        record_audit_event(
            entity=record,
            action="REGISTRATION_SUBMITTED",
            actor=request.user,
            after={"status": record.lifecycle_status, "version": record.current_version.version},
        )
        return Response({"review_public_id": str(review.public_id), "status": record.lifecycle_status})

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        if not is_admin(request.user):
            raise PermissionDenied("Only a director can approve or reject registration.")
        record = self.get_object()
        if record.lifecycle_status != RegistryRecord.STATUS_IN_REVIEW:
            raise serializers.ValidationError("This record is not awaiting review.")
        decision = str(request.data.get("decision", "")).upper()
        if decision not in {RegistrationReview.DECISION_APPROVED, RegistrationReview.DECISION_REJECTED}:
            raise serializers.ValidationError({"decision": "Choose APPROVED or REJECTED."})
        review = record.reviews.filter(decision=RegistrationReview.DECISION_PENDING).first()
        if not review:
            raise serializers.ValidationError("Pending review not found.")
        if decision == RegistrationReview.DECISION_APPROVED:
            matches = duplicate_matches(
                user=request.user,
                schema=record.schema,
                registry_id=record.registry_id,
                aliases=record.aliases.values_list("alias", flat=True),
                catalog_number=record.catalog_number,
                sequence_checksum=record.current_version.sequence_checksum,
                data=record.current_version.data,
                exclude_record=record,
            )
            if matches:
                return Response(
                    {"detail": "Potential duplicates appeared after submission.", "duplicates": matches},
                    status=status.HTTP_409_CONFLICT,
                )
        with transaction.atomic():
            review.decision = decision
            review.reviewer = request.user
            review.comments = request.data.get("comments", review.comments)
            review.reviewed_at = timezone.now()
            review.save(update_fields=["decision", "reviewer", "comments", "reviewed_at"])
            if decision == RegistrationReview.DECISION_APPROVED:
                record.lifecycle_status = RegistryRecord.STATUS_REGISTERED
                record.registered_at = timezone.now()
                record.save(update_fields=["lifecycle_status", "registered_at", "updated_at"])
            else:
                record.lifecycle_status = RegistryRecord.STATUS_DRAFT
                record.save(update_fields=["lifecycle_status", "updated_at"])
        record_audit_event(
            entity=record,
            action="REGISTRATION_REVIEWED",
            actor=request.user,
            after={"status": record.lifecycle_status, "decision": decision},
            details={"comments": review.comments},
        )
        return Response({"status": record.lifecycle_status, "decision": decision})

    @action(detail=True, methods=["post"], url_path="retire")
    def retire(self, request, pk=None):
        record = self.get_object()
        self._require_write(record)
        if record.lifecycle_status != RegistryRecord.STATUS_REGISTERED:
            raise serializers.ValidationError("Only registered records can be retired.")
        record.lifecycle_status = RegistryRecord.STATUS_RETIRED
        record.retired_at = timezone.now()
        record.save(update_fields=["lifecycle_status", "retired_at", "updated_at"])
        record_audit_event(
            entity=record,
            action="REGISTRY_RECORD_RETIRED",
            actor=request.user,
            reason=request.data.get("reason", ""),
            after={"status": record.lifecycle_status},
        )
        return Response({"status": record.lifecycle_status})


class RegistryRelationshipViewSet(viewsets.ModelViewSet):
    serializer_class = RegistryRelationshipSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    def get_queryset(self):
        allowed = registry_records_for_user(self.request.user)
        queryset = RegistryRelationship.objects.filter(
            source__in=allowed, target__in=allowed
        ).select_related("source", "target", "created_by")
        record = self.request.query_params.get("record")
        if record:
            queryset = queryset.filter(Q(source_id=record) | Q(target_id=record))
        return queryset

    def perform_create(self, serializer):
        source = serializer.validated_data["source"]
        target = serializer.validated_data["target"]
        if not user_can_write_record(self.request.user, source) or not user_can_write_record(self.request.user, target):
            raise PermissionDenied("You cannot relate one or more selected records.")
        relationship = serializer.save()
        record_audit_event(
            entity=source,
            action="REGISTRY_RELATION_CREATED",
            actor=self.request.user,
            after={
                "relationship_public_id": str(relationship.public_id),
                "target_public_id": str(target.public_id),
                "relationship_type": relationship.relationship_type,
            },
        )

    def perform_destroy(self, instance):
        if not user_can_write_record(self.request.user, instance.source):
            raise PermissionDenied("You cannot remove this relationship.")
        source = instance.source
        public_id = str(instance.public_id)
        instance.delete()
        record_audit_event(
            entity=source,
            action="REGISTRY_RELATION_DELETED",
            actor=self.request.user,
            before={"relationship_public_id": public_id},
        )
