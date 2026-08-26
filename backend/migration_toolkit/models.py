from django.conf import settings
from django.db import models


class SampleExternalID(models.Model):
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="external_ids",
    )
    source_system = models.CharField(max_length=128)
    external_id = models.CharField(max_length=255)
    label = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("source_system", "external_id", "label")]
        indexes = [
            models.Index(fields=["source_system", "external_id"]),
            models.Index(fields=["label"]),
        ]

    def __str__(self):
        return f"{self.source_system}:{self.label}:{self.external_id}"


class MigrationProfile(models.Model):
    SOURCE_TYPE_CSV = "CSV"
    SOURCE_TYPE_DATABASE = "DATABASE"

    SOURCE_TYPE_CHOICES = [
        (SOURCE_TYPE_CSV, "CSV"),
        (SOURCE_TYPE_DATABASE, "Database"),
    ]

    name = models.CharField(max_length=128, unique=True)
    source_system = models.CharField(max_length=128, default="Legacy DB")
    source_type = models.CharField(
        max_length=32,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_TYPE_CSV,
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class MigrationMappingTemplate(models.Model):
    name = models.CharField(max_length=128, unique=True)
    source_system = models.CharField(max_length=128, default="Legacy DB")
    source_type = models.CharField(
        max_length=32,
        choices=MigrationProfile.SOURCE_TYPE_CHOICES,
        default=MigrationProfile.SOURCE_TYPE_CSV,
    )
    description = models.TextField(blank=True)
    configuration = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_mapping_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MigrationDatabaseConnection(models.Model):
    ENGINE_POSTGRESQL = "POSTGRESQL"
    ENGINE_MYSQL = "MYSQL"
    ENGINE_SQLITE = "SQLITE"

    ENGINE_CHOICES = [
        (ENGINE_POSTGRESQL, "PostgreSQL"),
        (ENGINE_MYSQL, "MySQL / MariaDB"),
        (ENGINE_SQLITE, "SQLite"),
    ]

    name = models.CharField(max_length=128, unique=True)
    engine = models.CharField(max_length=32, choices=ENGINE_CHOICES)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(null=True, blank=True)
    database_name = models.CharField(
        max_length=512,
        help_text="Database name, or a path below MIGRATION_SQLITE_ROOT for SQLite.",
    )
    username = models.CharField(max_length=128, blank=True)
    password_env_var = models.CharField(
        max_length=128,
        blank=True,
        help_text="Environment variable containing the read-only source password.",
    )
    ssl_mode = models.CharField(max_length=32, default="prefer", blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_database_connections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class MigrationDataset(models.Model):
    ENTITY_PROJECT = "PROJECT"
    ENTITY_USER = "USER"
    ENTITY_SAMPLE = "SAMPLE"
    ENTITY_RESULT = "RESULT"
    ENTITY_REGISTRY = "REGISTRY"

    ENTITY_CHOICES = [
        (ENTITY_PROJECT, "Projects"),
        (ENTITY_USER, "Users"),
        (ENTITY_SAMPLE, "Samples"),
        (ENTITY_RESULT, "Historical results"),
        (ENTITY_REGISTRY, "Registry records"),
    ]

    profile = models.ForeignKey(
        MigrationProfile,
        on_delete=models.CASCADE,
        related_name="datasets",
    )
    connection = models.ForeignKey(
        MigrationDatabaseConnection,
        on_delete=models.PROTECT,
        related_name="datasets",
    )
    name = models.CharField(max_length=128)
    entity_type = models.CharField(max_length=32, choices=ENTITY_CHOICES)
    source_schema = models.CharField(max_length=128, blank=True)
    source_table = models.CharField(max_length=128)
    source_key_column = models.CharField(max_length=128)
    row_limit = models.PositiveIntegerField(default=10000)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["entity_type", "id"]
        unique_together = [("profile", "name")]

    def __str__(self):
        return f"{self.profile.name}: {self.name}"


class MigrationFieldMapping(models.Model):
    TARGET_PROJECT_CODE = "PROJECT_CODE"
    TARGET_PROJECT_NAME = "PROJECT_NAME"
    TARGET_SAMPLE_ID = "SAMPLE_ID"
    TARGET_EXTERNAL_ID = "EXTERNAL_ID"
    TARGET_CUSTOM_FIELD = "CUSTOM_FIELD"
    TARGET_WORK_ITEM_NAME = "WORK_ITEM_NAME"
    TARGET_RESULT_VALUE = "RESULT_VALUE"
    TARGET_PROJECT_DESCRIPTION = "PROJECT_DESCRIPTION"
    TARGET_USER_USERNAME = "USER_USERNAME"
    TARGET_USER_EMAIL = "USER_EMAIL"
    TARGET_USER_FIRST_NAME = "USER_FIRST_NAME"
    TARGET_USER_LAST_NAME = "USER_LAST_NAME"
    TARGET_USER_ROLE = "USER_ROLE"
    TARGET_SAMPLE_TYPE = "SAMPLE_TYPE"
    TARGET_SAMPLE_STATUS = "SAMPLE_STATUS"
    TARGET_SAMPLE_CREATED_AT = "SAMPLE_CREATED_AT"
    TARGET_WORK_ITEM_TYPE = "WORK_ITEM_TYPE"
    TARGET_WORK_ITEM_STATUS = "WORK_ITEM_STATUS"
    TARGET_WORK_ITEM_CREATED_AT = "WORK_ITEM_CREATED_AT"
    TARGET_RESULT_KEY = "RESULT_KEY"
    TARGET_RESULT_UNIT = "RESULT_UNIT"
    TARGET_RESULT_CREATED_AT = "RESULT_CREATED_AT"
    TARGET_RESULT_QC_STATUS = "RESULT_QC_STATUS"
    TARGET_RESULT_ENTERED_BY = "RESULT_ENTERED_BY"
    TARGET_RESULT_REFERENCE_MIN = "RESULT_REFERENCE_MIN"
    TARGET_RESULT_REFERENCE_MAX = "RESULT_REFERENCE_MAX"
    TARGET_REGISTRY_ID = "REGISTRY_ID"
    TARGET_REGISTRY_SCHEMA = "REGISTRY_SCHEMA"
    TARGET_REGISTRY_NAME = "REGISTRY_NAME"
    TARGET_REGISTRY_DESCRIPTION = "REGISTRY_DESCRIPTION"
    TARGET_REGISTRY_CATALOG_NUMBER = "REGISTRY_CATALOG_NUMBER"
    TARGET_REGISTRY_ALIAS = "REGISTRY_ALIAS"
    TARGET_REGISTRY_TAGS = "REGISTRY_TAGS"
    TARGET_REGISTRY_STATUS = "REGISTRY_STATUS"
    TARGET_REGISTRY_DATA = "REGISTRY_DATA"
    TARGET_REGISTRY_SEQUENCE = "REGISTRY_SEQUENCE"

    TARGET_TYPE_CHOICES = [
        (TARGET_PROJECT_CODE, "Project Code"),
        (TARGET_PROJECT_NAME, "Project Name"),
        (TARGET_SAMPLE_ID, "Sample ID"),
        (TARGET_EXTERNAL_ID, "External ID / Alias"),
        (TARGET_CUSTOM_FIELD, "Sample Custom Field"),
        (TARGET_WORK_ITEM_NAME, "Work Item Name"),
        (TARGET_RESULT_VALUE, "Result Value"),
        (TARGET_PROJECT_DESCRIPTION, "Project Description"),
        (TARGET_USER_USERNAME, "User Username"),
        (TARGET_USER_EMAIL, "User Email"),
        (TARGET_USER_FIRST_NAME, "User First Name"),
        (TARGET_USER_LAST_NAME, "User Last Name"),
        (TARGET_USER_ROLE, "User Role"),
        (TARGET_SAMPLE_TYPE, "Sample Type"),
        (TARGET_SAMPLE_STATUS, "Sample Status"),
        (TARGET_SAMPLE_CREATED_AT, "Sample Created At"),
        (TARGET_WORK_ITEM_TYPE, "Work Item Type"),
        (TARGET_WORK_ITEM_STATUS, "Work Item Status"),
        (TARGET_WORK_ITEM_CREATED_AT, "Work Item Created At"),
        (TARGET_RESULT_KEY, "Result Key"),
        (TARGET_RESULT_UNIT, "Result Unit"),
        (TARGET_RESULT_CREATED_AT, "Result Created At"),
        (TARGET_RESULT_QC_STATUS, "Result QC Status"),
        (TARGET_RESULT_ENTERED_BY, "Result Entered By"),
        (TARGET_RESULT_REFERENCE_MIN, "Result Reference Minimum"),
        (TARGET_RESULT_REFERENCE_MAX, "Result Reference Maximum"),
        (TARGET_REGISTRY_ID, "Registry ID"),
        (TARGET_REGISTRY_SCHEMA, "Registry Schema Code"),
        (TARGET_REGISTRY_NAME, "Registry Record Name"),
        (TARGET_REGISTRY_DESCRIPTION, "Registry Description"),
        (TARGET_REGISTRY_CATALOG_NUMBER, "Registry Catalog Number"),
        (TARGET_REGISTRY_ALIAS, "Registry Alias"),
        (TARGET_REGISTRY_TAGS, "Registry Tags"),
        (TARGET_REGISTRY_STATUS, "Registry Lifecycle Status"),
        (TARGET_REGISTRY_DATA, "Registry Data Field"),
        (TARGET_REGISTRY_SEQUENCE, "Registry Sequence"),
    ]

    VALUE_TYPE_STRING = "STRING"
    VALUE_TYPE_NUMBER = "NUMBER"
    VALUE_TYPE_BOOLEAN = "BOOLEAN"

    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_STRING, "String"),
        (VALUE_TYPE_NUMBER, "Number"),
        (VALUE_TYPE_BOOLEAN, "Boolean"),
    ]

    profile = models.ForeignKey(
        MigrationProfile,
        on_delete=models.CASCADE,
        related_name="field_mappings",
    )
    dataset = models.ForeignKey(
        MigrationDataset,
        on_delete=models.CASCADE,
        related_name="field_mappings",
        null=True,
        blank=True,
        help_text="Database dataset for this mapping; leave empty for CSV profiles.",
    )
    source_column = models.CharField(max_length=128)
    target_type = models.CharField(max_length=64, choices=TARGET_TYPE_CHOICES)
    target_field = models.CharField(
        max_length=128,
        blank=True,
        help_text="Used for custom field name, external ID label, or result key.",
    )
    value_type = models.CharField(
        max_length=16,
        choices=VALUE_TYPE_CHOICES,
        default=VALUE_TYPE_STRING,
    )
    required = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "dataset", "source_column", "target_type", "target_field"],
                condition=models.Q(dataset__isnull=False),
                name="migration_db_mapping_unique",
            ),
            models.UniqueConstraint(
                fields=["profile", "source_column", "target_type", "target_field"],
                condition=models.Q(dataset__isnull=True),
                name="migration_csv_mapping_unique",
            ),
        ]

    def __str__(self):
        return f"{self.profile.name}: {self.source_column} -> {self.target_type}"


