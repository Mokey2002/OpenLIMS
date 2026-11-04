"""Shared validation for explicit, reviewable chat laboratory operations."""
import hashlib
import json
import re
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import is_admin, is_tech
from projects.models import Project


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({'detail': 'Use only the displayed operation fields.'})
        if hasattr(data, 'getlist') and any(len(data.getlist(key)) != 1 for key in data):
            raise ValidationError({'detail': 'Supply each field once.'})
        if any(isinstance(field, serializers.IntegerField) and isinstance(data.get(key), bool) for key, field in self.fields.items()):
            raise ValidationError({'detail': 'Record IDs and row numbers must be integers, not booleans.'})
        return super().to_internal_value(data)


class OffsetDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        if not isinstance(value, str) or not re.search(r'(?:Z|[+-]\d{2}:\d{2})$', value):
            raise ValidationError('Use an explicit UTC/offset timestamp.')
        parsed = super().to_internal_value(value)
        if not timezone.is_aware(parsed):
            raise ValidationError('Use an explicit UTC/offset timestamp.')
        return parsed


class CompletePrecisionEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return super().default(value)


def plain(value):
    return json.loads(json.dumps(value, cls=CompletePrecisionEncoder, allow_nan=False))


def fingerprint(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require_writer(user):
    if not user.is_active or not (is_admin(user) or is_tech(user)):
        raise PermissionDenied('An active Tech or Admin is required for this operation.')


def project_for_user(code, user, *, lock=False):
    if not user.is_active:
        raise PermissionDenied('Your account is inactive.')
    records = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    if lock:
        records = records.select_for_update(of=('self',))
    matches = list(records.filter(code__iexact=code)[:2])
    if len(matches) != 1:
        raise ValidationError('Use one exact accessible project code.')
    return matches[0]


def person_for_project(name, project, user):
    if name.casefold() in {'me', 'myself'}:
        name = user.username
    records = get_user_model().objects.filter(is_active=True, username__iexact=name)
    matches = list(records[:2])
    if len(matches) != 1 or not (is_admin(matches[0]) or project.members.filter(pk=matches[0].pk).exists()):
        raise ValidationError('Use an exact active username with access to this project.')
    return matches[0]


def assert_unchanged(action, plan):
    if fingerprint(plan['state']) != action.payload.get('digest'):
        raise ValidationError('The scope, permissions or evidence changed after preview. Nothing was changed; request a new preview.')


def preview(title, user, project, records, *, proposed=None, excluded=None, warnings=None):
    return {'title': title, 'operation': title, 'project': {'label': project.code},
        'requested_user': {'username': user.username}, 'records_affected': len(records),
        'current_values': {'Project': project.code}, 'proposed_values': proposed or {},
        'records': records, 'excluded': excluded or [], 'warnings': warnings or []}
