"""Correct rejected source rows into a new, idempotent native import preview."""
import csv
import hashlib
import io
import uuid
from types import SimpleNamespace

from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from events.models import Event
from imports.assistant_uploads import MARKER, digest, inspect_upload, profile_snapshot, read_file, require_writer
from imports.csv_utils import get_csv_dict_reader
from imports.models import ImportJob, ImportRowRepair

from .instrument_imports import accessible_job, job_reply, prepare
from .lab_operation_common import StrictSerializer
from .models import AssistantAction


class RowCorrectionSerializer(StrictSerializer):
    row = serializers.IntegerField(min_value=1, max_value=10000)
    values = serializers.DictField(child=serializers.CharField(max_length=2000, allow_blank=True))

    def validate_values(self, value):
        if not 1 <= len(value) <= 50:
            raise ValidationError('Correct between one and 50 displayed source columns.')
        return value


class ImportRepairSerializer(StrictSerializer):
    parent_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
    corrections = RowCorrectionSerializer(many=True, min_length=1, max_length=20)
    skip_duplicates = serializers.BooleanField(default=True)


def repair_source(pk, user, *, lock=False):
    job = accessible_job(pk, user)
    require_writer(user, job.project)
    if job.uploaded_by_id != user.pk:
        raise PermissionDenied('Only the original uploader can prepare row repairs.')
    if lock:
        job = ImportJob.objects.select_for_update(of=('self',)).select_related('instrument', 'project').get(pk=job.pk)
    if job.status not in {'COMPLETED', 'FAILED'}:
        raise ValidationError('Wait for the original import to finish or fail before repairing its rejected rows.')
    frozen = job.summary[MARKER]
    if (frozen.get('owner_id') != job.uploaded_by_id or frozen.get('project_id') != job.project_id
            or frozen.get('instrument_id') != job.instrument_id or frozen.get('run_id') != job.run_id):
        raise ValidationError('The original import identity changed.')
    raw = read_file(job)
    if hashlib.sha256(raw).hexdigest() != frozen['file_sha256']:
        raise ValidationError('The original file changed. Its recorded source rows cannot be safely repaired.')
    reader, _ = get_csv_dict_reader(raw.decode('utf-8-sig'), SimpleNamespace(**frozen['config']))
    rows = list(reader)
    if len(rows) > 10000:
        raise ValidationError('The source exceeds the row repair limit.')
    rejected = {row['row']: row for row in job.summary.get('row_report', []) if row['status'] == 'rejected'}
    config = profile_snapshot(job.instrument)
    columns = list(dict.fromkeys([config['sample_id_column'], *[mapping['source_column'] for mapping in config['mappings']]]))
    return job, rows, rejected, columns, config


def rejected_rows(pk, user, offset=0):
    job, rows, rejected, columns, config = repair_source(pk, user)
    numbers = sorted(rejected)
    claims = {row.row_number: row for row in ImportRowRepair.objects.filter(parent=job).select_related('child')}
    return {'parent_id': job.pk, 'project': job.project.code, 'run_id': job.run_id, 'columns': columns,
        'mapping_changed': config != job.summary[MARKER]['config'], 'total': len(numbers), 'offset': offset,
        'next_offset': offset + 20 if offset + 20 < len(numbers) else None,
        'rows': [{'row': number, 'reason': rejected[number]['reason'],
                  'values': {key: rows[number - 1].get(key) or '' for key in columns},
                  'repair_job_id': claims[number].child_id if number in claims else None,
                  'repair_status': claims[number].child.status if number in claims else None} for number in numbers[offset:offset + 20]]}


