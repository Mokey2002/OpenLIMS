from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MigrationFieldMapping, MigrationMappingTemplate, MigrationProfile


def _mapping_payload(mapping):
    return {
        "source_column": mapping.source_column,
        "target_type": mapping.target_type,
        "target_field": mapping.target_field,
        "value_type": mapping.value_type,
        "required": mapping.required,
    }


def profile_mapping_configuration(profile):
    if profile.source_type == MigrationProfile.SOURCE_TYPE_CSV:
        return {
            "version": 1,
            "mappings": [
                _mapping_payload(mapping)
                for mapping in profile.field_mappings.filter(dataset__isnull=True).order_by("id")
            ],
        }
    return {
        "version": 1,
        "datasets": [
            {
                "name": dataset.name,
                "entity_type": dataset.entity_type,
                "source_schema": dataset.source_schema,
                "source_table": dataset.source_table,
                "source_key_column": dataset.source_key_column,
                "mappings": [
                    _mapping_payload(mapping)
                    for mapping in dataset.field_mappings.all().order_by("id")
                ],
            }
            for dataset in profile.datasets.all().prefetch_related("field_mappings").order_by("id")
        ],
    }


def save_mapping_template(profile, name, actor, description=""):
    name = str(name or "").strip()
    if not name:
        raise ValidationError("Template name is required.")
    existing = MigrationMappingTemplate.objects.filter(name=name).first()
    if existing and existing.created_by_id not in [None, actor.id]:
        raise ValidationError("A mapping template with this name belongs to another user.")
    template, _ = MigrationMappingTemplate.objects.update_or_create(
        name=name,
        defaults={
            "source_system": profile.source_system,
            "source_type": profile.source_type,
            "description": description,
            "configuration": profile_mapping_configuration(profile),
            "created_by": actor,
        },
    )
    return template


@transaction.atomic
def apply_mapping_template(template, profile):
    if template.source_type != profile.source_type:
        raise ValidationError("Template and profile source types must match.")

    created = 0
    updated = 0
    unmatched_datasets = []

    def apply_mappings(mappings, dataset=None):
        nonlocal created, updated
        for item in mappings:
            mapping, was_created = MigrationFieldMapping.objects.update_or_create(
                profile=profile,
                dataset=dataset,
                source_column=item["source_column"],
                target_type=item["target_type"],
                target_field=item.get("target_field", ""),
                defaults={
                    "value_type": item.get(
                        "value_type", MigrationFieldMapping.VALUE_TYPE_STRING
                    ),
                    "required": item.get("required", False),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            mapping.full_clean()

    configuration = template.configuration or {}
    if profile.source_type == MigrationProfile.SOURCE_TYPE_CSV:
        apply_mappings(configuration.get("mappings", []))
    else:
        profile_datasets = list(profile.datasets.all())
        for dataset_template in configuration.get("datasets", []):
            candidates = [
                dataset
                for dataset in profile_datasets
                if dataset.name == dataset_template.get("name")
                and dataset.entity_type == dataset_template.get("entity_type")
            ]
            if not candidates:
                candidates = [
                    dataset
                    for dataset in profile_datasets
                    if dataset.entity_type == dataset_template.get("entity_type")
                ]
            if len(candidates) != 1:
                unmatched_datasets.append(
                    {
                        "name": dataset_template.get("name"),
                        "entity_type": dataset_template.get("entity_type"),
                    }
                )
                continue
            apply_mappings(dataset_template.get("mappings", []), candidates[0])

    return {
        "created": created,
        "updated": updated,
        "unmatched_datasets": unmatched_datasets,
    }
