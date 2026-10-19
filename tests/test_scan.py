import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils.timezone import now
from django.utils.translation import override
from django_scopes import scope
from pretix.base.models import Event, Order, OrderPosition, Organizer

from pretix_stamp_rally.exporters import StampRallyListExporter
from pretix_stamp_rally.models import StampRallyBooth, StampRallyStamp
from pretix_stamp_rally.services import (
    STATUS_CANCELED,
    STATUS_DUPLICATE,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_UNPAID,
    collect_stamp,
    filter_by_participation,
    is_complete,
    participation_counts,
    progress_queryset,
)


@pytest.fixture
def event():
    organizer = Organizer.objects.create(name="Dummy", slug="dummy-stamp-rally")
    event = Event.objects.create(
        organizer=organizer,
        name="Dummy",
        slug="dummy-stamp-rally",
        date_from=now(),
        plugins="pretix_stamp_rally",
    )
    event.settings.timezone = "Europe/Berlin"
    event.settings.set("stamprally_required_count", 0)
    event.settings.set("stamprally_require_paid", True)
    with scope(organizer=organizer):
        yield event


@pytest.fixture
def item(event):
    return event.items.create(name="Ticket", default_price=3, admission=True)


@pytest.fixture
def position(event, item):
    order = Order.objects.create(
        code="RALLY",
        event=event,
        email="dummy@dummy.test",
        status=Order.STATUS_PAID,
        locale="en",
        datetime=now() - timedelta(days=1),
        expires=now() + timedelta(days=10),
        total=Decimal("23.00"),
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )
    return OrderPosition.objects.create(
        order=order,
        item=item,
        variation=None,
        price=Decimal("23.00"),
        attendee_name_parts={"full_name": "Aiko"},
        positionid=1,
        secret="ticketsecret123",
    )


@pytest.fixture
def booths(event):
    return [
        StampRallyBooth.objects.create(event=event, name="Stage", position=1),
        StampRallyBooth.objects.create(event=event, name="Food", position=2),
        StampRallyBooth.objects.create(event=event, name="Shop", position=3),
    ]


@pytest.mark.django_db
def test_scan_collects_stamp(event, position, booths):
    result = collect_stamp(event, booths[0], position.secret)
    assert result.status == STATUS_OK
    assert result.collected == 1
    assert StampRallyStamp.objects.filter(position=position, booth=booths[0]).exists()


@pytest.mark.django_db
def test_rescan_same_booth_is_duplicate(event, position, booths):
    collect_stamp(event, booths[0], position.secret)
    result = collect_stamp(event, booths[0], position.secret)
    assert result.status == STATUS_DUPLICATE
    assert StampRallyStamp.objects.filter(position=position).count() == 1


@pytest.mark.django_db
def test_complete_after_all_booths(event, position, booths):
    for booth in booths:
        result = collect_stamp(event, booth, position.secret)
    assert result.status == STATUS_OK
    assert result.complete
    assert result.collected == 3
    assert is_complete(position, event)


@pytest.mark.django_db
def test_complete_after_required_subset(event, position, booths):
    event.settings.set("stamprally_required_count", 2)
    collect_stamp(event, booths[0], position.secret)
    result = collect_stamp(event, booths[1], position.secret)
    assert result.complete
    assert result.collected == 2


@pytest.mark.django_db
def test_unknown_ticket_is_invalid(event, booths):
    result = collect_stamp(event, booths[0], "does-not-exist")
    assert result.status == STATUS_INVALID
    assert StampRallyStamp.objects.count() == 0


@pytest.mark.django_db
def test_unpaid_ticket_rejected(event, position, booths):
    position.order.status = Order.STATUS_PENDING
    position.order.valid_if_pending = False
    position.order.save()
    result = collect_stamp(event, booths[0], position.secret)
    assert result.status == STATUS_UNPAID


@pytest.mark.django_db
def test_canceled_ticket_rejected(event, position, booths):
    position.canceled = True
    position.save()
    result = collect_stamp(event, booths[0], position.secret)
    assert result.status == STATUS_CANCELED


@pytest.mark.django_db
def test_url_payload_still_finds_ticket(event, position, booths):
    result = collect_stamp(event, booths[0], f"https://tickets.example/t/{position.secret}")
    assert result.status == STATUS_OK


