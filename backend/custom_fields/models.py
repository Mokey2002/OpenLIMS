from django.db import models

class FieldDefinition(models.Model):
    """
    Defines a custom field for an entity type (v1: Sample).
    Example: entity_type="Sample", name="patient_id", data_type="string"
    """
    DATA_TYPES = [
        ("string", "string"),
        ("int", "int"),
        ("float", "float"),
        ("bool", "bool"),
        ("date", "date"),
        ("json", "json"),
    ]

    entity_type = models.CharField(max_length=64)  # "Sample" for v1
    name = models.CharField(max_length=64)         # machine name, e.g. patient_id
    label = models.CharField(max_length=128, blank=True)  # human label
    data_type = models.CharField(max_length=16, choices=DATA_TYPES, default="string")
    required = models.BooleanField(default=False)
    rules = models.JSONField(default=dict, blank=True)  # validations, allowed values, etc.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("entity_type", "name")]

    def __str__(self):
        return f"{self.entity_type}.{self.name}"


class FieldValue(models.Model):
    """
    Stores a value for a field definition for a specific entity instance.
    v1: entity_type="Sample" and entity_id="<sample.id>"
    """
    field_definition = models.ForeignKey(FieldDefinition, on_delete=models.CASCADE, related_name="values")
    entity_type = models.CharField(max_length=64)  # "Sample"
    entity_id = models.CharField(max_length=64)    # sample.id as string
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("field_definition", "entity_type", "entity_id")]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} {self.field_definition.name}"
