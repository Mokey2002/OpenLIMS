"""Versioned sample intake configuration; deliberately no executable rules."""
import math
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


def validate_fields(fields):
    if not isinstance(fields, list) or len(fields) > 50:
        raise serializers.ValidationError("Use a list of at most 50 fields. / Máximo 50 campos.")
    keys = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) - {"key", "en", "es", "type", "required", "unit"}:
            raise serializers.ValidationError("Invalid field definition. / Definición inválida.")
        key = field.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or key in keys:
            raise serializers.ValidationError("Field keys must be unique identifiers. / Claves únicas requeridas.")
        keys.add(key)
        if not isinstance(field.get("type"), str) or field["type"] not in {"text", "number", "date", "boolean"}:
            raise serializers.ValidationError("Unsupported field type. / Tipo no compatible.")
        for language in ("en", "es"):
            if not isinstance(field.get(language), str) or not field[language].strip() or len(field[language]) > 128:
                raise serializers.ValidationError("English and Spanish labels are required. / Se requieren etiquetas en inglés y español.")
        if not isinstance(field.get("required", False), bool) or not isinstance(field.get("unit", ""), str) or len(field.get("unit", "")) > 32:
            raise serializers.ValidationError("Invalid required flag or unit. / Obligatorio o unidad inválidos.")
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
        elif kind == "date":
            try:
                valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
            except (ValueError, TypeError):
                valid = False
        if not valid:
            errors[field["key"]] = "Invalid value. / Valor inválido."
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


def schema_for(code):
    # The largest published revision ID wins; archiving the newest does not revive an older version.
    form = SampleForm.objects.filter(code=code, published=True).order_by("-id").first()
    if form and form.archived:
        raise serializers.ValidationError({"sample_type": "Archived type. / Tipo archivado."})
    return {"version": form.pk, "code": code, "fields": form.fields,
            "name_en": form.name_en, "name_es": form.name_es} if form else {}
