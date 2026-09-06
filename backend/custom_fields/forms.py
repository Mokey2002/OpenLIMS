"""Versioned sample intake configuration; deliberately no executable rules."""
import math
import hashlib
import json
import re
from datetime import date
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from django.db import transaction
from django.db.models import OuterRef, Subquery
from core.permissions import IsAuthenticatedReadOnlyAdminWrite
from events.models import Event
from .models import SampleForm


def review_token(obj):
    active = SampleForm.objects.filter(code=obj.code, published=True).order_by("-id").values("id", "archived").first()
    return hashlib.sha256(json.dumps({"id": obj.pk, "code": obj.code, "fields": obj.fields,
        "en": obj.name_en, "es": obj.name_es, "active": active}, sort_keys=True).encode()).hexdigest()


def validate_fields(fields):
    if not isinstance(fields, list) or len(fields) > 50:
        raise serializers.ValidationError("Use a list of at most 50 fields. / Máximo 50 campos.")
    keys = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) - {"key", "en", "es", "type", "required", "unit", "choices", "min", "max", "show_if"}:
            raise serializers.ValidationError("Invalid field definition. / Definición inválida.")
        key = field.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or key in keys:
            raise serializers.ValidationError("Field keys must be unique identifiers. / Claves únicas requeridas.")
        keys.add(key)
        if not isinstance(field.get("type"), str) or field["type"] not in {"text", "number", "date", "boolean", "select"}:
            raise serializers.ValidationError("Unsupported field type. / Tipo no compatible.")
        for language in ("en", "es"):
            if not isinstance(field.get(language), str) or not field[language].strip() or len(field[language]) > 128:
                raise serializers.ValidationError("English and Spanish labels are required. / Se requieren etiquetas en inglés y español.")
        if not isinstance(field.get("required", False), bool) or not isinstance(field.get("unit", ""), str) or len(field.get("unit", "")) > 32:
            raise serializers.ValidationError("Invalid required flag or unit. / Obligatorio o unidad inválidos.")
        if field["type"] == "select":
            choices = field.get("choices")
            if not isinstance(choices, list) or not 1 <= len(choices) <= 100 or any(not isinstance(c, str) or not c.strip() or len(c) > 128 for c in choices) or len(set(choices)) != len(choices):
                raise serializers.ValidationError("Provide unique dropdown options. / Proporcione opciones únicas.")
        elif "choices" in field:
            raise serializers.ValidationError("Options require a dropdown. / Las opciones requieren una lista.")
        for bound in ("min", "max"):
            if bound in field and (field["type"] != "number" or type(field[bound]) not in (int, float) or not -1e100 <= field[bound] <= 1e100):
                raise serializers.ValidationError("Invalid numeric bound. / Límite numérico inválido.")
        if field.get("min", -1e100) > field.get("max", 1e100):
            raise serializers.ValidationError("Minimum exceeds maximum. / El mínimo supera el máximo.")
        condition = field.get("show_if")
        if condition is not None:
            previous = next((f for f in fields[:len(keys) - 1] if f["key"] == condition.get("key")), None) if isinstance(condition, dict) else None
            if not previous or set(condition) != {"key", "equals"} or previous.get("show_if") or previous["type"] not in {"boolean", "select"}:
                raise serializers.ValidationError("Conditions must reference an earlier unconditional yes/no or dropdown field. / La condición debe usar un campo anterior de sí/no o lista sin condición.")
            if (previous["type"] == "boolean" and not isinstance(condition["equals"], bool)) or (previous["type"] == "select" and condition["equals"] not in previous["choices"]):
                raise serializers.ValidationError("Invalid condition value. / Valor de condición inválido.")
    return fields


def validate_values(schema, values):
    if not isinstance(values, dict):
        raise serializers.ValidationError({"form_values": "Expected an object. / Se requiere un objeto."})
    fields = schema.get("fields", [])
    if set(values) - {f["key"] for f in fields}:
        raise serializers.ValidationError({"form_values": "Unknown field. / Campo desconocido."})
    errors = {}
    for field in fields:
        value = values.get(field["key"])
        condition = field.get("show_if")
        if condition and values.get(condition["key"]) != condition["equals"]:
            if value is not None and value != "":
                errors[field["key"]] = "Hidden field must be empty. / El campo oculto debe estar vacío."
            continue
        if value is None or value == "":
            if field.get("required"):
                errors[field["key"]] = "Required. / Obligatorio."
            continue
        kind = field["type"]
        valid = True
        if kind == "text":
            valid = isinstance(value, str) and len(value) <= 4000 and (not field.get("required") or bool(value.strip()))
        elif kind == "number":
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
        elif kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "select":
            valid = isinstance(value, str) and value in field["choices"]
        elif kind == "date":
            try:
                valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            except (ValueError, TypeError):
                valid = False
        if not valid:
            errors[field["key"]] = "Invalid value. / Valor inválido."
        elif kind == "number" and (value < field.get("min", -float("inf")) or value > field.get("max", float("inf"))):
            errors[field["key"]] = "Outside allowed range. / Fuera del intervalo permitido."
    if errors:
        raise serializers.ValidationError({"form_values": errors})


class SampleFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleForm
        fields = ["id", "code", "name_en", "name_es", "fields", "published", "archived", "created_at"]
        read_only_fields = ["id", "published", "archived", "created_at"]

    def validate_code(self, value):
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value):
            raise serializers.ValidationError("Use letters, numbers and underscores. / Use letras, números y guiones bajos.")
        return value

    def validate_fields(self, value):
        return validate_fields(value)


class SampleFormViewSet(ModelViewSet):
    serializer_class = SampleFormSerializer
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None

    def get_queryset(self):
        from core.permissions import is_admin
        qs = SampleForm.objects.order_by("code", "-id")
        if not is_admin(self.request.user) or self.request.query_params.get("active") == "1":
            latest = SampleForm.objects.filter(code=OuterRef("code"), published=True).order_by("-id")
            qs = qs.filter(pk=Subquery(latest.values("pk")[:1]), archived=False)
        return qs

    def log(self, obj, action):
        Event.objects.create(entity_type="SampleForm", entity_id=str(obj.pk), action=action,
                             actor=self.request.user, payload={"code": obj.code, "fields": obj.fields})

    @transaction.atomic
    def perform_create(self, serializer):
        self.log(serializer.save(), "FORM_DRAFT_CREATED")

    @transaction.atomic
    def perform_update(self, serializer):
        obj = SampleForm.objects.select_for_update().get(pk=serializer.instance.pk)
        if obj.published or obj.archived:
            raise serializers.ValidationError("Create a new draft; this version is immutable. / Cree un borrador nuevo; esta versión es inmutable.")
        serializer.instance = obj
        self.log(serializer.save(), "FORM_DRAFT_UPDATED")

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def publish(self, request, pk=None):
        obj = SampleForm.objects.select_for_update().get(pk=self.get_object().pk)
        if obj.archived:
            return Response({"detail": "Archived. / Archivado."}, status=status.HTTP_400_BAD_REQUEST)
        validate_fields(obj.fields)
        if request.data.get("review_token") and request.data["review_token"] != review_token(obj):
            raise serializers.ValidationError("Publication changed; review again. / La publicación cambió; revísela de nuevo.")
        if not obj.published:
            obj.published = True
            obj.save(update_fields=["published"])
            self.log(obj, "FORM_PUBLISHED")
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def archive(self, request, pk=None):
        obj = SampleForm.objects.select_for_update().get(pk=self.get_object().pk)
        obj.archived = True
        obj.save(update_fields=["archived"])
        self.log(obj, "FORM_ARCHIVED")
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["get"], url_path="publish-preview")
    def publish_preview(self, request, pk=None):
        from core.permissions import is_admin
        from rest_framework.exceptions import PermissionDenied
        if not is_admin(request.user):
            raise PermissionDenied()
        obj = self.get_object()
        validate_fields(obj.fields)
        previous = SampleForm.objects.filter(code=obj.code, published=True).order_by("-id").first()
        old = {f["key"]: f for f in previous.fields} if previous else {}
        new = {f["key"]: f for f in obj.fields}
        from samples.models import Sample
        return Response({"review_token": review_token(obj), "previous_version": previous.pk if previous else None,
            "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
            "existing_samples": Sample.objects.filter(sample_type=obj.code).count(),
            "will_be_latest": previous is None or obj.pk >= previous.pk})


def schema_for(code):
    # The largest published revision ID wins; archiving the newest does not revive an older version.
    form = SampleForm.objects.filter(code=code, published=True).order_by("-id").first()
    if form and form.archived:
        raise serializers.ValidationError({"sample_type": "Archived type. / Tipo archivado."})
    return {"version": form.pk, "code": code, "fields": form.fields,
            "name_en": form.name_en, "name_es": form.name_es} if form else {}