def preview_repair(user, fields):
    serializer = ImportRepairSerializer(data=fields)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    saved_file = None
    try:
        with transaction.atomic():
            parent, rows, rejected, columns, config = repair_source(fields['parent_id'], user, lock=True)
            corrections = sorted(fields['corrections'], key=lambda row: row['row'])
            numbers = [row['row'] for row in corrections]
            if len(set(numbers)) != len(numbers) or any(number not in rejected for number in numbers):
                raise ValidationError('Choose each originally rejected data row once. Imported or duplicate rows cannot be retried here.')
            corrected = []
            for correction in corrections:
                if set(correction['values']) - set(columns):
                    raise ValidationError('Correct only the displayed sample ID and mapped source columns.')
                values = {key: rows[correction['row'] - 1].get(key) or '' for key in columns}
                values.update(correction['values'])
                corrected.append(values)
            output = io.StringIO()
            header_index = 0 if parent.instrument.auto_detect_header else parent.instrument.header_row_index or 0
            if header_index > 10000:
                raise ValidationError('The configured metadata header exceeds the chat repair limit.')
            output.write('OpenLIMS row repair metadata\n' * header_index)
            writer = csv.DictWriter(output, fieldnames=columns, delimiter=parent.instrument.delimiter)
            writer.writeheader()
            writer.writerows(corrected)
            raw = output.getvalue().encode('utf-8')
            analysis = inspect_upload(raw, parent.instrument, parent.project, user, fields['skip_duplicates'])
            if analysis['counts']['rows_rejected'] or not analysis['accepted']:
                errors = ' '.join(f"Original row {numbers[row['row'] - 1]}: {row['reason']}" for row in analysis['report'] if row['status'] == 'rejected')[:4000]
                raise ValidationError({'detail': 'Some corrected rows are still invalid; no repair import was created. ' + errors,
                                       'validation': {'row_report': analysis['report'], 'counts': analysis['counts']}})
            repair_digest = digest({'parent': parent.pk, 'owner': user.pk, 'file': parent.summary[MARKER]['file_sha256'],
                                    'config': config, 'corrections': corrections, 'skip_duplicates': fields['skip_duplicates']})
            run_id = f'repair-{parent.pk}-{repair_digest[:32]}'
            child = ImportJob.objects.filter(instrument=parent.instrument, run_id=run_id).first()
            if child and (child.uploaded_by_id != user.pk or child.project_id != parent.project_id
                    or child.summary.get('repair', {}).get('parent_id') != parent.pk
                    or child.summary.get('repair', {}).get('correction_digest') != repair_digest
                    or hashlib.sha256(read_file(child)).hexdigest() != analysis['file_sha256']):
                raise ValidationError('The repair run identity or corrected file changed. Review the existing receipt before preparing another correction.')
            claims = list(ImportRowRepair.objects.filter(parent=parent, row_number__in=numbers).select_related('child'))
            old_ids = sorted({claim.child_id for claim in claims})
            list(AssistantAction.objects.select_for_update().filter(action_type='QUEUE_IMPORT', payload__import_job_id__in=old_ids).order_by('pk'))
            old_jobs = {job.pk: job for job in ImportJob.objects.select_for_update().filter(pk__in=old_ids).order_by('pk')}
            for old in old_jobs.values():
                if child is not None and old.pk == child.pk:
                    continue
                if old.status == 'COMPLETED':
                    raise ValidationError(f'A selected row was already imported by repair #{old.pk}. Use its receipt or an audited result correction; do not import it twice.')
                if old.status == 'RUNNING' or old.status == 'PENDING' and not old.summary.get('awaiting_assistant_confirmation'):
                    raise ValidationError('A selected row is already queued for repair. Wait for its receipt or use the existing recovery controls.')
                old_numbers = set(ImportRowRepair.objects.filter(parent=parent, child=old).values_list('row_number', flat=True))
                if not old_numbers.issubset(numbers):
                    raise ValidationError('An earlier repair includes additional rows. Include all of those rows when replacing its unconfirmed preview.')
            if child and child.pk in old_jobs and all(claim.child_id == child.pk for claim in claims) and len(claims) == len(numbers):
                return job_reply(old_jobs[child.pk], user)
            for old in old_jobs.values():
                AssistantAction.objects.filter(action_type='QUEUE_IMPORT', payload__import_job_id=old.pk, status='PROPOSED').update(status='CANCELLED', error_message='Replaced by a corrected row-repair preview.')
                old.status = 'FAILED'
                old.summary = {**old.summary, 'error': 'This unconfirmed repair was superseded. No measurements were imported by this preview.'}
                old.save(update_fields=['status', 'summary'])
            if child is None:
                child = ImportJob(instrument=parent.instrument, project=parent.project, uploaded_by=user, run_id=run_id,
                    source_type='UPLOAD', status='PENDING', summary={})
                child.uploaded_file.name = child.uploaded_file.storage.save(
                    f'assistant_artifacts/import_repairs/{uuid.uuid4().hex}.csv', ContentFile(raw))
                saved_file = (child.uploaded_file.storage, child.uploaded_file.name)
                child.save()
            child.summary = {'repair': {'parent_id': parent.pk, 'parent_run_id': parent.run_id,
                'parent_file_sha256': parent.summary[MARKER]['file_sha256'], 'source_rows': numbers, 'correction_digest': repair_digest,
                'child_file_sha256': analysis['file_sha256'],
                'mapping_changed': config != parent.summary[MARKER]['config']}}
            for number in numbers:
                ImportRowRepair.objects.update_or_create(parent=parent, row_number=number, defaults={'child': child, 'created_by': user})
            result = prepare(child, analysis, user, fields['skip_duplicates'])
            Event.objects.create(entity_type='ImportJob', entity_id=str(child.pk), actor=user, action='ROW_REPAIR_PREPARED',
                payload={'assistant_action_id': str(result['pending_action']['id']),
                         'parent_id': parent.pk, 'source_rows': numbers, 'file_sha256': analysis['file_sha256']})
            return result
    except Exception:
        if saved_file:
            saved_file[0].delete(saved_file[1])
        raise
