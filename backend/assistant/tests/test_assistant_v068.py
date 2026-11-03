import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.db import close_old_connections, connection
from rest_framework.test import APITransactionTestCase, APITestCase

from assistant.models import AssistantAction
from imports.assistant_uploads import MARKER, process_prepared_job
from imports.models import ImportJob, InstrumentColumnMapping, InstrumentProfile
from imports.tasks import process_assistant_import_job, process_import_job
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True, OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class AssistantV068Tests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="assistant-import-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=self.media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.user = get_user_model().objects.create_user(username="import-tech")
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.other = get_user_model().objects.create_user(username="other-tech")
        self.other.groups.add(Group.objects.get(name="tech"))
        self.project = Project.objects.create(code="CHAT-IMPORT", name="Chat import project")
        self.project.members.add(self.user)
        self.private = Project.objects.create(code="PRIVATE-IMPORT", name="Private project")
        self.private.members.add(self.other)
        self.instrument = InstrumentProfile.objects.create(code="SEQ-CHAT", name="Chat sequencer", sample_id_column="sample_id")
        self.mapping = InstrumentColumnMapping.objects.create(instrument=self.instrument, source_column="concentration", target_key="concentration", value_type="NUMBER", min_value=0, max_value=100)
        self.client.force_authenticate(self.user)

    def upload(self, raw=b"sample_id,concentration\nCHAT-1,4.5\n", run="RUN-1", skip=True, expected=(200, 201)):
        reply = self.client.post("/api/assistant/instrument-imports/", {"instrument": self.instrument.pk,
            "project": self.project.pk, "run_id": run, "skip_duplicates": str(skip).lower(),
            "uploaded_file": SimpleUploadedFile("sequencer.csv", raw, content_type="text/csv")}, format="multipart")
        self.assertIn(reply.status_code, expected, reply.data)
        return reply

    def confirm(self, reply, expected=202, publish_error=False):
        action = reply.data["pending_action"]
        with patch("imports.tasks.process_assistant_import_job.delay", side_effect=OSError("broker offline") if publish_error else None) as queued, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/assistant/actions/{action['confirmation_token']}/confirm/", {"confirm": True}, format="json")
        self.assertEqual(response.status_code, expected, response.data)
        return response, queued

    def test_upload_previews_mapping_and_does_not_import_until_confirmation(self):
        reply = self.upload()
        self.assertFalse(Sample.objects.exists())
        self.assertFalse(WorkItem.objects.exists())
        self.assertEqual(reply.data["instrument_import_job"]["mappings"][0]["target_key"], "concentration")
        confirmed, queued = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        queued.assert_called_once_with(job_id, reply.data["pending_action"]["id"])
        process_assistant_import_job.run(job_id, reply.data["pending_action"]["id"])
        self.assertEqual(Result.objects.get().value_number, 4.5)
        job = ImportJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "COMPLETED")
        receipt = job.summary["receipt"]
        self.assertEqual((receipt["rows_received"], receipt["rows_imported"], receipt["rows_accounted"]), (1, 1, 1))
        action = AssistantAction.objects.get(pk=reply.data["pending_action"]["id"])
        self.assertEqual(action.status, "COMPLETED")
        self.assertEqual(action.result["rows_imported"], 1)

    def test_every_row_is_accounted_for_and_duplicate_policy_preserves_replicates(self):
        raw = b"sample_id,concentration\nR-1,5\nR-1,5\nR-2,NaN\nR-3,0\n,2\nR-1,6\n"
        reply = self.upload(raw)
        planned = reply.data["instrument_import_job"]["counts"]
        self.assertEqual((planned["rows_received"], planned["rows_to_import"], planned["rows_rejected"], planned["duplicates_skipped"]), (6, 3, 2, 1))
        confirmed, _ = self.confirm(reply)
        process_prepared_job(confirmed.data["result"]["import_job_id"])
        self.assertEqual(WorkItem.objects.count(), 3)
        self.assertEqual(Result.objects.count(), 3)
        report = self.client.get(reply.data["instrument_import_job"]["download_url"])
        text = b"".join(report.streaming_content).decode("utf-8-sig")
        self.assertEqual(len(text.splitlines()), 7)
        self.assertIn("rejected", text)
        self.assertIn("duplicate", text)
        keep = self.upload(b"sample_id,concentration\nREPLICATE,5\nREPLICATE,5\n", run="RUN-REPLICATES", skip=False)
        self.assertEqual(keep.data["instrument_import_job"]["counts"]["rows_to_import"], 2)
        self.assertEqual(keep.data["instrument_import_job"]["counts"]["duplicates_skipped"], 0)

    def test_same_run_upload_confirmation_and_worker_redelivery_do_not_duplicate(self):
        reply = self.upload()
        duplicate = self.upload()
        self.assertEqual(ImportJob.objects.count(), 1)
        self.assertEqual(duplicate.data["pending_action"]["id"], reply.data["pending_action"]["id"])
        confirmed, _ = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        process_prepared_job(job_id)
        process_prepared_job(job_id)
        self.confirm(reply, expected=200)
        self.assertEqual((Sample.objects.count(), WorkItem.objects.count(), Result.objects.count()), (1, 1, 1))
        self.mapping.max_value = 1
        self.mapping.save()
        again = self.upload()
        self.assertEqual(again.data["instrument_import_job"]["status"], "COMPLETED")
        self.upload(b"sample_id,concentration\nDIFFERENT,5\n", expected=(409,))

    def test_unconfirmed_worker_calls_cannot_import(self):
        reply = self.upload()
        job_id = reply.data["instrument_import_job"]["id"]
        process_import_job.run(job_id)
        self.assertFalse(Result.objects.exists())
        self.assertEqual(ImportJob.objects.get(pk=job_id).status, "PENDING")

    def test_configuration_changes_block_confirmation_and_revalidation_replaces_preview(self):
        reply = self.upload()
        self.mapping.max_value = 50
        self.mapping.save()
        _, queued = self.confirm(reply, expected=400)
        queued.assert_not_called()
        self.assertFalse(Result.objects.exists())
        job_id = reply.data["instrument_import_job"]["id"]
        fresh = self.client.post(f"/api/assistant/instrument-imports/{job_id}/revalidate/", {}, format="json")
        self.assertEqual(fresh.status_code, 200, fresh.data)
        self.assertNotEqual(fresh.data["pending_action"]["id"], reply.data["pending_action"]["id"])
        self.confirm(fresh)
        process_prepared_job(job_id)
        self.assertEqual(Result.objects.count(), 1)

    def test_worker_rechecks_access_and_rolls_back_all_results_on_late_failure(self):
        reply = self.upload(b"sample_id,concentration\nFIRST,5\nSECOND,6\n")
        confirmed, _ = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        original = Result.objects.update_or_create
        calls = []
        def fail_later(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("simulated worker failure")
            return original(*args, **kwargs)
        with patch.object(Result.objects, "update_or_create", side_effect=fail_later):
            process_prepared_job(job_id)
        self.assertEqual((Sample.objects.count(), WorkItem.objects.count(), Result.objects.count()), (0, 0, 0))
        job = ImportJob.objects.get(pk=job_id)
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.summary["receipt"]["rows_imported"], 0)
        self.assertTrue(all(row["status"] == "not_imported" for row in job.summary["row_report"]))
        self.assertEqual(self.client.post(f"/api/import-jobs/{job_id}/retry/", {}, format="json").status_code, 400)

    def test_old_failure_finalization_cannot_fail_a_newly_confirmed_generation(self):
        from assistant.lifecycle import finish_queued_action

        reply = self.upload()
        self.confirm(reply)
        job_id = reply.data["instrument_import_job"]["id"]
        replacements = []

        def revalidate_then_finalize(**kwargs):
            fresh = self.client.post(f"/api/assistant/instrument-imports/{job_id}/revalidate/", {}, format="json")
            self.assertEqual(fresh.status_code, 200, fresh.data)
            self.confirm(fresh)
            replacements.append(fresh.data["pending_action"]["id"])
            return finish_queued_action(**kwargs)

        with patch("imports.tasks.process_rows", side_effect=ValueError("simulated processing failure")), \
                patch("assistant.lifecycle.finish_queued_action", side_effect=revalidate_then_finalize):
            process_prepared_job(job_id)

        self.assertEqual(AssistantAction.objects.get(pk=reply.data["pending_action"]["id"]).status, "CANCELLED")
        self.assertEqual(AssistantAction.objects.get(pk=replacements[0]).status, "QUEUED")
        self.assertFalse(Result.objects.exists())
        process_prepared_job(job_id, replacements[0])
        self.assertEqual(AssistantAction.objects.get(pk=replacements[0]).status, "COMPLETED")
        self.assertEqual(Result.objects.count(), 1)

    def test_native_edits_and_deletion_cannot_free_an_assistant_run_identity(self):
        reply = self.upload()
        job_id = reply.data["instrument_import_job"]["id"]
        endpoint = f"/api/import-jobs/{job_id}/"
        for completed in (False, True):
            if completed:
                self.confirm(reply)
                process_prepared_job(job_id)
            with self.subTest(completed=completed):
                updated = self.client.patch(endpoint, {"run_id": "REPLACED-RUN"}, format="json")
                self.assertEqual(updated.status_code, 400, updated.data)
                deleted = self.client.delete(endpoint)
                self.assertEqual(deleted.status_code, 400, deleted.data)
                self.assertEqual(ImportJob.objects.get(pk=job_id).run_id, "RUN-1")
        recovered = self.upload()
        self.assertEqual(recovered.data["instrument_import_job"]["id"], job_id)
        self.assertEqual((Sample.objects.count(), WorkItem.objects.count(), Result.objects.count()), (1, 1, 1))

    def test_permission_revocation_after_queue_fails_without_lab_writes(self):
        reply = self.upload()
        confirmed, _ = self.confirm(reply)
        self.project.members.remove(self.user)
        job_id = confirmed.data["result"]["import_job_id"]
        process_prepared_job(job_id)
        self.assertFalse(Result.objects.exists())
        self.assertEqual(ImportJob.objects.get(pk=job_id).status, "FAILED")
        self.assertEqual(self.client.get(f"/api/assistant/instrument-imports/{job_id}/").status_code, 404)

    def test_private_or_wrong_project_samples_are_rejected_without_disclosing_values(self):
        Sample.objects.create(sample_id="PRIVATE-SAMPLE", project=self.private, created_by=self.other)
        reply = self.upload(b"sample_id,concentration\nPRIVATE-SAMPLE,5\nPUBLIC-NEW,6\n")
        counts = reply.data["instrument_import_job"]["counts"]
        self.assertEqual((counts["rows_rejected"], counts["rows_to_import"]), (1, 1))
        self.assertNotIn("Private project", str(reply.data))
        self.client.force_authenticate(self.other)
        job_id = reply.data["instrument_import_job"]["id"]
        self.assertEqual(self.client.get(f"/api/assistant/instrument-imports/{job_id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/assistant/instrument-imports/{job_id}/report/").status_code, 404)

    def test_malformed_headers_nonfinite_values_and_invalid_mappings_do_not_stage_jobs(self):
        for raw in [b"sample_id,concentration,concentration\nS-1,1,2\n", b"sample_id,other\nS-1,1\n",
                    b"sample_id,concentration\nS-1,NaN\nS-2,Infinity\nS-3,1e999\n",
                    b"sample_id,concentration\nS-1,5,extra\n"]:
            with self.subTest(raw=raw):
                self.upload(raw, expected=(400,))
        self.assertFalse(ImportJob.objects.exists())
        InstrumentColumnMapping.objects.create(instrument=self.instrument, source_column="other", target_key="concentration", value_type="NUMBER")
        self.upload(expected=(400,))

    def test_broker_failure_is_visible_and_explicit_resume_is_idempotent(self):
        reply = self.upload()
        confirmed, _ = self.confirm(reply, publish_error=True)
        job_id = confirmed.data["result"]["import_job_id"]
        job = ImportJob.objects.get(pk=job_id)
        self.assertIn("delivery", job.summary["queue_error"])
        self.assertFalse(Result.objects.exists())
        with patch("imports.tasks.process_assistant_import_job.delay") as queued, self.captureOnCommitCallbacks(execute=True):
            resume = self.client.post(f"/api/assistant/instrument-imports/{job_id}/resume/", {}, format="json")
        self.assertEqual(resume.status_code, 200, resume.data)
        queued.assert_called_once()
        process_prepared_job(job_id)
        self.assertEqual(Result.objects.count(), 1)

    def test_hundred_row_file_has_a_complete_receipt_and_current_mapping(self):
        raw = ("sample_id,concentration\n" + "".join(f"LAB-{index:03},5\n" for index in range(100))).encode()
        reply = self.upload(raw)
        confirmed, _ = self.confirm(reply)
        process_prepared_job(confirmed.data["result"]["import_job_id"])
        job = ImportJob.objects.get(pk=confirmed.data["result"]["import_job_id"])
        self.assertEqual(job.summary["receipt"]["rows_imported"], 100)
        self.assertEqual(job.summary["receipt"]["rows_accounted"], 100)
        self.assertEqual(Result.objects.count(), 100)

    def test_natural_start_project_selection_and_recovery_commands(self):
        reply = self.client.post("/api/assistant/chat/", {"message": "Could you import this sequencer file into project CHAT-IMPORT?"}, format="json")
        self.assertEqual(reply.status_code, 200, reply.data)
        self.assertEqual(reply.data["instrument_import_form"]["project_id"], self.project.pk)
        staged = self.upload()
        listing = self.client.post("/api/assistant/chat/", {"message": "Show my instrument imports"}, format="json")
        self.assertIn(f"#{staged.data['instrument_import_job']['id']}", listing.data["answer"])

    def test_tsv_metadata_headers_case_variants_and_false_values_are_preserved(self):
        self.instrument.delimiter = "\t"
        self.instrument.save()
        self.mapping.value_type = "BOOLEAN"
        self.mapping.min_value = self.mapping.max_value = None
        self.mapping.save()
        reply = self.upload(b"Instrument export\nOperator: laboratory\nsample_id\tconcentration\nCase-Sample\tfalse\nCASE-SAMPLE\ttrue\n")
        confirmed, _ = self.confirm(reply)
        process_prepared_job(confirmed.data["result"]["import_job_id"])
        self.assertEqual(Sample.objects.count(), 1)
        self.assertEqual(Result.objects.count(), 2)
        self.assertEqual(set(Result.objects.values_list("value_boolean", flat=True)), {False, True})

    def test_file_mutation_and_mapping_mutation_after_queue_are_rejected(self):
        reply = self.upload()
        confirmed, _ = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        job = ImportJob.objects.get(pk=job_id)
        with job.uploaded_file.open("wb") as staged:
            staged.write(b"sample_id,concentration\nCHANGED,5\n")
        process_prepared_job(job_id)
        self.assertEqual(ImportJob.objects.get(pk=job_id).status, "FAILED")
        self.assertFalse(Result.objects.exists())

    def test_completed_job_redelivery_repairs_interrupted_action_finalization(self):
        reply = self.upload()
        confirmed, _ = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        with patch("assistant.lifecycle.finish_queued_action", side_effect=OSError("interrupted finalization")):
            with self.assertRaises(OSError):
                process_prepared_job(job_id)
        self.assertEqual(ImportJob.objects.get(pk=job_id).status, "COMPLETED")
        self.assertEqual(AssistantAction.objects.get(pk=reply.data["pending_action"]["id"]).status, "QUEUED")
        process_prepared_job(job_id)
        self.assertEqual(AssistantAction.objects.get(pk=reply.data["pending_action"]["id"]).status, "COMPLETED")
        self.assertEqual(Result.objects.count(), 1)

    def test_report_escapes_spreadsheet_formulas_and_preserves_all_rows(self):
        reply = self.upload(b"sample_id,concentration\n=FORMULA,5\n")
        report = self.client.get(reply.data["instrument_import_job"]["download_url"])
        text = b"".join(report.streaming_content).decode("utf-8-sig")
        self.assertIn("'=FORMULA", text)

    def test_revalidating_an_unstarted_queue_invalidates_its_old_delivery_generation(self):
        reply = self.upload()
        confirmed, _ = self.confirm(reply)
        job_id = confirmed.data["result"]["import_job_id"]
        old_id = reply.data["pending_action"]["id"]
        self.mapping.max_value = 50
        self.mapping.save()
        fresh = self.client.post(f"/api/assistant/instrument-imports/{job_id}/revalidate/", {}, format="json")
        self.assertEqual(fresh.status_code, 200, fresh.data)
        self.assertEqual(AssistantAction.objects.get(pk=old_id).status, "CANCELLED")
        self.confirm(fresh)
        process_prepared_job(job_id, old_id)
        self.assertFalse(Result.objects.exists())
        process_prepared_job(job_id, fresh.data["pending_action"]["id"])
        self.assertEqual(Result.objects.count(), 1)

    def test_viewers_cannot_upload_and_duplicate_multipart_file_fields_are_rejected(self):
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.upload(expected=(403,))
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get(name="tech"))
        files = [SimpleUploadedFile("first.csv", b"sample_id,concentration\nA,5\n"), SimpleUploadedFile("second.csv", b"sample_id,concentration\nB,5\n")]
        response = self.client.post("/api/assistant/instrument-imports/", {"instrument": self.instrument.pk, "project": self.project.pk,
            "run_id": "MULTIPLE", "uploaded_file": files}, format="multipart")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ImportJob.objects.exists())

    def test_row_limit_and_invalid_utf8_are_rejected_before_staging(self):
        with patch("imports.assistant_uploads.MAX_ROWS", 2):
            self.upload(b"sample_id,concentration\nA,1\nB,2\nC,3\n", expected=(400,))
        self.upload(b"sample_id,concentration\n\xff,1\n", expected=(400,))
        self.assertFalse(ImportJob.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class AssistantImportConcurrencyTests(APITransactionTestCase):
    setUp = AssistantV068Tests.setUp
    upload = AssistantV068Tests.upload

    def test_two_workers_commit_one_measurement_set(self):
        reply = self.upload()
        token = reply.data["pending_action"]["confirmation_token"]
        with patch("imports.tasks.process_assistant_import_job.delay"):
            confirmed = self.client.post(f"/api/assistant/actions/{token}/confirm/", {"confirm": True}, format="json")
        self.assertEqual(confirmed.status_code, 202, confirmed.data)
        job_id = confirmed.data["result"]["import_job_id"]
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return process_prepared_job(job_id)["receipt"]["rows_imported"]
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results, [1, 1])
        self.assertEqual((Sample.objects.count(), WorkItem.objects.count(), Result.objects.count()), (1, 1, 1))
        self.assertTrue(process_assistant_import_job.acks_late)
        self.assertTrue(process_assistant_import_job.reject_on_worker_lost)
