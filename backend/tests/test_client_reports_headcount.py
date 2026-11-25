"""Zestawienie zaangażowania liczy osoby, nie kontrakty (audyt 24.11.2026, runda 4).

Dwa błędy: kolejny kontrakt tej samej osoby od 1. dnia miesiąca (zmiana stawki)
dawał „zakończyła” w poprzednim miesiącu i „weszła” w następnym, a linia
„Członkowie zespołu…” i arkusz „Według zamówień” liczyły kontrakty. Osoby,
numery i daty fikcyjne; bez bazy — odczyty generatora podmienione.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.client_reports.generators import headcount
from app.services.client_reports.generators.common import ContractInPeriod
from app.services.client_reports.generators.headcount import people_in_period
from app.services.client_reports.registry import ReportContext
from app.services.client_reports.schedule import Period

OCT = Period("2026-10", date(2026, 10, 1), date(2026, 10, 31), "październik 2026")
NOV = Period("2026-11", date(2026, 11, 1), date(2026, 11, 30), "listopad 2026")


def _row(
    contract_id: int,
    candidate_id: int,
    start: date,
    end: date | None,
    order: str | None = "ZAM/1",
) -> ContractInPeriod:
    return ContractInPeriod(
        contract_id=contract_id,
        person=f"Osoba {candidate_id}",
        start_date=start,
        end_date=end,
        role=None,
        project_name=None,
        order_number=order,
        rate_client=None,
        rate_client_currency=None,
        rate_unit=None,
        candidate_id=candidate_id,
    )


# Osoba 7: kontrakt do 31.10, kolejny (nowa stawka) od 1.11 — ciągłość.
OLD = _row(1, 7, date(2026, 3, 1), date(2026, 10, 31))
NEW = _row(2, 7, date(2026, 11, 1), None)


def test_rate_change_on_first_day_is_neither_end_nor_start() -> None:
    # Październik widzi tylko stary kontrakt; następca zaczyna się 1.11.
    assert people_in_period(
        [OLD], OCT.start, OCT.end, continues_after=frozenset({7})
    ) == (1, 0, 0)
    # Listopad widzi tylko nowy kontrakt; poprzednik skończył się 31.10.
    assert people_in_period(
        [NEW], NOV.start, NOV.end, continued_from=frozenset({7})
    ) == (1, 0, 0)


def test_real_gap_still_counts_as_start() -> None:
    # Poprzedni kontrakt skończył się 30.10 — dzień przerwy, więc to nie ciągłość
    # (zbiór z bazy pyta wyłącznie o koniec dokładnie dzień przed okresem).
    assert people_in_period([NEW], NOV.start, NOV.end) == (1, 1, 0)


def test_end_without_successor_is_an_end() -> None:
    assert people_in_period([OLD], OCT.start, OCT.end) == (1, 0, 1)


def _ctx(period: Period) -> ReportContext:
    return ReportContext(
        client_id=11,
        client_name="Klient testowy",
        period=period,
        params={},
        today=date(2026, 11, 24),
    )


@pytest.mark.asyncio
async def test_load_reads_neighbours_and_reports_continuity(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_rows(db, client_id, start, end):
        return [NEW]

    async def fake_neighbours(db, client_id, candidate_ids, start, end):
        calls.append((client_id, frozenset(candidate_ids), start, end))
        return frozenset({7}), frozenset()

    monkeypatch.setattr(headcount, "contracts_in_period", fake_rows)
    monkeypatch.setattr(headcount, "continuing_people", fake_neighbours)

    data = await headcount._load(object(), _ctx(NOV))

    assert calls == [(11, frozenset({7}), NOV.start, NOV.end)]
    lines = {line.label: line.value for line in data.lines}
    assert lines["weszli w okresie"] == "0"
    assert lines["zakończyli w okresie"] == "0"


@pytest.mark.asyncio
async def test_team_line_and_orders_sheet_count_people_not_contracts(
    monkeypatch,
) -> None:
    # 4 kontrakty, 3 osoby: osoba 1 zmieniła stawkę w połowie miesiąca
    # (dwa kontrakty pod tym samym zamówieniem).
    rows = [
        _row(1, 1, date(2026, 1, 1), date(2026, 11, 15), "ZAM/1"),
        _row(2, 1, date(2026, 11, 16), None, "ZAM/1"),
        _row(3, 2, date(2026, 2, 1), None, "ZAM/1"),
        _row(4, 3, date(2026, 5, 1), None, None),
    ]

    async def fake_rows(db, client_id, start, end):
        return rows

    async def fake_neighbours(db, client_id, candidate_ids, start, end):
        return frozenset(), frozenset()

    monkeypatch.setattr(headcount, "contracts_in_period", fake_rows)
    monkeypatch.setattr(headcount, "continuing_people", fake_neighbours)

    data = await headcount._load(object(), _ctx(NOV))

    lines = {line.label: line.value for line in data.lines}
    assert lines["Członkowie zespołu świadczący usługi w okresie"] == "3"
    # Linia o kontraktach zostaje o kontraktach.
    assert lines["kontrakty z numerem zamówienia"] == "3 z 4"
    summary, orders = data.sheets[:2]
    assert summary.rows[0][1] == 3
    assert dict(orders.rows) == {"ZAM/1": 2, headcount.NO_ORDER: 1}
    assert data.checks == (
        "1 os. bez numeru zamówienia w NEXUSIE — uzupełnij zamówienie albo wyślij z uwagą.",
    )
