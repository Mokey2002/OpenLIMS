"""Instrument time and stock reservations, confirmed as one atomic operation."""
from datetime import timedelta
from decimal import Decimal
from django.db import IntegrityError

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import is_admin
from events.models import Event
from imports.models import InstrumentProfile
from inventory.models import InstrumentBooking, InventoryLot, InventoryItem, InventoryReservation
from inventory.units import convert_quantity, normalize_unit

from .inventory_operations import _lot_snapshot
from .lab_operation_common import (StrictSerializer, OffsetDateTimeField, assert_unchanged,
    plain, preview, project_for_user, require_writer)


class StockSerializer(StrictSerializer):
    lot = serializers.CharField(max_length=128)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal('0.0001'))
    unit = serializers.CharField(max_length=32)


class ResourceSerializer(StrictSerializer):
    project = serializers.CharField(max_length=64)
    mode = serializers.ChoiceField(choices=['book', 'cancel'], default='book')
    instrument = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    starts_at = OffsetDateTimeField(required=False)
    ends_at = OffsetDateTimeField(required=False)
    stocks = StockSerializer(many=True, max_length=10, required=False, default=list)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    booking_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1, required=False)

    def validate(self, data):
        if data['mode'] == 'cancel':
            if 'booking_id' not in data or data['instrument'] or data['stocks'] or 'starts_at' in data or 'ends_at' in data:
                raise ValidationError('Cancellation requires only a project and booking ID.')
        elif not data['instrument'] or 'starts_at' not in data or 'ends_at' not in data or 'booking_id' in data:
            raise ValidationError('Choose an instrument and explicit start/end times.')
        return data


def _audit(action, entity, pk, name, values):
    Event.objects.create(entity_type=entity, entity_id=str(pk), action=name, actor=action.requested_by,
        payload={'assistant_action_id': str(action.pk), **plain(values)})


def resource_plan(user, fields, *, lock=False):
    require_writer(user)
    serializer = ResourceSerializer(data=fields)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    project = project_for_user(fields['project'], user, lock=lock)
    booking = None
    if fields['mode'] == 'cancel':
        booking = InstrumentBooking.objects.filter(pk=fields['booking_id'], project=project).first()
        if booking is None or not (is_admin(user) or booking.created_by_id == user.pk):
            raise PermissionDenied('Booking unavailable or you cannot cancel it.')
        instrument_id = booking.instrument_id
    else:
        instruments = list(InstrumentProfile.objects.filter(code__iexact=fields['instrument'])[:2])
        if len(instruments) != 1:
            raise ValidationError('Use one exact configured instrument code.')
        instrument_id = instruments[0].pk
    # Every booking/cancellation uses this row lock, including across projects.
    instruments = InstrumentProfile.objects.select_for_update() if lock else InstrumentProfile.objects.all()
    instrument = instruments.get(pk=instrument_id)
    if booking is not None:
        booking = (InstrumentBooking.objects.select_for_update() if lock else InstrumentBooking.objects).get(pk=booking.pk)
        if booking.status != 'ACTIVE':
            raise ValidationError('This booking is no longer active.')
        lot_ids = booking.reservations.values_list('lot_id', flat=True)
        if lock:
            list(InventoryLot.objects.select_for_update().filter(pk__in=lot_ids).order_by('pk'))
        reservations = booking.reservations.all().order_by('pk')
        if lock:
            reservations = reservations.select_for_update()
        reservations = list(reservations)
        rows = [{'id': booking.pk, 'label': instrument.code, 'current': {'Start': booking.starts_at.isoformat(), 'End': booking.ends_at.isoformat()}, 'proposed': {'Booking': 'Cancel'}}]
        rows += [{'id': row.pk, 'label': f'Stock reservation #{row.pk}', 'current': {'Status': row.status}, 'proposed': {'Status': 'RELEASED'}} for row in reservations if row.status == 'ACTIVE']
        state = {'instrument': [instrument.pk, instrument.code], 'project': project.pk,
            'booking': [booking.pk, booking.status, booking.starts_at, booking.ends_at, booking.created_by_id, booking.updated_at],
            'reservations': [[row.pk, row.status, row.quantity, row.unit, row.project_id, row.updated_at] for row in reservations]}
        return {'fields': plain(fields), 'project': project, 'instrument': instrument, 'booking': booking,
            'reservations': reservations, 'state': state, 'preview': preview('Cancel instrument booking', user, project, rows,
                warnings=['Active linked stock reservations are released. Consumed stock is not reversed.'])}
    start, end = fields['starts_at'], fields['ends_at']
    if start <= timezone.now() or end <= start or end - start > timedelta(days=14):
        raise ValidationError('Choose a future start and a later end, at most 14 days apart.')
    if InstrumentBooking.objects.filter(instrument=instrument, status='ACTIVE', starts_at__lt=end, ends_at__gt=start).exists():
        raise ValidationError('This instrument is already booked during that window. Choose another time.')
    codes = [stock['lot'].casefold() for stock in fields['stocks']]
    if len(codes) != len(set(codes)):
        raise ValidationError('List each stock lot once.')
    selected = []
    for stock in fields['stocks']:
        lots = list(InventoryLot.objects.filter(lot_code__iexact=stock['lot'])[:2])
        if len(lots) != 1:
            raise ValidationError('Use an exact stock lot code.')
        selected.append((lots[0].pk, stock))
    if lock:
        list(InventoryLot.objects.select_for_update().filter(pk__in=[pk for pk, _ in selected]).order_by('pk'))
    stocks = []
    for pk, stock in selected:
        lot = InventoryLot.objects.select_related('item', 'location', 'container').prefetch_related('reservations').get(pk=pk)
        if lot.item.category != InventoryItem.CATEGORY_REAGENT or lot.status != 'ACTIVE':
            raise ValidationError('Choose an active reagent lot; quarantined stock cannot be reserved.')
        if lot.expiration_date and lot.expiration_date < timezone.localtime(end).date():
            raise ValidationError('This reagent expires before the booking finishes.')
        unit = normalize_unit(stock['unit'])
        amount = convert_quantity(stock['quantity'], unit, lot.unit)
        if amount <= 0 or amount > lot.available_quantity:
            raise ValidationError('This lot has insufficient compatible, unreserved stock.')
        stocks.append({'lot': lot, 'quantity': stock['quantity'], 'unit': unit, 'snapshot': _lot_snapshot(lot)})
    rows = [{'id': instrument.pk, 'label': instrument.code, 'current': {'Booking': 'Available in the requested window'},
             'proposed': {'Start': start.isoformat(), 'End': end.isoformat()}}]
    rows += [{'id': row['lot'].pk, 'label': row['lot'].lot_code, 'current': {'Available': f"{row['lot'].available_quantity} {row['lot'].unit}"},
              'proposed': {'Reserve': f"{row['quantity']} {row['unit']}"}} for row in stocks]
    state = {'instrument': [instrument.pk, instrument.code], 'project': project.pk,
             'start': start, 'end': end, 'stocks': [[row['lot'].pk, row['quantity'], row['unit'], row['snapshot']] for row in stocks]}
    return {'fields': plain(fields), 'project': project, 'instrument': instrument, 'stocks': stocks, 'state': state,
        'preview': preview('Reserve instrument and reagents', user, project, rows,
            proposed={'Note': fields['note']}, warnings=['Availability covers OpenLIMS bookings only, not an external calendar or physical instrument readiness.',
                'Reagent stock is reserved immediately. No stock is consumed and no experiment is started.', 'All reservations succeed together or none are created.'])}