class MigrationJob(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_PREVIEWED = "PREVIEWED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_PARTIAL_FAILED = "PARTIAL_FAILED"
    STATUS_FAILED = "FAILED"
    STATUS_ROLLED_BACK = "ROLLED_BACK"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_PREVIEWED, "Previewed"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_PARTIAL_FAILED, "Partial Failed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_ROLLED_BACK, "Rolled Back"),
    ]

    CONFLICT_SKIP = "SKIP"
    CONFLICT_MERGE = "MERGE"
    CONFLICT_OVERWRITE = "OVERWRITE"
    CONFLICT_CREATE_NEW = "CREATE_NEW"

    CONFLICT_POLICY_CHOICES = [
        (CONFLICT_SKIP, "Skip existing records"),
        (CONFLICT_MERGE, "Fill blank fields on existing records"),
        (CONFLICT_OVERWRITE, "Overwrite mapped fields"),
        (CONFLICT_CREATE_NEW, "Create a new record with a unique identifier"),
    ]

    profile = models.ForeignKey(
        MigrationProfile,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_jobs",
    )
    uploaded_file = models.FileField(upload_to="migration_jobs/", null=True, blank=True)
    source_connection = models.ForeignKey(
        MigrationDatabaseConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_jobs",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_jobs",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PREVIEWED,
    )
    summary = models.JSONField(default=dict, blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    preview_fingerprint = models.CharField(max_length=64, blank=True)
    conflict_policy = models.CharField(
        max_length=32,
        choices=CONFLICT_POLICY_CHOICES,
        default=CONFLICT_SKIP,
    )
    committed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committed_migration_jobs",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rolled_back_migration_jobs",
    )
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rollback_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"MigrationJob {self.id} - {self.profile.name}"


