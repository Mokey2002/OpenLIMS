from django.db.models import Q
from django.http import HttpResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.audit import record_audit_event
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from core.project_access import get_project_access_queryset

from .file_formats import export_sequence_revision, parse_sequence_file
from .molecular import (
    RESTRICTION_ENZYMES,
    find_orfs,
    gc_content,
    melting_temperature,
    molecular_weight,
    restriction_sites,
    reverse_complement,
    transcribe,
    translate,
    virtual_digest,
)
from .models import ConstructAssemblyPlan, Sequence, SequenceFeatureLibrary, SequenceRevision
from .serializers import (
    ConstructAssemblyPlanSerializer,
    SequenceFeatureLibrarySerializer,
    SequenceRevisionSerializer,
    SequenceSerializer,
)
from .services import create_sequence_revision, restore_sequence_revision, sequence_revision_diff


class SequenceViewSet(viewsets.ModelViewSet):
    serializer_class = SequenceSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = (
            Sequence.objects.select_related(
                "project", "sample", "created_by", "current_revision",
                "current_revision__registry_record",
            )
            .prefetch_related("features__library_feature", "revisions__features")
            .all()
        )
        queryset = get_project_access_queryset(
            queryset,
            self.request.user,
            project_lookup="project",
            owner_lookup="created_by",
        )
        project_id = self.request.query_params.get("project")
        sample_id = self.request.query_params.get("sample")
        registry_record = self.request.query_params.get("registry_record")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)
        if registry_record:
            queryset = queryset.filter(revisions__registry_record_id=registry_record).distinct()
        return queryset

    def perform_update(self, serializer):
        before_revision = serializer.instance.current_revision_id
        sequence_record = serializer.save()
        if sequence_record.current_revision_id == before_revision:
            record_audit_event(
                entity=sequence_record,
                action="SEQUENCE_METADATA_UPDATED",
                actor=self.request.user,
                after={"name": sequence_record.name, "description": sequence_record.description},
            )

    def perform_destroy(self, instance):
        if instance.revisions.filter(registry_record__isnull=False).exists():
            raise serializers.ValidationError(
                "Sequences linked to Registry history cannot be deleted."
            )
        instance.delete()

    @action(detail=True, methods=["get"], url_path="workspace")
    def workspace(self, request, pk=None):
        sequence_record = self.get_object()
        data = self.get_serializer(sequence_record).data
        features = data.get("features", [])
        for output, feature_type in [
            ("annotations", "ANNOTATION"),
            ("primers", "PRIMER"),
            ("translations", "TRANSLATION"),
            ("highlights", "HIGHLIGHT"),
        ]:
            data[output] = [
                self._to_seqviz_feature(feature)
                for feature in features
                if feature["feature_type"] == feature_type
            ]
        return Response(data)

    @staticmethod
    def _to_seqviz_feature(feature):
        return {
            "id": feature["id"],
            "name": feature.get("name") or "",
            "start": feature["start"],
            "end": feature["end"],
            "direction": feature["direction"],
            "color": feature["color"],
            **(feature.get("metadata") or {}),
        }

    @action(detail=True, methods=["get"], url_path="revisions")
    def revisions(self, request, pk=None):
        sequence_record = self.get_object()
        queryset = sequence_record.revisions.select_related(
            "created_by", "registry_record"
        ).prefetch_related("features")
        return Response(SequenceRevisionSerializer(queryset, many=True).data)

    @action(detail=True, methods=["get"], url_path="revision-diff")
    def revision_diff(self, request, pk=None):
        sequence_record = self.get_object()
        left = sequence_record.revisions.filter(revision=request.query_params.get("left")).first()
        right = sequence_record.revisions.filter(revision=request.query_params.get("right")).first()
        if not left or not right:
            raise serializers.ValidationError("Choose valid left and right revision numbers.")
        return Response(sequence_revision_diff(left, right))

    @action(detail=True, methods=["post"], url_path="restore-revision")
    def restore_revision(self, request, pk=None):
        sequence_record = self.get_object()
        source = sequence_record.revisions.filter(revision=request.data.get("revision")).first()
        if not source:
            raise serializers.ValidationError({"revision": "Revision not found."})
        restored = restore_sequence_revision(
            sequence_record,
            source,
            actor=request.user,
            change_summary=request.data.get("change_summary", ""),
        )
        return Response(SequenceRevisionSerializer(restored).data, status=201)

    @action(detail=True, methods=["post"], url_path="molecular-tools")
    def molecular_tools(self, request, pk=None):
        sequence_record = self.get_object()
        operation = request.data.get("operation", "ANALYZE").upper()
        sequence = sequence_record.sequence
        try:
            if operation == "ANALYZE":
                data = {
                    "length": len(sequence),
                    "gc_content": gc_content(sequence) if sequence_record.sequence_type in {"DNA", "RNA"} else None,
                    "molecular_weight": molecular_weight(sequence, sequence_record.sequence_type),
                }
                if sequence_record.sequence_type in {"DNA", "RNA"}:
                    data["orfs"] = find_orfs(sequence, minimum_codons=request.data.get("minimum_codons", 10))
                return Response(data)
            if operation == "REVERSE_COMPLEMENT":
                return Response({"sequence": reverse_complement(sequence, sequence_record.sequence_type)})
            if operation == "TRANSCRIBE":
                return Response({"sequence": transcribe(sequence)})
            if operation == "TRANSLATE":
                return Response({
                    "sequence": translate(sequence, frame=request.data.get("frame", 0), stop_at_stop=request.data.get("stop_at_stop", False))
                })
            if operation == "PRIMER_PROPERTIES":
                primer = request.data.get("sequence", sequence)
                return Response({
                    "sequence": primer,
                    "length": len(primer),
                    "gc_content": gc_content(primer),
                    "melting_temperature": melting_temperature(primer),
                })
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        raise serializers.ValidationError({"operation": "Unsupported molecular operation."})

    @action(detail=True, methods=["post"], url_path="restriction-sites")
    def restriction_site_analysis(self, request, pk=None):
        sequence_record = self.get_object()
        if sequence_record.sequence_type != "DNA":
            raise serializers.ValidationError("Restriction analysis requires DNA.")
        enzymes = request.data.get("enzymes") or list(RESTRICTION_ENZYMES)
        try:
            return Response({"sites": restriction_sites(sequence_record.sequence, enzymes)})
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=True, methods=["post"], url_path="virtual-digest")
    def digest(self, request, pk=None):
        sequence_record = self.get_object()
        if sequence_record.sequence_type != "DNA":
            raise serializers.ValidationError("Virtual digest requires DNA.")
        try:
            return Response(
                virtual_digest(
                    sequence_record.sequence,
                    sequence_record.topology,
                    request.data.get("enzymes") or list(RESTRICTION_ENZYMES),
                )
            )
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=True, methods=["get"], url_path="duplicates")
    def duplicates(self, request, pk=None):
        sequence_record = self.get_object()
        checksum = sequence_record.current_revision.checksum if sequence_record.current_revision else ""
        matches = self.get_queryset().filter(
            current_revision__checksum=checksum
        ).exclude(pk=sequence_record.pk)
        return Response({
            "duplicate": matches.exists(),
            "matches": [
                {"public_id": str(item.public_id), "name": item.name, "project": item.project_code if hasattr(item, "project_code") else (item.project.code if item.project else None)}
                for item in matches
            ],
        })

    @action(detail=False, methods=["post"], url_path="import-file")
    def import_file(self, request):
        uploaded = request.FILES.get("file")
        content = request.data.get("content")
        if uploaded:
            content = uploaded.read().decode("utf-8-sig")
        if not content:
            raise serializers.ValidationError({"file": "Provide a FASTA or GenBank file."})
        file_format = request.data.get("format") or (
            "genbank" if uploaded and uploaded.name.lower().endswith((".gb", ".gbk", ".genbank")) else "fasta"
        )
        try:
            parsed = parse_sequence_file(content, file_format)
        except Exception as exc:
            raise serializers.ValidationError({"file": f"Unable to parse sequence file: {exc}"}) from exc
        created = []
        for item in parsed:
            source_metadata = item.pop("source_metadata", {})
            item["project"] = request.data.get("project") or None
            item["change_summary"] = f"Imported from {file_format.upper()}"
            serializer = self.get_serializer(
                data=item,
                context={
                    **self.get_serializer_context(),
                    "import_source_metadata": source_metadata,
                    "import_source_type": (
                        "GENBANK_IMPORT"
                        if file_format.lower() in {"genbank", "gb", "gbk"}
                        else "FASTA_IMPORT"
                    ),
                },
            )
            serializer.is_valid(raise_exception=True)
            created.append(serializer.save())
        return Response(self.get_serializer(created, many=True).data, status=201)

    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        sequence_record = self.get_object()
        revision_number = request.query_params.get("revision")
        revision = (
            sequence_record.revisions.filter(revision=revision_number).first()
            if revision_number
            else sequence_record.current_revision
        )
        if not revision:
            raise serializers.ValidationError("Sequence revision not found.")
        file_format = request.query_params.get("file_format", "fasta")
        content = export_sequence_revision(revision, file_format)
        genbank = file_format.lower() in {"genbank", "gb", "gbk"}
        extension = "gb" if genbank else "fasta"
        response = HttpResponse(content, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{sequence_record.name}.{extension}"'
        return response


class SequenceFeatureLibraryViewSet(viewsets.ModelViewSet):
    serializer_class = SequenceFeatureLibrarySerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    def get_queryset(self):
        queryset = SequenceFeatureLibrary.objects.select_related("project", "created_by")
        return get_project_access_queryset(
            queryset,
            self.request.user,
            project_lookup="project",
            owner_lookup="created_by",
        )


class ConstructAssemblyPlanViewSet(viewsets.ModelViewSet):
    serializer_class = ConstructAssemblyPlanSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    def get_queryset(self):
        accessible_sequences = get_project_access_queryset(
            Sequence.objects.all(),
            self.request.user,
            project_lookup="project",
            owner_lookup="created_by",
        )
        return ConstructAssemblyPlan.objects.filter(
            target_sequence__in=accessible_sequences
        ).select_related("target_sequence", "created_by").prefetch_related("fragments__source_revision")

    @action(detail=True, methods=["post"], url_path="assemble")
    def assemble(self, request, pk=None):
        plan = self.get_object()
        if plan.status == ConstructAssemblyPlan.STATUS_ASSEMBLED:
            raise serializers.ValidationError("This assembly plan has already been assembled.")
        assembled = []
        for fragment in plan.fragments.select_related("source_revision").all():
            sequence = fragment.source_revision.sequence[fragment.start:fragment.end]
            if fragment.reverse_complement:
                sequence = reverse_complement(sequence)
            assembled.append(fragment.left_overhang + sequence + fragment.right_overhang)
        if not assembled:
            raise serializers.ValidationError("Add at least one assembly fragment.")
        target = plan.target_sequence
        target.sequence_type = "DNA"
        target.sequence = "".join(assembled)
        target.save(update_fields=["sequence_type", "sequence", "updated_at"])
        revision = create_sequence_revision(
            target,
            actor=request.user,
            change_summary=request.data.get("change_summary", f"Assembled from plan {plan.name}"),
            registry_record=target.current_revision.registry_record if target.current_revision else None,
            audit_action="CONSTRUCT_ASSEMBLED",
        )
        plan.status = ConstructAssemblyPlan.STATUS_ASSEMBLED
        plan.save(update_fields=["status", "updated_at"])
        return Response(SequenceRevisionSerializer(revision).data, status=201)
