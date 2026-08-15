import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import GeneratedArtifact
from custom_fields.models import FieldDefinition, FieldValue
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch


class AssistantComparisonTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = tempfile.mkdtemp(prefix="openlims-comparison-test-")
        cls.settings_override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls.settings_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.settings_override.disable()
        shutil.rmtree(cls.media_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        user_model = get_user_model()
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech = user_model.objects.create_user(username="eduardo")
        self.outsider = user_model.objects.create_user(username="outsider")
        self.tech.groups.add(tech_group)
        self.outsider.groups.add(viewer_group)

        self.alpha = Project.objects.create(code="ALPHA", name="Alpha")
        self.beta = Project.objects.create(code="BETA", name="Beta")
        self.private = Project.objects.create(code="PRIVATE", name="Private")
        self.alpha.members.add(self.tech)
        self.beta.members.add(self.tech)
        self.private.members.add(self.outsider)

        self.batch_alpha = SampleBatch.objects.create(
            code="B-100",
            project=self.alpha,
            created_by=self.tech,
        )
        self.batch_beta = SampleBatch.objects.create(
            code="B-200",
            project=self.beta,
            created_by=self.tech,
        )
        self.samples = [
            Sample.objects.create(
                sample_id="S-100",
                project=self.alpha,
                batch=self.batch_alpha,
                created_by=self.tech,
            ),
            Sample.objects.create(
                sample_id="S-101",
                project=self.alpha,
                batch=self.batch_alpha,
                created_by=self.tech,
            ),
            Sample.objects.create(
                sample_id="S-102",
                project=self.beta,
                batch=self.batch_beta,
                created_by=self.tech,
            ),
        ]
        self.private_sample = Sample.objects.create(
            sample_id="S-PRIVATE",
            project=self.private,
            created_by=self.outsider,
        )

        required = FieldDefinition.objects.create(
            entity_type="Sample",
            name="source",
            label="Source",
            data_type="string",
            required=True,
        )
        FieldValue.objects.create(
            field_definition=required,
            entity_type="Sample",
            entity_id=str(self.samples[0].id),
            value="blood",
        )

        for index, sample in enumerate(self.samples):
            work = WorkItem.objects.create(
                sample=sample,
                name="Chemistry",
                work_type="CHEMISTRY",
                assigned_to=self.tech if index == 0 else None,
                due_at=timezone.now() - timedelta(days=1) if index == 1 else None,
                created_by=self.tech,
            )
            Result.objects.create(
                work_item=work,
                key="glucose",
                value_type=Result.VALUE_TYPE_NUMBER,
                value_number=[10.0, 12.0, 100.0][index],
                unit="mg/dL",
                reference_min=5.0,
                reference_max=20.0,
                qc_passed=index < 2,
            )

        private_work = WorkItem.objects.create(
            sample=self.private_sample,
            name="Private chemistry",
            work_type="CHEMISTRY",
            created_by=self.outsider,
        )
        Result.objects.create(
            work_item=private_work,
            key="glucose",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=9999.0,
            unit="mg/dL",
            reference_max=20.0,
            qc_passed=False,
        )

        self.samples[1].status_changed_at = timezone.now() - timedelta(days=20)
        self.samples[1].save(update_fields=["status_changed_at"])
        self.client.force_authenticate(self.tech)

    def chat(self, message, context=None):
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def confirm(self, response):
        token = response.data["pending_action"]["confirmation_token"]
        return self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

    def test_compares_three_samples_with_numeric_graph_and_table(self):
        response = self.chat("Compare samples S-100, S-101, and S-102")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["comparison"]["rows"]), 3)
        self.assertEqual(response.data["chart"]["chartType"], "bar")
        self.assertEqual(len(response.data["chart"]["series"]), 3)
        source_column = next(
            column
            for column in response.data["comparison"]["columns"]
            if column["label"] == "source"
        )
        first_row = next(
            row
            for row in response.data["comparison"]["rows"]
            if row["entity"] == "S-100"
        )
        self.assertEqual(first_row[source_column["key"]], "blood")
        self.assertEqual(
            response.data["context"]["comparison"]["identifiers"],
            ["S-100", "S-101", "S-102"],
        )
        self.assertNotIn("pending_action", response.data)

    def test_vague_sample_comparison_asks_for_accessible_identifiers(self):
        response = self.chat("Can you compare two samples?")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Which samples would you like to compare?",
            response.data["answer"],
        )
        self.assertTrue(
            response.data["context"]["comparison"]["awaiting_identifiers"]
        )
        self.assertIn(
            "Compare samples S-100, S-101, and S-102",
            response.data["suggestions"],
        )
        self.assertNotIn("S-PRIVATE", str(response.data["suggestions"]))

    def test_comparison_clarification_accepts_identifier_only_follow_up(self):
        clarification = self.chat("Can you compare two samples?")
        response = self.chat(
            "S-100 and S-102",
            context=clarification.data["context"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["context"]["comparison"]["identifiers"],
            ["S-100", "S-102"],
        )
        self.assertEqual(len(response.data["comparison"]["rows"]), 2)

    def test_unavailable_identifiers_get_permission_filtered_suggestions(self):
        response = self.chat(
            "Compare samples NOT-SEEDED-001 and NOT-SEEDED-002"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("found 0 of 2 requested identifiers", response.data["answer"])
        self.assertNotIn("resolved 0", response.data["answer"])
        self.assertIn(
            "Compare samples S-100, S-101, and S-102",
            response.data["suggestions"],
        )
        self.assertNotIn("S-PRIVATE", str(response.data["suggestions"]))

    def test_comparison_suggestions_are_generated_from_current_records(self):
        replacement_ids = ["DEMO-ALPHA-001", "DEMO-ALPHA-002", "DEMO-BETA-001"]
        for sample, sample_id in zip(self.samples, replacement_ids):
            sample.sample_id = sample_id
            sample.save(update_fields=["sample_id"])

        response = self.chat("Can you compare two samples?")

        self.assertIn(
            "Compare samples DEMO-ALPHA-001, DEMO-ALPHA-002, and DEMO-BETA-001",
            response.data["suggestions"],
        )
        self.assertNotIn("S-100", str(response.data["suggestions"]))

    def test_sample_comparison_honors_bar_chart_and_named_result(self):
        response = self.chat(
            "Compare samples S-100 and S-102 using a bar chart of glucose"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "bar")
        self.assertEqual(
            [row["measurement"] for row in response.data["chart"]["data"]],
            ["glucose (mg/dL)"],
        )
        self.assertEqual(
            response.data["context"]["comparison"]["result_keys"],
            ["glucose"],
        )

    def test_sample_comparison_honors_line_chart(self):
        response = self.chat(
            "Compare samples S-100 and S-102 using a line chart of glucose"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "line")

    def test_chart_style_follow_up_switches_comparison_to_dot_plot(self):
        first = self.chat(
            "Compare samples S-100 and S-102 using a bar chart of glucose"
        )
        follow_up = self.chat(
            "Use a dot plot",
            context=first.data["context"],
        )

        self.assertEqual(follow_up.status_code, 200)
        self.assertEqual(follow_up.data["chart"]["chartType"], "dot")
        self.assertEqual(
            follow_up.data["context"]["comparison"]["result_keys"],
            ["glucose"],
        )
        self.assertEqual(
            follow_up.data["context"]["comparison"]["chart_type"],
            "dot",
        )

    def test_dot_request_with_two_ids_does_not_require_compare_keyword(self):
        response = self.chat(
            "Show samples S-100 and S-102 as plotted dots for glucose"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "dot")
        self.assertEqual(
            response.data["context"]["comparison"]["identifiers"],
            ["S-100", "S-102"],
        )

    def test_scatter_plot_uses_two_named_numeric_results_as_axes(self):
        for index in [0, 2]:
            Result.objects.create(
                work_item=self.samples[index].work_items.get(),
                key="purity",
                value_type=Result.VALUE_TYPE_NUMBER,
                value_number=[95.0, 88.0][0 if index == 0 else 1],
                unit="%",
                qc_passed=index == 0,
            )

        response = self.chat(
            "Plot glucose versus purity for samples S-100 and S-102 as a scatter plot"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "scatter")
        self.assertEqual(response.data["chart"]["xAxisLabel"], "glucose (mg/dL)")
        self.assertEqual(
            response.data["chart"]["series"][0]["axisLabel"],
            "purity (%)",
        )
        self.assertEqual(
            {row["sample"] for row in response.data["chart"]["data"]},
            {"S-100", "S-102"},
        )
        self.assertEqual(
            response.data["context"]["comparison"]["result_keys"],
            ["glucose", "purity"],
        )

    def test_scatter_plot_without_two_result_names_requests_axes(self):
        response = self.chat(
            "Compare samples S-100 and S-102 using a scatter plot"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["chart"])
        self.assertIn("needs two numeric result names", response.data["answer"])

    def test_named_result_that_does_not_exist_does_not_fall_back_to_other_data(self):
        response = self.chat(
            "Compare samples S-100 and S-102 using a bar chart of lactate"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["chart"])
        self.assertIn(
            "No accessible numeric result matched: lactate",
            response.data["answer"],
        )
        self.assertNotIn("glucose (mg/dL)", str(response.data))

        follow_up = self.chat(
            "Use a dot plot",
            context=response.data["context"],
        )
        self.assertIsNone(follow_up.data["chart"])
        self.assertIn("matched: lactate", follow_up.data["answer"])

    def test_regular_endpoint_accepts_dot_chart_and_result_filter(self):
        response = self.client.post(
            "/api/assistant/comparisons/",
            {
                "analysis": "compare",
                "kind": "sample",
                "identifiers": ["S-100", "S-102"],
                "metric": "results",
                "chart_type": "dot",
                "result_keys": ["glucose"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "dot")
        self.assertEqual(len(response.data["chart"]["data"]), 1)

    def test_project_follow_up_preserves_scope_and_changes_graph(self):
        first = self.chat("Compare Project Alpha and Project Beta")
        follow_up = self.chat(
            "Graph the QC failure rates for the last 30 days",
            context=first.data["context"],
        )

        self.assertEqual(follow_up.status_code, 200)
        self.assertEqual(
            follow_up.data["context"]["comparison"]["identifiers"],
            ["ALPHA", "BETA"],
        )
        self.assertEqual(follow_up.data["context"]["comparison"]["days"], 30)
        self.assertEqual(follow_up.data["context"]["comparison"]["metric"], "qc")
        labels = {series["label"] for series in follow_up.data["chart"]["series"]}
        self.assertEqual(labels, {"QC pass rate (%)", "QC failure rate (%)"})

        explanation = self.chat(
            "Why is Beta higher?",
            context=follow_up.data["context"],
        )
        self.assertIn("Top failed-result contributors in BETA", explanation.data["answer"])
        self.assertIn("glucose: 1", explanation.data["answer"])

    def test_comparison_context_does_not_capture_inventory_or_reagent_questions(self):
        first = self.chat("Compare Project Alpha and Project Beta")

        inventory = self.chat(
            "Show the inventory below its reorder level",
            context=first.data["context"],
        )
        reagent = self.chat(
            "Why is this reagent unusually low?",
            context=first.data["context"],
        )

        for response in [inventory, reagent]:
            self.assertNotIn("comparison", response.data)
            self.assertNotIn("chart", response.data)

    def test_regular_endpoint_compares_batches(self):
        response = self.client.post(
            "/api/assistant/comparisons/",
            {
                "analysis": "compare",
                "kind": "batch",
                "identifiers": ["B-100", "B-200"],
                "metric": "work",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["entity"] for row in response.data["comparison"]["rows"]},
            {"B-100", "B-200"},
        )
        self.assertEqual(response.data["chart"]["meta"]["title"], "Batch workload comparison")

    def test_result_trend_uses_matching_numeric_results(self):
        response = self.chat(
            "Graph glucose results for Project Alpha and Project Beta over the last 90 days"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chart"]["chartType"], "line")
        self.assertEqual(len(response.data["chart"]["series"]), 2)
        self.assertEqual(response.data["comparison"]["kind"], "trend")
        self.assertIn("3 numeric measurement", response.data["answer"])

    def test_outlier_review_does_not_disclose_private_result(self):
        response = self.chat("Find unusual glucose results in Project Alpha and Project Beta")

        self.assertEqual(response.status_code, 200)
        samples = {row["sample"] for row in response.data["comparison"]["rows"]}
        self.assertIn("S-102", samples)
        self.assertNotIn("S-PRIVATE", samples)
        self.assertNotIn("9999", str(response.data))

    def test_bottleneck_analysis_reports_stale_sample_and_overdue_work(self):
        response = self.chat("Where are samples getting stuck in Project Alpha?")

        self.assertEqual(response.status_code, 200)
        row = response.data["comparison"]["rows"][0]
        self.assertEqual(row["entity"], "ALPHA")
        self.assertEqual(row["stale_samples"], 1)
        self.assertEqual(row["overdue_work"], 1)
        self.assertTrue(response.data["chart"]["stacked"])

    def test_private_identifier_is_not_resolved_for_comparison(self):
        response = self.chat("Compare samples S-100 and S-PRIVATE")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("comparison", response.data)
        self.assertIn("at least two accessible samples", response.data["answer"])
        self.assertNotIn("9999", str(response.data))

    def test_confirmed_pdf_export_recalculates_and_creates_artifact(self):
        comparison = self.chat("Compare Project Alpha and Project Beta")
        proposal = self.chat(
            "Export this comparison as PDF",
            context=comparison.data["context"],
        )

        self.assertEqual(proposal.data["pending_action"]["type"], "COMPLIANCE_REPORT")
        confirmed = self.confirm(proposal)

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data["status"], "COMPLETED")
        artifact = GeneratedArtifact.objects.get(
            id=confirmed.data["result"]["artifact_id"]
        )
        self.assertEqual(artifact.kind, GeneratedArtifact.KIND_REPORT_PDF)
        self.assertEqual(
            artifact.parameters["report_type"],
            "COMPARISON_ANALYSIS",
        )
        with artifact.file.open("rb") as stream:
            self.assertEqual(stream.read(4), b"%PDF")

    def test_regular_endpoint_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/assistant/comparisons/",
            {
                "analysis": "compare",
                "kind": "sample",
                "identifiers": ["S-100", "S-101"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)
