"""Frozen batch metadata updates and permission-checked shift handovers."""
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from events.models import Event
from notifications.models import Notification
from pipelines.models import PipelineRun, PipelineStepRun
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample, SampleBatch

from .daily_work import inspect_work, scoped_work
from .lab_operation_common import (StrictSerializer, OffsetDateTimeField, assert_unchanged,
    person_for_project, plain, preview, project_for_user, require_writer)
from .workflow_actions import FINAL_SAMPLES

MAX_WORK = 100


class BatchSerializer(StrictSerializer):
    project = serializers.CharField(max_length=64)
    batch = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    scope = serializers.ChoiceField(choices=['unassigned', 'mine', 'team'], default='unassigned')
    assign_to = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    deadline_mode = serializers.ChoiceField(choices=['keep', 'set', 'clear'], default='keep')
    due_at = OffsetDateTimeField(required=False, allow_null=True, default=None)

    def validate(self, data):
        if not data['assign_to'] and data['deadline_mode'] == 'keep':
            raise ValidationError('Choose an assignee or a deadline change.')
        if (data['deadline_mode'] == 'set') != (data['due_at'] is not None):
            raise ValidationError('Set requires an exact deadline; keep/clear must omit its value.')
        return data


class HandoverSerializer(StrictSerializer):
    project = serializers.CharField(max_length=64)
    batch = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    source = serializers.CharField(max_length=150, default='me')
    recipient = serializers.CharField(max_length=150)
    send_notice = serializers.BooleanField(default=True)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True, default='Please review the current work and its recorded blockers before proceeding.')


