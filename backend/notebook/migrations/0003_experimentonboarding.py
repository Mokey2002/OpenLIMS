from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("notebook", "0002_experimentreview_workflow_checksum_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name="ExperimentOnboarding",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ("experiment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="notebook.experiment")),
        ],
    )]
