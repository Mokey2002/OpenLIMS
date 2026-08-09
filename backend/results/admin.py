from django.contrib import admin
from .models import Result, SampleAttachment, WorkItem

admin.site.register(WorkItem)
admin.site.register(Result)
admin.site.register(SampleAttachment)