def execute_resources(action):
    plan = resource_plan(action.requested_by, action.payload['fields'], lock=True)
    assert_unchanged(action, plan)
    details = []
    if plan['fields']['mode'] == 'cancel':
        booking = plan['booking']
        booking.status = 'CANCELLED'
        booking.save(update_fields=['status', 'updated_at'])
        _audit(action, 'InstrumentBooking', booking.pk, 'INSTRUMENT_BOOKING_CANCELLED', {'project_id': plan['project'].pk})
        details.append({'label': f'Instrument booking #{booking.pk}', 'outcome': 'Cancelled'})
        for reservation in plan['reservations']:
            if reservation.status == 'ACTIVE':
                reservation.status = 'RELEASED'
                reservation.save(update_fields=['status', 'updated_at'])
                _audit(action, 'InventoryLot', reservation.lot_id, 'INVENTORY_RELEASED', {'reservation_id': reservation.pk})
                details.append({'label': f'Stock reservation #{reservation.pk}', 'outcome': 'Released'})
    else:
        try:
            booking = InstrumentBooking.objects.create(instrument=plan['instrument'], project=plan['project'],
                starts_at=plan['fields']['starts_at'], ends_at=plan['fields']['ends_at'], note=plan['fields']['note'],
                created_by=action.requested_by, action=action)
        except IntegrityError as exc:
            raise ValidationError('This instrument was booked by another request. Choose a new time window.') from exc
        details.append({'label': f'Instrument booking #{booking.pk}', 'outcome': 'Reserved', 'instrument': plan['instrument'].code})
        for stock in plan['stocks']:
            reservation = InventoryReservation(lot=stock['lot'], project=plan['project'], quantity=stock['quantity'],
                unit=stock['unit'], created_by=action.requested_by)
            reservation.full_clean()
            reservation.save()
            booking.reservations.add(reservation)
            _audit(action, 'InventoryLot', stock['lot'].pk, 'INVENTORY_RESERVED',
                {'reservation_id': reservation.pk, 'quantity': str(stock['quantity']), 'unit': stock['unit'], 'booking_id': booking.pk})
            details.append({'label': stock['lot'].lot_code, 'outcome': 'Reserved', 'quantity': str(stock['quantity']), 'unit': stock['unit']})
        _audit(action, 'InstrumentBooking', booking.pk, 'INSTRUMENT_BOOKED',
            {'project_id': plan['project'].pk, 'instrument_id': plan['instrument'].pk, 'starts_at': plan['fields']['starts_at'], 'ends_at': plan['fields']['ends_at']})
    return {'operation': 'RESOURCE_CANCEL' if plan['fields']['mode'] == 'cancel' else 'RESOURCE_BOOK',
        'booking_id': booking.pk, 'succeeded_count': len(details), 'failed_count': 0, 'details': details,
        'message': 'Booking and linked reservations updated. No stock was consumed.'}