def _another_position(event, item, code, secret, name, email):
    order = Order.objects.create(
        code=code,
        event=event,
        email=email,
        status=Order.STATUS_PAID,
        locale="en",
        datetime=now() - timedelta(days=1),
        expires=now() + timedelta(days=10),
        total=Decimal("23.00"),
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
    )
    return OrderPosition.objects.create(
        order=order,
        item=item,
        variation=None,
        price=Decimal("23.00"),
        attendee_name_parts={"full_name": name},
        attendee_email=email,
        positionid=1,
        secret=secret,
    )


def _export_rows(event, status):
    exporter = StampRallyListExporter(event, event.organizer)
    rows = []
    with override("en"):
        for row in exporter.iterate_list({"status": status}):
            if isinstance(row, exporter.ProgressSetTotal):
                continue
            rows.append(row)
    header, *body = rows
    return [dict(zip(header, row)) for row in body]


@pytest.mark.django_db
def test_scan_records_attendee_for_raffle(event, position, booths):
    position.attendee_email = "aiko@example.test"
    position.save()
    result = collect_stamp(event, booths[0], position.secret)
    stamp = StampRallyStamp.objects.get(pk=result.stamp.pk)
    assert stamp.attendee_name == "Aiko"
    assert stamp.attendee_email == "aiko@example.test"
    assert stamp.order_code == "RALLY"


@pytest.mark.django_db
def test_later_scan_fills_missing_attendee_but_keeps_recorded_name(event, position, booths):
    position.attendee_name_parts = {}
    position.attendee_email = ""
    position.save()
    first = collect_stamp(event, booths[0], position.secret)
    assert first.stamp.attendee_name == ""
    assert first.stamp.attendee_email == "dummy@dummy.test"

    position.attendee_name_parts = {"full_name": "Aiko Updated"}
    position.attendee_email = "new@example.test"
    position.save()
    collect_stamp(event, booths[0], position.secret)
    stamp = StampRallyStamp.objects.get(pk=first.stamp.pk)
    assert stamp.attendee_name == "Aiko Updated"
    assert stamp.attendee_email == "dummy@dummy.test"


@pytest.mark.django_db
def test_partial_and_complete_filters(event, item, position, booths):
    position.attendee_email = "aiko@example.test"
    position.save()
    other = _another_position(event, item, "PART1", "partialsecret", "Ken", "ken@example.test")
    for booth in booths:
        collect_stamp(event, booth, position.secret)
    collect_stamp(event, booths[0], other.secret)

    counts = participation_counts(event)
    assert counts == {"scanned": 2, "partial": 1, "complete": 1, "booths": 3}

    partial = list(filter_by_participation(progress_queryset(event), event, "partial"))
    complete = list(filter_by_participation(progress_queryset(event), event, "complete"))
    assert [entry.pk for entry in partial] == [other.pk]
    assert [entry.pk for entry in complete] == [position.pk]

    partial_rows = _export_rows(event, "partial")
    complete_rows = _export_rows(event, "complete")
    assert len(partial_rows) == 1
    assert partial_rows[0]["Attendee name"] == "Ken"
    assert partial_rows[0]["Attendee email"] == "ken@example.test"
    assert partial_rows[0]["Raffle status"] == "Partial"
    assert partial_rows[0]["Stage"]
    assert partial_rows[0]["Food"] == ""
    assert partial_rows[0]["Shop"] == ""

    assert len(complete_rows) == 1
    assert complete_rows[0]["Attendee name"] == "Aiko"
    assert complete_rows[0]["Attendee email"] == "aiko@example.test"
    assert complete_rows[0]["Order code"] == "RALLY"
    assert complete_rows[0]["Raffle status"] == "Complete"
    assert complete_rows[0]["Stage"]
    assert complete_rows[0]["Food"]
    assert complete_rows[0]["Shop"]


@pytest.mark.django_db
def test_inactive_booth_does_not_count(event, position, booths):
    booths[2].active = False
    booths[2].save()
    collect_stamp(event, booths[0], position.secret)
    collect_stamp(event, booths[1], position.secret)
    assert is_complete(position, event)
    result = collect_stamp(event, booths[2], position.secret)
    assert result.status == "inactive"
