"""Regression cases found while reviewing existing lab workflows."""
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from imports.assistant_uploads import process_prepared_job
from imports.models import ImportJob, ImportRowRepair
from results.models import Result

from . import test_lab_operations as fixtures


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class WorkflowRobustnessTests(APITestCase):
    setUp = fixtures.LabOperationTests.setUp
    user = fixtures.LabOperationTests.user
    preview = fixtures.LabOperationTests.preview
    confirm = fixtures.LabOperationTests.confirm
    parent_import = fixtures.LabOperationTests.parent_import

    def test_original_assistant_uploads_use_private_storage(self):
        parent = self.parent_import()
        self.assertTrue(parent.uploaded_file.name.startswith('assistant_artifacts/instrument_uploads/'))
        from config.urls import private_assistant_media
        self.assertIs(resolve(parent.uploaded_file.url).func, private_assistant_media)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(parent.uploaded_file.url).status_code, 404)

    def test_legacy_assistant_upload_media_urls_are_explicitly_denied(self):
        from config.urls import private_assistant_media
        url = '/media/imports/assistant-1234567890abcdef1234567890abcdef.csv'
        self.assertIs(resolve(url).func, private_assistant_media)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_debug_media_normalization_cannot_bypass_source_privacy(self):
        from types import ModuleType
        from django.conf import settings
        from django.core.files.base import ContentFile
        from django.urls import re_path
        from config.urls import serve_public_media
        parent = self.parent_import()
        raw = b'private-instrument-fixture'
        storage = parent.uploaded_file.storage
        legacy = storage.save('imports/assistant-1234567890abcdef1234567890abcdef.csv', ContentFile(raw))
        public = storage.save('imports/assistant-calibration.csv', ContentFile(b'ordinary-media'))
        urls = ModuleType('guarded_media_test_urls')
        urls.urlpatterns = [re_path(r'^media/(?P<path>.*)$', serve_public_media, {'document_root': settings.MEDIA_ROOT})]
        self.client.force_authenticate(None)
        with override_settings(ROOT_URLCONF=urls, DEBUG=True):
            paths = [parent.uploaded_file.name, '/' + parent.uploaded_file.name,
                     'public/../' + parent.uploaded_file.name, legacy.replace('imports/', 'imports//'),
                     legacy.replace('imports/', 'imports/sub/../')]
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(self.client.get('/media/' + path).status_code, 404)
            response = self.client.get('/media/' + public)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'ordinary-media')

    def test_source_download_requires_owner_or_admin_and_current_project_access(self):
        parent = self.parent_import()
        url = f'/api/v1/assistant/instrument-imports/{parent.pk}/source/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content), b'sample_id,value\nS-100,10\nS-101,bad\n')
        self.assertIn('no-store', self.client.get(f'/api/assistant/instrument-imports/{parent.pk}/report/')['Cache-Control'])
        for user in [self.maria, self.viewer, self.outsider]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_authenticate(self.user('administrator', 'admin'))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.project.members.remove(self.actor)
        self.client.force_authenticate(self.actor)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_general_import_listing_does_not_return_public_assistant_file_urls(self):
        parent = self.parent_import()
        url = f'/api/v1/import-jobs/{parent.pk}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(f'/assistant/instrument-imports/{parent.pk}/source/', response.data['uploaded_file'])
        self.client.force_authenticate(self.maria)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data['uploaded_file'])

    def test_source_visibility_does_not_query_roles_for_every_import_row(self):
        from django.db import connection
        from django.test import RequestFactory
        from django.test.utils import CaptureQueriesContext
        from imports.serializers import ImportJobSerializer
        parent = self.parent_import()
        loaded = ImportJob.objects.select_related('instrument', 'project', 'uploaded_by').get(pk=parent.pk)
        request = RequestFactory().get('/api/import-jobs/')
        request.user = self.maria
        with CaptureQueriesContext(connection) as queries:
            rows = ImportJobSerializer([loaded] * 20, many=True, context={'request': request}).data
        self.assertTrue(all(row['uploaded_file'] is None for row in rows))
        self.assertLessEqual(len(queries), 1)

    def test_source_download_validates_checksum_and_keeps_legacy_files_accessible(self):
        from django.core.files.base import ContentFile
        parent = self.parent_import()
        url = f'/api/v1/assistant/instrument-imports/{parent.pk}/source/'
        raw = b'sample_id,value\nS-100,10\nS-101,bad\n'
        parent.uploaded_file.name = parent.uploaded_file.storage.save(
            'imports/assistant-1234567890abcdef1234567890abcdef.csv', ContentFile(raw))
        parent.save(update_fields=['uploaded_file'])
        self.assertEqual(self.client.get(parent.uploaded_file.url).status_code, 404)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), raw)
        with parent.uploaded_file.storage.open(parent.uploaded_file.name, 'wb') as file:
            file.write(b'changed-file')
        self.assertEqual(self.client.get(url).status_code, 400)

    def repair_fields(self, parent):
        return {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]}

    def test_missing_stored_files_return_a_controlled_error_without_changing_claims(self):
        parent = self.parent_import()
        fields = self.repair_fields(parent)
        first = self.preview('repair', fields)
        child = ImportJob.objects.get(pk=first['instrument_import_job']['id'])
        child.uploaded_file.storage.delete(child.uploaded_file.name)
        response = self.client.post(f'/api/assistant/instrument-imports/{child.pk}/revalidate/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('unavailable', str(response.data).lower())
        self.preview('repair', fields, status=400)
        self.assertEqual(ImportRowRepair.objects.get(parent=parent).child_id, child.pk)
        self.assertEqual(Result.objects.count(), 1)

    def test_expired_and_cancelled_repairs_get_new_confirmable_previews(self):
        parent = self.parent_import()
        fields = self.repair_fields(parent)
        reply = self.preview('repair', fields)
        child_id = reply['instrument_import_job']['id']
        for status in ['EXPIRED', 'CANCELLED']:
            with self.subTest(status=status):
                previous = reply['pending_action']['id']
                AssistantAction.objects.filter(pk=previous).update(status=status, expires_at=timezone.now() - timedelta(minutes=1))
                reply = self.preview('repair', fields)
                self.assertEqual(reply['instrument_import_job']['id'], child_id)
                self.assertNotEqual(reply['pending_action']['id'], previous)
                self.assertEqual(Result.objects.count(), 1)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            action = self.confirm(reply)
        process_prepared_job(child_id, action['id'])
        process_prepared_job(child_id, action['id'])
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(ImportJob.objects.count(), 2)
        self.assertEqual(ImportRowRepair.objects.count(), 1)

    def test_failed_repair_can_be_validated_again_without_another_child(self):
        parent = self.parent_import()
        fields = self.repair_fields(parent)
        first = self.preview('repair', fields)
        child_id = first['instrument_import_job']['id']
        with patch('imports.tasks.process_assistant_import_job.delay'):
            action = self.confirm(first)
        with patch('imports.tasks.process_rows', side_effect=ValueError('Temporary processing failure')):
            process_prepared_job(child_id, action['id'])
        self.assertEqual(ImportJob.objects.get(pk=child_id).status, 'FAILED')
        retried = self.preview('repair', fields)
        self.assertEqual(retried['instrument_import_job']['id'], child_id)
        self.assertNotEqual(retried['pending_action']['id'], first['pending_action']['id'])
        self.assertEqual(Result.objects.count(), 1)
        with patch('imports.tasks.process_assistant_import_job.delay'):
            action = self.confirm(retried)
        process_prepared_job(child_id, action['id'])
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(ImportJob.objects.count(), 2)
