from django.contrib import admin

from .models import MassSpecRun


@admin.register(MassSpecRun)
class MassSpecRunAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "project",
        "sample",
        "status",
        "spectra_count",
        "ms1_count",
        "ms2_count",
        "uploaded_by",
        "created_at",
    ]
    list_filter = ["status", "created_at", "processed_at"]
    search_fields = ["name", "original_filename", "sample__sample_id", "project__code"]
    readonly_fields = [
        "original_filename",
        "status",
        "error_message",
        "spectra_count",
        "ms1_count",
        "ms2_count",
        "rt_min",
        "rt_max",
        "mz_min",
        "mz_max",
        "uploaded_by",
        "created_at",
        "processed_at",
    ]
