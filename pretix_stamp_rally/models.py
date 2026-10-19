import string
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from pretix.base.models import LoggedModel


def generate_scan_token():
    return get_random_string(40, allowed_chars=string.ascii_letters + string.digits)


class StampRallyBooth(LoggedModel):
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="stamp_rally_booths",
    )
    name = models.CharField(max_length=190, verbose_name=_("Booth name"))
    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
        help_text=_("Shown to booth staff on the scanner page."),
    )
    position = models.PositiveIntegerField(default=0, verbose_name=_("Sort order"))
    active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("Inactive booths cannot be scanned and do not count toward completion."),
    )
    scan_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_scan_token,
        verbose_name=_("Scanner token"),
    )

    class Meta:
        ordering = ("position", "id")

    def __str__(self):
        return str(self.name)

    def regenerate_token(self):
        self.scan_token = generate_scan_token()
        self.save(update_fields=["scan_token"])


class StampRallyStamp(models.Model):
    booth = models.ForeignKey(
        StampRallyBooth,
        on_delete=models.CASCADE,
        related_name="stamps",
    )
    position = models.ForeignKey(
        "pretixbase.OrderPosition",
        on_delete=models.CASCADE,
        related_name="stamp_rally_stamps",
    )
    datetime = models.DateTimeField(auto_now_add=True)
    attendee_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Attendee name"),
    )
    attendee_email = models.CharField(
        max_length=254,
        blank=True,
        default="",
        verbose_name=_("Attendee email"),
    )
    order_code = models.CharField(
        max_length=16,
        blank=True,
        default="",
        verbose_name=_("Order code"),
    )

    class Meta:
        ordering = ("datetime",)
        unique_together = (("booth", "position"),)
        indexes = [
            models.Index(fields=["position"]),
        ]

    def __str__(self):
        return f"{self.booth_id}:{self.position_id}"
