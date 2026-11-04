"""Real PostgreSQL races for chat operations; each thread owns its connection."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITransactionTestCase

from assistant.models import AssistantAction
from imports.models import ImportJob, ImportRowRepair
from inventory.models import InstrumentBooking, InventoryReservation
from notebook.models import Experiment

from . import test_lab_operations as fixtures


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks/exclusion constraints required')
@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class LabOperationConcurrencyTests(APITransactionTestCase):
    setUp = fixtures.LabOperationTests.setUp
    user = fixtures.LabOperationTests.user
    preview = fixtures.LabOperationTests.preview
    confirm = fixtures.LabOperationTests.confirm
    resources = fixtures.LabOperationTests.resources
    parent_import = fixtures.LabOperationTests.parent_import
    pipeline = fixtures.LabOperationTests.pipeline

    def race(self, requests):
        barrier = Barrier(len(requests))
        def run(item):
            user_id, path, payload = item
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=user_id))
                barrier.wait(timeout=15)
                response = client.post(path, payload, format='json')
                return response.status_code, response.data
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            return list(executor.map(run, requests))

    def confirmation(self, user, reply):
        return user.pk, f"/api/assistant/actions/{reply['pending_action']['confirmation_token']}/confirm/", {'confirm': True}

    def test_instrument_conflict_across_different_projects_is_serialized(self):
        fields = self.resources(stocks=[])
        first = self.preview('resources', fields)
        self.client.force_authenticate(self.outsider)
        second = self.preview('resources', {**fields, 'project': 'PRIVATE'})
        result = self.race([self.confirmation(self.actor, first), self.confirmation(self.outsider, second)])
        self.assertEqual(sorted(code for code, _ in result), [200, 400], result)
        self.assertEqual(InstrumentBooking.objects.count(), 1)

    def test_two_instruments_cannot_over_reserve_one_lot(self):
        from imports.models import InstrumentProfile
        InstrumentProfile.objects.create(code='SEQ-2', name='Second sequencer', sample_id_column='sample_id')
        fields = self.resources(stocks=[{'lot': 'LOT-1', 'quantity': '15', 'unit': 'ml'}])
        first = self.preview('resources', fields)
        self.client.force_authenticate(self.outsider)
        second = self.preview('resources', {**fields, 'project': 'PRIVATE', 'instrument': 'SEQ-2'})
        result = self.race([self.confirmation(self.actor, first), self.confirmation(self.outsider, second)])
        self.assertEqual(sorted(code for code, _ in result), [200, 400], result)
        self.assertEqual(InstrumentBooking.objects.count(), 1)
        self.assertEqual(InventoryReservation.objects.count(), 1)

    def test_duplicate_repair_validation_creates_one_child_and_one_row_claim(self):
        parent = self.parent_import()
        payload = {'kind': 'repair', 'fields': {'parent_id': parent.pk, 'corrections': [{'row': 2, 'values': {'value': '12'}}]}}
        request = self.actor.pk, '/api/assistant/lab-operations/preview/', payload
        result = self.race([request, request])
        self.assertTrue(all(code == 201 for code, _ in result), result)
        self.assertEqual(len({body['instrument_import_job']['id'] for _, body in result}), 1)
        self.assertEqual(ImportJob.objects.count(), 2)
        self.assertEqual(ImportRowRepair.objects.count(), 1)

    def test_two_notebook_previews_cannot_create_duplicate_drafts(self):
        run = self.pipeline()
        fields = {'project': 'ALPHA', 'source_kind': 'pipeline', 'source_id': run.pk, 'notebook_id': self.notebook.pk, 'title': 'Evidence'}
        first = self.preview('notebook', fields)
        self.client.force_authenticate(self.maria)
        second = self.preview('notebook', fields)
        result = self.race([self.confirmation(self.actor, first), self.confirmation(self.maria, second)])
        self.assertEqual(sorted(code for code, _ in result), [200, 400], result)
        self.assertEqual(Experiment.objects.count(), 1)

    def test_database_exclusion_also_protects_other_insertion_paths(self):
        self.client.force_authenticate(self.actor)
        first = self.confirm(self.preview('resources', self.resources(stocks=[])))
        booking = InstrumentBooking.objects.get(pk=first['result']['booking_id'])
        other = AssistantAction.objects.create(action_type='LAB_OPERATION', requested_by=self.actor,
            expires_at=timezone.now() + timedelta(minutes=15))
        with self.assertRaises(IntegrityError) as error:
            with transaction.atomic():
                InstrumentBooking.objects.create(instrument=self.instrument, project=self.private, starts_at=booking.starts_at,
                    ends_at=booking.ends_at, created_by=self.outsider, action=other)
        self.assertEqual(error.exception.__cause__.diag.constraint_name, 'instrument_booking_no_overlap')
