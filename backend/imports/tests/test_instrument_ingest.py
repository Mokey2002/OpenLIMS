import pytest

from imports.models import ImportJob
from results.models import Result, WorkItem
from samples.models import Sample

pytestmark = pytest.mark.django_db


def test_instrument_ingest_requires_api_key(
    api_client,
    instrument_profile,
    ingest_payload,
):
    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
    )

    assert response.status_code == 403


def test_instrument_ingest_with_valid_key_creates_sample_and_results(
    api_client,
    instrument_profile,
    instrument_headers,
    ingest_payload,
):
    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
        **instrument_headers,
    )

    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["results_created"] == 3
    assert body["samples_created"] == 1

    job = ImportJob.objects.get(run_id="RUN-001")
    assert job.status == "COMPLETED"
    assert job.source_type == "API"

    sample = Sample.objects.get(sample_id="S-INGEST-001")
    work_item = WorkItem.objects.get(sample=sample)

    results = Result.objects.filter(work_item=work_item)
    assert results.count() == 3
    assert results.filter(key="concentration").exists()
    assert results.filter(key="purity").exists()
    assert results.filter(key="qc_flag").exists()


def test_instrument_ingest_duplicate_run_id_is_rejected(
    api_client,
    instrument_profile,
    instrument_headers,
    ingest_payload,
):
    first = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
        **instrument_headers,
    )

    second = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
        **instrument_headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert ImportJob.objects.count() == 1


def test_instrument_ingest_records_skipped_rows_for_invalid_values(
    api_client,
    instrument_profile,
    instrument_headers,
):
    payload = {
        "instrument_code": "NOVAFLEX",
        "run_id": "RUN-BAD-001",
        "rows": [
            {
                "sample_id": "S-BAD-001",
                "concentration": "bad-value",
                "purity": 97.1,
                "qc_flag": "PASS",
            }
        ],
    }

    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        payload,
        format="json",
        **instrument_headers,
    )

    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["results_created"] == 2
    assert len(body["skipped_rows"]) == 1
    assert body["skipped_rows"][0]["column"] == "concentration"