"""Constrained presentation settings; never a source of data permissions."""
import base64
import re
from io import BytesIO

from django.db import transaction
from django.db.models import Q
from PIL import Image
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from core.permissions import is_admin
from events.models import Event
from .models import WorkspaceView, PrintTemplate

WIDGETS = ["summary", "assigned", "overdue", "attention"]
COLUMNS = ["name", "sample", "status", "qc", "due"]
ROLES = ["admin", "tech", "qc_reviewer", "viewer"]


def selection(value, choices, required=False):
    if not isinstance(value, list) or any(not isinstance(x, str) or x not in choices for x in value) or len(set(value)) != len(value) or (required and not value):
        raise ValidationError("Invalid selection. / Selección inválida.")
    return value


class WorkspaceViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkspaceView
        fields = ["id", "owner", "role", "name", "config"]
        read_only_fields = ["owner"]

    def validate_role(self, value):
        if value and value not in ROLES:
            raise ValidationError("Unknown role. / Rol desconocido.")
        if value and not is_admin(self.context["request"].user):
            raise PermissionDenied()
        return value

    def validate_config(self, value):
        if not isinstance(value, dict) or set(value) - {"widgets", "columns", "status", "query"}:
            raise ValidationError("Invalid view. / Vista inválida.")
        selection(value.get("widgets", WIDGETS), WIDGETS, True)
        selection(value.get("columns", COLUMNS), COLUMNS, True)
        if value.get("status", "") not in ["", "PENDING", "IN_PROGRESS"] or not isinstance(value.get("query", ""), str) or len(value.get("query", "")) > 80:
            raise ValidationError("Invalid filter. / Filtro inválido.")
        return value


class WorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkspaceViewSerializer

    def get_queryset(self):
        user = self.request.user
        roles = ROLES if is_admin(user) else list(user.groups.values_list("name", flat=True))
        return WorkspaceView.objects.filter(Q(owner=user) | Q(owner__isnull=True, role__in=roles)).order_by("name", "id")

    def perform_create(self, serializer):
        serializer.save(owner=None if serializer.validated_data.get("role") else self.request.user)

    def perform_update(self, serializer):
        obj = serializer.instance
        if obj.owner_id != self.request.user.pk and not is_admin(self.request.user):
            raise PermissionDenied()
        role = serializer.validated_data.get("role", obj.role)
        serializer.save(owner=None if role else self.request.user)

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.pk and not is_admin(self.request.user):
            raise PermissionDenied()
        instance.delete()


def validate_print_config(kind, value):
    common = {"title", "footer", "logo", "page_size"}
    allowed = common | ({"orientation", "show_summary", "show_chart", "summary_position", "chart_position"} if kind == "REPORT" else {"columns", "rows", "show_project", "border"})
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValidationError("Invalid template settings. / Configuración de plantilla inválida.")
    for key, limit in [("title", 80), ("footer", 100)]:
        if not isinstance(value.get(key, ""), str) or len(value.get(key, "")) > limit or any(ord(c) < 32 for c in value.get(key, "")):
            raise ValidationError("Invalid template text. / Texto de plantilla inválido.")
    if value.get("page_size", "LETTER") not in ["LETTER", "A4"] or value.get("orientation", "portrait") not in ["portrait", "landscape"]:
        raise ValidationError("Invalid page layout. / Diseño de página inválido.")
    for key in ["show_summary", "show_chart", "show_project", "border"]:
        if key in value and type(value[key]) is not bool:
            raise ValidationError("Expected a checkbox value. / Se requiere un valor de casilla.")
    for key in ["summary_position", "chart_position"]:
        if value.get(key, "before") not in ["before", "after"]:
            raise ValidationError("Invalid section position. / Posición de sección inválida.")
    if kind == "LABEL":
        for key, choices in [("columns", [1, 2]), ("rows", [3, 4, 5])]:
            if type(value.get(key, choices[-1])) is not int or value.get(key, choices[-1]) not in choices:
                raise ValidationError("Unsupported label grid. / Cuadrícula de etiquetas no compatible.")
    logo = value.get("logo", "")
    if not isinstance(logo, str) or len(logo) > 280000:
        raise ValidationError("Logo exceeds 200 KB. / El logotipo supera 200 KB.")
    if logo:
        try:
            if not re.fullmatch(r"data:image/png;base64,[A-Za-z0-9+/=]+", logo):
                raise ValueError()
            raw = base64.b64decode(logo.split(",", 1)[1], validate=True)
            with Image.open(BytesIO(raw)) as img:
                if img.format != "PNG" or max(img.size) > 1000 or len(raw) > 200000:
                    raise ValueError()
                img.verify()
        except Exception:
            raise ValidationError("Use a PNG logo up to 200 KB and 1000 pixels. / Use un PNG de hasta 200 KB y 1000 píxeles.") from None
    return value


class PrintTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintTemplate
        fields = ["id", "name", "kind", "config", "revision", "archived"]

    def validate(self, attrs):
        kind = attrs.get("kind", self.instance.kind if self.instance else "REPORT")
        if self.instance and kind != self.instance.kind:
            raise ValidationError("Template kind cannot change. / El tipo no puede cambiar.")
        validate_print_config(kind, attrs.get("config", self.instance.config if self.instance else {}))
        if self.instance and attrs.get("revision") != self.instance.revision:
            raise ValidationError("Template changed; reload before saving. / La plantilla cambió; vuelva a cargarla.")
        return attrs


class PrintTemplateViewSet(viewsets.ModelViewSet):
    from rest_framework.decorators import action
    from core.permissions import IsAuthenticatedReadOnlyAdminWrite
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]
    serializer_class = PrintTemplateSerializer
    queryset = PrintTemplate.objects.order_by("kind", "name", "id")
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        from django.http import HttpResponse
        from types import SimpleNamespace
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        template = {"name": data["name"], "revision": 0, "config": data.get("config", {})}
        if data["kind"] == "LABEL":
            from assistant.barcode_operations import _render_labels
            sample = SimpleNamespace(sample_id="DEMO-001", project=SimpleNamespace(code="DEMO"))
            label = SimpleNamespace(barcode="OPENLIMS-SAMPLE-1-DEMO-001")
            content = _render_labels([(sample, label, True)] * 12, template)
        elif request.data.get("report_type", "project") in ["comparison", "investigation"]:
            from .print_rendering import render_analysis
            kind = request.data["report_type"]
            result = {
                "answer": "Synthetic summary for layout preview.",
                "chart": {"chartType": "bar", "xKey": "entity", "data": [{"entity": "Demo A", "value": 3}, {"entity": "Demo B", "value": 7}], "series": [{"name": "Demo metric", "dataKey": "value"}]},
                "comparison": {"title": "Synthetic comparison", "columns": [{"key": "sample", "label": "Sample"}, {"key": "value", "label": "Value"}],
                               "rows": [{"sample": "DEMO-001", "value": n} for n in range(40)], "notes": ["Synthetic method note; no laboratory records used."]},
                "investigation": {"title": "Synthetic investigation", "findings": [{"severity": "medium", "confidence": "low", "evidence_type": "demo", "title": "Example finding", "detail": "Synthetic evidence for checking the layout."}] * 20,
                                  "results": [{"id": n, "key": "Demo analyte", "display_value": "3 ng", "reference_min": 1, "reference_max": 5, "unit": "ng", "qc_status": "PASS", "entered_by": "demo"} for n in range(10)],
                                  "disclaimers": ["Synthetic preview; no scientific conclusions."]},
            }
            content = render_analysis(result, {kind + "_spec": {"scope": "synthetic"}}, template, kind)
        else:
            if request.data.get("report_type", "project") != "project":
                raise ValidationError("Unsupported report preview.")
            from .print_rendering import render_report
            content = render_report([{"timestamp": "2026-01-01T12:00:00", "actor": "demo", "action": "SAMPLE_UPDATED", "entity_type": "Sample", "entity_id": "DEMO-001"}] * 40,
                                    {"project_label": "DEMO - synthetic preview", "timezone": "UTC"}, template)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="template-preview.pdf"'
        return response

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        self.queryset = self.queryset.select_for_update()
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        with transaction.atomic():
            obj = serializer.save(revision=1)
            self.audit(obj)

    def perform_update(self, serializer):
        obj = serializer.save(revision=serializer.instance.revision + 1)
        self.audit(obj)

    def audit(self, obj):
        Event.objects.create(entity_type="PrintTemplate", entity_id=str(obj.pk), action="PRINT_TEMPLATE_SAVED", actor=self.request.user,
                             payload={"name": obj.name, "kind": obj.kind, "revision": obj.revision, "archived": obj.archived})


def print_snapshot(context, kind):
    template_id = (context or {}).get("print_template_id")
    if template_id is None:
        return {}
    if type(template_id) is not int:
        raise ValidationError("Invalid print template. / Plantilla de impresión inválida.")
    obj = PrintTemplate.objects.filter(pk=template_id, kind=kind, archived=False).first()
    if not obj:
        raise ValidationError("Template unavailable. / Plantilla no disponible.")
    return {"id": obj.pk, "name": obj.name, "revision": obj.revision, "config": validate_print_config(kind, obj.config)}
