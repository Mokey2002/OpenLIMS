import csv
import io
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from datetime import datetime, timedelta, timezone as utc
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from django.urls import resolve
from django.db import close_old_connections, connection
from rest_framework.test import APITestCase, APITransactionTestCase

from assistant.models import AssistantAction, GeneratedArtifact
from assistant.provider_tools import dispatch_tool
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep
from pipelines.services import start_pipeline
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample
from settings_app.models import SystemSettings


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
class AssistantV070Tests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="assistant-v070-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        settings = override_settings(MEDIA_ROOT=self.media)
        settings.enable()
        self.addCleanup(settings.disable)
        self.tech = self.user("daily-tech")
        self.maria = self.user("maria")
        self.viewer = self.user("daily-viewer", "viewer")
        self.reviewer = self.user("reviewer", "qc_reviewer")
        self.outsider = self.user("outsider")
        self.project = Project.objects.create(code="ALPHA", name="Alpha")
        self.project.members.add(self.tech, self.maria, self.viewer, self.reviewer)
        self.similar = Project.objects.create(code="ALPHABET", name="Different project")
        self.similar.members.add(self.tech)
        self.private = Project.objects.create(code="PRIVATE", name="Private")
        self.private.members.add(self.outsider)
        self.sample = Sample.objects.create(sample_id="S-100", project=self.project, created_by=self.tech)
        self.linked = Sample.objects.create(sample_id="LINKED", project=self.private, created_by=self.outsider)
        self.linked.linked_projects.add(self.project)
        self.secret = Sample.objects.create(sample_id="SECRET", project=self.private, created_by=self.outsider)
        self.work = WorkItem.objects.create(sample=self.sample, name="Initial work", assigned_to=self.tech, created_by=self.tech)
        self.client.force_authenticate(self.tech)

    def user(self, name, role="tech"):
        user = get_user_model().objects.create_user(username=name)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def chat(self, message, context=None):
        reply = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(reply.status_code, 200, reply.data)
        return reply.data

    def confirm(self, action, expected=200):
        reply = self.client.post(f"/api/assistant/actions/{action['confirmation_token']}/confirm/", {"confirm": True}, format="json")
        self.assertEqual(reply.status_code, expected, reply.data)
        return reply.data

    def daily(self, **query):
        reply = self.client.get("/api/v1/assistant/daily-work/", query)
        self.assertEqual(reply.status_code, 200, reply.data)
        return reply.data["daily_work"]

    def action(self, operation, work=None, expected=201, **fields):
        from assistant.daily_work import inspect_work, scoped_work
        work = work or self.work
        row = inspect_work(scoped_work(self.client.handler._force_user).get(pk=work.pk), self.client.handler._force_user)
        reply = self.client.post("/api/v1/assistant/daily-work/actions/", {"operation": operation, "work_item_id": work.pk, "digest": row["digest"], **fields}, format="json")
        self.assertEqual(reply.status_code, expected, reply.data)
        return reply.data

    def result(self, work=None, **fields):
        return Result.objects.create(work_item=work or self.work, key=fields.pop("key", "concentration"), value_type="NUMBER", value_number=fields.pop("value_number", 0), entered_by=self.tech, **fields)

    def pipeline(self):
        definition = AnalysisDefinition.objects.create(code="PREP", name="Prep", required_fields=[{"key": "concentration", "value_type": "NUMBER", "required": True}])
        procedure = ProcedureDefinition.objects.create(code="PREP", name="Prep", analysis=definition)
        template = PipelineTemplate.objects.create(code="PREP", name="Prep")
        PipelineTemplateStep.objects.create(template=template, position=1, procedure=procedure, requires_qc=True)
        PipelineTemplateStep.objects.create(template=template, position=2, procedure=procedure)
        run = start_pipeline(sample=self.sample, template=template, actor=self.tech)
        first = run.steps.get(position=1)
        first.work_item.assigned_to = self.tech
        first.work_item.save()
        return run, first

    def project_report(self, **query):
        reply = self.client.get(f"/api/v1/assistant/project-investigations/{self.project.pk}/", query)
        self.assertEqual(reply.status_code, 200, reply.data)
        return reply.data["project_investigation"]

    def export(self, output="CSV", expected=201, **query):
        reply = self.client.post(f"/api/v1/assistant/project-investigations/{self.project.pk}/export/", {"output_format": output, **query}, format="json")
        self.assertEqual(reply.status_code, expected, reply.data)
        return reply.data

    def test_daily_priorities_assign_start_deadline_complete_and_idempotence(self):
        reply = self.chat("What should I work on today?")
        self.assertEqual(reply["personal_work"]["username"], self.tech.username)
        self.assertEqual(reply["daily_work"]["rows"][0]["id"], self.work.pk)
        assigned = self.action("DAILY_ASSIGN", assignee="maria")["pending_action"]
        self.work.refresh_from_db()
        self.assertEqual(self.work.assigned_to, self.tech)
        self.confirm(assigned)
        self.confirm(assigned)
        self.work.refresh_from_db()
        self.assertEqual(self.work.assigned_to, self.maria)
        self.assertEqual(self.daily()["rows"], [])
        self.assertEqual(self.daily(scope="team")["rows"][0]["id"], self.work.pk)
        started = self.action("DAILY_START")["pending_action"]
        self.confirm(started)
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, "IN_PROGRESS")
        due = "2026-12-02T12:30:00-08:00"
        self.confirm(self.action("DAILY_DUE", due_at=due)["pending_action"])
        self.work.refresh_from_db()
        self.assertEqual(self.work.due_at, datetime(2026, 12, 2, 20, 30, tzinfo=utc.utc))
        completed = self.action("DAILY_COMPLETE")["pending_action"]
        self.confirm(completed)
        self.confirm(completed)
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).status, "COMPLETED")
        self.assertEqual(Event.objects.filter(action="WORK_ITEM_COMPLETED", payload__assistant_action_id=completed["id"]).count(), 1)

    def test_pipeline_missing_fields_qc_gate_and_separation_are_preserved(self):
        run, step = self.pipeline()
        self.action("DAILY_COMPLETE", work=step.work_item, expected=400)
        self.result(step.work_item)
        self.confirm(self.action("DAILY_COMPLETE", work=step.work_item)["pending_action"])
        self.assertEqual(run.steps.get(position=1).status, "AWAITING_QC")
        self.assertEqual(run.steps.get(position=2).status, "BLOCKED")
        self.assertTrue(any(row["review"] == "Awaiting workflow QC" for row in self.daily()["rows"]))
        self.tech.groups.add(Group.objects.get(name="qc_reviewer"))
        config = SystemSettings.load()
        config.qc_separation_of_duties = True
        config.save()
        self.action("WORKFLOW_REVIEW", work=step.work_item, decision="APPROVED", reason="Self review", expected=400)
        self.client.force_authenticate(self.reviewer)
        approved = self.action("WORKFLOW_REVIEW", work=step.work_item, decision="APPROVED", reason="Independent recorded evidence review")["pending_action"]
        self.confirm(approved)
        self.assertEqual(run.steps.get(position=2).status, "READY")
        self.assertEqual(Result.objects.get(work_item=step.work_item).qc_status, "PENDING_REVIEW")

    def test_blocked_work_is_not_offered_as_available_overdue_work(self):
        run, step = self.pipeline()
        work = step.work_item
        work.due_at = timezone.now() - timedelta(days=1)
        work.save()
        step.status = "BLOCKED"
        step.save()
        row = next(row for row in self.daily()["rows"] if row["id"] == work.pk)
        self.assertEqual(row["review"], "Blocked")
        self.assertFalse(row["can_start"] or row["can_complete"])
        self.action("DAILY_START", work=work, expected=400)
        self.assertEqual(self.daily(focus="actionable")["rows"][0]["id"], self.work.pk)
        failed = WorkItem.objects.create(sample=self.sample, name="Non-QC failure", work_type="OTHER-FAILURE", status="FAILED", assigned_to=self.tech)
        self.assertNotIn(failed.pk, [row["id"] for row in self.daily(focus="qc")["rows"]])
        self.assertIn(failed.pk, [row["id"] for row in self.daily(focus="blocked")["rows"]])

    def test_stale_evidence_permissions_and_assignee_identity_are_rechecked(self):
        pending = self.action("DAILY_COMPLETE")["pending_action"]
        self.result()
        self.confirm(pending, expected=400)
        pending = self.action("DAILY_ASSIGN", assignee="maria")["pending_action"]
        self.project.members.remove(self.maria)
        self.confirm(pending, expected=400)
        self.project.members.remove(self.tech)
        self.assertEqual(self.daily()["rows"], [])
        self.client.force_authenticate(self.viewer)
        self.assertFalse(any(row["can_complete"] for row in self.daily(scope="team")["rows"]))
        self.action("DAILY_START", expected=400)

    def test_filters_pagination_limits_and_calendar_boundaries_are_explicit(self):
        anchor = datetime(2026, 11, 4, 18, tzinfo=utc.utc)
        for index in range(26):
            WorkItem.objects.create(sample=self.sample, name=f"Task {index}", work_type=f"TASK-{index}", assigned_to=self.tech, due_at=anchor - timedelta(hours=1))
        with patch("assistant.daily_work.timezone.now", return_value=anchor):
            first = self.daily(focus="today")
            self.assertEqual(len(first["rows"]), 25)
            self.assertEqual(first["next_offset"], 25)
            self.assertEqual(len(self.daily(focus="today", offset=25)["rows"]), 1)
            self.assertEqual(first["day"]["end_exclusive"], "2026-11-05T00:00:00+00:00")
            with patch("assistant.daily_work.SCAN_LIMIT", 3):
                limited = self.daily()
                self.assertTrue(limited["truncated"])
                self.assertEqual(limited["assessed"], 3)
        response = self.client.get("/api/assistant/daily-work/", {"unknown_filter": "anything"})
        self.assertEqual(response.status_code, 400)
        self.action("DAILY_DUE", due_at="2026-11-04T12:00:00", expected=400)

    def test_nonfinite_daily_values_are_visible_and_cannot_be_completed(self):
        self.result(value_number=float("nan"))
        row = self.daily()["rows"][0]
        self.assertIsNone(row["evidence"][0]["value"])
        self.assertFalse(row["can_complete"])
        self.action("DAILY_COMPLETE", expected=400)

    def test_project_investigation_counts_overlap_denominators_and_provenance(self):
        instrument = InstrumentProfile.objects.create(code="SEQ", name="Sequencer")
        job = ImportJob.objects.create(instrument=instrument, project=self.project, uploaded_by=self.tech, run_id="R1")
        self.work.source_import_job = job
        self.work.save()
        self.result(qc_passed=False, qc_status="REJECTED")
        self.result(key="unevaluated", qc_passed=None)
        self.result(key="passed", qc_passed=True)
        self.result(key="override", qc_passed=False, qc_status="APPROVED")
        linked_work = WorkItem.objects.create(sample=self.linked, name="Linked")
        self.result(linked_work, key="review_only", qc_passed=None, qc_status="REJECTED")
        self.result(WorkItem.objects.create(sample=self.secret, name="Secret"), key="SECRET-EVIDENCE", qc_passed=False)
        WorkItem.objects.create(sample=self.sample, name="Rejected gate", status="COMPLETED", qc_status="REJECTED", reviewed_at=timezone.now(), review_note="Actual workflow rejection")
        report = self.project_report(group_by="instrument")
        self.assertEqual(report["summary"]["results"], 5)
        self.assertEqual(report["summary"]["assessed_checks"], 3)
        self.assertEqual(report["summary"]["failed_checks"], 2)
        self.assertEqual(report["summary"]["flagged_results"], 3)
        self.assertEqual(report["summary"]["failure_rate"], 66.67)
        self.assertEqual(report["summary"]["rejected_work_gates"], 1)
        self.assertEqual({row["label"] for row in report["groups"]}, {"SEQ", "No linked instrument"})
        self.assertNotIn("SECRET-EVIDENCE", str(report))
        self.assertEqual(report["work_gates"][0]["reason"], "Actual workflow rejection")
        key_report = self.project_report(key="concentration")
        self.assertEqual(key_report["summary"]["results"], 1)
        self.assertEqual(key_report["work_gates"], [])

    def test_combined_natural_request_followups_and_provider_bridge(self):
        self.result(qc_passed=False)
        reply = self.chat("Investigate ALPHA’s QC failures and export a report.")
        self.assertEqual(reply["project_investigation"]["project_id"], self.project.pk)
        self.assertIn("pending_action", reply)
        self.assertFalse(GeneratedArtifact.objects.exists())
        grouped = self.chat("Graph failures by operator", reply["context"])
        self.assertEqual(grouped["project_investigation"]["group_by"], "operator")
        self.assertEqual(grouped["chart"]["xKey"], "label")
        direct = dispatch_tool({"route": "tool", "tool": "project_investigation", "arguments": {"command": "Investigate project ALPHA QC failures"}, "confidence": .99}, self.tech)
        self.assertTrue(direct["skip_llm"])
        self.assertEqual(direct["project_investigation"]["summary"]["flagged_results"], 1)
        daily = dispatch_tool({"route": "tool", "tool": "daily_work", "arguments": {"command": "What should I work on today?"}, "confidence": .99}, self.tech)
        self.assertIn("daily_work", daily)

    def test_report_freezes_window_recalculates_on_confirmation_and_cleans_failure_files(self):
        original = self.result(qc_passed=False, qc_failure_reason="=FORMULA()")
        pending = self.export()["pending_action"]
        frozen = AssistantAction.objects.get(pk=pending["id"]).payload["filters"]["project_qc_spec"]
        self.assertIn("date_before", frozen)
        original.qc_passed = True
        original.save()
        outcome = self.confirm(pending)
        self.confirm(pending)
        artifact = GeneratedArtifact.objects.get()
        self.assertEqual(outcome["result"]["row_count"], 0)
        with artifact.file.open("rb") as source:
            content = source.read().decode("utf-8-sig")
        self.assertIn("ALPHA", content)
        self.assertEqual(artifact.parameters["generated_window"]["end_exclusive"], frozen["date_before"])
        self.assertEqual(artifact.project_id, self.project.pk)
        pending = self.export("PDF")["pending_action"]
        pdf = self.confirm(pending)
        artifact = GeneratedArtifact.objects.get(pk=pdf["result"]["artifact_id"])
        with artifact.file.open("rb") as source:
            self.assertTrue(source.read().startswith(b"%PDF"))
        before = {p for p in Path(self.media).rglob("*") if p.is_file()}
        pending = self.export()["pending_action"]
        original_create = Event.objects.create
        def fail_generated(**fields):
            if fields.get("action") == "REPORT_GENERATED":
                raise ValueError("Simulated audit failure")
            return original_create(**fields)
        with patch.object(Event.objects, "create", side_effect=fail_generated):
            self.confirm(pending, expected=400)
        self.assertEqual(before, {p for p in Path(self.media).rglob("*") if p.is_file()})

    def test_csv_formula_safety_and_download_permissions_after_revocation(self):
        self.result(qc_passed=False, qc_failure_reason="=SUM(1,1)")
        linked_work = WorkItem.objects.create(sample=self.linked, name="Linked")
        self.result(linked_work, qc_passed=True)
        confirmed = self.confirm(self.export()["pending_action"])
        artifact = GeneratedArtifact.objects.get()
        from config.urls import private_assistant_media
        raw_path = "/media/" + artifact.file.name
        self.assertIs(resolve(raw_path).func, private_assistant_media)
        self.assertEqual(self.client.get(raw_path).status_code, 404)
        with artifact.file.open("rb") as source:
            rows = list(csv.reader(io.StringIO(source.read().decode("utf-8-sig"))))
        self.assertTrue(any("'=SUM(1,1)" in row for row in rows))
        url = confirmed["result"]["download_url"]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.linked.linked_projects.remove(self.project)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.linked.linked_projects.add(self.project)
        self.project.members.remove(self.tech)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_exact_project_filters_caps_and_calendar_window(self):
        anchor = timezone.now()
        record = self.result(qc_passed=False)
        last_month_end = timezone.localdate().replace(day=1)
        old = timezone.make_aware(datetime.combine(last_month_end, datetime.min.time())) - timedelta(seconds=1)
        Result.objects.filter(pk=record.pk).update(created_at=old)
        report = self.project_report(period="last_month")
        self.assertEqual(report["summary"]["results"], 1)
        self.assertEqual(report["window"]["end_exclusive"], timezone.make_aware(datetime.combine(last_month_end, datetime.min.time())).isoformat())
        self.assertEqual(self.project_report(period="this_month")["summary"]["results"], 0)
        with patch("assistant.project_investigations.MAX_RESULTS", 0):
            reply = self.client.get(f"/api/assistant/project-investigations/{self.project.pk}/", {"period": "last_month"})
            self.assertEqual(reply.status_code, 400)
        self.assertNotIn("project_investigation", self.chat("Investigate project AL QC failures"))
        self.assertNotIn("project_investigation", self.chat("Investigate project PRIVATE QC failures"))
        self.assertNotIn("project_investigation", self.chat("Investigate project ALPHA QC failures except controls"))
        self.export(expected=400, days=30, period="last_month")

    def test_saved_daily_and_project_views_refresh_evidence_without_replaying_actions(self):
        daily = self.chat("What should I work on today?")
        project = self.chat("Investigate project ALPHA QC failures")
        ids = []
        for index, reply in enumerate([daily, project]):
            saved = self.client.post("/api/assistant/conversations/", {"name": f"Saved view {index}", "turn_tokens": [reply["save_turn_token"]]}, format="json")
            self.assertEqual(saved.status_code, 201, saved.data)
            ids.append(saved.data["id"])
        self.result(qc_passed=False)
        restored = self.client.get(f"/api/assistant/conversations/{ids[1]}/").data
        self.assertEqual(restored["history"][1]["reply"]["project_investigation"]["summary"]["flagged_results"], 1)
        self.work.status = "COMPLETED"
        self.work.save()
        restored = self.client.get(f"/api/assistant/conversations/{ids[0]}/").data
        self.assertEqual(restored["history"][1]["reply"]["daily_work"]["rows"], [])
        self.assertFalse(AssistantAction.objects.exists())
        self.project.members.remove(self.tech)
        restored = self.client.get(f"/api/assistant/conversations/{ids[1]}/").data
        self.assertNotIn("project_investigation", restored["history"][1]["reply"])
        self.assertEqual(restored["context"], {})

    def test_typed_and_provider_work_actions_retain_the_daily_scope(self):
        context = self.chat("What should I work on today?")["context"]
        added = self.chat(f"Add result concentration = 0 to work item #{self.work.pk} for sample S-100", context)
        self.assertIn("daily_work", added)
        self.confirm(added["pending_action"])
        assigned = dispatch_tool({"route": "tool", "tool": "guided_actions", "arguments": {
            "command": f"Assign work item #{self.work.pk} for sample S-100 to maria"}, "confidence": .99}, self.tech, context)
        self.assertIn("daily_work", assigned["context"])
        self.assertIn("daily_digest", assigned["pending_action"]["payload"])


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class DailyWorkConcurrencyTests(APITransactionTestCase):
    setUp = AssistantV070Tests.setUp
    user = AssistantV070Tests.user
    action = AssistantV070Tests.action

    def test_competing_completion_proposals_commit_one_work_change(self):
        from assistant.actions import confirm_action
        actions = [self.action("DAILY_COMPLETE")["pending_action"] for _ in range(2)]
        barrier = Barrier(2)

        def confirm(action):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.tech.pk)
                barrier.wait(timeout=10)
                return confirm_action(action["confirmation_token"], user).status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(confirm, actions))
        self.assertEqual(sorted(statuses), ["COMPLETED", "FAILED"])
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).status, "COMPLETED")
        self.assertEqual(Event.objects.filter(action="WORK_ITEM_COMPLETED", entity_id=str(self.work.pk)).count(), 1)
