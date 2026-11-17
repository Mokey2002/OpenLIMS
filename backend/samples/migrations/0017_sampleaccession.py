from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0016_sample_form"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name="SampleAccession",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("label_verified_at", models.DateTimeField(blank=True, null=True)),
            ("label_verified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="verified_sample_labels", to=settings.AUTH_USER_MODEL)),
            ("receipt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="accession", to="samples.samplecustodyevent")),
            ("sample", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="accession", to="samples.sample")),
        ],
    )]
