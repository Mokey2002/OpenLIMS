"""Real HTTP/ASGI smoke test, separate from browser response mocks."""
import json
import html
import re
import uuid
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from channels.testing import ChannelsLiveServerTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.conf import settings
from django.db import connections
from rest_framework_simplejwt.tokens import AccessToken

from projects.models import Project
from samples.models import Sample
from results.models import WorkItem, Result


@override_settings(DEBUG=True, SECRET_KEY="live-http-test-secret-key-longer-than-thirty-two-characters")
class AssistantLiveHTTPTests(ChannelsLiveServerTestCase):
    serve_static = False

    @classmethod
    def setUpClass(cls):
        # The live server inherits this publication stub; test jobs must never
        # reach a development worker configured for a different database.
        cls._import_publication = patch("imports.tasks.process_assistant_import_job.delay", return_value=None)
        cls._import_publication.start()
        # pytest-django has already selected the test database. Tell Channels
        # its explicit name so the child does not add a second "test_" prefix.
        cls._test_name = settings.DATABASES["default"]["TEST"].get("NAME")
        settings.DATABASES["default"]["TEST"]["NAME"] = connections["default"].settings_dict["NAME"]
        try:
            super().setUpClass()
        except Exception:
            cls._import_publication.stop()
            settings.DATABASES["default"]["TEST"]["NAME"] = cls._test_name
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._import_publication.stop()
            settings.DATABASES["default"]["TEST"]["NAME"] = cls._test_name

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="live-chat-owner")
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.project = Project.objects.create(code="LIVE-CHAT", name="Live chat test")
        self.project.members.add(self.user)
        sample = Sample.objects.create(sample_id="LIVE-CHAT-1", project=self.project, created_by=self.user)
        work = WorkItem.objects.create(sample=sample, name="Live HTTP test")
        self.result = Result.objects.create(work_item=work, key="concentration", value_type="NUMBER", value_number=45, qc_passed=False)
        self.token = str(AccessToken.for_user(self.user))
        self.opener = build_opener(ProxyHandler({}))

    def http(self, path, data=None):
        request = Request(self.live_server_url + path, data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            return self.opener.open(request, timeout=15)
        except HTTPError as error:
            if error.code != 500:
                raise
            body = error.read().decode()
            values = re.findall(r'<pre class="exception_value">(.*?)</pre>', body, re.S)
            raise AssertionError("HTTP 500: " + html.unescape(" ".join(values))[:1000]) from error

    def test_real_http_stream_filters_save_and_permission_refresh(self):
        with self.http("/api/v1/assistant/chat/stream/", {"message": "Show QC failures for project LIVE-CHAT", "request_id": str(uuid.uuid4())}) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            text = response.read().decode()
        self.assertLess(text.index("event: progress"), text.index("event: complete"))
        complete = text.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0]
        reply = json.loads(complete)
        self.assertEqual(reply["read_plan"]["steps"][0]["result_query"]["total"], 1)
        self.assertIn("45.0", reply["answer"])
        with self.http("/api/v1/assistant/conversations/", {"name": "Real HTTP review", "turn_tokens": [reply["save_turn_token"]]}) as response:
            conversation_id = json.load(response)["id"]
        Result.objects.filter(pk=self.result.pk).update(value_number=17)
        with self.http(f"/api/v1/assistant/conversations/{conversation_id}/") as response:
            restored = json.load(response)
        self.assertIn("17.0", restored["history"][1]["reply"]["answer"])
        self.project.members.remove(self.user)
        with self.http(f"/api/v1/assistant/conversations/{conversation_id}/") as response:
            denied = json.load(response)
        self.assertNotIn("17.0", str(denied))
        request_id = str(uuid.uuid4())
        with self.http(f"/api/v1/assistant/chat/requests/{request_id}/cancel/", {}):
            pass
        with self.assertRaises(HTTPError) as error:
            self.http("/api/v1/assistant/chat/stream/", {"message": "Who am I?", "request_id": request_id})
        self.assertEqual(error.exception.code, 409)

    def test_real_streamed_workflow_preparation_through_human_qc(self):
        from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep

        sample = self.result.work_item.sample
        template = PipelineTemplate.objects.create(code="LIVE-PREP", name="Live sequencing preparation")
        for position, code in [(1, "LIVE-EXTRACTION"), (2, "SEQUENCING")]:
            analysis = AnalysisDefinition.objects.create(code=code, name=code,
                required_fields=[{"key": "checked", "value_type": "BOOLEAN", "required": True}] if position == 1 else [])
            procedure = ProcedureDefinition.objects.create(code=code, name=code, analysis=analysis)
            PipelineTemplateStep.objects.create(template=template, position=position, procedure=procedure, requires_qc=position == 1)

        def get_plan():
            with self.http(f"/api/v1/assistant/workflows/{sample.pk}/") as response:
                return json.load(response)

        def propose(operation, **fields):
            with self.http(f"/api/v1/assistant/workflows/{sample.pk}/actions/", {"operation": operation,
                    "plan_digest": get_plan()["plan_digest"], **fields}) as response:
                return json.load(response)["pending_action"]

        def confirm(action):
            with self.http(f"/api/v1/assistant/actions/{action['confirmation_token']}/confirm/", {"confirm": True}) as response:
                self.assertEqual(json.load(response)["status"], "COMPLETED")

        with self.http("/api/v1/assistant/chat/stream/", {"message": f"Help me prepare sample {sample.sample_id} for sequencing",
                "request_id": str(uuid.uuid4())}) as response:
            stream = response.read().decode()
        reply = json.loads(stream.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0])
        self.assertEqual(reply["workflow_plan"]["readiness"], "needs_workflow")
        confirm(propose("WORKFLOW_START", template_id=template.pk))
        step = sample.pipeline_runs.get().steps.get(position=1)
        with self.http("/api/v1/assistant/chat/", {"message": f"Add result checked = false to work item #{step.work_item_id} for sample {sample.sample_id}",
                "context": reply["context"]}) as response:
            entry = json.load(response)
        self.assertIn("workflow_plan", entry)
        confirm(entry["pending_action"])
        confirm(propose("WORKFLOW_COMPLETE", step_id=step.pk))
        self.assertEqual(get_plan()["steps"][0]["status"], "AWAITING_QC")
        reviewer = get_user_model().objects.create_user(username="live-workflow-reviewer")
        reviewer.groups.add(Group.objects.get_or_create(name="qc_reviewer")[0])
        self.project.members.add(reviewer)
        self.token = str(AccessToken.for_user(reviewer))
        confirm(propose("WORKFLOW_REVIEW", step_id=step.pk, decision="APPROVED", reason="Reviewed the actual recorded evidence."))
        self.assertEqual(get_plan()["readiness"], "available")
        self.assertEqual(Result.objects.get(work_item_id=step.work_item_id).qc_status, "PENDING_REVIEW")
        self.project.members.remove(reviewer)
        with self.assertRaises(HTTPError) as error:
            get_plan()
        self.assertEqual(error.exception.code, 404)

    def test_real_http_stream_accepts_page_reference_and_rechecks_revoked_access(self):
        sample = self.result.work_item.sample
        page = {"kind": "sample", "record_id": str(sample.public_id)}
        def stream():
            with self.http("/api/v1/assistant/chat/stream/", {"message": "Show results for this sample", "page_context": page,
                      "request_id": str(uuid.uuid4())}) as response:
                text = response.read().decode()
            return json.loads(text.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0])
        reply = stream()
        self.assertEqual(reply["page_context_used"]["record_id"], str(sample.public_id))
        self.assertIn("45.0", reply["answer"])
        self.project.members.remove(self.user)
        denied = stream()
        self.assertTrue(denied["clarification"])
        self.assertNotIn("45.0", str(denied))

    def test_natural_filtered_page_conversation_over_real_streaming_http(self):
        sample = self.result.work_item.sample
        context = {}
        for message, expected_period in [
            ("Hi, could you show me the failed results for this sample from today?", "today"),
            ("What about last month?", "last_month"),
            ("Thanks! Could you compare those with last week?", "last_month"),
        ]:
            with self.http("/api/v1/assistant/chat/stream/", {"message": message, "context": context,
                      "page_context": {"kind": "sample", "record_id": str(sample.public_id)},
                      "request_id": str(uuid.uuid4())}) as response:
                body = response.read().decode()
            self.assertNotIn("event: error", body)
            reply = json.loads(body.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0])
            step = reply["read_plan_spec"]["steps"][0]
            self.assertEqual(step["arguments"], {"sample": "LIVE-CHAT-1"})
            self.assertEqual(step["filters"]["period"], expected_period)
            self.assertEqual(step["filters"]["qc"], "failed")
            context = reply["context"]
        self.assertEqual(step["operation"], "sample_results_compare")
        self.assertEqual(step["filters"]["compare_period"], "last_week")

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, OPENLIMS_ASSISTANT_LLM_ENABLED=False)
    def test_real_streamed_registration_previews_then_confirms_and_retries_without_duplicates(self):
        original = Sample.objects.count()
        with self.http("/api/v1/assistant/chat/stream/", {"message": "Register 2 DNA samples in project LIVE-CHAT and assign them to me",
                  "request_id": str(uuid.uuid4())}) as response:
            body = response.read().decode()
        reply = json.loads(body.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0])
        self.assertEqual(Sample.objects.count(), original)
        action = reply["pending_action"]
        self.assertEqual(action["preview"]["proposed_values"]["assigned_to"], self.user.username)
        path = f"/api/v1/assistant/actions/{action['confirmation_token']}/confirm/"
        with self.http(path, {"confirm": True}) as response:
            confirmed = json.load(response)
        self.assertEqual(confirmed["status"], "COMPLETED")
        ids = confirmed["result"]["context"]["sample_ids"]
        self.assertEqual(Sample.objects.filter(pk__in=ids, assigned_to=self.user, project=self.project).count(), 2)
        with self.http(path, {"confirm": True}) as response:
            retried = json.load(response)
        self.assertEqual(retried["result"]["context"]["sample_ids"], ids)
        self.assertEqual(Sample.objects.count(), original + 2)

    def test_real_multipart_instrument_upload_confirmation_and_complete_row_receipt(self):
        from imports.models import InstrumentColumnMapping, InstrumentProfile
        from imports.assistant_uploads import process_prepared_job
        profile = InstrumentProfile.objects.create(code="LIVE-UPLOAD", name="Live upload", sample_id_column="sample_id")
        InstrumentColumnMapping.objects.create(instrument=profile, source_column="concentration", target_key="concentration", value_type="NUMBER")
        boundary = "openlims-live-upload-boundary"
        parts = []
        for key, value in {"instrument": profile.pk, "project": self.project.pk, "run_id": "LIVE-RUN-1", "skip_duplicates": "true"}.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="uploaded_file"; filename="instrument.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
            + b"sample_id,concentration\nLIVE-UPLOAD-1,5\nLIVE-UPLOAD-1,5\nLIVE-UPLOAD-BAD,NaN\nLIVE-UPLOAD-2,0\n"
            + f'\r\n--{boundary}--\r\n'.encode())
        request = Request(self.live_server_url + "/api/v1/assistant/instrument-imports/", data=b"".join(parts),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with self.opener.open(request, timeout=15) as response:
            reply = json.load(response)
        job_id = reply["instrument_import_job"]["id"]
        self.assertFalse(WorkItem.objects.filter(source_import_job_id=job_id).exists())
        action = reply["pending_action"]
        with self.http(f"/api/v1/assistant/actions/{action['confirmation_token']}/confirm/", {"confirm": True}) as response:
            self.assertEqual(json.load(response)["status"], "QUEUED")
        process_prepared_job(job_id, action["id"])
        with self.http(f"/api/v1/assistant/instrument-imports/{job_id}/") as response:
            receipt = json.load(response)
        self.assertEqual(receipt["status"], "COMPLETED")
        self.assertEqual(receipt["counts"]["rows_received"], 4)
        self.assertEqual(receipt["counts"]["rows_imported"], 2)
        self.assertEqual(receipt["counts"]["rows_rejected"], 1)
        self.assertEqual(receipt["counts"]["duplicates_skipped"], 1)
        self.assertEqual(receipt["counts"]["rows_accounted"], 4)
        self.assertEqual(receipt["action"]["status"], "COMPLETED")
        with self.http(f"/api/v1/assistant/instrument-imports/{job_id}/report/") as response:
            self.assertEqual(len(response.read().decode("utf-8-sig").splitlines()), 5)
