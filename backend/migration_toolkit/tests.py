import sqlite3
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from migration_toolkit.database_services import (
    apply_database_migration,
    prepare_database_preview,
)
from migration_toolkit.database_sources import inspect_source
from migration_toolkit.models import (
    MigrationDatabaseConnection,
    MigrationDataset,
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
)
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


pytestmark = pytest.mark.django_db


def _create_source(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE legacy_users (
            id INTEGER PRIMARY KEY, username TEXT, email TEXT, first_name TEXT,
            last_name TEXT, role TEXT
        );
        CREATE TABLE legacy_projects (
            id INTEGER PRIMARY KEY, code TEXT, name TEXT, description TEXT
        );
        CREATE TABLE legacy_samples (
            id INTEGER PRIMARY KEY, sample_code TEXT, project_code TEXT,
            sample_type TEXT, status TEXT, created_at TEXT, collection_site TEXT
        );
        CREATE TABLE legacy_results (
            id INTEGER PRIMARY KEY, sample_code TEXT, work_name TEXT,
            result_key TEXT, result_value TEXT, unit TEXT, created_at TEXT,
            qc_status TEXT, entered_by TEXT, reference_min TEXT, reference_max TEXT
        );
        INSERT INTO legacy_users VALUES
            (1, 'legacytech', 'legacy@example.org', 'Legacy', 'Tech', 'tech');
        INSERT INTO legacy_projects VALUES
            (1, 'SISBI-001', 'SISBI Study', 'Imported historical study');
        INSERT INTO legacy_samples VALUES
            (1, 'OLD-S-001', 'SISBI-001', 'SERUM', 'REPORTED',
             '2020-01-02T03:04:05+00:00', 'CU');
        INSERT INTO legacy_results VALUES
            (1, 'OLD-S-001', 'Legacy Chemistry', 'glucose', '91.5', 'mg/dL',
             '2020-01-03T03:04:05+00:00', 'APPROVED', 'legacytech', '70', '100');
        """
    )
    connection.commit()
    connection.close()


def _map(dataset, target, column, value_type="STRING", required=False, target_field=""):
    return MigrationFieldMapping.objects.create(
        profile=dataset.profile,
        dataset=dataset,
        source_column=column,
        target_type=target,
        target_field=target_field,
        value_type=value_type,
        required=required,
    )


def _configure_profile(tmp_path, admin_user):
    source_path = tmp_path / "sisbi.sqlite3"
    _create_source(source_path)
    source = MigrationDatabaseConnection.objects.create(
        name="SISBI fixture",
        engine=MigrationDatabaseConnection.ENGINE_SQLITE,
        database_name=source_path.name,
        created_by=admin_user,
    )
    profile = MigrationProfile.objects.create(
        name="SISBI database",
        source_system="SISBI",
        source_type=MigrationProfile.SOURCE_TYPE_DATABASE,
        created_by=admin_user,
    )

    users = MigrationDataset.objects.create(
        profile=profile, connection=source, name="Users",
        entity_type=MigrationDataset.ENTITY_USER, source_table="legacy_users",
        source_key_column="id",
    )
    _map(users, MigrationFieldMapping.TARGET_USER_USERNAME, "username", required=True)
    _map(users, MigrationFieldMapping.TARGET_USER_EMAIL, "email")
    _map(users, MigrationFieldMapping.TARGET_USER_FIRST_NAME, "first_name")
    _map(users, MigrationFieldMapping.TARGET_USER_LAST_NAME, "last_name")
    _map(users, MigrationFieldMapping.TARGET_USER_ROLE, "role")

    projects = MigrationDataset.objects.create(
        profile=profile, connection=source, name="Projects",
        entity_type=MigrationDataset.ENTITY_PROJECT, source_table="legacy_projects",
        source_key_column="id",
    )
    _map(projects, MigrationFieldMapping.TARGET_PROJECT_CODE, "code", required=True)
    _map(projects, MigrationFieldMapping.TARGET_PROJECT_NAME, "name", required=True)
    _map(projects, MigrationFieldMapping.TARGET_PROJECT_DESCRIPTION, "description")

    samples = MigrationDataset.objects.create(
        profile=profile, connection=source, name="Samples",
        entity_type=MigrationDataset.ENTITY_SAMPLE, source_table="legacy_samples",
        source_key_column="id",
    )
    _map(samples, MigrationFieldMapping.TARGET_SAMPLE_ID, "sample_code", required=True)
    _map(samples, MigrationFieldMapping.TARGET_PROJECT_CODE, "project_code", required=True)
    _map(samples, MigrationFieldMapping.TARGET_SAMPLE_TYPE, "sample_type")
    _map(samples, MigrationFieldMapping.TARGET_SAMPLE_STATUS, "status")
    _map(samples, MigrationFieldMapping.TARGET_SAMPLE_CREATED_AT, "created_at")

    results = MigrationDataset.objects.create(
        profile=profile, connection=source, name="Results",
        entity_type=MigrationDataset.ENTITY_RESULT, source_table="legacy_results",
        source_key_column="id",
    )
    _map(results, MigrationFieldMapping.TARGET_SAMPLE_ID, "sample_code", required=True)
    _map(results, MigrationFieldMapping.TARGET_WORK_ITEM_NAME, "work_name")
    _map(results, MigrationFieldMapping.TARGET_RESULT_KEY, "result_key", required=True)
    _map(
        results, MigrationFieldMapping.TARGET_RESULT_VALUE, "result_value",
        value_type=MigrationFieldMapping.VALUE_TYPE_NUMBER, required=True,
    )
    _map(results, MigrationFieldMapping.TARGET_RESULT_UNIT, "unit")
    _map(results, MigrationFieldMapping.TARGET_RESULT_CREATED_AT, "created_at")
    _map(results, MigrationFieldMapping.TARGET_RESULT_QC_STATUS, "qc_status")
    _map(results, MigrationFieldMapping.TARGET_RESULT_ENTERED_BY, "entered_by")
    _map(results, MigrationFieldMapping.TARGET_RESULT_REFERENCE_MIN, "reference_min")
    _map(results, MigrationFieldMapping.TARGET_RESULT_REFERENCE_MAX, "reference_max")
    return source_path, source, profile


def test_database_preview_and_commit_imports_all_supported_entities(tmp_path, admin_user):
    source_path, source, profile = _configure_profile(tmp_path, admin_user)
    with override_settings(MIGRATION_SQLITE_ROOT=tmp_path):
        inspection = inspect_source(source)
        assert {item["name"] for item in inspection["tables"]} == {
            "legacy_users", "legacy_projects", "legacy_samples", "legacy_results"
        }

        summary, snapshot, _ = prepare_database_preview(profile)
        assert summary["ready_to_commit"] is True
        assert summary["rows_processed"] == 4
        assert summary["entity_counts"]["USER"]["to_create"] == 1
        assert summary["entity_counts"]["PROJECT"]["to_create"] == 1
        assert summary["entity_counts"]["SAMPLE"]["to_create"] == 1
        assert summary["entity_counts"]["RESULT"]["rows"] == 1

        job = MigrationJob.objects.create(
            profile=profile, source_connection=source, uploaded_by=admin_user,
            status=MigrationJob.STATUS_PREVIEWED, summary=summary,
            source_snapshot=snapshot, preview_fingerprint=summary["preview_fingerprint"],
        )
        result_summary = apply_database_migration(job, admin_user)

    imported_user = admin_user.__class__.objects.get(username="legacytech")
    assert imported_user.is_active is False
    assert imported_user.has_usable_password() is False
    assert list(imported_user.groups.values_list("name", flat=True)) == ["tech"]
    project = Project.objects.get(code="SISBI-001")
    sample = Sample.objects.get(sample_id="OLD-S-001")
    assert sample.project == project
    assert sample.sample_type == "SERUM"
    assert sample.status == Sample.STATUS_REPORTED
    assert sample.created_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=datetime_timezone.utc)
    work_item = WorkItem.objects.get(sample=sample, name="Legacy Chemistry")
    result = Result.objects.get(work_item=work_item, key="glucose")
    assert result.value_number == 91.5
    assert result.unit == "mg/dL"
    assert result.reference_min == 70
    assert result.reference_max == 100
    assert result.qc_status == Result.QC_APPROVED
    assert result.entered_by == imported_user
    assert result.created_at == datetime(2020, 1, 3, 3, 4, 5, tzinfo=datetime_timezone.utc)
    assert result_summary["row_records_created"] == 4
    assert job.row_records.count() == 4


def test_commit_is_blocked_if_source_changes_after_preview(tmp_path, admin_user):
    source_path, source, profile = _configure_profile(tmp_path, admin_user)
    with override_settings(MIGRATION_SQLITE_ROOT=tmp_path):
        summary, snapshot, _ = prepare_database_preview(profile)
        job = MigrationJob.objects.create(
            profile=profile, source_connection=source, uploaded_by=admin_user,
            status=MigrationJob.STATUS_PREVIEWED, summary=summary,
            source_snapshot=snapshot, preview_fingerprint=summary["preview_fingerprint"],
        )
        connection = sqlite3.connect(source_path)
        connection.execute("UPDATE legacy_projects SET name = ? WHERE id = 1", ["Changed"])
        connection.commit()
        connection.close()
        with pytest.raises(ValidationError, match="changed after preview"):
            apply_database_migration(job, admin_user)

    assert Project.objects.filter(code="SISBI-001").exists() is False


def test_database_configuration_and_preview_are_director_only(
    tmp_path, admin_user, tech_client
):
    _, source, profile = _configure_profile(tmp_path, admin_user)
    assert tech_client.get("/api/migration-database-connections/").status_code == 403
    assert tech_client.get("/api/migration-datasets/").status_code == 403
    response = tech_client.post(
        "/api/migration-jobs/preview/",
        {"profile": profile.id},
        format="json",
    )
    assert response.status_code == 403


def test_director_can_queue_the_exact_database_preview(
    tmp_path, admin_user, admin_client
):
    _, _, profile = _configure_profile(tmp_path, admin_user)
    with override_settings(MIGRATION_SQLITE_ROOT=tmp_path):
        preview = admin_client.post(
            "/api/migration-jobs/preview/",
            {"profile": profile.id},
            format="json",
        )
        assert preview.status_code == 201
        assert preview.data["summary"]["ready_to_commit"] is True

        with patch("migration_toolkit.views.run_migration_job.delay") as delay:
            commit = admin_client.post(
                f"/api/migration-jobs/{preview.data['id']}/commit/",
                {},
                format="json",
            )

    assert commit.status_code == 202
    assert commit.data["id"] == preview.data["id"]
    assert commit.data["status"] == MigrationJob.STATUS_PENDING
    delay.assert_called_once_with(preview.data["id"])


def test_csv_commit_is_bound_to_the_reviewed_file_and_mappings(
    tmp_path, admin_user, admin_client
):
    profile = MigrationProfile.objects.create(
        name="Reviewed CSV",
        source_system="Legacy CSV",
        source_type=MigrationProfile.SOURCE_TYPE_CSV,
        created_by=admin_user,
    )
    sample_mapping = MigrationFieldMapping.objects.create(
        profile=profile,
        source_column="sample_id",
        target_type=MigrationFieldMapping.TARGET_SAMPLE_ID,
        required=True,
    )
    MigrationFieldMapping.objects.create(
        profile=profile,
        source_column="project_code",
        target_type=MigrationFieldMapping.TARGET_PROJECT_CODE,
        required=True,
    )
    upload = SimpleUploadedFile(
        "legacy.csv",
        b"sample_id,project_code\nS-100,P-100\n",
        content_type="text/csv",
    )
    with override_settings(MEDIA_ROOT=tmp_path):
        preview = admin_client.post(
            "/api/migration-jobs/preview/",
            {"profile": profile.id, "uploaded_file": upload},
            format="multipart",
        )
        assert preview.status_code == 201
        assert preview.data["summary"]["ready_to_commit"] is True

        sample_mapping.required = False
        sample_mapping.save(update_fields=["required"])
        commit = admin_client.post(
            f"/api/migration-jobs/{preview.data['id']}/commit/",
            {},
            format="json",
        )

    assert commit.status_code == 409
    assert "changed after preview" in commit.data["detail"]
    assert MigrationJob.objects.get(id=preview.data["id"]).status == MigrationJob.STATUS_PREVIEWED
