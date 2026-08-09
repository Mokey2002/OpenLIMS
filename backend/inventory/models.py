from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

class Location(models.Model):
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=64)  # freezer, rack, shelf, etc.

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Container(models.Model):
    container_id = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=64)  # tube, plate, box
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="containers",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    def clean(self):
        super().clean()
        if self.parent_id and self.parent_id == self.id:
            raise ValidationError({"parent": "A container cannot contain itself."})
        if self.parent and self.parent.location_id != self.location_id:
            raise ValidationError(
                {"parent": "A child container must use its parent location."}
            )

        ancestor = self.parent
        seen = {self.id} if self.id else set()
        while ancestor is not None:
            if ancestor.id in seen:
                raise ValidationError({"parent": "Container hierarchy contains a cycle."})
            seen.add(ancestor.id)
            ancestor = ancestor.parent

    def __str__(self):
        return self.container_id

    @property
    def path_label(self):
        parts = [self.location.name]
        ancestors = []
        current = self
        while current is not None:
            ancestors.append(current.container_id)
            current = current.parent
        return " / ".join(parts + list(reversed(ancestors)))


class InventoryItem(models.Model):
    CATEGORY_REAGENT = "REAGENT"
    CATEGORY_SUPPLY = "SUPPLY"

    CATEGORY_CHOICES = [
        (CATEGORY_REAGENT, "Reagent"),
        (CATEGORY_SUPPLY, "Supply"),
    ]

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    category = models.CharField(
        max_length=32,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_REAGENT,
    )
    default_unit = models.CharField(max_length=32, default="unit")
    reorder_level = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="inventory_item_code_ci_unique",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class InventoryLot(models.Model):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_DEPLETED = "DEPLETED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_DEPLETED, "Depleted"),
    ]

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.PROTECT,
        related_name="lots",
    )
    lot_code = models.CharField(max_length=64, unique=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=32)
    expiration_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_lots",
    )
    container = models.ForeignKey(
        Container,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_lots",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expiration_date", "lot_code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="inventory_lot_quantity_nonnegative",
            ),
            models.UniqueConstraint(
                Lower("lot_code"),
                name="inventory_lot_code_ci_unique",
            ),
        ]

    def clean(self):
        super().clean()
        from .units import units_compatible

        if self.quantity < 0:
            raise ValidationError({"quantity": "Quantity cannot be below zero."})
        if self.item_id and not units_compatible(self.unit, self.item.default_unit):
            raise ValidationError(
                {"unit": "The lot unit is incompatible with the item's default unit."}
            )
        if self.container_id and self.location_id:
            if self.container.location_id != self.location_id:
                raise ValidationError(
                    {"container": "The container is not in the selected location."}
                )

    @property
    def available_quantity(self):
        from .units import convert_quantity

        reserved = Decimal("0")
        for reservation in self.reservations.filter(
            status=InventoryReservation.STATUS_ACTIVE
        ):
            reserved += convert_quantity(
                reservation.quantity,
                reservation.unit,
                self.unit,
            )
        return self.quantity - reserved

    def __str__(self):
        return f"{self.item.code} / {self.lot_code}"


class InventoryReservation(models.Model):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_RELEASED = "RELEASED"
    STATUS_CONSUMED = "CONSUMED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_RELEASED, "Released"),
        (STATUS_CONSUMED, "Consumed"),
    ]

    lot = models.ForeignKey(
        InventoryLot,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="inventory_reservations",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=32)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_reservations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="inventory_reservation_quantity_positive",
            )
        ]

    def clean(self):
        super().clean()
        from .units import units_compatible

        if self.quantity <= 0:
            raise ValidationError({"quantity": "Reserved quantity must be positive."})
        if self.lot_id and not units_compatible(self.unit, self.lot.unit):
            raise ValidationError(
                {"unit": "The reservation unit is incompatible with the lot unit."}
            )
