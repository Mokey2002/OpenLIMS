from django.contrib import admin
from .models import FieldDefinition, FieldValue

admin.site.register(FieldDefinition)
admin.site.register(FieldValue)
