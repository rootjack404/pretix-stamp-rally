import json
from django.db import migrations, models


def _historical_name(position):
    cached = (position.attendee_name_cached or "").strip()
    if cached:
        return cached[:255]
    parts = position.attendee_name_parts or {}
    if isinstance(parts, str):
        try:
            parts = json.loads(parts)
        except ValueError:
            parts = {}
    full_name = (parts.get("full_name") or "").strip()
    if full_name:
        return full_name[:255]
    joined = " ".join(
        piece.strip()
        for piece in ((parts.get("given_name") or ""), (parts.get("family_name") or ""))
        if piece and piece.strip()
    )
    return joined[:255]


def fill_attendee_snapshots(apps, schema_editor):
    from django_scopes import scopes_disabled

    StampRallyStamp = apps.get_model("pretix_stamp_rally", "StampRallyStamp")
    with scopes_disabled():
        stamps = StampRallyStamp.objects.select_related("position", "position__order").iterator()
        for stamp in stamps:
            position = stamp.position
            name = _historical_name(position)
            email = (position.attendee_email or position.order.email or "").strip()[:254]
            order_code = (position.order.code or "")[:16]
            changed = []
            if name and not stamp.attendee_name:
                stamp.attendee_name = name
                changed.append("attendee_name")
            if email and not stamp.attendee_email:
                stamp.attendee_email = email
                changed.append("attendee_email")
            if order_code and not stamp.order_code:
                stamp.order_code = order_code
                changed.append("order_code")
            if changed:
                stamp.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_stamp_rally", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stamprallystamp",
            name="attendee_name",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Attendee name"),
        ),
        migrations.AddField(
            model_name="stamprallystamp",
            name="attendee_email",
            field=models.CharField(blank=True, default="", max_length=254, verbose_name="Attendee email"),
        ),
        migrations.AddField(
            model_name="stamprallystamp",
            name="order_code",
            field=models.CharField(blank=True, default="", max_length=16, verbose_name="Order code"),
        ),
        migrations.RunPython(fill_attendee_snapshots, migrations.RunPython.noop),
    ]
