from django.contrib import admin
from .models import Sample, SampleBatch, SampleCustodyEvent, SampleRelationship

admin.site.register(Sample)
admin.site.register(SampleBatch)
admin.site.register(SampleRelationship)
admin.site.register(SampleCustodyEvent)
