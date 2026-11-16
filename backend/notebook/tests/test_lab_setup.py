from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from projects.models import Project
from samples.models import Sample
from settings_app.models import SystemSettings


class LabSetupTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('setup-admin', password='test-only-password')
        self.viewer = get_user_model().objects.create_user('setup-viewer')
        self.tech = get_user_model().objects.create_user('setup-tech')
        self.tech.groups.add(Group.objects.get_or_create(name='tech')[0])

    def progress(self, user):
        self.client.force_authenticate(user)
        response = self.client.get('/api/v1/onboarding/')
        self.assertEqual(response.status_code, 200)
        return response.data['lab_setup']

    def test_saved_records_drive_progress_without_creating_anything(self):
        get_user_model().objects.exclude(pk=self.admin.pk).update(is_active=False)
        first = self.progress(self.admin)
        self.assertFalse(first['users_added'])
        self.assertFalse(first['project_created'])
        self.assertFalse(first['sample_registered'])
        self.viewer.is_active = True
        self.viewer.save()
        project = Project.objects.create(name='First study', code='SETUP')
        project.members.add(self.admin)
        sample = Sample.objects.create(sample_id='FIRST', project=project)
        updated = self.progress(self.admin)
        self.assertTrue(updated['users_added'])
        self.assertTrue(updated['project_created'])
        self.assertTrue(updated['sample_registered'])
        sample.delete()
        self.assertFalse(self.progress(self.admin)['sample_registered'])
        self.assertEqual(Project.objects.count(), 1)

    def test_non_admin_cannot_infer_other_users_or_private_records(self):
        project = Project.objects.create(name='Private study', code='PRIVATE')
        Sample.objects.create(sample_id='PRIVATE-1', project=project)
        for user in (self.viewer, self.tech):
            data = self.progress(user)
            self.assertIsNone(data['users_added'])
            self.assertFalse(data['can_add_users'])
            self.assertFalse(data['can_create_project'])
            self.assertFalse(data['project_created'])
            self.assertFalse(data['sample_registered'])
        self.assertFalse(self.progress(self.viewer)['can_register_sample'])
        self.assertTrue(self.progress(self.tech)['can_register_sample'])
        project.members.add(self.viewer)
        self.assertTrue(self.progress(self.viewer)['project_created'])
        self.assertTrue(self.progress(self.viewer)['sample_registered'])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_lab_setup_available_with_notebook_disabled_and_requires_login(self):
        settings = SystemSettings.load()
        settings.notebook_enabled = False
        settings.save()
        self.assertTrue(self.progress(self.admin)['can_create_project'])
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/api/v1/onboarding/').status_code, [401, 403])
