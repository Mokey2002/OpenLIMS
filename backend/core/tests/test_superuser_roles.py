"""Fresh deployment superusers must have the same UI and API access."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from rest_framework.test import APITestCase, APIClient

from core.serializers import (
    MeSerializer, UserLiteSerializer, UserListSerializer,
    UserCreateSerializer, UserAdminUpdateSerializer,
)
from samples.models import Sample


User = get_user_model()
PASSWORD = 'DeploymentTestPassword123!'


class SuperuserRoleTests(APITestCase):
    def login(self, user):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get('/api/v1/auth/csrf/')
        response = self.client.post('/api/v1/auth/login/', {'username': user.username, 'password': PASSWORD},
            format='json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['user']

    def post(self, path, data):
        return self.client.post(path, data, format='json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_createsuperuser_login_session_and_protein_sample_creation(self):
        with patch.dict('os.environ', {'DJANGO_SUPERUSER_PASSWORD': PASSWORD}):
            call_command('createsuperuser', username='root', email='root@example.org',
                interactive=False, stdout=StringIO())
        root = User.objects.get(username='root')
        self.assertTrue(root.is_superuser)
        self.assertFalse(root.groups.exists())
        self.assertEqual(self.login(root)['roles'], ['admin'])
        for prefix in ['/api/', '/api/v1/']:
            self.assertEqual(self.client.get(prefix + 'me/').data['roles'], ['admin'])
        session = self.client.get('/api/v1/session/')
        self.assertEqual(session.status_code, 200, session.data)
        self.assertEqual(session.data['user']['roles'], ['admin'])
        project = self.post('/api/v1/projects/', {'name': 'Protein samples', 'code': 'PROTEIN-LAB'})
        self.assertEqual(project.status_code, 201, project.data)
        sample = self.post('/api/v1/samples/', {'sample_id': 'PROTEIN-001', 'sample_type': 'PROTEIN',
            'project': project.data['id']})
        self.assertEqual(sample.status_code, 201, sample.data)
        self.assertEqual(Sample.objects.get(sample_id='PROTEIN-001').sample_type, 'PROTEIN')
        self.assertFalse(root.groups.exists())

    def test_all_user_representations_preserve_groups_and_include_effective_admin(self):
        root = User.objects.create_superuser('owner', 'owner@example.org', PASSWORD)
        viewer, _ = Group.objects.get_or_create(name='viewer')
        root.groups.add(viewer)
        for serializer in [MeSerializer, UserLiteSerializer, UserListSerializer, UserCreateSerializer, UserAdminUpdateSerializer]:
            with self.subTest(serializer=serializer.__name__):
                self.assertEqual(set(serializer(root).data['roles']), {'admin', 'viewer'})
        self.assertEqual(list(root.groups.values_list('name', flat=True)), ['viewer'])
        admin, _ = Group.objects.get_or_create(name='admin')
        root.groups.add(admin)
        self.assertEqual(MeSerializer(root).data['roles'].count('admin'), 1)
        self.client.force_authenticate(root)
        for path in ['/api/v1/users/', '/api/v1/admin-users/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn('admin', next(row for row in response.data['results'] if row['id'] == root.pk)['roles'])

    def test_root_username_staff_flag_and_other_roles_do_not_gain_admin_access(self):
        for username, staff, role in [('root', False, None), ('staff', True, None), ('reader', False, 'viewer'), ('operator', False, 'tech')]:
            with self.subTest(username=username):
                user = User.objects.create_user(username=username, is_staff=staff)
                if role:
                    user.groups.add(Group.objects.get_or_create(name=role)[0])
                self.client.force_authenticate(user)
                me = self.client.get('/api/v1/me/')
                self.assertEqual(me.data['roles'], [role] if role else [])
                self.assertEqual(self.client.post('/api/v1/projects/', {'name': 'Forbidden', 'code': username}, format='json').status_code, 403)
                self.assertEqual(self.client.get('/api/v1/admin-users/').status_code, 403)
                user.refresh_from_db()
                self.assertFalse(user.is_superuser)

    def test_role_demotion_removes_effective_admin_on_the_next_request(self):
        root = User.objects.create_superuser('owner', 'owner@example.org', PASSWORD)
        User.objects.create_superuser('backup-owner', password=None)
        self.assertEqual(self.login(root)['roles'], ['admin'])
        response = self.client.patch(f'/api/v1/admin-users/{root.pk}/', {'role': 'viewer'}, format='json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['roles'], ['viewer'])
        self.assertEqual(self.client.get('/api/v1/me/').data['roles'], ['viewer'])
        root.refresh_from_db()
        self.assertFalse(root.is_superuser)
        self.assertEqual(list(root.groups.values_list('name', flat=True)), ['viewer'])
        self.assertEqual(self.post('/api/v1/projects/', {'name': 'Forbidden', 'code': 'AFTER-DEMOTION'}).status_code, 403)
