import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_stamp_rally", "0002_stamp_attendee_snapshot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pretixbase", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StampRallyDraw",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("title", models.CharField(blank=True, default="", max_length=190, verbose_name="Prize")),
                (
                    "pool",
                    models.CharField(
                        choices=[
                            ("complete", "Complete (all active booths)"),
                            ("all", "Everyone who was scanned at least once"),
                            ("partial", "Partial — missing at least one booth"),
                        ],
                        max_length=16,
                        verbose_name="Who can win",
                    ),
                ),
                ("winner_count", models.PositiveIntegerField(verbose_name="Winners drawn")),
                ("pool_size", models.PositiveIntegerField(verbose_name="Tickets in the draw")),
                ("exclude_previous", models.BooleanField(default=True, verbose_name="Previous winners were skipped")),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stamp_rally_draws",
                        to="pretixbase.event",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stamp_rally_draws",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="StampRallyWinner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("place", models.PositiveIntegerField(verbose_name="Place")),
                ("attendee_name", models.CharField(blank=True, default="", max_length=255)),
                ("attendee_email", models.CharField(blank=True, default="", max_length=254)),
                ("order_code", models.CharField(blank=True, default="", max_length=16)),
                ("positionid", models.PositiveIntegerField(default=0)),
                ("booths_scanned", models.PositiveIntegerField(default=0)),
                ("booths_total", models.PositiveIntegerField(default=0)),
                (
                    "draw",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="winners",
                        to="pretix_stamp_rally.stamprallydraw",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stamp_rally_wins",
                        to="pretixbase.orderposition",
                    ),
                ),
            ],
            options={
                "ordering": ("place", "id"),
                "unique_together": {("draw", "place"), ("draw", "position")},
            },
        ),
    ]
