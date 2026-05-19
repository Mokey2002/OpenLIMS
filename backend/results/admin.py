from django.contrib import admin
from .models import WorkItem,Result, SampleAttachment

admin.site.register(WorkItem)
admin.site.register(Result)
admin.site.register(SampleAttachment)
