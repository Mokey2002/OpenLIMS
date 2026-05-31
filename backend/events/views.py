import csv
import json

from django.db.models import Q
from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyAdminWrite

from .models import Event
from .serializers import EventSerializer


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Audit/event log.

    Users can view events.
    Admin/director users can export audit logs.
    """

    serializer_class = EventSerializer
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]

    def get_queryset(self):
        queryset = (
            Event.objects
            .select_related("actor")
            .all()
            .order_by("-timestamp")
        )

        entity_type = self.request.query_params.get("entity_type")
        action_value = self.request.query_params.get("action")
        actor = self.request.query_params.get("actor")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        search = self.request.query_params.get("search")

        if entity_type:
            queryset = queryset.filter(entity_type__iexact=entity_type)

        if action_value:
            queryset = queryset.filter(action__iexact=action_value)

        if actor:
            queryset = queryset.filter(actor__username__icontains=actor)

        if date_from:
            parsed_from = parse_datetime(date_from)
            if parsed_from:
                queryset = queryset.filter(timestamp__gte=parsed_from)

        if date_to:
            parsed_to = parse_datetime(date_to)
            if parsed_to:
                queryset = queryset.filter(timestamp__lte=parsed_to)

        if search:
            queryset = queryset.filter(
                Q(action__icontains=search)
                | Q(entity_type__icontains=search)
                | Q(entity_id__icontains=search)
                | Q(actor__username__icontains=search)
            )

        return queryset

    def _export_queryset(self):
        return self.get_queryset()[:10000]

    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(self, request):
        queryset = self._export_queryset()

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="openlims-audit-log.csv"'
        )

        writer = csv.writer(response)
        writer.writerow([
            "id",
            "timestamp",
            "actor",
            "entity_type",
            "entity_id",
            "action",
            "payload",
        ])

        for event in queryset:
            writer.writerow([
                event.id,
                event.timestamp.isoformat() if event.timestamp else "",
                event.actor.username if event.actor else "",
                event.entity_type,
                event.entity_id,
                event.action,
                json.dumps(event.payload or {}, default=str),
            ])

        return response

    @action(detail=False, methods=["get"], url_path="export-json")
    def export_json(self, request):
        queryset = self._export_queryset()

        data = []

        for event in queryset:
            data.append({
                "id": event.id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "actor": event.actor.username if event.actor else None,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "action": event.action,
                "payload": event.payload or {},
            })

        response = HttpResponse(
            json.dumps(data, indent=2, default=str),
            content_type="application/json",
        )
        response["Content-Disposition"] = (
            'attachment; filename="openlims-audit-log.json"'
        )

        return response

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        queryset = self.get_queryset()

        return Response({
            "total_events": queryset.count(),
            "entity_types": sorted(
                queryset.values_list("entity_type", flat=True).distinct()
            ),
            "actions": sorted(
                queryset.values_list("action", flat=True).distinct()
            ),
        })
