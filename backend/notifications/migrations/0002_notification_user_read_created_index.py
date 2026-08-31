from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["user", "is_read", "-created_at"],
                name="notif_user_read_created_idx",
            ),
        ),
    ]
