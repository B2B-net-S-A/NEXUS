"""Doba nie zmienia się w środku biegu testów.

16.09.2026 shard CI padł na `test_order_line_roster.py`, choć zmieniany PR nie
dotykał zamówień. Moduł liczy `_TODAY = business_today()` RAZ, przy imporcie,
a kod produkcyjny woła `business_today()` przy każdym wywołaniu; shard trwał
14m56s i przekroczył północ warszawską, więc wpis z końcem „dziś" stał się
wpisem z końcem „wczoraj".

28 modułów testowych liczy datę z zegara przy imporcie, a każdy kolejny
dopisany test wnosi ten sam błąd od nowa — dlatego naprawą jest przypięcie doby
w `conftest`, a nie poprawka w tamtych plikach. Ten plik pilnuje przypięcia.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine

from app.core.scheduling import DEFAULT_TZ, business_today
from tests import conftest

WARSAW = ZoneInfo(DEFAULT_TZ)

#: Stała liczona przy imporcie — dokładnie ten wzorzec, który się wywrócił.
_MODULE_TODAY = business_today()


def test_module_constant_matches_runtime_today():
    """Sedno sprawy: data z importu i data z wywołania to ten sam dzień.

    Bez przypięcia ta asercja jest prawdziwa przez ~23 godziny na dobę i fałszywa
    w oknie, w którym bieg przekracza północ — czyli test, który przechodzi
    zawsze poza tym jednym razem, kiedy ktoś patrzy.
    """
    assert _MODULE_TODAY == business_today()


class TestPinnedMoment:
    def test_same_day_is_a_no_op(self):
        """Przez większość doby przypięcie ma nie robić nic."""
        today = date(2026, 9, 16)
        assert conftest.pinned_moment(today, today) is None

    def test_after_midnight_pins_back_to_session_day(self):
        session_day = date(2026, 9, 16)
        pinned = conftest.pinned_moment(session_day, date(2026, 9, 17))
        assert pinned is not None
        assert pinned.date() == session_day
        assert pinned.tzinfo is not None

    def test_pins_as_close_to_midnight_as_possible(self):
        """Cofnięcie ma być najmniejsze z możliwych — z powodu zegara bazy.

        `occurred_at` i podobne znaczniki stawia Postgres (``server_default``),
        a jego zegara przypiąć się nie da. Każda minuta cofnięcia Pythona to
        minuta rozjazdu wobec wierszy; kod liczący okna („to samo zdarzenie
        w ciągu 10 minut") łamie się, gdy rozjazd przekroczy okno. Zmierzone na
        `test_client_deletion`: cofnięcie o godzinę wywraca dedup, o minuty nie.
        """
        pinned = conftest.pinned_moment(date(2026, 9, 16), date(2026, 9, 17))
        assert (pinned.hour, pinned.minute) == (23, 59)

    def test_pin_stays_inside_the_session_day(self):
        """Zegar pod przypięciem stoi (``tick=False``), więc nie przepełznie dalej.

        Przy 23:59 płynący zegar przekroczyłby północ po minucie — czyli zrobiłby
        dokładnie to, przed czym przypięcie broni.
        """
        pinned = conftest.pinned_moment(date(2026, 9, 16), date(2026, 9, 17))
        with time_machine.travel(pinned, tick=False):
            assert business_today() == date(2026, 9, 16)

    def test_pinning_survives_a_whole_day_of_drift(self):
        """Przypięcie działa niezależnie od tego, jak daleko odjechał zegar."""
        session_day = date(2026, 9, 16)
        for drift in (1, 2, 30):
            pinned = conftest.pinned_moment(
                session_day, session_day + timedelta(days=drift)
            )
            assert pinned.date() == session_day


class TestFixtureBehaviour:
    def test_fixture_is_autouse(self):
        """Ochrona ma obejmować każdy test, także dopisany jutro.

        Fixture wymagany jawnie chroniłby tylko tych, którzy o nim pamiętają —
        a to jest dokładnie ta pamięć, której zabrakło w 28 modułach.
        """
        fixture = conftest._pin_business_day
        # Nazwa atrybutu zmieniła się między wersjami pytesta
        # (`_pytestfixturefunction` → `_fixture_function_marker`), a ten test ma
        # pilnować autouse, nie wersji frameworka.
        marker = getattr(fixture, "_fixture_function_marker", None) or getattr(
            fixture, "_pytestfixturefunction", None
        )
        assert marker is not None, "fixture stracił znacznik pytesta"
        assert marker.autouse is True

    def test_production_today_follows_the_pin(self):
        """Wewnątrz przypięcia kod produkcyjny widzi dzień sesji, nie kalendarz.

        Odtwarza całą awarię: sesja wystartowała wczoraj, zegar jest już dziś,
        a `business_today()` — którego woła kod produkcyjny — ma mimo to zwrócić
        wczorajszy dzień, bo z niego pochodzą stałe modułów testowych.
        """
        yesterday = business_today() - timedelta(days=1)
        pinned = conftest.pinned_moment(yesterday, business_today())
        assert pinned is not None
        with time_machine.travel(pinned, tick=False):
            assert business_today() == yesterday

    def test_clock_is_released_after_the_pin(self):
        """Przypięcie nie może wyciec na kolejne testy."""
        before = business_today()
        pinned = datetime.combine(
            before - timedelta(days=3), time(12, 0), tzinfo=WARSAW
        )
        with time_machine.travel(pinned, tick=False):
            assert business_today() != before
        assert business_today() == before


@pytest.mark.parametrize("minutes_past_midnight", [1, 5, 59])
def test_probe_of_the_original_failure(minutes_past_midnight):
    """Oryginalna awaria: wpis kończący się „dziś" tuż po północy.

    `is_line_on_active_roster` porównuje datę końca z `business_today()`.
    Wpis zbudowany na dzień D wypada z obsady, gdy zegar pokaże D+1 — i to
    jest poprawne zachowanie produkcyjne. Chroni nas przypięcie doby, nie
    zmiana tej reguły.
    """
    from app.services.client_order_lines import is_line_on_active_roster

    day = business_today()
    just_after_midnight = datetime.combine(
        day + timedelta(days=1), time(0, minutes_past_midnight), tzinfo=WARSAW
    )

    from app.models.client_order import ClientOrder, ClientOrderStatus

    order = ClientOrder(status=ClientOrderStatus("active"), end_date=day)

    assert is_line_on_active_roster(order, None) is True
    with time_machine.travel(just_after_midnight, tick=False):
        assert is_line_on_active_roster(order, None) is False
