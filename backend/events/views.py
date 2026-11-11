import csv
import json

from django.db.models import Q
from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from uuid import UUID

from core.permissions import (
    IsAdminOnly,
    IsAuthenticatedReadOnlyAdminWrite,
)

from .models import Event
from .access import events_for_user
from .serializers import EventSerializer
from .presentation import event_presentation, spreadsheet_text


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Audit/event log.

    Read:
      - admin
      - tech
      - viewer

    Export:
      - admin only
    """

    serializer_class = EventSerializer

    @action(detail=True, methods=["get"])
    def comparison(self, request, pk=None):
        from notebook.models import Experiment
        from notebook.permissions import user_can_notebook
        from notebook.services import compare_revisions
        from .comparison import can_compare_revision, field_changes, mapping
        event = self.get_object()
        comparison = None
        if can_compare_revision(event):
            try:
                identifier = UUID(str(event.entity_id))
                experiment = Experiment.objects.filter(public_id=identifier).first()
            except ValueError:
                experiment = Experiment.objects.filter(pk=int(event.entity_id)).first() if str(event.entity_id).isdigit() else None
            if not experiment or not user_can_notebook(request.user, experiment.notebook, "read"):
                raise NotFound("The recorded revision comparison is no longer available.")
            payload = mapping(event.payload)
            old_number = mapping(payload.get("before")).get("revision")
            after = experiment.revisions.filter(number=payload["after"]["revision"]).first()
            before = experiment.revisions.filter(number=old_number).first() if type(old_number) is int else None
            if not after or (old_number is not None and not before):
                raise NotFound("The recorded revision comparison is no longer available.")
            comparison = compare_revisions(before, after)
        return Response({"field_changes": field_changes(event), "revision_comparison": comparison})

    def get_permissions(self):
        if self.action in ["export_csv", "export_json"]:
            return [IsAdminOnly()]

        return [IsAuthenticatedReadOnlyAdminWrite()]

    def get_queryset(self):
        queryset = (
            Event.objects
            .select_related("actor")
            .all()
            .order_by("-timestamp", "-pk")
        )
        queryset = events_for_user(queryset, self.request.user)

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
                | Q(payload__icontains=search)
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
            "entity_label", "action_label", "description", "source",
        ])

        for event in queryset:
            display = event_presentation(event)
            writer.writerow([
                event.id,
                event.timestamp.isoformat() if event.timestamp else "",
                event.actor.username if event.actor else "",
                event.entity_type,
                event.entity_id,
                event.action,
                json.dumps(event.payload or {}, default=str),
                *[spreadsheet_text(display[field]) for field in ["entity_label", "action_label", "description", "source"]],
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
                **event_presentation(event),
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
                queryset.order_by().values_list("entity_type", flat=True).distinct()
            ),
            "actions": sorted(
                queryset.order_by().values_list("action", flat=True).distinct()
            ),
        })
