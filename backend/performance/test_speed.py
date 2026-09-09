"""Opt-in benchmarks; pytest-django owns creation/removal of the test database."""
import json
import math
import os
from time import perf_counter

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from projects.models import Project
from results.models import WorkItem
from samples.models import Sample

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(os.getenv("OPENLIMS_RUN_PERF") != "1", reason="Opt-in speed benchmark")]


def integer(name, default, minimum, maximum):
    value = int(os.getenv(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@pytest.fixture(scope="module")
def dataset(django_db_setup, django_db_blocker):
    count = integer("OPENLIMS_PERF_SAMPLES", 1000, 100, 500000)
    with django_db_blocker.unblock():
        user = get_user_model().objects.create_user(username="speed-tech")
        user.groups.add(Group.objects.get_or_create(name="tech")[0])
        project = Project.objects.create(name="Speed benchmark", code="SPEED")
        project.members.add(user)
        # Keep allocation bounded even for 500,000 samples. One assigned work item per sample.
        for start in range(0, count, 1000):
            samples = Sample.objects.bulk_create([
                Sample(sample_id=f"SPEED-{i:07d}", project=project, created_by=user)
                for i in range(start, min(start + 1000, count))
            ], batch_size=1000)
            WorkItem.objects.bulk_create([
                WorkItem(sample=sample, name="Benchmark work", assigned_to=user, created_by=user)
                for sample in samples
            ], batch_size=1000)
        first = Sample.objects.get(sample_id="SPEED-0000000")
    return user, count, first.pk


@pytest.mark.parametrize("scenario", ["session", "my_work", "sample_list", "sample_search", "sample_detail"])
def test_api_speed(dataset, django_db_blocker, record_property, scenario):
    user, count, first_pk = dataset
    rounds = integer("OPENLIMS_PERF_ROUNDS", 20, 5, 1000)
    paths = {
        "session": "/api/v1/session/",
        "my_work": "/api/v1/my-work/",
        "sample_list": "/api/v1/samples/?page_size=50",
        "sample_search": "/api/v1/samples/?search=SPEED-0000000&page_size=50",
        "sample_detail": f"/api/v1/samples/{first_pk}/",
    }
    client = APIClient()
    client.force_authenticate(user)
    with django_db_blocker.unblock():
        # Warm caches and record first request separately; do not time dataset setup.
        start = perf_counter()
        response = client.get(paths[scenario])
        first_request_ms = (perf_counter() - start) * 1000
        assert response.status_code == 200, response.content[:500]
        timings, sizes = [], []
        for _ in range(rounds):
            start = perf_counter()
            response = client.get(paths[scenario])
            timings.append((perf_counter() - start) * 1000)
            assert response.status_code == 200, response.content[:500]
            sizes.append(len(response.content))
        with CaptureQueriesContext(connection) as queries:
            client.get(paths[scenario])
        if scenario == "sample_list":
            assert response.data["count"] == count
            assert len(response.data["results"]) == 50
        elif scenario == "sample_search":
            assert response.data["count"] == 1
            assert response.data["results"][0]["sample_id"] == "SPEED-0000000"
        elif scenario == "my_work":
            assert response.data["summary"]["assigned"] == count
            assert len(response.data["assigned_work"]) == 12
        ordered = sorted(timings)
        report = {"scenario": scenario, "database": connection.vendor, "samples": count,
                  "work_items": count, "rounds": rounds, "first_request_ms": round(first_request_ms, 2),
                  "p50_ms": round(ordered[math.ceil(rounds * .5) - 1], 2),
                  "p95_ms": round(ordered[math.ceil(rounds * .95) - 1], 2),
                  "max_ms": round(max(timings), 2), "max_response_bytes": max(sizes), "queries": len(queries)}
        print(json.dumps(report, sort_keys=True))
        for key, value in report.items():
            record_property(key, value)
        # Optional machine-specific gates; never present arbitrary thresholds as measured capacity.
        if os.getenv("OPENLIMS_PERF_P95_MS"):
            assert report["p95_ms"] <= float(os.environ["OPENLIMS_PERF_P95_MS"]), report
        if os.getenv("OPENLIMS_PERF_MAX_QUERIES"):
            assert report["queries"] <= int(os.environ["OPENLIMS_PERF_MAX_QUERIES"]), report
