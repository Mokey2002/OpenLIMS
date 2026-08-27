import csv

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.entities import resolve_entity
from core.permissions import IsAdminOnly, is_admin, is_tech
from events.models import Event

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
from .serializers import (
    BarcodeIdentitySerializer,
    ContainerSerializer,
    InventoryAlertSerializer,
    InventoryCycleCountLineSerializer,
    InventoryCycleCountSerializer,
    InventoryItemSerializer,
    InventoryLotSerializer,
    InventoryPlacementSerializer,
    InventoryReservationSerializer,
    InventoryTransactionSerializer,
    LocationSerializer,
)
from .services import (
    assign_barcode,
    perform_inventory_operation,
    reconcile_cycle_count,
    refresh_inventory_alerts,
    resolve_barcode,
)


class InventoryAdminWritePermission(IsAdminOnly):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)

        return super().has_permission(request, view)


class InventoryOperationPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_admin(request.user) or is_tech(request.user)


def location_payload(location):
    return {
        "id": location.id,
        "name": location.name,
        "kind": location.kind,
        "code": location.code,
        "parent": location.parent_id,
        "path": location.path_label,
    }


def container_payload(container):
    return {
        "id": container.id,
        "container_id": container.container_id,
        "kind": container.kind,
        "location": container.location_id,
        "location_name": container.location.name if container.location else None,
        "parent": container.parent_id,
        "path": container.path_label,
    }


class LocationViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Location.objects.all().order_by("name")
    serializer_class = LocationSerializer

    def perform_create(self, serializer):
        location = serializer.save()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_CREATED",
            actor=self.request.user,
            payload=location_payload(location),
        )

    def perform_update(self, serializer):
        old_location = self.get_object()
        old_payload = location_payload(old_location)

        location = serializer.save()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_UPDATED",
            actor=self.request.user,
            payload={
                "before": old_payload,
                "after": location_payload(location),
            },
        )

    def perform_destroy(self, instance):
        payload = location_payload(instance)
        location_id = instance.id

        instance.delete()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location_id),
            action="LOCATION_DELETED",
            actor=self.request.user,
            payload=payload,
        )


class ContainerViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Container.objects.select_related("location").all().order_by("container_id")
    serializer_class = ContainerSerializer

    def perform_create(self, serializer):
        container = serializer.save()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container.id),
            action="CONTAINER_CREATED",
            actor=self.request.user,
            payload=container_payload(container),
        )

    def perform_update(self, serializer):
        old_container = self.get_object()
        old_payload = container_payload(old_container)

        container = serializer.save()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container.id),
            action="CONTAINER_UPDATED",
            actor=self.request.user,
            payload={
                "before": old_payload,
                "after": container_payload(container),
            },
        )

    def perform_destroy(self, instance):
        payload = container_payload(instance)
        container_id = instance.id

        instance.delete()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container_id),
            action="CONTAINER_DELETED",
            actor=self.request.user,
            payload=payload,
        )


class InventoryItemViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = InventoryItem.objects.prefetch_related("lots__reservations").all()
    serializer_class = InventoryItemSerializer

    def perform_create(self, serializer):
        item = serializer.save()
        Event.objects.create(
            entity_type="InventoryItem",
            entity_id=str(item.id),
            action="INVENTORY_ITEM_CREATED",
            actor=self.request.user,
            payload={"code": item.code, "name": item.name},
        )


class InventoryLotViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = (
        InventoryLot.objects.select_related("item", "location", "container")
        .prefetch_related("reservations")
        .all()
    )
    serializer_class = InventoryLotSerializer

    def perform_create(self, serializer):
        lot = serializer.save()
        initial_quantity = lot.quantity
        if initial_quantity > 0:
            InventoryLot.objects.filter(pk=lot.pk).update(quantity=0)
            lot.refresh_from_db()
            perform_inventory_operation(
                lot=lot,
                operation=InventoryTransaction.OP_RECEIVE,
                actor=self.request.user,
                reason="Initial lot receipt",
                amount=initial_quantity,
                unit=lot.unit,
                metadata={"source": "inventory_lot_create"},
            )
            lot.refresh_from_db()
        Event.objects.create(
            entity_type="InventoryLot",
            entity_id=str(lot.id),
            action="INVENTORY_LOT_CREATED",
            actor=self.request.user,
            payload={
                "item_code": lot.item.code,
                "lot_code": lot.lot_code,
                "quantity": str(lot.quantity),
                "unit": lot.unit,
                "expiration_date": (
                    lot.expiration_date.isoformat() if lot.expiration_date else None
                ),
            },
        )

    def perform_update(self, serializer):
        protected = {"quantity", "status", "location", "container"}
        attempted = protected.intersection(self.request.data)
        if attempted:
            raise ValidationError({field: "Use an immutable inventory transaction for this change." for field in attempted})
        serializer.save()


class InventoryReservationViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    http_method_names = ["get", "head", "options"]
    serializer_class = InventoryReservationSerializer

    def get_queryset(self):
        queryset = InventoryReservation.objects.select_related(
            "lot",
            "lot__item",
            "project",
            "created_by",
        ).all()
        user = self.request.user
        if user.is_superuser or user.groups.filter(name="admin").exists():
            return queryset
        return queryset.filter(project__members=user).distinct()


class BarcodeIdentityViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = BarcodeIdentitySerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return BarcodeIdentity.objects.select_related("content_type", "created_by").all()

    def create(self, request, *args, **kwargs):
        try:
            obj = resolve_entity(
                request.data.get("entity_type"),
                request.data.get("target_public_id"),
                request.user,
                write=True,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            raise ValidationError({"target_public_id": str(exc)}) from exc
        identity, created = assign_barcode(obj=obj, barcode=request.data.get("barcode"), actor=request.user)
        return Response(self.get_serializer(identity).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def resolve(self, request):
        identity, obj = resolve_barcode(request.query_params.get("barcode"), request.user)
        return Response({"identity": self.get_serializer(identity).data, "target": {"entity_type": identity.entity_type, "public_id": str(obj.public_id), "label": str(obj)}})


class InventoryPlacementViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = InventoryPlacementSerializer

    def get_queryset(self):
        return InventoryPlacement.objects.select_related("container", "sample", "lot", "placed_by").all()

    def perform_create(self, serializer):
        serializer.save(placed_by=self.request.user)

    def perform_destroy(self, instance):
        instance.removed_at = timezone.now()
        instance.save(update_fields=["removed_at"])


class InventoryTransactionViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = InventoryTransactionSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return InventoryTransaction.objects.select_related(
            "lot", "lot__item", "actor", "from_location", "to_location",
            "from_container", "to_container", "work_item", "experiment",
        ).all()

    def create(self, request, *args, **kwargs):
        lot = None
        barcode = request.data.get("barcode")
        if barcode:
            _identity, obj = resolve_barcode(barcode, request.user)
            if not isinstance(obj, InventoryLot):
                raise ValidationError({"barcode": "The scanned barcode does not identify an inventory lot."})
            lot = obj
        if lot is None:
            lot_id = request.data.get("lot")
            lot = InventoryLot.objects.filter(pk=lot_id).first()
        if lot is None:
            public_id = request.data.get("lot_public_id")
            lot = InventoryLot.objects.filter(public_id=public_id).first()
        if lot is None:
            raise ValidationError({"lot": "Choose or scan an inventory lot."})

        work_item = None
        if request.data.get("work_item_public_id"):
            try:
                work_item = resolve_entity("work_item", request.data["work_item_public_id"], request.user, write=True)
            except (ValueError, LookupError, PermissionError) as exc:
                raise ValidationError({"work_item_public_id": str(exc)}) from exc
        experiment = None
        if request.data.get("experiment_public_id"):
            try:
                experiment = resolve_entity("experiment", request.data["experiment_public_id"], request.user, write=True)
            except (ValueError, LookupError, PermissionError) as exc:
                raise ValidationError({"experiment_public_id": str(exc)}) from exc

        to_location = Location.objects.filter(pk=request.data.get("to_location")).first()
        to_container = Container.objects.filter(pk=request.data.get("to_container")).first()
        entry = perform_inventory_operation(
            lot=lot,
            operation=request.data.get("operation"),
            actor=request.user,
            reason=request.data.get("reason"),
            amount=request.data.get("amount", 0),
            unit=request.data.get("unit") or lot.unit,
            to_location=to_location,
            to_container=to_container,
            work_item=work_item,
            experiment=experiment,
            request_item_public_id=request.data.get("request_item_public_id") or None,
            metadata=request.data.get("metadata") or {},
        )
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)


class InventoryAlertViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = InventoryAlertSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return InventoryAlert.objects.select_related("item", "lot").all()

    @action(detail=False, methods=["post"])
    def refresh(self, request):
        return Response({"open_alerts": refresh_inventory_alerts()})


class InventoryCycleCountViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = InventoryCycleCountSerializer

    def get_queryset(self):
        return InventoryCycleCount.objects.select_related("location", "created_by", "reconciled_by").prefetch_related("lines__lot").all()

    def perform_create(self, serializer):
        cycle_count = serializer.save(created_by=self.request.user, status=InventoryCycleCount.STATUS_IN_PROGRESS)
        lots = InventoryLot.objects.filter(location=cycle_count.location).exclude(status__in=[InventoryLot.STATUS_DISPOSED, InventoryLot.STATUS_RETURNED])
        InventoryCycleCountLine.objects.bulk_create([
            InventoryCycleCountLine(
                cycle_count=cycle_count,
                lot=lot,
                expected_quantity=lot.quantity,
                unit=lot.unit,
            )
            for lot in lots
        ])

    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        transactions = reconcile_cycle_count(
            cycle_count=self.get_object(),
            actor=request.user,
            reason=request.data.get("reason") or "Cycle count reconciliation",
        )
        return Response({"transactions": [str(row.public_id) for row in transactions]})

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        cycle_count = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="cycle-count-{cycle_count.public_id}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "cycle_count",
                "location",
                "status",
                "lot",
                "expected_quantity",
                "observed_quantity",
                "variance",
                "unit",
                "counted_by",
                "counted_at",
                "note",
            ]
        )
        for line in cycle_count.lines.select_related("lot", "counted_by"):
            writer.writerow(
                [
                    str(cycle_count.public_id),
                    cycle_count.location.path_label,
                    cycle_count.status,
                    line.lot.lot_code,
                    line.expected_quantity,
                    line.observed_quantity,
                    line.variance,
                    line.unit,
                    line.counted_by.username if line.counted_by else "",
                    line.counted_at.isoformat() if line.counted_at else "",
                    line.note,
                ]
            )
        return response


class InventoryCycleCountLineViewSet(ModelViewSet):
    permission_classes = [InventoryOperationPermission]
    serializer_class = InventoryCycleCountLineSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return InventoryCycleCountLine.objects.select_related("cycle_count", "lot", "counted_by").all()

    def perform_update(self, serializer):
        if serializer.instance.cycle_count.status == InventoryCycleCount.STATUS_RECONCILED:
            raise ValidationError({"cycle_count": "Reconciled counts cannot be modified."})
        serializer.save(counted_by=self.request.user, counted_at=timezone.now())
