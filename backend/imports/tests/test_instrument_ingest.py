import pytest
from django.conf import settings
from rest_framework.test import APIClient

from imports.models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from samples.models import Sample
from results.models import WorkItem, Result


pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def instrument():
    profile = InstrumentProfile.objects.create(
        name="NovaFlex",
        code="NOVAFLEX",
        delimiter=",",
        has_header=True,
        sample_id_column="sample_id",
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="concentration",
        target_key="concentration",
        value_type="NUMBER",
        min_value=0,
        max_value=1000,
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="purity",
        target_key="purity",
        value_type="NUMBER",
        min_value=0,
        max_value=100,
    )

    return profile


def ingest_headers():
    return {
        "HTTP_X_INSTRUMENT_API_KEY": settings.INSTRUMENT_API_KEY,
    }


def test_instrument_ingest_requires_api_key(client, instrument):
    payload = {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-001",
        "rows": [{"sample_id": "S-001", "concentration": 12.4, "purity": 97.1}],
    }

    response = client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
    )

    assert response.status_code in (401, 403)


def test_instrument_ingest_with_valid_key_creates_sample_and_results(client, instrument):
    payload = {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-001",
        "rows": [
            {"sample_id": "S-001", "concentration": 12.4, "purity": 97.1},
        ],
    }

    response = client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
        **ingest_headers(),
    )

    assert response.status_code == 201
    assert ImportJob.objects.count() == 1
    assert Sample.objects.filter(sample_id="S-001").exists()

    sample = Sample.objects.get(sample_id="S-001")
    work_item = WorkItem.objects.get(sample=sample)
    results = Result.objects.filter(work_item=work_item)

    assert results.count() == 2
    assert results.filter(key="concentration").exists()
    assert results.filter(key="purity").exists()


def test_instrument_ingest_duplicate_run_id_is_rejected(client, instrument):
    payload = {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-001",
        "rows": [
            {"sample_id": "S-001", "concentration": 12.4, "purity": 97.1},
        ],
    }

    first = client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
        **ingest_headers(),
    )
    second = client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
        **ingest_headers(),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert ImportJob.objects.count() == 1


def test_instrument_ingest_records_skipped_rows_for_invalid_values(client, instrument):
    payload = {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-002",
        "rows": [
            {"sample_id": "S-002", "concentration": "bad-value", "purity": 97.1},
        ],
    }

    response = client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
        **ingest_headers(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["results_created"] == 1
    assert len(body["skipped_rows"]) == 1
    assert body["skipped_rows"][0]["column"] == "concentration"
