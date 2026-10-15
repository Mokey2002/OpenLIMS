from django.contrib import admin

from .models import (
    AnalysisDefinition,
    PipelineRun,
    PipelineStepRun,
    PipelineTemplate,
    PipelineTemplateStep,
    ProcedureDefinition,
    ProcedureReagentRequirement,
)


admin.site.register(AnalysisDefinition)
class ReagentRequirementInline(admin.TabularInline):
    model = ProcedureReagentRequirement
    extra = 0


@admin.register(ProcedureDefinition)
class ProcedureDefinitionAdmin(admin.ModelAdmin):
    inlines = [ReagentRequirementInline]

admin.site.register(PipelineTemplate)
admin.site.register(PipelineTemplateStep)
admin.site.register(PipelineRun)
admin.site.register(PipelineStepRun)
