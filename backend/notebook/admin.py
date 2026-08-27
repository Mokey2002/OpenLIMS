from django.contrib import admin

from .models import (
    Experiment,
    ExperimentBlock,
    ExperimentComment,
    ExperimentLink,
    ExperimentRevision,
    ExperimentReview,
    ExperimentTemplate,
    Notebook,
)


admin.site.register([
    Notebook,
    ExperimentTemplate,
    Experiment,
    ExperimentRevision,
    ExperimentBlock,
    ExperimentLink,
    ExperimentComment,
    ExperimentReview,
])
