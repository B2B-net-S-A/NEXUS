"""Raport „Marża per konsultant” z fakturami sprzed KSeF z archiwum eBI24 (24.11.2026).

Stawka rabatu w marży to stawka efektywna z obrotu roku od 1 stycznia. U klienta,
którego faktury za styczeń–marzec są tylko w archiwum eBI24, sam KSeF zaniżał
obrót o kwartał: stawka wychodziła za niska, raport ostrzegał o niepełnym roku,
a tempo roku liczył od pierwszej faktury z KSeF. Raport dolicza archiwum tym
samym ``annual_spend.archive_invoices`` co „Rabat od obrotu rocznego”. Świat
testu (klient, archiwum, KSeF, kurs) z ``test_client_reports_annual_spend_db``;
numery, kwoty, progi i kursy fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.services.client_reports.generators import annual_spend, margin_per_consultant
from app.services.client_reports.registry import format_amount
from app.services.client_reports.schedule import period_from_key
from tests.test_client_reports_annual_spend_db import (  # noqa: F401 — fikstura world
    SERVICE,
    FakeRates,
    _ctx,
    _invoice_json,
    _seed,
    world,
)

pytestmark = pytest.mark.asyncio

YEAR = period_from_key("annual", "2026")
TURNOVER = "Obrót 2026 do 24.11 (EUR)"
RATE = "Rabat roku (efektywny, od nadwyżki)"


def _lines(data) -> dict[str, str]:
    return {line.label: line.value for line in data.lines}


async def test_archive_gives_full_year_turnover_and_rate(world, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(annual_spend, "rates_to_pln_by_date", FakeRates())
    await _seed(world)
    try:
        async with AsyncSessionLocal() as db:
            data = await margin_per_consultant._load(db, _ctx(world, YEAR))
        lines = _lines(data)
        # I–III z archiwum po 200,00 EUR (luty w PLN po kursie), IV–X z KSeF po 80,00 EUR.
        assert lines[TURNOVER] == format_amount(Decimal("1160.00"))
        # Do 1000 po 1%, nadwyżka 160 po 2%: 13,20 z 1160 = 1,1379% (sam KSeF: 1%).
        assert lines[RATE] == "1,1379%"
        assert data.sheets[0].headers[4] == "Rate after FwC 1,1379%"
        # Rok pełny: bez ostrzeżenia i bez tempa roku.
        assert not [c for c in data.checks if "niepełny" in c or "W tempie" in c]
        assert (
            "Faktury sprzed KSeF z archiwum eBI24 w obrocie: 3 (miesiąc i kurs NBP "
            "z daty sprzedaży)." in data.checks
        )
        # Plik nieczytelny tym samym tekstem co w „Rabacie od obrotu rocznego”.
        assert [c for c in data.checks if "bez czytelnego pliku" in c] == [
            "Faktury sprzed KSeF bez czytelnego pliku w archiwum eBI24: 1 — nie weszły "
            "do obrotu, więc obrót jest zaniżony; sprawdź pliki archiwum przed wysłaniem."
        ]
    finally:
        await world.drop()


async def test_archive_from_march_flags_late_start(world, monkeypatch) -> None:  # noqa: F811
    """Archiwum od marca: rok dalej niepełny, tempo roku od pierwszej faktury z archiwum."""
    monkeypatch.setattr(annual_spend, "rates_to_pln_by_date", FakeRates())
    await world.client()
    await world.archive(
        "2026-03-31",
        _invoice_json([SERVICE]),
        number="A3/2026/UE",
        issue=date(2026, 4, 2),
    )
    for month in range(4, 11):
        await world.ksef(month)
    try:
        async with AsyncSessionLocal() as db:
            data = await margin_per_consultant._load(db, _ctx(world, YEAR))
        lines = _lines(data)
        assert lines[TURNOVER] == format_amount(Decimal("760.00"))
        assert lines[RATE] == "1%"
        assert [c for c in data.checks if "niepełny" in c] == [
            "Faktury z KSeF i archiwum eBI24 są w NEXUSIE od 31.03.2026 — obrót roku "
            "jest niepełny, a stawka rabatu może być za niska; uzupełnij pobranie "
            "z KSeF albo archiwum eBI24 przed wysłaniem."
        ]
        # 760,00 EUR w 239 dni od 31.03 do 24.11 = 1160,67 EUR w roku; od pierwszej
        # faktury z KSeF (03.05) wyszłoby więcej, bo z mniejszej liczby dni.
        assert (
            "W tempie z faktur obrót roku wyniesie ok. "
            f"{format_amount(Decimal('1160.67'))} EUR — rabat efektywny 1,1381%."
            in data.checks
        )
        assert not [c for c in data.checks if "bez czytelnego pliku" in c]
    finally:
        await world.drop()
