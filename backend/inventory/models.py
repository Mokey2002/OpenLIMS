from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from core.models import PublicIDModel

class Location(PublicIDModel):
    KIND_SITE = "SITE"
    KIND_BUILDING = "BUILDING"
    KIND_LABORATORY = "LABORATORY"
    KIND_ROOM = "ROOM"
    KIND_FREEZER = "FREEZER"
    KIND_SHELF = "SHELF"
    KIND_RACK = "RACK"
    KIND_BOX = "BOX"
    KIND_WELL = "WELL"
    KIND_CHOICES = [
        (KIND_SITE, "Site"),
        (KIND_BUILDING, "Building"),
        (KIND_LABORATORY, "Laboratory"),
        (KIND_ROOM, "Room"),
        (KIND_FREEZER, "Freezer"),
        (KIND_SHELF, "Shelf"),
        (KIND_RACK, "Rack"),
        (KIND_BOX, "Box"),
        (KIND_WELL, "Well"),
    ]

    code = models.CharField(max_length=64, null=True, blank=True, unique=True)
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=64)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_locations",
    )

    def clean(self):
        super().clean()
        if self.parent_id and self.parent_id == self.id:
            raise ValidationError({"parent": "A location cannot contain itself."})
        ancestor = self.parent
        seen = {self.id} if self.id else set()
        while ancestor is not None:
            if ancestor.id in seen:
                raise ValidationError({"parent": "Location hierarchy contains a cycle."})
            seen.add(ancestor.id)
            ancestor = ancestor.parent

    @property
    def path_label(self):
        parts = []
        current = self
        while current is not None:
            parts.append(current.name)
            current = current.parent
        return " / ".join(reversed(parts))

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Container(PublicIDModel):
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
    rows = models.PositiveIntegerField(null=True, blank=True)
    columns = models.PositiveIntegerField(null=True, blank=True)

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


class InventoryItem(PublicIDModel):
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
    vendor = models.CharField(max_length=255, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    catalog_number = models.CharField(max_length=128, blank=True, db_index=True)
    chemical_identity = models.CharField(max_length=255, blank=True)
    concentration = models.CharField(max_length=128, blank=True)
    hazard_statements = models.JSONField(default=list, blank=True)
    ghs_classifications = models.JSONField(default=list, blank=True)
    sds_url = models.URLField(blank=True)
    coa_url = models.URLField(blank=True)
    disposal_guidance = models.TextField(blank=True)
    storage_conditions = models.CharField(max_length=255, blank=True)
    default_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
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


class InventoryLot(PublicIDModel):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_DEPLETED = "DEPLETED"
    STATUS_QUARANTINED = "QUARANTINED"
    STATUS_DISPOSED = "DISPOSED"
    STATUS_RETURNED = "RETURNED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_DEPLETED, "Depleted"),
        (STATUS_QUARANTINED, "Quarantined"),
        (STATUS_DISPOSED, "Disposed"),
        (STATUS_RETURNED, "Returned"),
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
    received_date = models.DateField(null=True, blank=True)
    opened_date = models.DateField(null=True, blank=True)
    storage_conditions = models.CharField(max_length=255, blank=True)
    cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    quarantine_reason = models.TextField(blank=True)
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


class InventoryReservation(PublicIDModel):
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
    work_item = models.ForeignKey(
        "results.WorkItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_reservations",
    )
    experiment = models.ForeignKey(
        "notebook.Experiment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_reservations",
    )
    request_item_public_id = models.UUIDField(null=True, blank=True, db_index=True)
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


class BarcodeIdentity(PublicIDModel):
    barcode = models.CharField(max_length=128, unique=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    target_public_id = models.UUIDField(db_index=True)
    entity_type = models.SlugField(max_length=64)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_inventory_barcodes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["barcode"]
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                condition=Q(active=True),
                name="inventory_one_active_barcode_per_object",
            )
        ]


