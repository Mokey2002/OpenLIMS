from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settings_app", "0003_systemsettings_ui_language")]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="insight_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="notebook_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="registry_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="studies_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
