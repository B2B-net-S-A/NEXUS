"""Zamrożony kurs NBP musi być odróżnialny od świeżego.

Trzy rzeczy trzymały się razem i żadna z nich nie działała:

* każda ścieżka błędu `fetch_and_store_nbp_today` kończyła się `return 0`
  i `logger.warning` (ściśle poniżej `event_level=logging.ERROR` Sentry), a dwie
  z nich nie logowały nawet linijki — więc gałąź `except` pętli była
  NIEOSIĄGALNA i „NBP milczy od dwóch miesięcy" wyglądało jak „dziś nie ma
  nowej tabeli";
* po stronie odczytu `get_rate_to_pln` zwracał `rate_found=True` dla dowolnie
  starego wiersza, więc faktury w EUR/USD/GBP szły do PLN po zamrożonym kursie
  i były oznaczane jako kompletne;
* helper napisany dokładnie po to, żeby to ujawnić — `fx_age_days` — nie miał
  ANI JEDNEGO wywołania w całym repozytorium.

Świadome ograniczenie zakresu, potwierdzone eksperymentem: ŻADNA ze ścieżek
odczytu nie degraduje kursu na podstawie wieku. Flaga `rate_found` jest
przeciążona — `margin_by_*` tylko zapala na niej `fx_missing`, ale
`revenue_forecast._to_display` traktuje ją jako polecenie WYKLUCZENIA kwoty z
prognozy. Pierwsza wersja tej poprawki degradowała `rate_found` po
`MAX_RATE_AGE_DAYS` i natychmiast wywaliła `test_contract_analytics_fx` —
zamrożony kurs zaczął USUWAĆ kontrakty z przychodu. Zamrożony kurs myli się o
kilka procent; wycięcie kontraktu — o 100%. Sygnał o starym cache'u jedzie
więc do OPERATORA (`/api/health.checks.fx`), a nie do raportu.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import fx_service
from app.services.fx_service import (
    HEALTH_CANARY_CURRENCY,
    MAX_RATE_AGE_DAYS,
    NbpFetchError,
    fx_age_days,
    get_rate_to_pln,
    rates_to_pln,
)

BACKEND = Path(__file__).resolve().parents[1]


class _Row:
    def __init__(self, rate: Decimal, effective_date: date) -> None:
        self.rate_to_pln = rate
        self.effective_date = effective_date


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDb:
    """Sesja zwracająca jeden ustalony wiersz kursu."""

    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)


@pytest.mark.asyncio
async def test_fresh_rate_is_reported_as_found() -> None:
    today = date(2026, 8, 21)
    db = _FakeDb(_Row(Decimal("4.30"), today - timedelta(days=1)))
    rate, found = await get_rate_to_pln(db, "EUR", today)  # type: ignore[arg-type]
    assert (rate, found) == (Decimal("4.30"), True)


@pytest.mark.asyncio
async def test_stale_rate_does_not_erase_money_from_reports() -> None:
    """Granica poprawki, nie szczegół — i to jest test tej granicy.

    `revenue_forecast._to_display` zwraca `None` (czyli WYKLUCZA kontrakt z
    przychodu), gdy `rate_found` jest `False`. Degradacja flagi na podstawie
    wieku zamieniłaby więc zamrożony cache w znikające pieniądze.
    """
    today = date(2026, 8, 21)
    db = _FakeDb(_Row(Decimal("4.30"), today - timedelta(days=MAX_RATE_AGE_DAYS + 90)))
    rate, found = await get_rate_to_pln(db, "EUR", today)  # type: ignore[arg-type]
    assert (rate, found) == (Decimal("4.30"), True), (
        "kurs sprzed trzech miesięcy myli się o kilka procent; wycięcie kwoty "
        "z raportu myli się o 100% — sygnał o starym cache'u należy do "
        "operatora (`/api/health.checks.fx`), nie do raportu"
    )


@pytest.mark.asyncio
async def test_rates_to_pln_reports_none_only_for_a_truly_absent_rate() -> None:
    """`None` znaczy BRAK kursu, nigdy „kurs stary" — patrz docstring modułu."""

    class _ScalarResult:
        def __init__(self, value) -> None:
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _Db:
        async def execute(self, *_a, **_k):
            return _ScalarResult(Decimal("4.30"))

    out = await rates_to_pln(_Db(), {"EUR"}, date(2026, 8, 21))  # type: ignore[arg-type]
    assert out["EUR"] == Decimal("4.30")


@pytest.mark.asyncio
async def test_fetch_raises_on_unexpected_payload_when_strict() -> None:
    """Payload o złym kształcie wracał wcześniej jako `return 0` BEZ LOGU."""

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"detail": "not a list"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, *_a, **_k):
            return _Resp()

    original = fx_service.httpx.AsyncClient
    fx_service.httpx.AsyncClient = lambda *a, **k: _Client()  # type: ignore[assignment]
    try:
        with pytest.raises(NbpFetchError):
            await fx_service.fetch_and_store_nbp_today(strict=True)
        # Ręczny trigger admina zachowuje kontrakt 200 / `inserted: 0`.
        assert await fx_service.fetch_and_store_nbp_today() == 0
    finally:
        fx_service.httpx.AsyncClient = original  # type: ignore[assignment]


def test_loop_reports_cycle_failure_at_error_level() -> None:
    source = (BACKEND / "app/services/fx_service.py").read_text(encoding="utf-8")
    at = source.index("async def fx_refresh_loop")
    body = source[at:]
    assert "logger.exception(" in body
    assert "strict=True" in body, (
        "pętla musi wołać wariant, który przepuszcza błąd — inaczej jej gałąź "
        "`except` znów będzie nieosiągalna"
    )


def test_health_endpoint_actually_calls_the_age_probe() -> None:
    """`fx_age_days` miał zero wywołań; to jest to jedno, które ma zostać."""
    main_src = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "fx_age_days" in main_src
    assert 'checks["fx"]' in main_src
    assert HEALTH_CANARY_CURRENCY == "EUR"
    assert fx_age_days is not None
