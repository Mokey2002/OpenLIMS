from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settings_app", "0006_systemsettings_assistant_helper_enabled")]
    operations = [migrations.CreateModel(name="SampleStatusPolicy", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("transitions", models.JSONField(default=dict)),
        ("revision", models.PositiveIntegerField(default=1)),
    ])]
