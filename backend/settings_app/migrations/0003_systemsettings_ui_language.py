from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("settings_app", "0002_qc_separation_of_duties")]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="ui_language",
            field=models.CharField(
                choices=[("en", "English"), ("es", "Español")],
                default="en",
                max_length=5,
            ),
        ),
    ]
