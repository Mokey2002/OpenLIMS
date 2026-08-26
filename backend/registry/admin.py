from django.contrib import admin

from .models import (
    RegistrationReview,
    RegistryAlias,
    RegistryRecord,
    RegistryRecordVersion,
    RegistryRelationship,
    RegistrySchema,
)


admin.site.register(RegistrySchema)
admin.site.register(RegistryRecord)
admin.site.register(RegistryRecordVersion)
admin.site.register(RegistryAlias)
admin.site.register(RegistryRelationship)
admin.site.register(RegistrationReview)
