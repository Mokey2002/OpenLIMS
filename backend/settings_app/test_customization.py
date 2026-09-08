from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase
from rest_framework.exceptions import ValidationError

from assistant.barcode_operations import route_barcode_operations, _render_labels
from assistant.reporting_operations import route_reporting_operations, _pdf_bytes
from events.models import Event
from samples.models import Sample
from .models import WorkspaceView, PrintTemplate
from .customization import validate_print_config, print_snapshot


class CustomizationTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="director", is_superuser=True)
        self.tech = get_user_model().objects.create_user(username="tech")
        self.other = get_user_model().objects.create_user(username="other")
        self.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client.force_authenticate(self.admin)

    def test_personal_views_are_isolated_and_role_views_read_only(self):
        private = WorkspaceView.objects.create(owner=self.other, name="Private", config={})
        shared = WorkspaceView.objects.create(role="tech", name="Shared", config={})
        self.client.force_authenticate(self.tech)
        response = self.client.get("/api/workspace-views/")
        rows = response.data["results"]
        self.assertEqual([r["id"] for r in rows], [shared.pk])
        self.assertEqual(self.client.patch(f"/api/workspace-views/{private.pk}/", {"name": "hacked"}).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/workspace-views/{shared.pk}/", {"name": "hacked"}).status_code, 403)
        self.assertEqual(self.client.post("/api/workspace-views/", {"name": "Admin", "role": "admin", "config": {}}, format="json").status_code, 403)

    def test_view_validation_and_owner_cannot_be_spoofed(self):
        self.client.force_authenticate(self.tech)
        response = self.client.post("/api/workspace-views/", {"name": "Bench", "owner": self.other.pk, "config": {"widgets": ["assigned"], "columns": ["name"], "query": "DNA"}}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["owner"], self.tech.pk)
        for config in [{"widgets": []}, {"columns": ["secret"]}, {"columns": ["name", "name"]}, {"query": []}, {"script": "alert(1)"}]:
            self.assertEqual(self.client.post("/api/workspace-views/", {"name": "Bad", "config": config}, format="json").status_code, 400)

    def test_print_templates_admin_only_and_stale_revision_rejected(self):
        response = self.client.post("/api/print-templates/", {"name": "Lab", "kind": "REPORT", "config": {"title": "Lab report"}}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        url = f"/api/print-templates/{response.data['id']}/"
        self.assertEqual(self.client.patch(url, {"name": "New", "revision": 1}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"name": "Stale", "revision": 1}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"name": "Bad", "revision": 2}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/print-templates/preview/", {"name": "Bad", "kind": "REPORT", "config": {}}, format="json").status_code, 403)

    def test_unsafe_layouts_and_logos_rejected(self):
        for kind, config in [("LABEL", {"columns": 3}), ("LABEL", {"rows": True}), ("REPORT", {"page_size": "evil"}), ("REPORT", {"logo": "https://example.com/logo.png"}), ("REPORT", {"logo": "data:image/png;base64,AAAA"}), ("REPORT", {"title": "a" * 81}), ("REPORT", {"html": "<script>"})]:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                validate_print_config(kind, config)

    def test_print_previews_are_read_only_and_valid_pdf(self):
        for kind in ["LABEL", "REPORT"]:
            response = self.client.post("/api/print-templates/preview/", {"name": "Preview", "kind": kind, "config": {}}, format="json")
            self.assertEqual(response.status_code, 200, response.content[:200])
            self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertFalse(PrintTemplate.objects.exists())
        self.assertFalse(Event.objects.exists())

    def test_snapshots_survive_edits_and_archive(self):
        template = PrintTemplate.objects.create(name="Original", kind="REPORT", config={"title": "Original"})
        route = route_reporting_operations("Generate a PDF report", self.admin, {"print_template_id": template.pk})
        filters = deepcopy(route["pending_action"]["payload"]["filters"])
        template.config = {"title": "New"}
        template.archived = True
        template.save()
        self.assertEqual(filters["print_template"]["config"]["title"], "Original")
        self.assertTrue(_pdf_bytes([], filters, None).startswith(b"%PDF"))
        with self.assertRaises(ValidationError):
            print_snapshot({"print_template_id": template.pk}, "REPORT")

    def test_label_template_keeps_barcode_identity(self):
        sample = Sample.objects.create(sample_id="S-100")
        template = PrintTemplate.objects.create(name="A4", kind="LABEL", config={"page_size": "A4"})
        response = route_barcode_operations("Generate barcode label for sample S-100", self.admin, {"print_template_id": template.pk})
        payload = response["pending_action"]["payload"]
        self.assertEqual(payload["template"], "STANDARD_SAMPLE")
        self.assertEqual(payload["print_template"]["id"], template.pk)
        self.assertEqual(payload["sample_ids"], [sample.pk])
        with self.assertRaises(ValidationError):
            print_snapshot({"print_template_id": template.pk}, "REPORT")

    def test_pdf_grids_and_landscape_render(self):
        sample = SimpleNamespace(sample_id="DEMO-001", project=None)
        label = SimpleNamespace(barcode="OPENLIMS-SAMPLE-1-DEMO-001")
        for columns in [1, 2]:
            for rows in [3, 4, 5]:
                self.assertTrue(_render_labels([(sample, label, True)] * 12, {"config": {"columns": columns, "rows": rows, "page_size": "A4"}}).startswith(b"%PDF"))

    def test_analysis_exports_freeze_layout_and_csv_ignores_it(self):
        from assistant.comparisons import _comparison_export
        from assistant.investigations import _export_investigation
        template = PrintTemplate.objects.create(name="Evidence", kind="REPORT", config={"show_chart": False, "summary_position": "after"})
        for route, kind in [(_comparison_export, "comparison"), (_export_investigation, "investigation")]:
            context = {kind: {"identifier": "demo"}, "print_template_id": template.pk}
            result = route(context, "PDF")
            frozen = result["pending_action"]["payload"]["filters"]["print_template"]
            self.assertEqual(frozen["config"]["summary_position"], "after")
            self.assertEqual(frozen["revision"], 1)
            template.config = {"title": "Changed"}
            template.save()
            self.assertNotIn("title", frozen["config"])
            template.config = {"show_chart": False, "summary_position": "after"}
            template.save()
            csv = route({**context, "print_template_id": "invalid"}, "CSV")
            self.assertNotIn("print_template", csv["pending_action"]["payload"]["filters"])
        template.archived = True
        template.save()
        with self.assertRaises(ValidationError):
            _comparison_export({"print_template_id": template.pk}, "PDF")

    def test_analysis_preview_layouts_and_validation(self):
        for kind in ["comparison", "investigation"]:
            for orientation in ["portrait", "landscape"]:
                response = self.client.post("/api/print-templates/preview/", {"name": "Evidence", "kind": "REPORT", "report_type": kind,
                    "config": {"page_size": "A4", "orientation": orientation, "summary_position": "after", "chart_position": "after"}}, format="json")
                self.assertEqual(response.status_code, 200, response.content[:200])
                self.assertTrue(response.content.startswith(b"%PDF"))
        for config in [{"show_chart": "false"}, {"summary_position": []}, {"chart_position": "middle"}, {"hide_evidence": True}]:
            with self.assertRaises(ValidationError):
                validate_print_config("REPORT", config)
        self.assertEqual(PrintTemplate.objects.count(), 0)
