"""End-to-end confirmed chat capabilities and their native data contracts."""
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from events.models import Event
from imports.assistant_uploads import process_prepared_job
from imports.models import ImportJob, ImportRowRepair, InstrumentProfile, InstrumentColumnMapping
from inventory.models import InventoryItem, InventoryLot, InventoryReservation, InstrumentBooking
from notebook.models import Notebook, Experiment, ExperimentRevision
from notifications.models import Notification
from projects.models import Project
from results.models import WorkItem, Result
from samples.models import Sample, SampleBatch


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class LabOperationTests(APITestCase):
    def setUp(self):
        publication = patch('imports.tasks.broadcast_import_job_update')
        publication.start()
        self.addCleanup(publication.stop)
        media = tempfile.TemporaryDirectory(prefix='lab-operations-')
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = self.user('eduardo')
        self.maria = self.user('maria')
        self.outsider = self.user('outsider')
        self.viewer = self.user('viewer', 'viewer')
        self.project = Project.objects.create(code='ALPHA', name='Alpha')
        self.project.members.add(self.actor, self.maria, self.viewer)
        self.private = Project.objects.create(code='PRIVATE', name='Private')
        self.private.members.add(self.outsider)
        self.batch = SampleBatch.objects.create(code='B-100', project=self.project, created_by=self.actor)
        self.sample = Sample.objects.create(sample_id='S-100', project=self.project, batch=self.batch, created_by=self.actor)
        self.second = Sample.objects.create(sample_id='S-101', project=self.project, batch=self.batch, created_by=self.actor)
        self.work = WorkItem.objects.create(sample=self.sample, name='Prepare', assigned_to=self.actor, created_by=self.actor)
        self.unassigned = WorkItem.objects.create(sample=self.second, name='Measure', created_by=self.actor)
        self.instrument = InstrumentProfile.objects.create(code='SEQ-1', name='Sequencer', sample_id_column='sample_id')
        InstrumentColumnMapping.objects.create(instrument=self.instrument, source_column='value', target_key='concentration', value_type='NUMBER')
        item = InventoryItem.objects.create(code='BUFFER', name='Buffer', category='REAGENT', default_unit='ml')
        self.lot = InventoryLot.objects.create(item=item, lot_code='LOT-1', quantity=Decimal('20'), unit='ml')
        self.notebook = Notebook.objects.create(name='Project lab notes', scope='PROJECT', project=self.project, owner=self.actor)
        self.client.force_authenticate(self.actor)

    def user(self, username, role='tech'):
        user = get_user_model().objects.create_user(username=username)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def preview(self, kind, fields, status=201):
        reply = self.client.post('/api/v1/assistant/lab-operations/preview/', {'kind': kind, 'fields': fields}, format='json')
        self.assertEqual(reply.status_code, status, reply.data)
        return reply.data

    def confirm(self, reply):
        action = reply['pending_action']
        response = self.client.post(f"/api/assistant/actions/{action['confirmation_token']}/confirm/", {'confirm': True}, format='json')
        self.assertIn(response.status_code, [200, 202], response.data)
        return response.data

    def resources(self, **changes):
        start = timezone.now() + timedelta(days=2)
        return {'project': 'ALPHA', 'instrument': 'SEQ-1', 'starts_at': start.isoformat(), 'ends_at': (start + timedelta(hours=2)).isoformat(),
                'stocks': [{'lot': 'LOT-1', 'quantity': '2', 'unit': 'ml'}], **changes}

    def parent_import(self):
        reply = self.client.post('/api/assistant/instrument-imports/', {'instrument': self.instrument.pk, 'project': self.project.pk,
            'run_id': 'RUN-1', 'uploaded_file': SimpleUploadedFile('source.csv', b'sample_id,value\nS-100,10\nS-101,bad\n', content_type='text/csv')}, format='multipart')
        self.assertEqual(reply.status_code, 201, reply.data)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            confirmed = self.confirm(reply.data)
        job = ImportJob.objects.get(pk=confirmed['result']['import_job_id'])
        process_prepared_job(job.pk, confirmed['id'])
        job.refresh_from_db()
        self.assertEqual(job.status, 'COMPLETED')
        return job

    def test_batch_assignment_and_deadline_execute_once(self):
        due = (timezone.now() + timedelta(days=4)).isoformat()
        reply = self.preview('batch', {'project': 'ALPHA', 'batch': 'B-100', 'scope': 'unassigned', 'assign_to': 'maria', 'deadline_mode': 'set', 'due_at': due})
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.assigned_to_id)
        result = self.confirm(reply)
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.unassigned.refresh_from_db()
        self.assertEqual(self.unassigned.assigned_to, self.maria)
        self.assertIsNotNone(self.unassigned.due_at)
        self.assertEqual(self.confirm(reply)['result'], result['result'])

    def test_handover_reassigns_without_completing_and_sends_one_notice(self):
        reply = self.preview('handover', {'project': 'ALPHA', 'source': 'me', 'recipient': 'maria'})
        self.assertFalse(Notification.objects.exists())
        result = self.confirm(reply)
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.work.refresh_from_db()
        self.assertEqual(self.work.assigned_to, self.maria)
        self.assertEqual(self.work.status, 'PENDING')
        self.confirm(reply)
        self.assertEqual(Notification.objects.filter(user=self.maria).count(), 1)

    def test_resource_booking_reserves_stock_and_can_cancel_in_chat(self):
        reply = self.preview('resources', self.resources())
        self.assertFalse(InstrumentBooking.objects.exists())
        result = self.confirm(reply)
        self.assertEqual(result['status'], 'COMPLETED', result)
        self.assertEqual(InstrumentBooking.objects.count(), 1)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.available_quantity, Decimal('18'))
        cancelled = self.preview('resources', {'project': 'ALPHA', 'mode': 'cancel', 'booking_id': result['result']['booking_id']})
        self.assertEqual(self.confirm(cancelled)['status'], 'COMPLETED')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.available_quantity, Decimal('20'))
        self.assertEqual(InventoryReservation.objects.get().status, 'RELEASED')

    def test_notebook_draft_uses_real_import_results_and_native_revision(self):
        job = self.parent_import()
        reply = self.preview('notebook', {'project': 'ALPHA', 'source_kind': 'import', 'source_id': job.pk,
            'notebook_id': self.notebook.pk, 'title': 'Sequencing evidence'})
        self.assertEqual(Experiment.objects.count(), 0)
        result = self.confirm(reply)
        self.assertEqual(result['status'], 'COMPLETED', result)
        experiment = Experiment.objects.get()
        self.assertEqual(experiment.status, 'DRAFT')
        revision = ExperimentRevision.objects.get(experiment=experiment)
        self.assertTrue(revision.links.exists())
        table = revision.blocks.get(block_type='TABLE').data['rows']
        self.assertEqual(table[1][3], '10.0')
        self.assertEqual(self.confirm(reply)['result']['experiment_id'], experiment.pk)

    def test_repair_only_rejected_rows_and_never_duplicates_a_completed_repair(self):
        parent = self.parent_import()
        fields = {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]}
        reply = self.preview('repair', fields)
        child_id = reply['instrument_import_job']['id']
        self.assertNotEqual(child_id, parent.pk)
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(self.preview('repair', fields)['instrument_import_job']['id'], child_id)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            confirmed = self.confirm(reply)
        process_prepared_job(child_id, confirmed['id'])
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(ImportRowRepair.objects.get(parent=parent, row_number=2).child_id, child_id)
        self.assertEqual(self.preview('repair', fields, status=200)['instrument_import_job']['status'], 'COMPLETED')
        fields['corrections'][0]['values']['value'] = '13'
        self.preview('repair', fields, status=400)
        self.assertEqual(Result.objects.count(), 2)

    def test_all_five_commands_open_inline_forms(self):
        cases = [('Manage batch B-100 in project ALPHA', 'batch'), ('Reserve resources for project ALPHA', 'resources'),
            ('Repair import 12', 'repair'), ('Create a notebook draft from this run', 'notebook'), ('Hand my unfinished ALPHA work to maria', 'handover')]
        for message, kind in cases:
            with self.subTest(message=message):
                reply = self.client.post('/api/assistant/chat/', {'message': message}, format='json')
                self.assertEqual(reply.status_code, 200, reply.data)
                self.assertEqual(reply.data['lab_operation_form']['kind'], kind)
                self.assertNotIn('pending_action', reply.data)
        self.assertFalse(AssistantAction.objects.exists())

    def failed_confirmation(self, reply):
        response = self.client.post(f"/api/assistant/actions/{reply['pending_action']['confirmation_token']}/confirm/", {'confirm': True}, format='json')
        self.assertIn(response.status_code, [400, 403], response.data)
        return response.data

    def pipeline(self):
        from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep
        from pipelines.services import start_pipeline
        analysis = AnalysisDefinition.objects.create(code='PREP', name='Preparation')
        procedure = ProcedureDefinition.objects.create(code='EXTRACT', name='Extraction', version='2', analysis=analysis)
        template = PipelineTemplate.objects.create(code='PREP', name='Preparation')
        PipelineTemplateStep.objects.create(template=template, position=1, procedure=procedure)
        return start_pipeline(sample=self.sample, template=template, actor=self.actor)

    def test_batch_stale_scope_is_atomic_and_has_no_notification(self):
        reply = self.preview('batch', {'project': 'ALPHA', 'scope': 'unassigned', 'assign_to': 'maria'})
        sample = Sample.objects.create(sample_id='NEW-WORK', project=self.project, created_by=self.actor)
        WorkItem.objects.create(sample=sample, name='New work', created_by=self.actor)
        self.failed_confirmation(reply)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.assigned_to_id)
        self.assertFalse(Notification.objects.exists())

    def test_batch_exclusions_and_blocked_work_do_not_bypass_gates(self):
        run = self.pipeline()
        step = run.steps.get(position=1)
        step.status = 'BLOCKED'
        step.save()
        run.status = 'BLOCKED'
        run.save()
        failed = WorkItem.objects.create(sample=self.second, name='Failed', status='FAILED', created_by=self.actor)
        reply = self.preview('batch', {'project': 'ALPHA', 'scope': 'team', 'assign_to': 'maria'})
        self.assertIn(failed.pk, [row['id'] for row in reply['pending_action']['preview']['excluded']])
        self.assertEqual(self.confirm(reply)['status'], 'COMPLETED')
        step.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(step.status, 'BLOCKED')
        self.assertEqual(run.status, 'BLOCKED')
        self.assertEqual(step.work_item.status, 'PENDING')

    def test_actor_and_recipient_permissions_are_rechecked(self):
        reply = self.preview('batch', {'project': 'ALPHA', 'assign_to': 'maria'})
        self.project.members.remove(self.maria)
        self.failed_confirmation(reply)
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.assigned_to_id)
        self.client.force_authenticate(self.viewer)
        self.preview('batch', {'project': 'ALPHA', 'assign_to': 'eduardo'}, status=403)

    def test_batch_limit_and_deadline_validation(self):
        SampleBatch.objects.create(code='b-100', project=self.project, created_by=self.actor)
        self.preview('batch', {'project': 'ALPHA', 'batch': 'B-100', 'assign_to': 'maria'}, status=400)
        self.preview('batch', {'project': 'ALPHA', 'deadline_mode': 'set', 'due_at': '2026-12-01T10:00:00'}, status=400)
        self.preview('batch', {'project': 'ALPHA', 'assign_to': 'maria', 'unexpected': True}, status=400)
        for index in range(100):
            sample = Sample.objects.create(sample_id=f'LIMIT-{index}', project=self.project, created_by=self.actor)
            WorkItem.objects.create(sample=sample, name=f'Extra {index}', created_by=self.actor)
        self.preview('batch', {'project': 'ALPHA', 'assign_to': 'maria'}, status=400)
        self.assertFalse(AssistantAction.objects.exists())

    def test_deadlines_can_be_cleared_without_changing_assignment(self):
        self.unassigned.due_at = timezone.now() + timedelta(days=1)
        self.unassigned.save()
        reply = self.preview('batch', {'project': 'ALPHA', 'deadline_mode': 'clear'})
        self.assertEqual(self.confirm(reply)['status'], 'COMPLETED')
        self.unassigned.refresh_from_db()
        self.assertIsNone(self.unassigned.due_at)
        self.assertIsNone(self.unassigned.assigned_to_id)

    def test_handover_can_omit_notice_and_fails_atomically_if_assignment_changes(self):
        reply = self.preview('handover', {'project': 'ALPHA', 'recipient': 'maria', 'send_notice': False})
        self.assertEqual(self.confirm(reply)['status'], 'COMPLETED')
        self.assertFalse(Notification.objects.exists())
        self.work.assigned_to = self.actor
        self.work.save()
        reply = self.preview('handover', {'project': 'ALPHA', 'recipient': 'maria'})
        self.work.status = 'FAILED'
        self.work.save()
        self.failed_confirmation(reply)
        self.assertFalse(Notification.objects.exists())
        self.work.refresh_from_db()
        self.assertEqual(self.work.assigned_to, self.actor)

    def test_resource_conflicts_are_exclusive_but_adjacent_slots_are_allowed(self):
        fields = self.resources(stocks=[])
        self.confirm(self.preview('resources', fields))
        self.preview('resources', fields, status=400)
        from django.utils.dateparse import parse_datetime
        next_start = parse_datetime(fields['ends_at'])
        fields.update(starts_at=next_start.isoformat(), ends_at=(next_start + timedelta(hours=1)).isoformat())
        self.confirm(self.preview('resources', fields))
        self.assertEqual(InstrumentBooking.objects.count(), 2)

    def test_changed_stock_fails_without_creating_any_booking(self):
        reply = self.preview('resources', self.resources())
        self.lot.quantity = Decimal('1')
        self.lot.save()
        self.failed_confirmation(reply)
        self.assertFalse(InstrumentBooking.objects.exists())
        self.assertFalse(InventoryReservation.objects.exists())

    def test_invalid_stock_time_and_duplicate_lots_are_rejected(self):
        for fields in [self.resources(starts_at='2026-12-01T10:00:00'),
                       self.resources(stocks=[{'lot': 'LOT-1', 'quantity': '2', 'unit': 'g'}]),
                       self.resources(stocks=[{'lot': 'LOT-1', 'quantity': '100', 'unit': 'ml'}]),
                       self.resources(stocks=[{'lot': 'LOT-1', 'quantity': '1', 'unit': 'ml'}] * 2)]:
            with self.subTest(fields=fields):
                self.preview('resources', fields, status=400)
        self.lot.status = 'QUARANTINED'
        self.lot.save()
        self.preview('resources', self.resources(), status=400)
        self.assertFalse(AssistantAction.objects.exists())

    def test_cancel_does_not_reverse_consumed_stock_and_requires_owner(self):
        booked = self.confirm(self.preview('resources', self.resources()))
        fields = {'project': 'ALPHA', 'mode': 'cancel', 'booking_id': booked['result']['booking_id']}
        self.client.force_authenticate(self.maria)
        self.preview('resources', fields, status=403)
        self.client.force_authenticate(self.actor)
        reply = self.preview('resources', fields)
        reservation = InventoryReservation.objects.get()
        reservation.status = 'CONSUMED'
        reservation.save()
        self.failed_confirmation(reply)
        self.confirm(self.preview('resources', fields))
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'CONSUMED')

    def test_pipeline_notebook_preserves_zero_false_and_versions(self):
        run = self.pipeline()
        work = run.steps.get(position=1).work_item
        Result.objects.create(work_item=work, key='zero', value_type='NUMBER', value_number=0, qc_passed=False, qc_status='APPROVED', entered_by=self.actor)
        Result.objects.create(work_item=work, key='negative', value_type='BOOLEAN', value_boolean=False, entered_by=self.actor)
        fields = {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk, 'notebook_id': self.notebook.pk,
                  'title': 'Preparation evidence', 'method_notes': 'Actual method recorded by scientist.'}
        self.confirm(self.preview('notebook', fields))
        experiment = Experiment.objects.get()
        self.assertEqual(experiment.status, 'DRAFT')
        blocks = list(experiment.current_revision.blocks.values_list('data', flat=True))
        import json
        text = json.dumps(blocks)
        for expected in ['EXTRACT@2', '0.0', 'False', 'Failed', 'APPROVED', 'Actual method recorded by scientist.']:
            self.assertIn(expected, text)

    def test_notebook_audience_and_evidence_changes_require_a_fresh_preview(self):
        run = self.pipeline()
        fields = {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk, 'notebook_id': self.notebook.pk, 'title': 'Evidence'}
        reply = self.preview('notebook', fields)
        self.notebook.readers.add(self.outsider)
        self.failed_confirmation(reply)
        self.preview('notebook', fields, status=403)
        self.notebook.readers.remove(self.outsider)
        reply = self.preview('notebook', fields)
        Result.objects.create(work_item=run.steps.get(position=1).work_item, key='new', value_type='NUMBER', value_number=2, entered_by=self.actor)
        self.failed_confirmation(reply)
        self.assertFalse(Experiment.objects.exists())

    def test_notebook_respects_native_explicit_editor_permissions(self):
        run = self.pipeline()
        fields = {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk, 'notebook_id': self.notebook.pk, 'title': 'Evidence'}
        self.client.force_authenticate(self.viewer)
        self.preview('notebook', fields, status=403)
        self.notebook.editors.add(self.viewer)
        reply = self.preview('notebook', fields)
        self.assertEqual(self.confirm(reply)['status'], 'COMPLETED')

    def test_competing_notebook_previews_create_only_one_draft(self):
        run = self.pipeline()
        fields = {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk, 'notebook_id': self.notebook.pk, 'title': 'Evidence'}
        first, second = self.preview('notebook', fields), self.preview('notebook', fields)
        self.confirm(first)
        self.failed_confirmation(second)
        self.assertEqual(Experiment.objects.count(), 1)

    def test_repair_refuses_imported_or_still_invalid_rows_without_orphan_files(self):
        parent = self.parent_import()
        from pathlib import Path
        from django.conf import settings
        before = sorted(path.relative_to(settings.MEDIA_ROOT) for path in Path(settings.MEDIA_ROOT).rglob('*') if path.is_file())
        self.preview('repair', {'parent_id': parent.pk, 'corrections': [{'row': 1, 'values': {'value': '99'}}]}, status=400)
        failed = self.preview('repair', {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': 'still bad'}}]}, status=400)
        self.assertIn('Original row 2', str(failed))
        after = sorted(path.relative_to(settings.MEDIA_ROOT) for path in Path(settings.MEDIA_ROOT).rglob('*') if path.is_file())
        self.assertEqual(before, after)
        self.assertFalse(ImportRowRepair.objects.exists())

    def test_repair_supersedes_unconfirmed_corrections_but_never_queued_work(self):
        parent = self.parent_import()
        fields = {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]}
        first = self.preview('repair', fields)
        fields['corrections'][0]['values']['value'] = '13'
        second = self.preview('repair', fields)
        self.failed_confirmation(first)
        process_prepared_job(first['instrument_import_job']['id'], first['pending_action']['id'])
        self.assertEqual(Result.objects.count(), 1)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            confirmed = self.confirm(second)
        fields['corrections'][0]['values']['value'] = '14'
        self.preview('repair', fields, status=400)
        process_prepared_job(second['instrument_import_job']['id'], confirmed['id'])
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(Result.objects.order_by('-pk').first().value_number, 13)

    def test_repair_lineage_csv_and_private_file_path(self):
        parent = self.parent_import()
        reply = self.preview('repair', {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]})
        child = ImportJob.objects.get(pk=reply['instrument_import_job']['id'])
        self.assertTrue(child.uploaded_file.name.startswith('assistant_artifacts/import_repairs/'))
        self.assertEqual(self.client.get(child.uploaded_file.url).status_code, 404)
        from imports.assistant_uploads import report_csv
        import csv, io
        rows = list(csv.DictReader(io.StringIO(report_csv(child).decode('utf-8-sig'))))
        self.assertEqual(rows[0]['original_import'], str(parent.pk))
        self.assertEqual(rows[0]['original_data_row'], '2')

    def test_repair_source_and_mapping_are_rechecked(self):
        parent = self.parent_import()
        mapping = self.instrument.column_mappings.get()
        mapping.source_column = 'new_value'
        mapping.save()
        reply = self.preview('repair', {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'new_value': '12'}}]})
        self.assertTrue(reply['instrument_import_job']['repair']['mapping_changed'])
        self.client.force_authenticate(self.outsider)
        self.preview('repair', {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'new_value': '12'}}]}, status=404)

    def test_assistant_audit_entries_are_visible_only_to_actor_or_admin(self):
        run = self.pipeline()
        self.confirm(self.preview('notebook', {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk,
            'notebook_id': self.notebook.pk, 'title': 'PRIVATE SCIENTIFIC DRAFT'}))
        events = Event.objects.filter(payload__has_key='assistant_action_id')
        self.assertTrue(events.exists())
        self.client.force_authenticate(self.outsider)
        response = self.client.get('/api/events/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('PRIVATE SCIENTIFIC DRAFT', str(response.data))
        self.assertNotIn('assistant_action_id', str(response.data))
        for user in [self.actor, self.user('admin-auditor', 'admin')]:
            self.client.force_authenticate(user)
            self.assertIn('PRIVATE SCIENTIFIC DRAFT', str(self.client.get('/api/events/').data))

    def test_options_and_unknown_followups_do_not_leak_revoked_projects(self):
        options = self.client.get('/api/assistant/lab-operations/options/', {'kind': 'resources', 'project': 'ALPHA'})
        self.assertEqual(options.status_code, 200, options.data)
        self.assertNotIn('PRIVATE', str(options.data))
        context = {'lab_operation': {'kind': 'batch', 'defaults': {'project': 'ALPHA'}}}
        self.project.members.remove(self.actor)
        response = self.client.post('/api/assistant/chat/', {'message': 'please unpack that', 'context': context}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['context'], {})

    def test_malformed_fields_and_context_never_execute_an_operation(self):
        for fields in [{'project': 'ALPHA', 'source_kind': 'import', 'source_id': True, 'notebook_id': self.notebook.pk, 'title': 'Bad'},
                       {'project': 'ALPHA', 'source_kind': 'import', 'source_id': 10**100, 'notebook_id': self.notebook.pk, 'title': 'Bad'}]:
            self.preview('notebook', fields, status=400)
        for state in [{'kind': []}, {'kind': {}}, {'kind': 'batch', 'defaults': []}]:
            reply = self.client.post('/api/assistant/chat/', {'message': 'hello', 'context': {'lab_operation': state}}, format='json')
            self.assertEqual(reply.status_code, 200, reply.data)
        self.assertFalse(AssistantAction.objects.exists())

    def test_import_context_can_prefill_a_notebook_without_guessing_a_destination(self):
        parent = self.parent_import()
        response = self.client.post('/api/assistant/chat/', {'message': 'Create a notebook draft from this run',
            'context': {'instrument_import_job_id': parent.pk}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        defaults = response.data['lab_operation_form']['defaults']
        self.assertEqual(defaults['source_id'], parent.pk)
        self.assertEqual(defaults['source_kind'], 'import')
        self.assertEqual(defaults['project'], 'ALPHA')
        self.assertNotIn('notebook_id', defaults)
        self.assertFalse(Experiment.objects.exists())

    def test_unsupported_batch_conditions_do_not_widen_scope(self):
        response = self.client.post('/api/assistant/chat/', {'message': "Assign ALPHA's unassigned work to maria except S-101"}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('pending_action', response.data)
        self.assertNotIn('lab_operation_form', response.data)
        self.assertFalse(AssistantAction.objects.exists())

    def test_repair_failure_rolls_back_claims_actions_and_the_new_file(self):
        parent = self.parent_import()
        from assistant.import_repairs import preview_repair
        from pathlib import Path
        from django.conf import settings
        before = set(path.name for path in Path(settings.MEDIA_ROOT).rglob('*') if path.is_file())
        original = Event.objects.create
        def audit(**kwargs):
            if kwargs.get('action') == 'ROW_REPAIR_PREPARED':
                raise RuntimeError('Injected audit failure')
            return original(**kwargs)
        with patch('assistant.import_repairs.Event.objects.create', side_effect=audit), self.assertRaises(RuntimeError):
            preview_repair(self.actor, {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]})
        self.assertEqual(set(path.name for path in Path(settings.MEDIA_ROOT).rglob('*') if path.is_file()), before)
        self.assertEqual(ImportJob.objects.count(), 1)
        self.assertFalse(ImportRowRepair.objects.exists())

    def test_notebook_template_keeps_native_steps_revisions_and_private_audit(self):
        from notebook.models import ExperimentTemplate
        run = self.pipeline()
        template = ExperimentTemplate.objects.create(notebook=self.notebook, name='Recorded procedure',
            blocks=[{'block_type': 'RICH_TEXT', 'data': {'text': 'Template method instructions'}}],
            workflow_steps=[{'name': 'Review source evidence', 'fields': [], 'assignee': self.maria.pk}])
        reply = self.preview('notebook', {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk,
            'notebook_id': self.notebook.pk, 'template_id': template.pk, 'title': 'PRIVATE TEMPLATE DRAFT'})
        preview = reply['pending_action']['preview']
        self.assertEqual(preview['proposed_values']['Template workflow steps'][0]['assignee'], self.maria.pk)
        self.assertIn('internal assignment notifications', ' '.join(preview['warnings']))
        result = self.confirm(reply)['result']
        experiment = Experiment.objects.get(pk=result['experiment_id'])
        self.assertEqual(experiment.status, 'DRAFT')
        self.assertEqual(experiment.template_id, template.pk)
        self.assertEqual(experiment.workflow_steps.get().assignee_id, self.maria.pk)
        self.assertEqual(experiment.revisions.count(), 2)
        revision = experiment.revisions.order_by('-number').first()
        blocks = list(revision.blocks.values_list('data', flat=True))
        self.assertIn('Template method instructions', str(blocks))
        self.assertIn('EXTRACT@2', str(blocks))
        events = Event.objects.filter(entity_type__iexact='experiment', entity_id=str(experiment.public_id))
        self.assertTrue(events.exists())
        self.assertTrue(all('assistant_action_id' in event.payload for event in events))

    def test_repair_preserves_manual_header_and_hides_preview_audit(self):
        self.instrument.auto_detect_header = False
        self.instrument.header_row_index = 2
        self.instrument.save()
        response = self.client.post('/api/assistant/instrument-imports/', {'instrument': self.instrument.pk, 'project': self.project.pk,
            'run_id': 'HEADER-RUN', 'uploaded_file': SimpleUploadedFile('source.csv',
                b'Instrument metadata\nRun metadata\nsample_id,value\nS-100,10\nS-101,bad\n', content_type='text/csv')}, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            confirmed = self.confirm(response.data)
        parent_id = confirmed['result']['import_job_id']
        process_prepared_job(parent_id, confirmed['id'])
        repair = self.preview('repair', {'parent_id': parent_id, 'corrections': [{'row': 2, 'values': {'value': '12'}}]})
        child = ImportJob.objects.get(pk=repair['instrument_import_job']['id'])
        self.assertEqual(child.summary['repair']['source_rows'], [2])
        event = Event.objects.get(action='ROW_REPAIR_PREPARED')
        self.assertEqual(event.payload['assistant_action_id'], repair['pending_action']['id'])
        self.client.force_authenticate(self.outsider)
        self.assertNotIn('ROW_REPAIR_PREPARED', str(self.client.get('/api/events/').data))

    def test_repair_retry_rejects_a_changed_child_owner_or_file(self):
        parent = self.parent_import()
        fields = {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]}
        child = ImportJob.objects.get(pk=self.preview('repair', fields)['instrument_import_job']['id'])
        before = child.summary.copy()
        ImportJob.objects.filter(pk=child.pk).update(uploaded_by=self.maria)
        from imports.assistant_uploads import validate_repair_claim
        with self.assertRaises(ValueError):
            validate_repair_claim(ImportJob.objects.get(pk=child.pk))
        self.preview('repair', fields, status=400)
        child.refresh_from_db()
        self.assertEqual(child.summary, before)
        ImportJob.objects.filter(pk=child.pk).update(uploaded_by=self.actor)
        with child.uploaded_file.storage.open(child.uploaded_file.name, 'wb') as file:
            file.write(b'sample_id,value\nS-101,99\n')
        self.preview('repair', fields, status=400)
        self.assertEqual(ImportRowRepair.objects.get(parent=parent).child_id, child.pk)
        self.assertEqual(ImportJob.objects.count(), 2)
