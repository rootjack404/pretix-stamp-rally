import django.db.models.deletion
import pretix.base.models.base
from django.db import migrations, models

import pretix_stamp_rally.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("pretixbase", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StampRallyBooth",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=190, verbose_name="Booth name")),
                (
                    "description",
                    models.TextField(
                        blank=True,
                        help_text="Shown to booth staff on the scanner page.",
                        verbose_name="Description",
                    ),
                ),
                ("position", models.PositiveIntegerField(default=0, verbose_name="Sort order")),
                (
                    "active",
                    models.BooleanField(
                        default=True,
                        help_text="Inactive booths cannot be scanned and do not count toward completion.",
                        verbose_name="Active",
                    ),
                ),
                (
                    "scan_token",
                    models.CharField(
                        default=pretix_stamp_rally.models.generate_scan_token,
                        max_length=64,
                        unique=True,
                        verbose_name="Scanner token",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stamp_rally_booths",
                        to="pretixbase.event",
                    ),
                ),
            ],
            options={
                "ordering": ("position", "id"),
            },
            bases=(models.Model, pretix.base.models.base.LoggingMixin),
        ),
        migrations.CreateModel(
            name="StampRallyStamp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("datetime", models.DateTimeField(auto_now_add=True)),
                (
                    "booth",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stamps",
                        to="pretix_stamp_rally.stamprallybooth",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stamp_rally_stamps",
                        to="pretixbase.orderposition",
                    ),
                ),
            ],
            options={
                "ordering": ("datetime",),
                "unique_together": {("booth", "position")},
            },
        ),
        migrations.AddIndex(
            model_name="stamprallystamp",
            index=models.Index(fields=["position"], name="pretix_stam_positio_7f3a1c_idx"),
        ),
    ]
