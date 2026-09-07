from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from events.models import Event
from notifications.models import Notification
from samples.models import Sample
from results.models import WorkItem
from .automation import validate_automation
from .models import PipelineTemplateStep, PipelineRun
from .services import start_pipeline, sync_pipeline_step_from_work_item, retry_pipeline_step
from .test_step_forms import WorkflowFormTests


class WorkflowActionTests(TestCase):
    setUp = WorkflowFormTests.setUp

    def new_run(self, config, conditional=False):
        target = self.template_step
        if conditional:
            target = PipelineTemplateStep.objects.create(
                template=self.template, position=2, procedure=target.procedure,
                dependency_positions=[1], activation_condition={"source_kind": "measurement",
                    "source_position": 1, "result_key": "concentration", "operator": "LT", "value": 10})
        target.automation = config
        target.save()
        run = start_pipeline(sample=Sample.objects.create(sample_id="S2"), template=self.template, actor=self.admin)
        return run, run.steps.get(position=target.position)

    def config(self):
        return {"assigned_to": self.admin.pk, "notify_assignee": True, "notify_users": [self.admin.pk]}

    def complete_source(self, run, value):
        source = run.steps.get(position=1)
        source.form_values = {"concentration": value}
        source.save()
        source.work_item.status = WorkItem.STATUS_COMPLETED
        source.work_item.save()
        sync_pipeline_step_from_work_item(source.work_item, self.admin)
        return source

    def test_assignment_and_notification_deduplicated_on_repeated_sync(self):
        run, step = self.new_run(self.config(), conditional=True)
        self.assertEqual(Notification.objects.count(), 0)
        source = self.complete_source(run, 4)
        sync_pipeline_step_from_work_item(source.work_item, self.admin)
        step.refresh_from_db()
        self.assertEqual(step.work_item.assigned_to_id, self.admin.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Event.objects.filter(action="WORKFLOW_ACTIONS_APPLIED").count(), 1)

    def test_nonmatching_branch_never_assigns_or_notifies(self):
        run, step = self.new_run(self.config(), conditional=True)
        self.complete_source(run, 12)
        step.refresh_from_db()
        self.assertEqual(step.status, "SKIPPED")
        self.assertIsNone(step.work_item_id)
        self.assertFalse(Notification.objects.exists())

    def test_template_edits_do_not_change_running_actions(self):
        run, step = self.new_run(self.config(), conditional=True)
        self.template.steps.filter(position=2).update(automation={})
        self.complete_source(run, 4)
        step.refresh_from_db()
        self.assertEqual(step.automation, self.config())
        self.assertEqual(Notification.objects.count(), 1)

    def test_inaccessible_assignee_and_recipient_are_skipped_and_audited(self):
        user = get_user_model().objects.create_user(username="outsider")
        user.groups.add(Group.objects.get_or_create(name="tech")[0])
        run, step = self.new_run({"assigned_to": user.pk, "notify_assignee": True, "notify_users": [user.pk]})
        self.assertIsNone(step.work_item.assigned_to_id)
        self.assertFalse(Notification.objects.exists())
        event = Event.objects.get(action="WORKFLOW_ACTIONS_APPLIED", entity_id=str(run.pk))
        self.assertTrue(event.payload["assignment_skipped"])
        self.assertEqual(event.payload["skipped_recipients"], [user.pk])

    def test_disabled_user_is_rechecked_at_activation(self):
        user = get_user_model().objects.create_user(username="other_admin", is_superuser=True)
        run, step = self.new_run({"assigned_to": user.pk, "notify_assignee": True}, conditional=True)
        user.is_active = False
        user.save()
        self.complete_source(run, 4)
        step.refresh_from_db()
        self.assertIsNone(step.work_item.assigned_to_id)
        self.assertFalse(Notification.objects.exists())

    def test_project_membership_changes_are_rechecked(self):
        from projects.models import Project
        user = get_user_model().objects.create_user(username="member")
        user.groups.add(Group.objects.get_or_create(name="tech")[0])
        project = Project.objects.create(code="P", name="Project")
        project.members.add(user)
        run, step = self.new_run({"assigned_to": user.pk, "notify_users": [user.pk]}, conditional=True)
        run.sample.project = project
        run.sample.save()
        project.members.remove(user)
        self.complete_source(run, 4)
        step.refresh_from_db()
        self.assertIsNone(step.work_item.assigned_to_id)
        self.assertFalse(Notification.objects.exists())

    def test_authorized_technician_gets_assignment(self):
        from projects.models import Project
        user = get_user_model().objects.create_user(username="member")
        user.groups.add(Group.objects.get_or_create(name="tech")[0])
        project = Project.objects.create(code="P", name="Project")
        project.members.add(user)
        run, step = self.new_run({"assigned_to": user.pk, "notify_assignee": True}, conditional=True)
        run.sample.project = project
        run.sample.save()
        self.complete_source(run, 4)
        step.refresh_from_db()
        self.assertEqual(step.work_item.assigned_to_id, user.pk)
        self.assertEqual(Notification.objects.get().user_id, user.pk)

    def test_retry_notifies_once_for_new_attempt(self):
        run, step = self.new_run(self.config())
        old_id = step.work_item_id
        step.work_item.status = WorkItem.STATUS_FAILED
        step.work_item.save()
        sync_pipeline_step_from_work_item(step.work_item, self.admin)
        step = retry_pipeline_step(run=run, step=step, actor=self.admin, reason="Repeat extraction")
        self.assertNotEqual(step.work_item_id, old_id)
        self.assertEqual(step.work_item.assigned_to_id, self.admin.pk)
        self.assertEqual(Notification.objects.count(), 2)

    def test_invalid_actions_rejected(self):
        viewer = get_user_model().objects.create_user(username="viewer")
        for config in ([], {"unknown": True}, {"assigned_to": True}, {"assigned_to": viewer.pk},
                       {"notify_users": [99999]}, {"notify_users": [True]}, {"notify_assignee": True},
                       {"notify_users": "1"}, {"notify_users": [self.admin.pk] * 51}):
            with self.subTest(config=config), self.assertRaises(ValidationError):
                validate_automation(config)

    def test_template_api_roundtrip_and_nonadmin_denied(self):
        data = {"steps": [{"position": 1, "procedure": self.template_step.procedure_id, "automation": self.config()}]}
        response = self.client.patch(f"/api/pipeline-templates/{self.template.pk}/", data, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["steps"][0]["automation"], self.config())
        self.assertEqual(self.client.get("/api/pipeline-templates/action-users/").status_code, 200)
        user = get_user_model().objects.create_user(username="technician")
        user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/pipeline-templates/action-users/").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/pipeline-templates/{self.template.pk}/", data, format="json").status_code, 403)

    def test_activation_failure_rolls_back_notifications_and_run(self):
        from unittest.mock import patch
        from .services import _event
        def fail_after_actions(entity, entity_id, action, actor, payload):
            if action == "WORKFLOW_ACTIONS_APPLIED":
                self.assertTrue(Notification.objects.exists())
                raise RuntimeError("audit unavailable")
            return _event(entity, entity_id, action, actor, payload)
        with patch("pipelines.services._event", side_effect=fail_after_actions):
            with self.assertRaises(RuntimeError):
                self.new_run(self.config())
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(PipelineRun.objects.count(), 1)
