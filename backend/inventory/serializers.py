from rest_framework import serializers

from .models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from .units import UnitConversionError, convert_quantity, units_compatible


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "kind"]


class ContainerSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)
    sample_count = serializers.SerializerMethodField()
    sample_ids = serializers.SerializerMethodField()
    path = serializers.CharField(source="path_label", read_only=True)

    class Meta:
        model = Container
        fields = [
            "id",
            "container_id",
            "kind",
            "location",
            "location_name",
            "parent",
            "path",
            "sample_count",
            "sample_ids",
        ]

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
        return attrs


class InventoryItemSerializer(serializers.ModelSerializer):
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = [
            "id",
            "code",
            "name",
            "category",
            "default_unit",
            "reorder_level",
            "available_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "available_quantity", "created_at", "updated_at"]

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
            "item",
            "item_code",
            "lot_code",
            "quantity",
            "available_quantity",
            "unit",
            "expiration_date",
            "status",
            "location",
            "location_name",
            "container",
            "container_code",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "available_quantity", "created_at", "updated_at"]

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
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
