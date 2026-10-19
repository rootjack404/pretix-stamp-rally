import json
from django.utils.translation import gettext_lazy as _
from pretix.base.shredder import BaseDataShredder
from pretix.helpers.json import CustomJSONEncoder

from .models import StampRallyStamp


class StampRallyShredder(BaseDataShredder):
    verbose_name = _("Stamp rally scans")
    identifier = "stamprally"
    description = _(
        "This will remove all stamp rally scans, including the attendee name and email recorded with each scan."
    )

    def generate_files(self):
        stamps = StampRallyStamp.objects.filter(booth__event=self.event).select_related(
            "booth", "position", "position__order"
        )
        data = [
            {
                "booth": s.booth.name,
                "order": s.order_code or s.position.order.code,
                "position": s.position.positionid,
                "attendee_name": s.attendee_name or s.position.attendee_name,
                "attendee_email": s.attendee_email or s.position.attendee_email or s.position.order.email,
                "datetime": s.datetime.isoformat(),
            }
            for s in stamps
        ]
        yield "stamp-rally.json", "application/json", json.dumps(data, cls=CustomJSONEncoder, indent=4)

    def shred_data(self, progress_callback=None):
        StampRallyStamp.objects.filter(booth__event=self.event).delete()
