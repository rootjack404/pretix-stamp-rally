import json
from django.utils.translation import gettext_lazy as _
from pretix.base.shredder import BaseDataShredder
from pretix.helpers.json import CustomJSONEncoder

from .models import StampRallyDraw, StampRallyStamp, StampRallyWinner


class StampRallyShredder(BaseDataShredder):
    verbose_name = _("Stamp rally scans")
    identifier = "stamprally"
    description = _(
        "This will remove stamp rally scans and raffle results, including the attendee name and email stored with them."
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

        winners = StampRallyWinner.objects.filter(draw__event=self.event).select_related("draw")
        winner_data = [
            {
                "draw": winner.draw_id,
                "prize": winner.draw.title,
                "place": winner.place,
                "order": winner.order_code,
                "position": winner.positionid,
                "attendee_name": winner.attendee_name,
                "attendee_email": winner.attendee_email,
                "created": winner.draw.created.isoformat(),
            }
            for winner in winners
        ]
        yield "stamp-rally-raffle.json", "application/json", json.dumps(winner_data, cls=CustomJSONEncoder, indent=4)

    def shred_data(self, progress_callback=None):
        StampRallyStamp.objects.filter(booth__event=self.event).delete()
        StampRallyDraw.objects.filter(event=self.event).delete()
