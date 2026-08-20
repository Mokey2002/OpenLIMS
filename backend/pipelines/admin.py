from django.contrib import admin

from .models import (
    AnalysisDefinition,
    PipelineRun,
    PipelineStepRun,
    PipelineTemplate,
    PipelineTemplateStep,
    ProcedureDefinition,
)


admin.site.register(AnalysisDefinition)
admin.site.register(ProcedureDefinition)
admin.site.register(PipelineTemplate)
admin.site.register(PipelineTemplateStep)
admin.site.register(PipelineRun)
admin.site.register(PipelineStepRun)