class MigrationRowRecord(models.Model):
    STATUS_IMPORTED = "IMPORTED"
    STATUS_SKIPPED = "SKIPPED"
    STATUS_ERROR = "ERROR"

    STATUS_CHOICES = [
        (STATUS_IMPORTED, "Imported"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_ERROR, "Error"),
    ]

    ACTION_CREATE = "CREATE"
    ACTION_MATCH = "MATCH"
    ACTION_SKIP = "SKIP"
    ACTION_MERGE = "MERGE"
    ACTION_OVERWRITE = "OVERWRITE"
    ACTION_CREATE_NEW = "CREATE_NEW"
    ACTION_ERROR = "ERROR"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Created"),
        (ACTION_MATCH, "Matched"),
        (ACTION_SKIP, "Skipped"),
        (ACTION_MERGE, "Merged"),
        (ACTION_OVERWRITE, "Overwritten"),
        (ACTION_CREATE_NEW, "Created with a new identifier"),
        (ACTION_ERROR, "Error"),
    ]

    migration_job = models.ForeignKey(
        MigrationJob,
        on_delete=models.CASCADE,
        related_name="row_records",
    )
    source_dataset = models.ForeignKey(
        MigrationDataset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="row_records",
    )
    entity_type = models.CharField(max_length=32, blank=True)
    source_key = models.CharField(max_length=255, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_row_records",
    )
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_row_records",
    )
    row_number = models.PositiveIntegerField()
    project_code = models.CharField(max_length=128, blank=True)
    project_name = models.CharField(max_length=255, blank=True)
    sample_code = models.CharField(max_length=128, blank=True)
    raw_row = models.JSONField(default=dict, blank=True)
    raw_row_text = models.TextField(blank=True)
    unmapped_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_IMPORTED,
    )
    action = models.CharField(
        max_length=32,
        choices=ACTION_CHOICES,
        default=ACTION_CREATE,
    )
    target_object_type = models.CharField(max_length=32, blank=True)
    target_object_id = models.CharField(max_length=64, blank=True)
    errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["migration_job", "source_dataset", "row_number"],
                condition=models.Q(source_dataset__isnull=False),
                name="migration_db_row_unique",
            ),
            models.UniqueConstraint(
                fields=["migration_job", "row_number"],
                condition=models.Q(source_dataset__isnull=True),
                name="migration_csv_row_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["migration_job", "row_number"]),
            models.Index(fields=["project", "sample"]),
            models.Index(fields=["sample_code"]),
            models.Index(fields=["project_code"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Migration row {self.row_number} for job {self.migration_job_id}"


class MigrationObjectChange(models.Model):
    ACTION_CREATED = "CREATED"
    ACTION_UPDATED = "UPDATED"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_UPDATED, "Updated"),
    ]

    migration_job = models.ForeignKey(
        MigrationJob,
        on_delete=models.CASCADE,
        related_name="object_changes",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=32)
    object_id = models.CharField(max_length=64)
    identifier = models.CharField(max_length=255, blank=True)
    previous_values = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["migration_job", "object_type", "object_id", "action"],
                name="migration_object_change_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["migration_job", "action"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.migration_job_id}: {self.action} {self.object_type} {self.object_id}"
