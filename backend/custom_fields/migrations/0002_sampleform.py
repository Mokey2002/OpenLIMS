from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("custom_fields", "0001_initial")]
    operations = [migrations.CreateModel(name="SampleForm", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("code", models.CharField(max_length=64, db_index=True)),
        ("name_en", models.CharField(max_length=128)),
        ("name_es", models.CharField(max_length=128)),
        ("fields", models.JSONField(default=list)),
        ("published", models.BooleanField(default=False)),
        ("archived", models.BooleanField(default=False)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
    ])]
