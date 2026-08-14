from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from events.models import Event
from projects.models import Project
from rest_framework.test import APITestCase
from results.models import Result, WorkItem
from samples.models import Sample
from settings_app.models import SystemSettings

from assistant.models import AssistantAction


class AssistantQCOperationsTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tech = user_model.objects.create_user(username="qc-tech")
        self.reviewer = user_model.objects.create_user(username="eduardo-reviewer")
        self.maria = user_model.objects.create_user(
            username="maria",
            first_name="Maria",
        )
        self.viewer = user_model.objects.create_user(username="qc-viewer")

        tech_group, _ = Group.objects.get_or_create(name="tech")
        reviewer_group, _ = Group.objects.get_or_create(name="qc_reviewer")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech.groups.add(tech_group)
        self.reviewer.groups.add(reviewer_group)
        self.maria.groups.add(reviewer_group)
        self.viewer.groups.add(viewer_group)

        self.project = Project.objects.create(code="ALPHA", name="Alpha")
        self.project.members.add(
            self.tech,
            self.reviewer,
            self.maria,
            self.viewer,
        )
        self.sample = Sample.objects.create(
            sample_id="S-1042",
            project=self.project,
            created_by=self.tech,
        )
        self.work_item = WorkItem.objects.create(
            sample=self.sample,
            name="Sequencing QC",
            status=WorkItem.STATUS_COMPLETED,
        )
        self.failed = self.make_result(
            "mean_q_score",
            26.1,
            reference_min=30,
            reference_max=45,
            qc_passed=False,
            qc_failure_reason="Mean Q score is below the validated minimum.",
        )
        self.passed = self.make_result(
            "percent_q30",
            92.4,
            reference_min=80,
            reference_max=100,
            qc_passed=True,
        )

    def make_result(self, key, value, **kwargs):
        return Result.objects.create(
            work_item=self.work_item,
            key=key,
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=value,
            unit=kwargs.pop("unit", "%"),
            qc_rule=kwargs.pop("qc_rule", "Value must be within the reference range."),
            entered_by=kwargs.pop("entered_by", self.tech),
            **kwargs,
        )

    def chat(self, message, *, user=None, context=None):
        self.client.force_authenticate(user or self.tech)
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def confirm(self, proposal, *, user=None):
        token = proposal.data["pending_action"]["confirmation_token"]
        self.client.force_authenticate(user or self.reviewer)
        return self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

    def test_read_only_qc_intelligence_includes_rules_and_ranges(self):
        failed = self.chat("Show results that failed QC this week.")
        awaiting = self.chat("Which results are awaiting approval?")
        why = self.chat(f"Why did result R-{self.failed.id} fail QC?")
        compare = self.chat(
            "Compare this value with its reference range.",
            context=why.data["context"],
        )

        self.assertIn(f"R-{self.failed.id}", failed.data["answer"])
        self.assertIn(f"R-{self.failed.id}", awaiting.data["answer"])
        self.assertIn("below the validated minimum", why.data["answer"])
        self.assertIn("Reference range: 30", why.data["answer"])
        self.assertIn("QC rule:", compare.data["answer"])
        self.assertIn("Reference comparison: below", compare.data["answer"])

    def test_qc_sample_lists_distinguish_review_failures_and_workflow_status(self):
        needing_review = self.chat("Show me which samples need QC")
        failed = self.chat("Which samples failed QC?")

        self.sample.status = Sample.STATUS_QC
        self.sample.save(update_fields=["status", "updated_at"])
        in_qc = self.chat("Which samples are in QC?")

        self.assertIn("result(s) needing QC review", needing_review.data["answer"])
        self.assertIn(self.sample.sample_id, needing_review.data["answer"])
        self.assertNotIn("chart", needing_review.data)
        self.assertNotIn("investigation", needing_review.data)

        self.assertIn("result(s) that failed QC", failed.data["answer"])
        self.assertIn(f"R-{self.failed.id}", failed.data["answer"])
        self.assertNotIn(f"R-{self.passed.id}", failed.data["answer"])

        self.assertIn("sample(s) in QC", in_qc.data["answer"])
        self.assertIn(self.sample.sample_id, in_qc.data["answer"])

    def test_explicit_qc_question_overrides_investigation_context_without_graph(self):
        context = {
            "investigation": {
                "subject_type": "sample",
                "identifier": self.sample.sample_id,
                "days": 90,
                "group_by": "overview",
            }
        }

        samples = self.chat(
            "Tell me which samples need QC",
            context=context,
        )
        results = self.chat(
            "Show results that failed QC this week",
            context=context,
        )

        for response in [samples, results]:
            self.assertNotIn("chart", response.data)
            self.assertNotIn("investigation", response.data)
            self.assertIn(self.sample.sample_id, response.data["answer"])

    def test_results_needing_review_and_approved_results_are_concise_lists(self):
        pending = self.chat("Which results need QC review?")
        self.assertIn(f"R-{self.failed.id}", pending.data["answer"])
        self.assertNotIn("chart", pending.data)

        self.passed.qc_status = Result.QC_APPROVED
        self.passed.save(update_fields=["qc_status", "updated_at"])
        approved = self.chat("Show approved results")

        self.assertIn(f"R-{self.passed.id}", approved.data["answer"])
        self.assertNotIn("pending_action", approved.data)
        self.assertNotIn("chart", approved.data)

    def test_data_style_how_do_i_question_is_not_hijacked_by_sop_router(self):
        response = self.chat("How do I show which samples need QC?")

        self.assertIn(self.sample.sample_id, response.data["answer"])
        self.assertNotIn("Approved documentation answer", response.data["answer"])
        self.assertNotIn("chart", response.data)

    def test_approval_requires_reason_confirmation_and_is_replay_safe(self):
        missing_reason = self.chat(
            f"Approve result R-{self.passed.id}.",
            user=self.reviewer,
        )
        self.assertNotIn("pending_action", missing_reason.data)
        self.assertIn("explicit reason", missing_reason.data["answer"])

        proposal = self.chat(
            f"Approve result R-{self.passed.id} because the control passed.",
            user=self.reviewer,
        )
        self.passed.refresh_from_db()
        self.assertEqual(self.passed.qc_status, Result.QC_PENDING_REVIEW)
        self.assertEqual(
            proposal.data["pending_action"]["preview"]["records_affected"],
            1,
        )

        first = self.confirm(proposal)
        second = self.confirm(proposal)
        self.passed.refresh_from_db()

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(self.passed.qc_status, Result.QC_APPROVED)
        self.assertEqual(self.passed.qc_reviewed_by, self.reviewer)
        self.assertEqual(self.passed.qc_review_note, "the control passed")
        event = Event.objects.get(
            entity_type="Result",
            entity_id=str(self.passed.id),
            action="QC_RESULT_APPROVED",
        )
        self.assertEqual(event.payload["before"]["qc_status"], Result.QC_PENDING_REVIEW)
        self.assertEqual(event.payload["after"]["qc_status"], Result.QC_APPROVED)
        self.assertEqual(event.payload["reason"], "the control passed")
        self.assertEqual(
            Event.objects.filter(
                entity_type="Result",
                entity_id=str(self.passed.id),
                action="QC_RESULT_APPROVED",
            ).count(),
            1,
        )

    def test_reject_and_explicit_reopen_states(self):
        rejected = self.chat(
            f"Reject result R-{self.failed.id} because the control failed.",
            user=self.reviewer,
        )
        self.confirm(rejected)
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.qc_status, Result.QC_REJECTED)

        flag = self.chat(
            f"Flag result R-{self.failed.id} for review.",
            user=self.tech,
        )
        self.assertNotIn("pending_action", flag.data)
        self.assertIn("explicitly reopened", flag.data["answer"])

        reopened = self.chat(
            f"Reopen result R-{self.failed.id} because a new control was run.",
            user=self.reviewer,
        )
        response = self.confirm(reopened)
        self.failed.refresh_from_db()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.failed.qc_status, Result.QC_REOPENED)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(self.failed.id),
                action="QC_RESULT_REOPENED",
            ).exists()
        )

    def test_unauthorized_approval_is_rejected_and_audited(self):
        response = self.chat(
            f"Approve result R-{self.passed.id} because it looks good.",
            user=self.tech,
        )

        self.assertNotIn("pending_action", response.data)
        self.assertIn("Only QC reviewers", response.data["answer"])
        self.assertTrue(
            Event.objects.filter(
                entity_type="Result",
                entity_id=str(self.passed.id),
                action="QC_AUTHORIZATION_DENIED",
                actor=self.tech,
            ).exists()
        )

    def test_separation_of_duties_blocks_self_approval(self):
        settings_obj = SystemSettings.load()
        settings_obj.qc_separation_of_duties = True
        settings_obj.save(update_fields=["qc_separation_of_duties", "updated_at"])
        self.passed.entered_by = self.reviewer
        self.passed.save(update_fields=["entered_by", "updated_at"])

        response = self.chat(
            f"Approve result R-{self.passed.id} because the range passed.",
            user=self.reviewer,
        )

        self.assertNotIn("pending_action", response.data)
        self.assertIn("No results are eligible", response.data["answer"])
        self.passed.refresh_from_db()
        self.assertEqual(self.passed.qc_status, Result.QC_PENDING_REVIEW)

    def test_separation_of_duties_is_rechecked_and_audited_at_confirmation(self):
        self.passed.entered_by = self.reviewer
        self.passed.save(update_fields=["entered_by", "updated_at"])
        proposal = self.chat(
            f"Approve result R-{self.passed.id} because the range passed.",
            user=self.reviewer,
        )
        settings_obj = SystemSettings.load()
        settings_obj.qc_separation_of_duties = True
        settings_obj.save(update_fields=["qc_separation_of_duties", "updated_at"])

        response = self.confirm(proposal)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["result"]["succeeded_count"], 0)
        self.assertEqual(response.data["result"]["failed_count"], 1)
        self.passed.refresh_from_db()
        self.assertEqual(self.passed.qc_status, Result.QC_PENDING_REVIEW)
        self.assertTrue(
            Event.objects.filter(
                entity_type="Result",
                entity_id=str(self.passed.id),
                action="QC_AUTHORIZATION_DENIED",
                actor=self.reviewer,
            ).exists()
        )

    def test_bulk_preview_freezes_ids_and_reports_drift_individually(self):
        results = [self.passed]
        for index in range(3):
            results.append(
                self.make_result(
                    f"bulk_{index}",
                    90 + index,
                    reference_min=80,
                    reference_max=100,
                    qc_passed=True,
                )
            )
        first_id = min(result.id for result in results)
        last_id = max(result.id for result in results)
        proposal = self.chat(
            f"Approve results {first_id} through {last_id} because the controls passed.",
            user=self.reviewer,
        )
        frozen_ids = proposal.data["pending_action"]["preview"]["records"]
        self.assertEqual(len(frozen_ids), len(results))

        drifted = results[-1]
        drifted.qc_assigned_to = self.maria
        drifted.save(update_fields=["qc_assigned_to", "updated_at"])
        confirmed = self.confirm(proposal)

        self.assertEqual(confirmed.data["result"]["succeeded_count"], len(results) - 1)
        self.assertEqual(confirmed.data["result"]["failed_count"], 1)
        self.assertIn(
            "changed after preview", confirmed.data["result"]["failed"][0]["reason"]
        )

    def test_failed_results_can_be_assigned_to_qc_reviewer(self):
        proposal = self.chat("Assign failed QC results to Maria.")
        response = self.confirm(proposal, user=self.tech)
        self.failed.refresh_from_db()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.failed.qc_assigned_to, self.maria)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(self.failed.id),
                action="QC_ASSIGNED",
            ).exists()
        )

    def test_qc_role_removed_before_confirmation_is_denied_and_audited(self):
        proposal = self.chat(
            f"Approve result R-{self.passed.id} because the control passed.",
            user=self.reviewer,
        )
        self.reviewer.groups.clear()
        response = self.confirm(proposal, user=self.reviewer)
        action = AssistantAction.objects.get(id=proposal.data["pending_action"]["id"])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(action.status, AssistantAction.STATUS_FAILED)
        self.assertTrue(
            Event.objects.filter(
                entity_type="Result",
                entity_id=str(self.passed.id),
                action="QC_AUTHORIZATION_DENIED",
            ).exists()
        )
