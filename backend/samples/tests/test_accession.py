from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APITestCase, APIClient

from assistant.models import BarcodeLabel
from custom_fields.models import SampleForm
from events.models import Event
from projects.models import Project
from samples.models import Sample, SampleAccession, SampleCustodyEvent


class AccessionTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('accession-admin', password=None)
        self.tech = get_user_model().objects.create_user('accession-tech')
        self.tech.groups.add(Group.objects.get_or_create(name='tech')[0])
        self.viewer = get_user_model().objects.create_user('accession-viewer')
        self.viewer.groups.add(Group.objects.get_or_create(name='viewer')[0])
        self.project = Project.objects.create(code='ACC', name='Receiving lab')
        self.project.members.add(self.admin, self.tech, self.viewer)
        self.client.force_authenticate(self.admin)

    def register(self, barcode='TUBE-001', **extra):
        return self.client.post('/api/v1/samples/accession-register/', {
            'barcode': barcode, 'project': self.project.pk, 'sample_type': 'GENERAL', **extra,
        }, format='json')

    def action(self, sample, action, **data):
        return self.client.post(f'/api/v1/samples/{sample.pk}/{action}/', data, format='json')

    def test_lookup_new_register_and_lookup_existing_do_not_receive(self):
        lookup = self.client.get('/api/v1/samples/accession-lookup/', {'barcode': 'TUBE-001'})
        self.assertEqual(lookup.data['kind'], 'new')
        self.assertFalse(Sample.objects.exists())
        created = self.register(status='ARCHIVED', received_by=self.viewer.pk)
        self.assertEqual(created.status_code, 201, created.data)
        sample = Sample.objects.get()
        self.assertEqual(sample.status, 'RECEIVED')
        self.assertEqual(sample.created_by, self.admin)
        self.assertFalse(SampleCustodyEvent.objects.exists())
        self.assertEqual(Event.objects.get(action='CREATED').actor, self.admin)
        lookup = self.client.get('/api/v1/samples/accession-lookup/', {'barcode': 'tube-001'})
        self.assertEqual(lookup.data['sample']['id'], sample.pk)
        self.assertIsNone(lookup.data['receipt'])

    def test_duplicate_identifiers_and_control_characters_do_not_create_samples(self):
        self.assertEqual(self.register().status_code, 201)
        for code in ['TUBE-001', 'tube-001', 'TUBE-001\x00', 'OPENLIMS-SAMPLE-999-X', 'X' * 65]:
            self.assertIn(self.register(code).status_code, [400, 404])
        self.assertEqual(Sample.objects.count(), 1)

    def test_minimum_fields_and_published_lab_fields_are_required(self):
        SampleForm.objects.create(code='DNA', name_en='DNA', name_es='ADN', published=True, fields=[
            {'key': 'volume', 'en': 'Volume', 'es': 'Volumen', 'type': 'number', 'required': True, 'unit': 'mL'},
        ])
        self.assertEqual(self.register(project=None).status_code, 400)
        self.assertEqual(self.register(sample_type='').status_code, 400)
        self.assertEqual(self.register(sample_type='DNA').status_code, 400)
        self.assertEqual(self.register(sample_type='TYPO').status_code, 400)
        self.assertEqual(self.register().status_code, 400)
        self.assertFalse(Sample.objects.exists())
        self.assertEqual(self.register(sample_type='DNA', form_values={'volume': 0.5}).status_code, 201)
        self.assertEqual(Sample.objects.get().form_values['volume'], 0.5)

    def test_printed_barcode_remains_an_alias_if_sample_id_is_corrected(self):
        self.register()
        sample = Sample.objects.get()
        sample.sample_id = 'CORRECTED-ID'
        sample.save()
        found = self.client.get('/api/v1/samples/accession-lookup/', {'barcode': 'TUBE-001'})
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.data['sample']['sample_id'], 'CORRECTED-ID')
        self.assertEqual(found.data['barcode'], 'TUBE-001')
        self.assertEqual(self.action(sample, 'accession-label').status_code, 200)

    def test_project_membership_and_active_accounts_are_required(self):
        private = Project.objects.create(code='NOJOIN', name='Not a receiving member')
        self.assertEqual(self.register(project=private.pk).status_code, 400)
        self.admin.is_active = False
        self.admin.save()
        self.assertEqual(self.register().status_code, 403)
        self.assertFalse(Sample.objects.exists())

    def test_receipt_and_label_confirmation_are_separate_and_idempotent(self):
        self.register()
        sample = Sample.objects.get()
        self.assertEqual(self.action(sample, 'verify-label', barcode=sample.sample_id).status_code, 400)
        first = self.action(sample, 'receive', barcode=sample.sample_id, reason='Received sealed at the bench')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertIsNone(first.data['label_verified_at'])
        again = self.action(sample, 'receive', barcode=sample.sample_id, reason='Retry after network interruption')
        self.assertEqual(again.data['receipt'], first.data['receipt'])
        self.assertEqual(SampleCustodyEvent.objects.filter(action='RECEIVE').count(), 1)
        self.assertEqual(Event.objects.filter(action='SAMPLE_RECEIVED').count(), 1)
        wrong = self.action(sample, 'verify-label', barcode='WRONG-TUBE')
        self.assertEqual(wrong.status_code, 400)
        self.assertIsNone(SampleAccession.objects.get().label_verified_at)
        confirmed = self.action(sample, 'verify-label', barcode=sample.sample_id)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['label_verified_by'], self.admin.username)
        self.assertEqual(self.action(sample, 'verify-label', barcode=sample.sample_id).data['label_verified_at'], confirmed.data['label_verified_at'])
        self.assertEqual(Event.objects.filter(action='SAMPLE_LABEL_VERIFIED').count(), 1)

    def test_existing_generated_labels_resolve_and_duplicate_namespace_is_blocked(self):
        sample = Sample.objects.create(sample_id='ORIGINAL', project=self.project, created_by=self.admin)
        BarcodeLabel.objects.create(sample=sample, barcode='EXTERNAL-CODE')
        found = self.client.get('/api/v1/samples/accession-lookup/', {'barcode': 'EXTERNAL-CODE'})
        self.assertEqual(found.data['sample']['id'], sample.pk)
        self.assertEqual(self.register('EXTERNAL-CODE').status_code, 400)
        self.assertEqual(self.action(sample, 'receive', barcode='EXTERNAL-CODE', reason='Received using existing label').status_code, 200)
        self.assertEqual(self.action(sample, 'verify-label', barcode='EXTERNAL-CODE').status_code, 200)

    def test_hidden_and_ambiguous_codes_never_expose_details_or_start_registration(self):
        hidden = Project.objects.create(code='HIDDEN', name='Hidden lab')
        sample = Sample.objects.create(sample_id='PRIVATE', project=hidden)
        self.client.force_authenticate(self.tech)
        found = self.client.get('/api/v1/samples/accession-lookup/', {'barcode': sample.sample_id})
        self.assertEqual(found.status_code, 404)
        self.assertNotIn('PRIVATE', str(found.data))
        self.assertEqual(self.register('PRIVATE').status_code, 404)
        self.assertEqual(self.action(sample, 'receive', barcode='PRIVATE', reason='Unauthorized receipt attempt').status_code, 404)
        self.client.force_authenticate(self.admin)
        visible = Sample.objects.create(sample_id='DUP-CODE', project=self.project)
        BarcodeLabel.objects.create(sample=sample, barcode=visible.sample_id)
        self.assertEqual(self.client.get('/api/v1/samples/accession-lookup/', {'barcode': visible.sample_id}).status_code, 404)

    def test_viewers_and_linked_project_members_cannot_change_receipt_or_labels(self):
        sample = Sample.objects.create(sample_id='READONLY', project=self.project)
        for actor in [self.viewer]:
            self.client.force_authenticate(actor)
            self.assertEqual(self.register().status_code, 403)
            for operation, data in [('receive', {'barcode': sample.sample_id, 'reason': 'Not allowed to receive'}), ('verify-label', {'barcode': sample.sample_id}), ('accession-label', {})]:
                self.assertEqual(self.action(sample, operation, **data).status_code, 403)
        private = Project.objects.create(code='OWNER', name='Primary project')
        sample.project = private
        sample.save()
        sample.linked_projects.add(self.project)
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.get('/api/v1/samples/accession-lookup/', {'barcode': sample.sample_id}).status_code, 200)
        self.assertEqual(self.action(sample, 'receive', barcode=sample.sample_id, reason='Linked access is read only').status_code, 403)
        self.assertFalse(SampleAccession.objects.exists())

    def test_printable_code128_pdf_does_not_mark_receipt_or_verification(self):
        self.register()
        sample = Sample.objects.get()
        for size in ['100x50', '75x35', 'A4']:
            response = self.action(sample, 'accession-label', size=size)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b'%PDF'))
            self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertFalse(SampleAccession.objects.exists())
        self.assertFalse(SampleCustodyEvent.objects.exists())
        self.assertEqual(Event.objects.filter(action='SAMPLE_LABEL_GENERATED').count(), 3)
        self.assertEqual(self.action(sample, 'accession-label', size='INVALID').status_code, 400)
        self.assertEqual(self.client.post(f'/api/v1/samples/{sample.pk}/accession-label/', [], format='json').status_code, 400)

    def test_long_barcodes_require_a_printable_size(self):
        self.assertEqual(self.register('X' * 64).status_code, 201)
        sample = Sample.objects.get()
        self.assertEqual(self.action(sample, 'accession-label', size='75x35').status_code, 400)
        self.assertEqual(self.action(sample, 'accession-label', size='A4').status_code, 200)

    def test_legacy_receipt_can_be_confirmed_without_receiving_again(self):
        self.register()
        sample = Sample.objects.get()
        legacy = SampleCustodyEvent.objects.create(sample=sample, action='RECEIVE', scanned_code=sample.sample_id, performed_by=self.tech, reason='Existing physical receipt')
        result = self.action(sample, 'verify-label', barcode=sample.sample_id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(SampleAccession.objects.get().receipt_id, legacy.pk)
        self.assertEqual(SampleCustodyEvent.objects.count(), 1)

    def test_legacy_receipt_is_preserved_and_terminal_records_cannot_receive(self):
        self.register()
        sample = Sample.objects.get()
        legacy = SampleCustodyEvent.objects.create(sample=sample, action='RECEIVE', scanned_code=sample.sample_id, performed_by=self.tech, reason='Original receiving note')
        first = self.action(sample, 'receive', barcode=sample.sample_id, reason='Retry on the receiving screen')
        self.assertEqual(first.data['receipt']['received_by'], self.tech.username)
        self.assertEqual(SampleAccession.objects.get().receipt_id, legacy.pk)
        self.assertEqual(SampleCustodyEvent.objects.count(), 1)
        sample.status = 'ARCHIVED'
        sample.save()
        self.assertEqual(self.action(sample, 'receive', barcode=sample.sample_id, reason='Do not receive an archive').status_code, 400)
        self.assertEqual(self.action(sample, 'verify-label', barcode=sample.sample_id).status_code, 400)


class AccessionConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != 'postgresql':
            raise SkipTest('Requires PostgreSQL uniqueness and row locks')
        super().setUpClass()

    def test_simultaneous_registration_and_receipt_cannot_duplicate_records(self):
        admin = get_user_model().objects.create_superuser('accession-race', password=None)
        project = Project.objects.create(code='RACE', name='Concurrent reception')
        project.members.add(admin)
        barrier = Barrier(2, timeout=10)

        def send(path, body):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=admin.pk))
                barrier.wait()
                return client.post(path, body, format='json').status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, '/api/v1/samples/accession-register/', {'barcode': 'RACE-TUBE', 'project': project.pk, 'sample_type': 'GENERAL'}) for _ in range(2)]
            codes = [f.result(timeout=30) for f in futures]
        self.assertCountEqual(codes, [201, 400])
        self.assertEqual(Sample.objects.count(), 1)
        sample = Sample.objects.get()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, f'/api/v1/samples/{sample.pk}/receive/', {'barcode': sample.sample_id, 'reason': 'Same tube scanned at two desks'}) for _ in range(2)]
            self.assertEqual([f.result(timeout=30) for f in futures], [200, 200])
        self.assertEqual(SampleCustodyEvent.objects.filter(action='RECEIVE').count(), 1)
        self.assertEqual(SampleAccession.objects.count(), 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, f'/api/v1/samples/{sample.pk}/verify-label/', {'barcode': sample.sample_id}) for _ in range(2)]
            self.assertEqual([f.result(timeout=30) for f in futures], [200, 200])
        self.assertEqual(Event.objects.filter(action='SAMPLE_LABEL_VERIFIED').count(), 1)
