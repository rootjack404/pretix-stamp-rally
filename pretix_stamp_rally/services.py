from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils.timezone import localtime
from django.utils.translation import gettext
from pretix.base.models import Order, OrderPosition

from .models import StampRallyBooth, StampRallyDraw, StampRallyStamp, StampRallyWinner

STATUS_OK = "ok"
STATUS_DUPLICATE = "duplicate"
STATUS_INVALID = "invalid"
STATUS_UNPAID = "unpaid"
STATUS_CANCELED = "canceled"
STATUS_INACTIVE = "inactive"

PARTICIPATION_ALL = "all"
PARTICIPATION_PARTIAL = "partial"
PARTICIPATION_COMPLETE = "complete"


@dataclass
class ScanResult:
    status: str
    message: str
    position: OrderPosition | None = None
    stamp: StampRallyStamp | None = None
    collected: int = 0
    required: int = 0
    complete: bool = False
    booth_name: str = ""

    @property
    def success(self):
        return self.status in (STATUS_OK, STATUS_DUPLICATE)


def normalize_ticket_code(raw):
    """Turn a scanned QR payload into a pretix ticket secret."""
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        path = urlparse(value).path.rstrip("/")
        if path:
            value = path.rsplit("/", 1)[-1]
    return value.replace(" ", "+")


def active_booths(event):
    return StampRallyBooth.objects.filter(event=event, active=True)


def required_stamp_count(event):
    active = active_booths(event).count()
    configured = event.settings.get("stamprally_required_count", as_type=int) or 0
    if configured <= 0:
        return active
    return min(int(configured), active)


def collected_stamp_count(position, event=None):
    qs = StampRallyStamp.objects.filter(position=position, booth__active=True)
    if event is not None:
        qs = qs.filter(booth__event=event)
    return qs.values("booth_id").distinct().count()


def is_complete(position, event):
    required = required_stamp_count(event)
    if required <= 0:
        return False
    return collected_stamp_count(position, event) >= required


def find_position(event, raw_code):
    secret = normalize_ticket_code(raw_code)
    if not secret:
        return None
    qs = OrderPosition.all.filter(order__event=event).select_related("order", "item", "addon_to")
    position = qs.filter(secret=secret).first()
    if position:
        return position
    # Scanning a parent ticket should stamp that attendee, not every add-on.
    return qs.filter(Q(addon_to__secret=secret) & Q(addon_to__isnull=False)).first()


def _ticket_blocked_reason(event, position):
    if position is None:
        return STATUS_INVALID, gettext("This is not a valid ticket for this event.")
    if position.canceled or position.order.status not in (Order.STATUS_PAID, Order.STATUS_PENDING):
        return STATUS_CANCELED, gettext("This ticket has been canceled.")
    require_paid = event.settings.get("stamprally_require_paid", as_type=bool)
    paid_ok = position.order.status == Order.STATUS_PAID or position.order.valid_if_pending
    if require_paid and not paid_ok:
        return STATUS_UNPAID, gettext("This ticket has not been paid.")
    return None, None


def progress_for(position, event):
    collected = collected_stamp_count(position, event)
    required = required_stamp_count(event)
    return collected, required, required > 0 and collected >= required


def attendee_snapshot(position):
    """Identity to keep with the scan, even if the order is edited later."""
    name = (position.attendee_name or "").strip()
    email = (position.attendee_email or position.order.email or "").strip()
    return {
        "attendee_name": name[:255],
        "attendee_email": email[:254],
        "order_code": (position.order.code or "")[:16],
    }


def _remember_attendee(stamp, position, created):
    snap = attendee_snapshot(position)
    if created:
        return stamp
    updates = {}
    for field, value in snap.items():
        if value and not getattr(stamp, field):
            updates[field] = value
            setattr(stamp, field, value)
    if updates:
        stamp.save(update_fields=list(updates))
    return stamp


def normalize_participation_filter(value):
    if value in (PARTICIPATION_PARTIAL, PARTICIPATION_COMPLETE):
        return value
    return PARTICIPATION_ALL


def recorded_attendee(position):
    """Name and email captured when the ticket was scanned, with a live fallback."""
    stamps = getattr(position, "active_stamps", None)
    if stamps is None:
        stamps = position.stamp_rally_stamps.all()
    name = ""
    email = ""
    order_code = ""
    for stamp in stamps:
        if not name and stamp.attendee_name:
            name = stamp.attendee_name
        if not email and stamp.attendee_email:
            email = stamp.attendee_email
        if not order_code and stamp.order_code:
            order_code = stamp.order_code
    if not name:
        name = position.attendee_name or ""
    if not email:
        email = position.attendee_email or position.order.email or ""
    if not order_code:
        order_code = position.order.code
    return {"name": name, "email": email, "order_code": order_code}


