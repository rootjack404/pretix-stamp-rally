from collections import OrderedDict
from django import forms
from django.utils.translation import gettext as _, gettext_lazy
from pretix.base.exporter import ListExporter

from .services import (
    PARTICIPATION_ALL,
    PARTICIPATION_COMPLETE,
    PARTICIPATION_PARTIAL,
    active_booths,
    describe_participation,
    filter_by_participation,
    format_scanned_at,
    normalize_participation_filter,
    progress_queryset,
)


class StampRallyListExporter(ListExporter):
    identifier = "stamprally"
    verbose_name = gettext_lazy("Stamp rally attendees")
    category = gettext_lazy("Check-in")
    description = gettext_lazy(
        "Export attendees who were scanned at stamp rally booths, including which booths they visited. "
        "Use the complete list as the raffle draw."
    )

    @property
    def additional_form_fields(self):
        return OrderedDict(
            [
                (
                    "status",
                    forms.ChoiceField(
                        label=gettext_lazy("Which attendees to export"),
                        choices=(
                            (PARTICIPATION_ALL, gettext_lazy("Everyone who was scanned at least once")),
                            (PARTICIPATION_PARTIAL, gettext_lazy("Partial — not scanned at every booth")),
                            (PARTICIPATION_COMPLETE, gettext_lazy("Complete — scanned at every active booth")),
                        ),
                        initial=PARTICIPATION_ALL,
                        required=True,
                    ),
                ),
            ]
        )

    def iterate_list(self, form_data):
        status = normalize_participation_filter((form_data or {}).get("status"))
        booths = list(active_booths(self.event))
        headers = [
            _("Order code"),
            _("Position"),
            _("Attendee name"),
            _("Attendee email"),
            _("Order email"),
            _("Product"),
            _("Booths scanned"),
            _("Active booths"),
            _("Raffle status"),
        ] + [str(booth.name) for booth in booths]
        yield headers

        queryset = filter_by_participation(progress_queryset(self.event), self.event, status)
        yield self.ProgressSetTotal(total=queryset.count())

        for position in queryset:
            info = describe_participation(position, booths)
            row = [
                info["identity"]["order_code"],
                position.positionid,
                info["identity"]["name"],
                info["identity"]["email"],
                position.order.email or "",
                str(position.item.name),
                info["collected"],
                info["total"],
                _("Complete") if info["complete"] else _("Partial"),
            ]
            for stamp in info["cells"]:
                row.append(format_scanned_at(stamp.datetime, self.timezone) if stamp else "")
            yield row

    def get_filename(self):
        return f"stamp-rally-{self.event.slug}"
