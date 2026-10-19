from pretix_stamp_rally.services import normalize_ticket_code, required_stamp_count


class DummySettings(dict):
    def get(self, key, as_type=None, default=None):
        value = super().get(key, 0 if default is None else default)
        if as_type is int:
            return int(value or 0)
        return value


class DummyBoothQS:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


class DummyEvent:
    def __init__(self, required, active):
        self.settings = DummySettings(stamprally_required_count=required)
        self._active = active

    def stamp_filter(self):
        return DummyBoothQS(self._active)


def test_normalize_strips_and_keeps_secret():
    assert normalize_ticket_code("  abcDEF123  ") == "abcDEF123"
    assert normalize_ticket_code("") == ""
    assert normalize_ticket_code(None) == ""


def test_normalize_extracts_secret_from_url():
    assert normalize_ticket_code("https://tickets.example/order/ABC/secretvalue/") == "secretvalue"
    assert normalize_ticket_code("https://example.com/foo+bar") == "foo+bar"


def test_normalize_turns_spaces_into_plus():
    assert normalize_ticket_code("abc def") == "abc+def"


def test_required_count_all_active_when_zero():
    from pretix_stamp_rally import services

    original = services.active_booths
    try:
        services.active_booths = lambda event: DummyBoothQS(5)
        event = DummyEvent(0, 5)
        assert required_stamp_count(event) == 5
    finally:
        services.active_booths = original


def test_required_count_caps_at_active_booths():
    from pretix_stamp_rally import services

    original = services.active_booths
    try:
        services.active_booths = lambda event: DummyBoothQS(3)
        event = DummyEvent(10, 3)
        assert required_stamp_count(event) == 3
        event = DummyEvent(2, 3)
        assert required_stamp_count(event) == 2
    finally:
        services.active_booths = original