def describe_participation(position, booths):
    stamps = getattr(position, "active_stamps", None)
    if stamps is None:
        stamps = list(position.stamp_rally_stamps.filter(booth__active=True).select_related("booth"))
    by_booth = {stamp.booth_id: stamp for stamp in stamps}
    total = len(booths)
    collected = position.stamp_count if hasattr(position, "stamp_count") else len(by_booth)
    complete = total > 0 and collected >= total
    return {
        "identity": recorded_attendee(position),
        "collected": collected,
        "total": total,
        "complete": complete,
        "cells": [by_booth.get(booth.pk) for booth in booths],
    }


def format_scanned_at(stamp_time: datetime | None, tz):
    if stamp_time is None:
        return ""
    local = localtime(stamp_time, timezone=tz) if tz else localtime(stamp_time)
    return local.strftime("%Y-%m-%d %H:%M")


def collect_stamp(event, booth, raw_code):
    if not booth.active:
        return ScanResult(
            status=STATUS_INACTIVE,
            message=gettext("This booth is not active."),
            booth_name=str(booth.name),
        )

    position = find_position(event, raw_code)
    blocked, message = _ticket_blocked_reason(event, position)
    if blocked:
        return ScanResult(status=blocked, message=message, booth_name=str(booth.name))

    stamp, created = StampRallyStamp.objects.get_or_create(
        booth=booth,
        position=position,
        defaults=attendee_snapshot(position),
    )
    stamp = _remember_attendee(stamp, position, created)
    collected, required, complete = progress_for(position, event)
    if created:
        status = STATUS_OK
        message = gettext("Stamp collected: {booth}").format(booth=booth.name)
        if complete:
            message = gettext("Stamp rally complete! {collected}/{required} booths.").format(
                collected=collected, required=required
            )
    else:
        status = STATUS_DUPLICATE
        message = gettext("This attendee already has the stamp for {booth}.").format(booth=booth.name)

    return ScanResult(
        status=status,
        message=message,
        position=position,
        stamp=stamp,
        collected=collected,
        required=required,
        complete=complete,
        booth_name=str(booth.name),
    )


def attendee_label(position):
    return position.attendee_name or position.order.email or position.order.code


def progress_queryset(event):
    """Order positions scanned at least once at an active booth, with collected counts."""
    active_stamps = StampRallyStamp.objects.filter(booth__event=event, booth__active=True).select_related("booth")
    return (
        OrderPosition.objects.filter(
            order__event=event,
            stamp_rally_stamps__booth__event=event,
            stamp_rally_stamps__booth__active=True,
        )
        .select_related("order", "item")
        .prefetch_related(Prefetch("stamp_rally_stamps", queryset=active_stamps, to_attr="active_stamps"))
        .annotate(
            stamp_count=Count(
                "stamp_rally_stamps",
                filter=Q(stamp_rally_stamps__booth__active=True, stamp_rally_stamps__booth__event=event),
                distinct=True,
            )
        )
        .order_by("-stamp_count", "order__code", "positionid")
        .distinct()
    )


def filter_by_participation(queryset, event, status):
    """Keep everyone scanned, only partial visits, or only attendees scanned at every active booth."""
    status = normalize_participation_filter(status)
    if status == PARTICIPATION_ALL:
        return queryset
    total = active_booths(event).count()
    if total <= 0:
        return queryset.none()
    if status == PARTICIPATION_COMPLETE:
        return queryset.filter(stamp_count__gte=total)
    return queryset.filter(stamp_count__lt=total)


class RaffleError(Exception):
    pass


def eligible_queryset(event, pool, exclude_previous=False):
    queryset = filter_by_participation(progress_queryset(event), event, pool)
    if exclude_previous:
        already_won = StampRallyWinner.objects.filter(draw__event=event, position__isnull=False).values("position_id")
        queryset = queryset.exclude(pk__in=already_won)
    return queryset


def raffle_pool_counts(event):
    rows = []
    for key, label in (
        (PARTICIPATION_COMPLETE, gettext("Complete (all booths)")),
        (PARTICIPATION_PARTIAL, gettext("Partial")),
        (PARTICIPATION_ALL, gettext("All scanned")),
    ):
        rows.append(
            {
                "key": key,
                "label": label,
                "total": eligible_queryset(event, key, exclude_previous=False).count(),
                "available": eligible_queryset(event, key, exclude_previous=True).count(),
            }
        )
    return rows


