import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("projects", "0003_projectpost"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="container",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="inventory.container",
            ),
        ),
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                (
                    "category",
                    models.CharField(
                        choices=[("REAGENT", "Reagent"), ("SUPPLY", "Supply")],
                        default="REAGENT",
                        max_length=32,
                    ),
                ),
                ("default_unit", models.CharField(default="unit", max_length=32)),
                (
                    "reorder_level",
                    models.DecimalField(decimal_places=4, default=0, max_digits=14),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="InventoryLot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("lot_code", models.CharField(max_length=64, unique=True)),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=14)),
                ("unit", models.CharField(max_length=32)),
                ("expiration_date", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("EXPIRED", "Expired"),
                            ("DEPLETED", "Depleted"),
                        ],
                        default="ACTIVE",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "container",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_lots",
                        to="inventory.container",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lots",
                        to="inventory.inventoryitem",
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_lots",
                        to="inventory.location",
                    ),
                ),
            ],
            options={"ordering": ["expiration_date", "lot_code"]},
        ),
        migrations.CreateModel(
            name="InventoryReservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=14)),
                ("unit", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("RELEASED", "Released"),
                            ("CONSUMED", "Consumed"),
                        ],
                        default="ACTIVE",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inventory_reservations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to="inventory.inventorylot",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_reservations",
                        to="projects.project",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="inventoryitem",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("code"),
                name="inventory_item_code_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventorylot",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gte", 0)),
                name="inventory_lot_quantity_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventorylot",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("lot_code"),
                name="inventory_lot_code_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventoryreservation",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gt", 0)),
                name="inventory_reservation_quantity_positive",
            ),
        ),
    ]
