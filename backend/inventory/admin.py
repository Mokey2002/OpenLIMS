from django.contrib import admin
from .models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)

admin.site.register(Location)
admin.site.register(Container)
admin.site.register(InventoryItem)
admin.site.register(InventoryLot)
admin.site.register(InventoryReservation)