def draw_raffle(event, *, pool, winner_count, exclude_previous, user, title="", rng=None):
    """Pick winners at random and store the result. Each ticket is one entry."""
    pool = normalize_participation_filter(pool)
    title = (title or "").strip()[:190]
    if winner_count < 1:
        raise RaffleError(gettext("Draw at least one winner."))

    booths = list(active_booths(event))
    with transaction.atomic():
        candidates = list(eligible_queryset(event, pool, exclude_previous=exclude_previous))
        if winner_count > len(candidates):
            raise RaffleError(
                gettext("Only {count} tickets can be drawn. Lower the number of winners.").format(count=len(candidates))
            )
        chosen = (rng or secrets.SystemRandom()).sample(candidates, winner_count)
        draw = StampRallyDraw.objects.create(
            event=event,
            user=user,
            title=title,
            pool=pool,
            winner_count=winner_count,
            pool_size=len(candidates),
            exclude_previous=exclude_previous,
        )
        logged_winners = []
        for place, position in enumerate(chosen, start=1):
            info = describe_participation(position, booths)
            identity = info["identity"]
            winner = StampRallyWinner.objects.create(
                draw=draw,
                position=position,
                place=place,
                attendee_name=(identity["name"] or attendee_label(position))[:255],
                attendee_email=(identity["email"] or "")[:254],
                order_code=(identity["order_code"] or "")[:16],
                positionid=position.positionid,
                booths_scanned=info["collected"],
                booths_total=info["total"],
            )
            logged_winners.append(
                {
                    "place": winner.place,
                    "order": winner.order_code,
                    "positionid": winner.positionid,
                    "name": winner.attendee_name,
                }
            )
    event.log_action(
        "pretix_stamp_rally.raffle.drawn",
        user=user,
        data={
            "draw": draw.pk,
            "title": draw.title,
            "pool": draw.pool,
            "pool_size": draw.pool_size,
            "winners": logged_winners,
        },
    )
    return draw


def ticket_line(order_code, positionid):
    code = order_code or ""
    if positionid:
        return f"{code}-{positionid}"
    return code


def raffle_face(position, booths):
    info = describe_participation(position, booths)
    identity = info["identity"]
    name = (identity["name"] or attendee_label(position) or "").strip()
    return {
        "name": name,
        "order": ticket_line(identity["order_code"] or position.order.code, position.positionid),
        "position": position.pk,
    }


def spin_raffle(event, *, pool, user, title=""):
    """Draw one winner and a reel that always stops on that winner."""
    pool = normalize_participation_filter(pool)
    booths = list(active_booths(event))
    candidates = list(eligible_queryset(event, pool, exclude_previous=True))
    if not candidates:
        raise RaffleError(gettext("Nobody is left to draw."))
    faces = [raffle_face(position, booths) for position in candidates]
    draw = draw_raffle(
        event,
        pool=pool,
        winner_count=1,
        exclude_previous=True,
        user=user,
        title=title,
    )
    winner = draw.winners.get()
    landing = {
        "name": winner.attendee_name,
        "order": ticket_line(winner.order_code, winner.positionid),
        "position": winner.position_id,
    }
    others = [face for face in faces if face["position"] != winner.position_id]
    secrets.SystemRandom().shuffle(others)
    reel = []
    if others:
        while len(reel) < 20:
            reel.extend(others)
        reel = reel[:20]
    else:
        reel = [landing for _ in range(8)]
    reel.append(landing)

    def public(face):
        return {"name": face["name"], "order": face["order"]}

    return {
        "draw": draw.pk,
        "title": draw.title,
        "winner": public(landing),
        "reel": [public(face) for face in reel],
        "remaining": eligible_queryset(event, pool, exclude_previous=True).count(),
    }


def void_raffle(draw, user):
    event = draw.event
    data = {
        "draw": draw.pk,
        "title": draw.title,
        "pool": draw.pool,
        "winners": [
            {"place": winner.place, "order": winner.order_code, "name": winner.attendee_name}
            for winner in draw.winners.all()
        ],
    }
    with transaction.atomic():
        draw.delete()
    event.log_action("pretix_stamp_rally.raffle.voided", user=user, data=data)


def participation_counts(event):
    queryset = progress_queryset(event)
    scanned = queryset.count()
    total = active_booths(event).count()
    if total <= 0:
        return {"scanned": scanned, "partial": 0, "complete": 0, "booths": 0}
    complete = queryset.filter(stamp_count__gte=total).count()
    return {
        "scanned": scanned,
        "partial": scanned - complete,
        "complete": complete,
        "booths": total,
    }