def _lock_records(ids):
    sample_ids = WorkItem.objects.filter(pk__in=ids).values_list('sample_id', flat=True)
    samples = list(Sample.objects.select_for_update().filter(pk__in=sample_ids).order_by('pk'))
    runs = list(PipelineRun.objects.select_for_update().filter(sample__in=samples).order_by('pk'))
    list(PipelineStepRun.objects.select_for_update().filter(pipeline_run__in=runs).order_by('pk'))
    list(WorkItem.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    list(Result.objects.select_for_update().filter(work_item_id__in=ids).order_by('pk'))


def work_plan(user, fields, *, handover=False, lock_ids=None):
    require_writer(user)
    serializer = (HandoverSerializer if handover else BatchSerializer)(data=fields)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    project = project_for_user(fields['project'], user, lock=lock_ids is not None)
    from .project_conversation import project_samples
    work = scoped_work(user).filter(sample__in=project_samples(project, user)).exclude(status__in=['COMPLETED', 'CANCELLED'])
    batch_id = None
    if fields['batch']:
        matches = list(SampleBatch.objects.filter(project=project, code__iexact=fields['batch'])[:2])
        if len(matches) != 1:
            raise ValidationError('Batch unavailable or ambiguous in this project. Use one exact code.')
        batch = matches[0]
        batch_id = batch.pk
        work = work.filter(sample__batch=batch)
    target = person_for_project(fields['recipient'] if handover else fields['assign_to'], project, user) if handover or fields['assign_to'] else None
    source = person_for_project(fields['source'], project, user) if handover else None
    if handover:
        if source.pk == target.pk:
            raise ValidationError('Choose a different handover recipient.')
        work = work.filter(assigned_to=source)
    elif fields['scope'] == 'mine':
        work = work.filter(assigned_to=user)
    elif fields['scope'] == 'unassigned':
        work = work.filter(assigned_to__isnull=True)
    if lock_ids is not None:
        _lock_records(lock_ids)
    records = list(work.order_by('pk')[:MAX_WORK + 1])
    if len(records) > MAX_WORK:
        raise ValidationError('This scope exceeds 100 unfinished work items. Narrow it to one batch; no subset was selected.')
    if not records:
        raise ValidationError('No unfinished accessible work matches this scope.')
    if Result.objects.filter(work_item__in=records).count() > 5000:
        raise ValidationError('This scope has too much result evidence. Narrow it to a smaller batch.')
    target_samples = set(get_sample_access_queryset(Sample.objects.filter(pk__in=[r.sample_id for r in records]), target, for_write=True).values_list('pk', flat=True)) if target else set()
    source_samples = set(get_sample_access_queryset(Sample.objects.filter(pk__in=[r.sample_id for r in records]), source, for_write=True).values_list('pk', flat=True)) if source else set()
    rows, eligible, excluded = [], [], []
    now = timezone.now()
    for work_item in records:
        row = inspect_work(work_item, user, now)
        rows.append(row)
        reason = None
        if work_item.sample.status in FINAL_SAMPLES or not user_can_modify_sample(user, work_item.sample):
            reason = 'The sample is final or not editable by you.'
        elif work_item.status not in ['PENDING', 'IN_PROGRESS']:
            reason = 'Failed work must be reviewed before metadata changes.'
        elif target and work_item.sample_id not in target_samples:
            reason = 'The recipient cannot access this sample.'
        elif source and work_item.sample_id not in source_samples:
            reason = 'The source user no longer has access to this sample.'
        proposed = {}
        if target:
            proposed['assigned_to'] = target.username
        if not handover and fields['deadline_mode'] != 'keep':
            proposed['due_at'] = fields['due_at'].isoformat() if fields['due_at'] else None
        current = {'assigned_to': row['assigned_to'], 'due_at': row['due']}
        if reason is None and all(current[key] == value for key, value in proposed.items()):
            reason = 'Already matches the requested metadata.'
        item = {'id': work_item.pk, 'label': f"Work #{work_item.pk} — {row['sample']}",
                'current': {**current, 'status': row['status'], 'attention': row['reason']}, 'proposed': proposed}
        if reason:
            excluded.append({'id': work_item.pk, 'label': item['label'], 'reason': reason})
        else:
            eligible.append(item)
    state = {'project': project.pk, 'batch': batch_id, 'rows': [(row['id'], row['digest']) for row in rows],
             'eligible': eligible, 'excluded': excluded, 'source': source.pk if source else None,
             'target': target.pk if target else None, 'target_samples': sorted(target_samples), 'source_samples': sorted(source_samples)}
    title = 'Shift handover' if handover else 'Batch work metadata'
    proposed = {'Recipient': target.username if target else 'Assignment unchanged'}
    if handover:
        proposed.update({'Internal notification': fields['send_notice'], 'Message': fields['message']})
    else:
        proposed['Deadline'] = fields['due_at'].isoformat() if fields['due_at'] else fields['deadline_mode']
    return {'fields': plain(fields), 'state': state, 'eligible': eligible, 'excluded': excluded,
        'work_ids': [work.pk for work in records], 'target': target, 'project': project,
        'preview': preview(title, user, project, eligible, proposed=proposed, excluded=excluded,
            warnings=['Only assignment/deadline metadata changes. Blocked work stays blocked; completion and QC decisions are unchanged.',
                      'All eligible changes apply together, or none apply if the preview becomes stale.', 'Completed/cancelled work is not selected.'])}


def execute_work_plan(action, *, handover=False):
    plan = work_plan(action.requested_by, action.payload['fields'], handover=handover, lock_ids=action.payload['work_ids'])
    assert_unchanged(action, plan)
    if not plan['eligible']:
        raise ValidationError('No eligible work remains.')
    results = []
    for item in plan['eligible']:
        work = WorkItem.objects.get(pk=item['id'])
        changed = []
        if 'assigned_to' in item['proposed']:
            work.assigned_to = plan['target']
            changed.append('assigned_to')
        if 'due_at' in item['proposed']:
            from django.utils.dateparse import parse_datetime
            work.due_at = parse_datetime(item['proposed']['due_at']) if item['proposed']['due_at'] else None
            changed.append('due_at')
        work.save(update_fields=[*changed, 'updated_at'])
        Event.objects.create(entity_type='WorkItem', entity_id=str(work.pk), actor=action.requested_by,
            action='SHIFT_HANDOVER' if handover else 'BATCH_METADATA_UPDATED',
            payload={'assistant_action_id': str(action.pk), 'before': item['current'], 'after': item['proposed'], 'project_id': plan['project'].pk})
        results.append({'label': item['label'], 'outcome': 'Updated', **item['proposed']})
    if handover and plan['fields']['send_notice']:
        Notification.objects.create(user=plan['target'], title='Work handover',
            message=f"{action.requested_by.username} handed over {len(results)} work items. {plan['fields']['message']}", link='/assistant')
    return {'operation': 'SHIFT_HANDOVER' if handover else 'BATCH_UPDATE', 'succeeded_count': len(results), 'failed_count': 0,
        'excluded_count': len(plan['excluded']), 'details': results,
        'message': f"Updated {len(results)} work items; {len(plan['excluded'])} excluded. Work completion and QC status were unchanged."}
