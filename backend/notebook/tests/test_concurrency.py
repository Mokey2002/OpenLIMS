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
