"""Real competing transactions; SQLite must not count as concurrency coverage."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from notebook.models import Experiment, Notebook
from notebook.services import create_revision


class NotebookConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Concurrency CI requires PostgreSQL, not SQLite")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def test_two_onboarding_requests_create_one_experiment(self):
        from rest_framework.test import APIClient
        from notebook.models import ExperimentTemplate, ExperimentOnboarding
        owner = get_user_model().objects.create_user(username="onboarding-owner")
        notebook = Notebook.objects.create(name="Onboarding", owner=owner)
        template = ExperimentTemplate.objects.create(notebook=notebook, name="Measure", created_by=owner,
            workflow_steps=[{"name": "Measure", "fields": []}])
        ready = Barrier(2, timeout=10)

        def start():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=owner.pk))
                ready.wait()
                response = client.post("/api/onboarding/", {"template": template.pk, "title": "First"})
                return response.status_code, response.data["experiment"]["public_id"]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(start), pool.submit(start)]
            results = [future.result(timeout=30) for future in futures]
        self.assertCountEqual([code for code, _ in results], [200, 201])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Experiment.objects.count(), 1)
        self.assertEqual(ExperimentOnboarding.objects.count(), 1)

    def test_two_writers_with_same_base_revision_cannot_both_succeed(self):
        owner = get_user_model().objects.create_user(username="concurrent-owner")
        notebook = Notebook.objects.create(name="Concurrent", scope="USER", owner=owner)
        experiment = Experiment.objects.create(notebook=notebook, title="Trial", created_by=owner)
        initial, _ = create_revision(experiment=experiment, actor=owner,
                                     blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Initial"}}], links=[])
        ready = Barrier(2, timeout=10)

        def save(text):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                actor = get_user_model().objects.get(pk=owner.pk)
                record = Experiment.objects.get(pk=experiment.pk)
                ready.wait()
                try:
                    revision, _ = create_revision(experiment=record, actor=actor,
                        blocks=[{"block_type": "RICH_TEXT", "data": {"text": text}}], links=[],
                        expected_revision_public_id=str(initial.public_id))
                    return ("saved", revision.pk)
                except ValidationError as error:
                    if "revision" not in error.detail:
                        raise
                    return ("conflict", None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save, "Writer A")
            second = pool.submit(save, "Writer B")
            results = [first.result(timeout=30), second.result(timeout=30)]
        self.assertCountEqual([status for status, _ in results], ["saved", "conflict"])
        experiment.refresh_from_db()
        winner = next(pk for status, pk in results if status == "saved")
        self.assertEqual(experiment.current_revision_id, winner)
        self.assertEqual(list(experiment.revisions.order_by("number").values_list("number", flat=True)), [1, 2])

    def test_two_workflow_writers_cannot_overwrite_the_same_version(self):
        from notebook.models import ExperimentWorkflowStep
        from notebook.workflows import update_step
        owner = get_user_model().objects.create_user(username="workflow-concurrent-owner")
        notebook = Notebook.objects.create(name="Workflow concurrent", owner=owner)
        experiment = Experiment.objects.create(notebook=notebook, title="Concurrent workflow", created_by=owner)
        step = ExperimentWorkflowStep.objects.create(experiment=experiment, position=1, assignee=owner,
            definition={"name": "Measure", "fields": [{"key": "value", "label": "Value", "type": "NUMBER", "required": True}]})
        ready = Barrier(2, timeout=10)

        def save(value):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                actor = get_user_model().objects.get(pk=owner.pk)
                record = Experiment.objects.get(pk=experiment.pk)
                ready.wait()
                try:
                    update_step(experiment=record, position=1, actor=actor,
                        data={"operation": "save", "expected_version": 1, "values": {"value": value}, "note": "Recorded"})
                    return ("saved", value)
                except ValidationError as error:
                    if "This step changed" not in str(error.detail):
                        raise
                    return ("conflict", None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save, 10)
            second = pool.submit(save, 20)
            results = [first.result(timeout=30), second.result(timeout=30)]
        self.assertCountEqual([status for status, _ in results], ["saved", "conflict"])
        step.refresh_from_db()
        self.assertEqual(step.version, 2)
        self.assertEqual(step.values["value"], next(value for status, value in results if status == "saved"))
