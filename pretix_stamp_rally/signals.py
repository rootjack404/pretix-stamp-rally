import copy
from django.dispatch import receiver
from django.template.loader import get_template
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    event_copy_data,
    logentry_display,
    register_data_exporters,
    register_data_shredders,
)
from pretix.control.signals import nav_event, order_info

from .exporters import StampRallyListExporter
from .models import StampRallyBooth
from .services import progress_for, required_stamp_count
from .shredders import StampRallyShredder


@receiver(nav_event, dispatch_uid="pretix_stamp_rally_nav")
def navbar_info(sender, request, **kwargs):
    url = resolve(request.path_info)
    can_settings = request.user.has_event_permission(
        request.organizer, request.event, "event.settings.general:write", request=request
    )
    can_read = request.user.has_event_permission(
        request.organizer, request.event, "event.orders:read", request=request
    )
    if not can_settings and not can_read:
        return []
    kw = {"event": request.event.slug, "organizer": request.organizer.slug}
    active = url.namespace == "plugins:pretix_stamp_rally"
    children = []
    if can_settings:
        children.append(
            {
                "label": _("Booths"),
                "url": reverse("plugins:pretix_stamp_rally:booths", kwargs=kw),
                "active": active and url.url_name in ("booths", "booth.add", "booth.edit", "booth.delete"),
            }
        )
        children.append(
            {
                "label": _("Settings"),
                "url": reverse("plugins:pretix_stamp_rally:settings", kwargs=kw),
                "active": active and url.url_name == "settings",
            }
        )
    if can_read:
        children.append(
            {
                "label": _("Progress"),
                "url": reverse("plugins:pretix_stamp_rally:progress", kwargs=kw),
                "active": active and url.url_name == "progress",
            }
        )
        children.append(
            {
                "label": _("Raffle"),
                "url": reverse("plugins:pretix_stamp_rally:raffle", kwargs=kw),
                "active": active and url.url_name in ("raffle", "raffle.stage", "raffle.spin", "raffle.void", "raffle.export"),
            }
        )
    return [
        {
            "label": _("Stamp rally"),
            "url": reverse(
                "plugins:pretix_stamp_rally:booths" if can_settings else "plugins:pretix_stamp_rally:progress",
                kwargs=kw,
            ),
            "active": active,
            "icon": "flag",
            "children": children,
        }
    ]


@receiver(order_info, dispatch_uid="pretix_stamp_rally_order_info")
def control_order_info(sender, request, order, **kwargs):
    if not sender.settings.get("stamprally_show_progress", as_type=bool):
        return ""
    booths = list(sender.stamp_rally_booths.filter(active=True))
    if not booths:
        return ""
    required = required_stamp_count(sender)
    rows = []
    for position in order.positions.filter(canceled=False).select_related("item").prefetch_related("stamp_rally_stamps"):
        stamped_ids = {s.booth_id for s in position.stamp_rally_stamps.all()}
        collected, _, complete = progress_for(position, sender)
        rows.append(
            {
                "position": position,
                "collected": collected,
                "required": required,
                "complete": complete,
                "booths": [(booth, booth.pk in stamped_ids) for booth in booths],
            }
        )
    template = get_template("pretix_stamp_rally/order_info.html")
    return template.render({"rows": rows, "required": required, "request": request})


@receiver(logentry_display, dispatch_uid="pretix_stamp_rally_logentry_display")
def pretix_stamp_rally_logentry_display(sender, logentry, **kwargs):
    plains = {
        "pretix_stamp_rally.booth.added": _("A stamp rally booth was created."),
        "pretix_stamp_rally.booth.changed": _("A stamp rally booth was changed."),
        "pretix_stamp_rally.booth.deleted": _("A stamp rally booth was deleted."),
        "pretix_stamp_rally.booth.token_reset": _("A stamp rally scanner link was reset."),
        "pretix_stamp_rally.stamp.added": _("A stamp rally stamp was collected."),
        "pretix_stamp_rally.raffle.drawn": _("A stamp rally raffle was drawn."),
        "pretix_stamp_rally.raffle.voided": _("A stamp rally raffle draw was voided."),
    }
    return plains.get(logentry.action_type)


@receiver(event_copy_data, dispatch_uid="pretix_stamp_rally_copy_data")
def copy_booths(sender, other, **kwargs):
    if sender.stamp_rally_booths.exists():
        return
    for booth in other.stamp_rally_booths.all():
        new_booth = copy.copy(booth)
        new_booth.pk = None
        new_booth.event = sender
        new_booth.scan_token = StampRallyBooth._meta.get_field("scan_token").get_default()
        new_booth.save()


@receiver(register_data_exporters, dispatch_uid="pretix_stamp_rally_export")
def register_exporter(sender, **kwargs):
    return StampRallyListExporter


@receiver(register_data_shredders, dispatch_uid="pretix_stamp_rally_shredder")
def register_shredder(sender, **kwargs):
    return StampRallyShredder
