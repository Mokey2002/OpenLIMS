from django.contrib import admin

from .models import (
    AssayRequestType,
    RequestResourceRequirement,
    WorkflowRequest,
    WorkflowRequestItem,
    WorkflowRequestMessage,
    WorkflowRequestReport,
    WorkflowRunGroup,
)


admin.site.register([
    AssayRequestType,
    RequestResourceRequirement,
    WorkflowRequest,
    WorkflowRequestItem,
    WorkflowRunGroup,
    WorkflowRequestMessage,
    WorkflowRequestReport,
])