class InventoryPlacement(PublicIDModel):
    container = models.ForeignKey(
        Container,
        on_delete=models.PROTECT,
        related_name="placements",
    )
    position = models.CharField(max_length=32)
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_placements",
    )
    lot = models.ForeignKey(
        InventoryLot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="placements",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_placements",
    )
    placed_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["container", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["container", "position"],
                condition=Q(removed_at__isnull=True),
                name="inventory_active_container_position_unique",
            ),
            models.CheckConstraint(
                condition=(Q(sample__isnull=False, lot__isnull=True) | Q(sample__isnull=True, lot__isnull=False)),
                name="inventory_placement_one_material",
            ),
        ]


class InventoryTransaction(PublicIDModel):
    OP_RECEIVE = "RECEIVE"
    OP_MOVE = "MOVE"
    OP_TRANSFER = "TRANSFER"
    OP_COUNT = "COUNT"
    OP_CONSUME = "CONSUME"
    OP_ADJUST = "ADJUST"
    OP_QUARANTINE = "QUARANTINE"
    OP_DISPOSE = "DISPOSE"
    OP_RETURN = "RETURN"
    OP_CHOICES = [
        (OP_RECEIVE, "Receive"),
        (OP_MOVE, "Move"),
        (OP_TRANSFER, "Transfer"),
        (OP_COUNT, "Count"),
        (OP_CONSUME, "Consume"),
        (OP_ADJUST, "Adjust"),
        (OP_QUARANTINE, "Quarantine"),
        (OP_DISPOSE, "Dispose"),
        (OP_RETURN, "Return"),
    ]

    lot = models.ForeignKey(
        InventoryLot,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    operation = models.CharField(max_length=20, choices=OP_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    unit = models.CharField(max_length=32)
    before_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    after_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    before_status = models.CharField(max_length=32)
    after_status = models.CharField(max_length=32)
    from_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions_from",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions_to",
    )
    from_container = models.ForeignKey(
        Container,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions_from",
    )
    to_container = models.ForeignKey(
        Container,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions_to",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_transactions",
    )
    reason = models.TextField()
    work_item = models.ForeignKey(
        "results.WorkItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    experiment = models.ForeignKey(
        "notebook.Experiment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inventory_transactions",
    )
    request_item_public_id = models.UUIDField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["lot", "-occurred_at"])]

    def save(self, *args, **kwargs):
        if self.pk and InventoryTransaction.objects.filter(pk=self.pk).exists():
            raise ValidationError("Inventory transactions are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Inventory transactions are immutable.")


class InventoryAlert(PublicIDModel):
    TYPE_EXPIRATION = "EXPIRATION"
    TYPE_LOW_STOCK = "LOW_STOCK"
    TYPE_REORDER = "REORDER"
    TYPE_RESERVATION = "RESERVATION"
    TYPE_CHOICES = [
        (TYPE_EXPIRATION, "Expiration"),
        (TYPE_LOW_STOCK, "Low stock"),
        (TYPE_REORDER, "Reorder"),
        (TYPE_RESERVATION, "Reservation"),
    ]
    STATUS_OPEN = "OPEN"
    STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
    STATUS_RESOLVED = "RESOLVED"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_ACKNOWLEDGED, "Acknowledged"),
        (STATUS_RESOLVED, "Resolved"),
    ]

    alert_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts")
    lot = models.ForeignKey(InventoryLot, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts")
    message = models.CharField(max_length=500)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    deduplication_key = models.CharField(max_length=255, unique=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_at", "id"]


class InventoryCycleCount(PublicIDModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_RECONCILED = "RECONCILED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_RECONCILED, "Reconciled"),
    ]

    name = models.CharField(max_length=255)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="cycle_counts")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_cycle_counts")
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reconciled_cycle_counts")
    created_at = models.DateTimeField(auto_now_add=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class InventoryCycleCountLine(PublicIDModel):
    cycle_count = models.ForeignKey(InventoryCycleCount, on_delete=models.CASCADE, related_name="lines")
    lot = models.ForeignKey(InventoryLot, on_delete=models.PROTECT, related_name="cycle_count_lines")
    expected_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    observed_quantity = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=32)
    note = models.TextField(blank=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_count_lines")
    counted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["lot__lot_code"]
        constraints = [
            models.UniqueConstraint(fields=["cycle_count", "lot"], name="inventory_cycle_count_lot_unique")
        ]

    @property
    def variance(self):
        if self.observed_quantity is None:
            return None
        return self.observed_quantity - self.expected_quantity
