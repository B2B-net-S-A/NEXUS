"""Opisy celów Delivery Leada mówią o tym, co naprawdę liczy mianownik.

Runda 6 audytu: notatka pod celem placementów brzmiała „Nowe requesty
w kwartale”, a liczba pod nią to rekrutacje ZAMKNIĘTE w kwartale — mianownik
hit ratio ligi DL (`competitions.dl_portfolio_counts`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import competitions, kpi_goals


@pytest.mark.asyncio
async def test_dl_goal_notes_describe_closed_recruitments(monkeypatch):
    async def fake_counts(db, *, start, end):
        return {7: 1}, {7: 4}

    monkeypatch.setattr(competitions, "dl_portfolio_counts", fake_counts)
    result = await kpi_goals._delivery_lead_goals(
        None, user=SimpleNamespace(id=7), now=datetime(2026, 9, 10, tzinfo=timezone.utc)
    )
    notes = {g.goal_id: g.note for g in result.goals}
    assert notes["dl_placements_quarter"] == "Rekrutacje zamknięte w kwartale: 4"
    assert "requesty" not in notes["dl_placements_quarter"].lower()


@pytest.mark.asyncio
async def test_dl_hit_ratio_without_closed_recruitments_says_so(monkeypatch):
    async def fake_counts(db, *, start, end):
        return {}, {}

    monkeypatch.setattr(competitions, "dl_portfolio_counts", fake_counts)
    result = await kpi_goals._delivery_lead_goals(
        None, user=SimpleNamespace(id=7), now=datetime(2026, 9, 10, tzinfo=timezone.utc)
    )
    note = {g.goal_id: g.note for g in result.goals}["dl_hit_ratio_quarter"]
    assert note is not None
    assert "zamknięto" in note
    assert "nowych requestów" not in note
