from django.contrib import admin
from .models import InstrumentProfile, InstrumentColumnMapping, ImportJob

admin.site.register(InstrumentProfile)
admin.site.register(InstrumentColumnMapping)
admin.site.register(ImportJob)
