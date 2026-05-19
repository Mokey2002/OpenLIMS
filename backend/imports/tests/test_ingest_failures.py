import pytest

pytestmark = pytest.mark.django_db


def test_missing_instrument_code(api_client, instrument_headers):
    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        {
            "run_id": "RUN-FAIL-1",
            "rows": [],
        },
        format="json",
        **instrument_headers,
    )

    assert response.status_code == 400


def test_unknown_instrument(api_client, instrument_headers):
    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        {
            "instrument_code": "UNKNOWN",
            "run_id": "RUN-FAIL-2",
            "rows": [],
        },
        format="json",
        **instrument_headers,
    )

    assert response.status_code == 404


def test_missing_rows(api_client, instrument_profile, instrument_headers):
    response = api_client.post(
        "/api/import-jobs/instrument-ingest/",
        {
            "instrument_code": "NOVAFLEX",
            "run_id": "RUN-FAIL-3",
        },
        format="json",
        **instrument_headers,
    )

    assert response.status_code == 400
