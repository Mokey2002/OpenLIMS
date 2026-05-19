import pytest
from results.models import Result

pytestmark = pytest.mark.django_db


def test_no_duplicate_results_created(
    api_client,
    instrument_profile,
    instrument_headers,
    ingest_payload,
):
    # First ingest
    api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
        **instrument_headers,
    )

    # Second ingest with SAME run_id (should fail)
    api_client.post(
        "/api/import-jobs/instrument-ingest/",
        ingest_payload,
        format="json",
        **instrument_headers,
    )

    # Ensure no duplicates
    results = Result.objects.filter(key="concentration")
    assert results.count() == 1
