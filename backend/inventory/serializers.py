import re

from rest_framework import serializers

from .models import (
    BarcodeIdentity,
    Container,
    InventoryAlert,
    InventoryCycleCount,
    InventoryCycleCountLine,
    InventoryItem,
    InventoryLot,
    InventoryPlacement,
    InventoryReservation,
    InventoryTransaction,
    Location,
)
from .units import UnitConversionError, convert_quantity, units_compatible


class LocationSerializer(serializers.ModelSerializer):
    path = serializers.CharField(source="path_label", read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)

    class Meta:
        model = Location
        fields = ["id", "public_id", "code", "name", "kind", "parent", "parent_name", "project", "project_code", "path"]
        read_only_fields = ["id", "public_id", "parent_name", "project_code", "path"]

    def validate_parent(self, value):
        if self.instance and value and value.pk == self.instance.pk:
            raise serializers.ValidationError("A location cannot contain itself.")
        ancestor = value
        while self.instance and ancestor is not None:
            if ancestor.pk == self.instance.pk:
                raise serializers.ValidationError("Location hierarchy cannot contain a cycle.")
            ancestor = ancestor.parent
        return value

    def validate_kind(self, value):
        supported = {choice[0] for choice in Location.KIND_CHOICES}
        if str(value).upper() not in supported:
            raise serializers.ValidationError("Choose a supported laboratory-space kind.")
        # Preserve legacy lowercase values while accepting the canonical v2
        # uppercase values used by the new UI.
        return value


class ContainerSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)
    sample_count = serializers.SerializerMethodField()
    sample_ids = serializers.SerializerMethodField()
    path = serializers.CharField(source="path_label", read_only=True)

    class Meta:
        model = Container
        fields = [
            "id",
            "public_id",
            "container_id",
            "kind",
            "location",
            "location_name",
            "parent",
            "rows",
            "columns",
            "path",
            "sample_count",
            "sample_ids",
        ]
        read_only_fields = ["id", "public_id", "path", "sample_count", "sample_ids"]

    def get_sample_count(self, obj):
        return obj.samples.count()

    def get_sample_ids(self, obj):
        return list(obj.samples.values_list("sample_id", flat=True))

    def validate(self, attrs):
        location = attrs.get("location", getattr(self.instance, "location", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent and location and parent.location_id != location.id:
            raise serializers.ValidationError(
                {"parent": "A child container must use its parent location."}
            )
        if self.instance and parent and parent.id == self.instance.id:
            raise serializers.ValidationError(
                {"parent": "A container cannot contain itself."}
            )
        if self.instance and parent:
            ancestor = parent
            while ancestor is not None:
                if ancestor.id == self.instance.id:
                    raise serializers.ValidationError(
                        {"parent": "Container hierarchy cannot contain a cycle."}
                    )
                ancestor = ancestor.parent
        kind = str(attrs.get("kind", getattr(self.instance, "kind", ""))).upper()
        rows = attrs.get("rows", getattr(self.instance, "rows", None))
        columns = attrs.get("columns", getattr(self.instance, "columns", None))
        if kind == "PLATE" and (not rows or not columns):
            raise serializers.ValidationError(
                {"rows": "Plate containers require row and column dimensions."}
            )
        if bool(rows) != bool(columns):
            raise serializers.ValidationError(
                {"rows": "Container rows and columns must be supplied together."}
            )
        return attrs


class InventoryItemSerializer(serializers.ModelSerializer):
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = [
            "id",
            "public_id",
            "code",
            "name",
            "category",
            "default_unit",
            "reorder_level",
            "vendor",
            "manufacturer",
            "catalog_number",
            "chemical_identity",
            "concentration",
            "hazard_statements",
            "ghs_classifications",
            "sds_url",
            "coa_url",
            "disposal_guidance",
            "storage_conditions",
            "default_cost",
            "currency",
            "available_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "available_quantity", "created_at", "updated_at"
        ]

    def get_available_quantity(self, obj):
        total = 0
        for lot in obj.lots.filter(status=InventoryLot.STATUS_ACTIVE):
            try:
                total += convert_quantity(
                    lot.available_quantity,
                    lot.unit,
                    obj.default_unit,
                )
            except UnitConversionError:
                continue
        return str(total)


class InventoryLotSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    available_quantity = serializers.SerializerMethodField()
    location_name = serializers.CharField(source="location.name", read_only=True)
    container_code = serializers.CharField(source="container.container_id", read_only=True)

    class Meta:
        model = InventoryLot
        fields = [
            "id",
            "public_id",
            "item",
            "item_code",
            "lot_code",
            "quantity",
            "available_quantity",
            "unit",
            "expiration_date",
            "received_date",
            "opened_date",
            "storage_conditions",
            "cost",
            "quarantine_reason",
            "status",
            "location",
            "location_name",
            "container",
            "container_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "available_quantity", "created_at", "updated_at"
        ]

    def get_available_quantity(self, obj):
        return str(obj.available_quantity)

    def validate(self, attrs):
        item = attrs.get("item", getattr(self.instance, "item", None))
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))
        location = attrs.get("location", getattr(self.instance, "location", None))
        container = attrs.get("container", getattr(self.instance, "container", None))
        if quantity is not None and quantity < 0:
            raise serializers.ValidationError(
                {"quantity": "Quantity cannot be below zero."}
            )
        if item and unit and not units_compatible(unit, item.default_unit):
            raise serializers.ValidationError(
                {"unit": "The lot unit is incompatible with the item's default unit."}
            )
        if container and location and container.location_id != location.id:
            raise serializers.ValidationError(
                {"container": "The container is not in the selected location."}
            )
        return attrs


class InventoryReservationSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)
    item_code = serializers.CharField(source="lot.item.code", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = InventoryReservation
        fields = [
            "id",
            "public_id",
            "lot",
            "lot_code",
            "item_code",
            "project",
            "project_code",
            "quantity",
            "unit",
            "status",
            "created_by",
            "created_by_username",
            "work_item",
            "experiment",
            "request_item_public_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        lot = attrs.get("lot", getattr(self.instance, "lot", None))
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        if lot and unit and not units_compatible(unit, lot.unit):
            raise serializers.ValidationError(
                {"unit": "The reservation unit is incompatible with the lot unit."}
            )
        return attrs


class BarcodeIdentitySerializer(serializers.ModelSerializer):
    target = serializers.SerializerMethodField()

    class Meta:
        model = BarcodeIdentity
        fields = [
            "id", "public_id", "barcode", "entity_type", "target_public_id",
            "target", "active", "created_by", "created_at",
        ]
        read_only_fields = ["id", "public_id", "target", "created_by", "created_at"]

    def get_target(self, obj):
        target = obj.content_object
        if target is None:
            return None
        return {"label": str(target), "model": target._meta.label_lower}


class InventoryPlacementSerializer(serializers.ModelSerializer):
    container_code = serializers.CharField(source="container.container_id", read_only=True)
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)

    class Meta:
        model = InventoryPlacement
        fields = [
            "id", "public_id", "container", "container_code", "position", "sample",
            "sample_code", "lot", "lot_code", "quantity", "unit", "placed_by",
            "placed_at", "removed_at",
        ]
        read_only_fields = ["id", "public_id", "placed_by", "placed_at", "removed_at"]

    def validate(self, attrs):
        sample = attrs.get("sample", getattr(self.instance, "sample", None))
        lot = attrs.get("lot", getattr(self.instance, "lot", None))
        if bool(sample) == bool(lot):
            raise serializers.ValidationError("Choose exactly one sample or inventory lot.")
        container = attrs.get("container", getattr(self.instance, "container", None))
        position = str(attrs.get("position", getattr(self.instance, "position", ""))).strip().upper()
        if not position:
            raise serializers.ValidationError({"position": "A container position is required."})
        if container and container.rows and container.columns:
            match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", position)
            if not match:
                raise serializers.ValidationError({"position": "Use a well position such as A1."})
            row_number = 0
            for character in match.group(1):
                row_number = row_number * 26 + (ord(character) - ord("A") + 1)
            column_number = int(match.group(2))
            if row_number > container.rows or column_number > container.columns:
                raise serializers.ValidationError(
                    {"position": f"Position is outside this {container.rows}x{container.columns} container."}
                )
        attrs["position"] = position
        return attrs


class InventoryTransactionSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)
    actor_username = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = InventoryTransaction
        fields = [
            "id", "public_id", "lot", "lot_code", "operation", "amount", "unit",
            "before_quantity", "after_quantity", "before_status", "after_status",
            "from_location", "to_location", "from_container", "to_container", "actor",
            "actor_username", "reason", "work_item", "experiment", "request_item_public_id",
            "metadata", "occurred_at",
        ]
        read_only_fields = fields


class InventoryAlertSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.code", read_only=True)
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)

    class Meta:
        model = InventoryAlert
        fields = [
            "id", "public_id", "alert_type", "item", "item_code", "lot", "lot_code",
            "message", "status", "deduplication_key", "due_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "alert_type", "item", "item_code", "lot", "lot_code", "message", "deduplication_key", "due_at", "created_at", "updated_at"]


class InventoryCycleCountLineSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)
    variance = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = InventoryCycleCountLine
        fields = [
            "id", "public_id", "cycle_count", "lot", "lot_code", "expected_quantity",
            "observed_quantity", "variance", "unit", "note", "counted_by", "counted_at",
        ]
        read_only_fields = ["id", "public_id", "expected_quantity", "variance", "counted_by", "counted_at"]


class InventoryCycleCountSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    reconciled_by_username = serializers.CharField(source="reconciled_by.username", read_only=True)
    lines = InventoryCycleCountLineSerializer(many=True, read_only=True)

    class Meta:
        model = InventoryCycleCount
        fields = [
            "id", "public_id", "name", "location", "location_name", "status", "created_by",
            "created_by_username", "reconciled_by", "reconciled_by_username", "created_at",
            "reconciled_at", "lines",
        ]
        read_only_fields = ["id", "public_id", "status", "created_by", "created_by_username", "reconciled_by", "reconciled_by_username", "created_at", "reconciled_at", "lines"]
