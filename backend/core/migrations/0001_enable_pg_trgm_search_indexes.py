from django.db import migrations


class Migration(migrations.Migration):



    dependencies = [
    ("samples", "0001_initial"),
    ("projects", "0001_initial"),
    ("events", "0001_initial"),
    ("sequences", "0001_initial"),
    ("alignments", "0001_initial"),
]
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE EXTENSION IF NOT EXISTS pg_trgm;

            CREATE INDEX IF NOT EXISTS samples_sample_sample_id_trgm_idx
            ON samples_sample USING gin (sample_id gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS samples_sample_status_trgm_idx
            ON samples_sample USING gin (status gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS projects_project_code_trgm_idx
            ON projects_project USING gin (code gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS projects_project_name_trgm_idx
            ON projects_project USING gin (name gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS projects_project_description_trgm_idx
            ON projects_project USING gin (description gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS events_event_action_trgm_idx
            ON events_event USING gin (action gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS events_event_entity_type_trgm_idx
            ON events_event USING gin (entity_type gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS events_event_entity_id_trgm_idx
            ON events_event USING gin (entity_id gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS sequences_sequence_name_trgm_idx
            ON sequences_sequence USING gin (name gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS sequences_sequence_type_trgm_idx
            ON sequences_sequence USING gin (sequence_type gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS alignments_alignmentjob_name_trgm_idx
            ON alignments_alignmentjob USING gin (name gin_trgm_ops);

            CREATE INDEX IF NOT EXISTS alignments_alignmentjob_status_trgm_idx
            ON alignments_alignmentjob USING gin (status gin_trgm_ops);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS samples_sample_sample_id_trgm_idx;
            DROP INDEX IF EXISTS samples_sample_status_trgm_idx;
            DROP INDEX IF EXISTS projects_project_code_trgm_idx;
            DROP INDEX IF EXISTS projects_project_name_trgm_idx;
            DROP INDEX IF EXISTS projects_project_description_trgm_idx;
            DROP INDEX IF EXISTS events_event_action_trgm_idx;
            DROP INDEX IF EXISTS events_event_entity_type_trgm_idx;
            DROP INDEX IF EXISTS events_event_entity_id_trgm_idx;
            DROP INDEX IF EXISTS sequences_sequence_name_trgm_idx;
            DROP INDEX IF EXISTS sequences_sequence_type_trgm_idx;
            DROP INDEX IF EXISTS alignments_alignmentjob_name_trgm_idx;
            DROP INDEX IF EXISTS alignments_alignmentjob_status_trgm_idx;
            """,
        ),
    ]
