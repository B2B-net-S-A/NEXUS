"""Co pod blokadą wiersza NADAL unieważnia dopasowanie importu MD — a co nie.

Do 09.2026 bramką było „linia musi być ``active``". Wynikało z niej, że
konsultant, który zszedł z zamówienia, przestawał przyjmować rozliczenie za
miesiąc, w którym jeszcze pracował — a raport z Finansów za sierpień wpływa
do systemu w połowie września. Regułą jest teraz OKRES
(``line_settles_in_month``): linia rozlicza miesiąc, jeśli go obsadzała.

Bramka pod blokadą nie znika — zmienia pytanie. Nadal unieważnia dopasowanie
policzone przed blokadą, gdy w międzyczasie linia została ANULOWANA albo
przeniesiona do innej grupy.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import md_consumption
from app.models.client_order import ClientOrderStatus
from app.models.contract import ContractStatus


def _contract(status=ContractStatus.active) -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _locked(
    *,
    status,
    group,
    start_date=date(2026, 1, 1),
    end_date=None,
    contract=None,
    group_id=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=73,
        order_group_id=group.id if group_id is None else group_id,
        order_group=group,
        status=status,
        start_date=start_date,
        end_date=end_date,
        contract=contract if contract is not None else _contract(),
    )


async def _apply(db, *, group, match_order) -> None:
    await md_consumption._apply_to_line(
        db,
        match_order=match_order,
        group=group,
        period_month="2026-08",
        md_reported=5,
        import_id=9,
        user_id=11,
    )


@pytest.mark.asyncio
async def test_a_line_ended_after_the_reported_month_still_takes_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sedno ticketu: zejście z zamówienia nie unieważnia zaległego raportu."""
    group = SimpleNamespace(id=41)
    matched = SimpleNamespace(id=73, order_group_id=group.id)
    locked = _locked(
        status=ClientOrderStatus.completed,
        group=group,
        end_date=date(2026, 8, 31),
        contract=_contract(ContractStatus.ended),
    )
    group.order_number = "CeZ/242/2025"
    locked.md_remaining = 331
    db = SimpleNamespace(scalar=AsyncMock(return_value=locked))
    apply = AsyncMock(
        return_value=SimpleNamespace(applied=5, previous=0, transferred=0)
    )
    monkeypatch.setattr(md_consumption, "apply_md_consumption", apply)
    monkeypatch.setattr(md_consumption, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(md_consumption, "describe_import", lambda *a, **k: "")

    await _apply(db, group=group, match_order=matched)

    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_cancelled_line_is_still_rejected_after_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anulowana linia znaczy „tej osoby tu nie było" — zużycia nie przyjmuje."""
    group = SimpleNamespace(id=41)
    matched = SimpleNamespace(id=73, order_group_id=group.id)
    locked = _locked(status=ClientOrderStatus.cancelled, group=group)
    db = SimpleNamespace(scalar=AsyncMock(return_value=locked))
    apply = AsyncMock()
    monkeypatch.setattr(md_consumption, "apply_md_consumption", apply)

    with pytest.raises(HTTPException) as exc:
        await _apply(db, group=group, match_order=matched)

    assert exc.value.status_code == 409
    assert "Obsada zamówienia zmieniła się" in exc.value.detail
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_line_whose_period_ends_before_the_month_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Okres jest granicą: lipcowa linia nie rozlicza sierpnia."""
    group = SimpleNamespace(id=41)
    matched = SimpleNamespace(id=73, order_group_id=group.id)
    locked = _locked(
        status=ClientOrderStatus.completed, group=group, end_date=date(2026, 7, 31)
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=locked))
    apply = AsyncMock()
    monkeypatch.setattr(md_consumption, "apply_md_consumption", apply)

    with pytest.raises(HTTPException) as exc:
        await _apply(db, group=group, match_order=matched)

    assert exc.value.status_code == 409
    apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_line_moved_to_another_group_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ostatnim sitem pod blokadą jest niezmienność grupy, nie status."""
    group = SimpleNamespace(id=41)
    matched = SimpleNamespace(id=73, order_group_id=group.id)
    locked = _locked(status=ClientOrderStatus.active, group=group, group_id=999)
    db = SimpleNamespace(scalar=AsyncMock(return_value=locked))
    apply = AsyncMock()
    monkeypatch.setattr(md_consumption, "apply_md_consumption", apply)

    with pytest.raises(HTTPException) as exc:
        await _apply(db, group=group, match_order=matched)

    assert exc.value.status_code == 409
    apply.assert_not_awaited()
