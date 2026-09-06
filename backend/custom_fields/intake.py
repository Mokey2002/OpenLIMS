"""Previewed, atomic CSV intake of new samples using published configurations."""
import csv
import hashlib
import io
import json
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from samples.serializers import SampleSerializer


def import_configured(view, request):
    content = request.data.get("csv", "")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
        raise ValidationError("CSV must be under 1 MB. / CSV de menos de 1 MB.")
    try:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
        headers = reader.fieldnames or []
        if not {"sample_id", "sample_type", "form_values"} <= set(headers) or len(headers) != len(set(headers)):
            raise ValidationError("Required unique columns: sample_id, sample_type, form_values. / Columnas únicas requeridas: sample_id, sample_type, form_values.")
        rows = []
        for row in reader:
            if len(rows) >= 500 or None in row:
                raise ValidationError("Maximum 500 rows; each row must match its headers. / Máximo 500 filas; revise las columnas.")
            rows.append(row)
    except csv.Error:
        raise ValidationError("Invalid CSV. / CSV inválido.") from None
    if not rows:
        raise ValidationError("CSV is empty. / CSV vacío.")
    serializers, errors, seen = [], [], set()
    for index, row in enumerate(rows, 2):
        try:
            code = (row.get("sample_id") or "").strip()
            if code.casefold() in seen:
                raise ValidationError("Duplicate sample ID. / ID duplicado.")
            seen.add(code.casefold())
            values = json.loads(row["form_values"] or "{}")
            serializer = SampleSerializer(data={"sample_id": code, "sample_type": row["sample_type"],
                "form_values": values, "project": request.data.get("project")}, context={"request": request})
            serializer.is_valid(raise_exception=True)
            schema = serializer.validated_data.get("form_schema", {})
            if row.get("form_version") and str(schema.get("version", "")) != row["form_version"]:
                raise ValidationError("Exported version differs from active version. / La versión exportada difiere de la activa.")
            from samples.access import validate_sample_project_assignment
            validate_sample_project_assignment(request.user, serializer.validated_data.get("project"))
            serializers.append(serializer)
        except (ValueError, TypeError, ValidationError) as error:
            errors.append({"row": index, "detail": str(error)})
    if errors:
        return Response({"errors": errors, "created": 0}, status=400)
    manifest = [{"sample_id": s.validated_data["sample_id"], "sample_type": s.validated_data.get("sample_type"),
                 "schema": s.validated_data["form_schema"], "values": s.validated_data["form_values"]} for s in serializers]
    token = hashlib.sha256(json.dumps({"rows": manifest, "project": request.data.get("project")}, sort_keys=True).encode()).hexdigest()
    if request.data.get("confirm") is not True:
        return Response({"count": len(rows), "preview_token": token, "created": 0})
    if request.data.get("preview_token") != token:
        raise ValidationError("Preview again; data or configuration changed. / Repita la vista previa; los datos o la configuración cambiaron.")
    try:
        with transaction.atomic():
            # Revalidate each schema during save; roll back the entire batch if publication raced the preview.
            for serializer in serializers:
                expected = serializer.validated_data["form_schema"]
                view.perform_create(serializer)
                if serializer.instance.form_schema != expected:
                    raise ValidationError("Configuration changed; preview again. / Configuración modificada; repita la vista previa.")
    except IntegrityError:
        raise ValidationError("Sample IDs conflict; nothing imported. / IDs en conflicto; no se importó nada.") from None
    return Response({"created": len(serializers)}, status=201)
