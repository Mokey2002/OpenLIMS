from django.contrib import admin

from .models import Sequence, SequenceFeature


class SequenceFeatureInline(admin.TabularInline):
    model = SequenceFeature
    extra = 0


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "sequence_type",
        "project",
        "sample",
        "created_by",
        "updated_at",
    ]
    list_filter = ["sequence_type", "created_at", "updated_at"]
    search_fields = ["name", "description", "sequence"]
    inlines = [SequenceFeatureInline]


@admin.register(SequenceFeature)
class SequenceFeatureAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "sequence_record",
        "feature_type",
        "name",
        "start",
        "end",
        "direction",
    ]
    list_filter = ["feature_type"]
    search_fields = ["name", "sequence_record__name"]