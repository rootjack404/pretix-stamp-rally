import pytest
from datetime import timedelta
from decimal import Decimal
from django.test import Client
from django.utils.timezone import now
from django_scopes import scope
from pretix.base.models import Event, Order, OrderPosition, Organizer, Team, User

from pretix_stamp_rally.models import StampRallyBooth, StampRallyDraw, StampRallyWinner
from pretix_stamp_rally.services import (
    PARTICIPATION_COMPLETE,
    RaffleError,
    collect_stamp,
    draw_raffle,
    eligible_queryset,
    spin_raffle,
    void_raffle,
)


@pytest.fixture
def event():
    organizer = Organizer.objects.create(name="Raffle", slug="dummy-raffle")
    event = Event.objects.create(
        organizer=organizer,
        name="Raffle",
        slug="dummy-raffle",
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
def booths(event):
    return [
        StampRallyBooth.objects.create(event=event, name="Stage", position=1),
        StampRallyBooth.objects.create(event=event, name="Food", position=2),
    ]


def _position(event, item, code, secret, name, email):
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


@pytest.mark.django_db
def test_draw_uses_only_completed_tickets_and_stores_attendee(event, item, booths):
    finished = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    partial = _position(event, item, "PART1", "part-secret", "Ken", "ken@example.test")
    for booth in booths:
        collect_stamp(event, booth, finished.secret)
    collect_stamp(event, booths[0], partial.secret)

    draw = draw_raffle(
        event,
        pool=PARTICIPATION_COMPLETE,
        winner_count=1,
        exclude_previous=True,
        user=None,
        title="Main prize",
    )
    winner = StampRallyWinner.objects.get(draw=draw)
    assert winner.position_id == finished.pk
    assert winner.place == 1
    assert winner.attendee_name == "Aiko"
    assert winner.attendee_email == "aiko@example.test"
    assert winner.order_code == "DONE1"
    assert winner.booths_scanned == 2
    assert draw.pool_size == 1
    assert draw.title == "Main prize"


@pytest.mark.django_db
def test_draw_refuses_more_winners_than_the_pool(event, item, booths):
    position = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    for booth in booths:
        collect_stamp(event, booth, position.secret)
    with pytest.raises(RaffleError):
        draw_raffle(event, pool=PARTICIPATION_COMPLETE, winner_count=2, exclude_previous=True, user=None)
    assert StampRallyDraw.objects.count() == 0


@pytest.mark.django_db
def test_second_draw_skips_previous_winners_until_voided(event, item, booths):
    first = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    second = _position(event, item, "DONE2", "done-secret-2", "Ken", "ken@example.test")
    for position in (first, second):
        for booth in booths:
            collect_stamp(event, booth, position.secret)

    opening = draw_raffle(event, pool=PARTICIPATION_COMPLETE, winner_count=1, exclude_previous=True, user=None)
    again = draw_raffle(event, pool=PARTICIPATION_COMPLETE, winner_count=1, exclude_previous=True, user=None)
    won = {opening.winners.get().position_id, again.winners.get().position_id}
    assert won == {first.pk, second.pk}

    with pytest.raises(RaffleError):
        draw_raffle(event, pool=PARTICIPATION_COMPLETE, winner_count=1, exclude_previous=True, user=None)

    voided_position_id = opening.winners.get().position_id
    void_raffle(opening, user=None)
    assert eligible_queryset(event, PARTICIPATION_COMPLETE, exclude_previous=True).count() == 1
    redraw = draw_raffle(event, pool=PARTICIPATION_COMPLETE, winner_count=1, exclude_previous=True, user=None)
    assert redraw.winners.get().position_id == voided_position_id
    assert redraw.winners.get().position_id != again.winners.get().position_id


@pytest.mark.django_db
def test_raffle_page_draws_and_downloads_winners(event, item, booths):
    position = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    for booth in booths:
        collect_stamp(event, booth, position.secret)
    user = User.objects.create_user("raffle@example.test", "dummy")
    team = Team.objects.create(
        organizer=event.organizer,
        name="Admins",
        all_events=True,
        all_event_permissions=True,
    )
    team.members.add(user)
    client = Client()
    assert client.login(email="raffle@example.test", password="dummy")
    url = f"/control/event/{event.organizer.slug}/{event.slug}/stamp-rally/raffle/"
    response = client.post(
        url,
        {"title": "Main prize", "pool": "complete", "winner_count": "1", "exclude_previous": "on"},
    )
    assert response.status_code == 302
    page = client.get(url)
    assert page.status_code == 200
    html = page.content.decode()
    assert "Aiko" in html
    assert "Main prize" in html
    draw = StampRallyDraw.objects.get()
    export = client.get(f"/control/event/{event.organizer.slug}/{event.slug}/stamp-rally/raffle/{draw.pk}/export/")
    assert export.status_code == 200
    body = export.content.decode()
    assert "Aiko" in body
    assert "aiko@example.test" in body
    assert "DONE1" in body


@pytest.mark.django_db
def test_slot_spin_stops_on_name_and_order_code(event, item, booths):
    finished = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    partial = _position(event, item, "PART1", "part-secret", "Ken", "ken@example.test")
    for booth in booths:
        collect_stamp(event, booth, finished.secret)
    collect_stamp(event, booths[0], partial.secret)

    result = spin_raffle(event, pool=PARTICIPATION_COMPLETE, user=None, title="Show prize")
    assert result["winner"] == {"name": "Aiko", "order": "DONE1-1"}
    assert result["reel"][-1] == result["winner"]
    assert all(face["name"] != "Ken" for face in result["reel"])
    assert "aiko@example.test" not in str(result)
    assert result["remaining"] == 0

    with pytest.raises(RaffleError):
        spin_raffle(event, pool=PARTICIPATION_COMPLETE, user=None, title="Show prize")


@pytest.mark.django_db
def test_slot_page_and_spin_api(event, item, booths):
    position = _position(event, item, "DONE1", "done-secret", "Aiko", "aiko@example.test")
    other = _position(event, item, "DONE2", "done-secret-2", "Ken", "ken@example.test")
    for person in (position, other):
        for booth in booths:
            collect_stamp(event, booth, person.secret)
    user = User.objects.create_user("stage@example.test", "dummy")
    team = Team.objects.create(
        organizer=event.organizer,
        name="Stage",
        all_events=True,
        all_event_permissions=True,
    )
    team.members.add(user)
    client = Client()
    assert client.login(email="stage@example.test", password="dummy")
    page_url = f"/control/event/{event.organizer.slug}/{event.slug}/stamp-rally/raffle/stage/"
    page = client.get(page_url)
    assert page.status_code == 200
    html = page.content.decode()
    assert 'id="spin-btn"' in html
    assert 'id="reel"' in html
    assert "Press spin" in html
    spin_url = f"/control/event/{event.organizer.slug}/{event.slug}/stamp-rally/raffle/spin/"
    spun = client.post(spin_url, data='{"pool": "complete", "title": "Show"}', content_type="application/json")
    assert spun.status_code == 200
    payload = spun.json()
    assert payload["status"] == "ok"
    assert payload["reel"][-1] == payload["winner"]
    assert payload["winner"]["order"] in ("DONE1-1", "DONE2-1")
    assert payload["winner"]["name"] in ("Aiko", "Ken")
