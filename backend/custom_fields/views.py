from rest_framework.viewsets import ModelViewSet
from .models import FieldDefinition, FieldValue
from .serializers import FieldDefinitionSerializer, FieldValueSerializer

class FieldDefinitionViewSet(ModelViewSet):
    serializer_class = FieldDefinitionSerializer

    def get_queryset(self):
        qs = FieldDefinition.objects.all().order_by("entity_type", "name")
        entity_type = self.request.query_params.get("entity_type")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        return qs


class FieldValueViewSet(ModelViewSet):
    serializer_class = FieldValueSerializer

    def get_queryset(self):
        qs = FieldValue.objects.select_related("field_definition").all().order_by("-updated_at")
        entity_type = self.request.query_params.get("entity_type")
        entity_id = self.request.query_params.get("entity_id")
        field_definition = self.request.query_params.get("field_definition")

        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        if entity_id:
            qs = qs.filter(entity_id=entity_id)
        if field_definition:
            qs = qs.filter(field_definition_id=field_definition)

        return qs
