import django.db.models.deletion
import uuid

import core.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0001_enable_pg_trgm_search_indexes"),
        ("projects", "0004_project_public_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EntityLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("source_object_id", models.CharField(max_length=64)),
                ("target_object_id", models.CharField(max_length=64)),
                ("relation_type", models.SlugField(max_length=64)),
                ("label", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_entity_links", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="entity_links", to="projects.project")),
                ("source_content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="openlims_source_links", to="contenttypes.contenttype")),
                ("target_content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="openlims_target_links", to="contenttypes.contenttype")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="SharedAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("target_object_id", models.CharField(max_length=64)),
                ("file", models.FileField(upload_to=core.models.shared_attachment_upload_to)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("media_type", models.CharField(blank=True, max_length=255)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="shared_attachments", to="projects.project")),
                ("target_content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="openlims_shared_attachments", to="contenttypes.contenttype")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="shared_attachments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="entitylink",
            constraint=models.UniqueConstraint(
                fields=("source_content_type", "source_object_id", "target_content_type", "target_object_id", "relation_type"),
                name="core_entity_link_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="entitylink",
            index=models.Index(fields=["source_content_type", "source_object_id"], name="core_link_source_idx"),
        ),
        migrations.AddIndex(
            model_name="entitylink",
            index=models.Index(fields=["target_content_type", "target_object_id"], name="core_link_target_idx"),
        ),
        migrations.AddIndex(
            model_name="entitylink",
            index=models.Index(fields=["project", "-created_at"], name="core_link_project_idx"),
        ),
        migrations.AddIndex(
            model_name="sharedattachment",
            index=models.Index(fields=["target_content_type", "target_object_id"], name="core_attach_target_idx"),
        ),
        migrations.AddIndex(
            model_name="sharedattachment",
            index=models.Index(fields=["project", "-created_at"], name="core_attach_project_idx"),
        ),
    ]
