"""„Przebieg miesiąca” na bazie: wiersz klienta liczony jak ekran klienta,
kolejka decyzji po powodzie, klient z raportem T4T poza kolejką osób, kwoty
tylko z uprawnieniem."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.services.client_settlements import month_close, service
from tests.test_client_audit_2026_09_24 import _candidate, _contract
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio


def _entry(out: dict, client_id: int) -> dict:
    return next(c for c in out["clients"] if c["client_id"] == client_id)


async def test_klient_z_uwaga_i_brakiem_raportu() -> None:
    client_id, contract_id, _ = await _world()
    missing_id = await _contract(client_id, await _candidate())
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            s = await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("17"),
                md_extra=None,
                actor=ACTOR,
            )
            await db.commit()
            assert s.status == "warnings"
        async with AsyncSessionLocal() as db:
            out = await month_close.overview(db, month, amounts=True)
            view = await service.month_view(db, client_id, month, amounts=True)
        entry = _entry(out, client_id)
        assert entry["people"] == len(view["rows"]) == 2
        assert entry["decide"] == 1
        assert entry["missing"] == 1
        assert entry["client_report"] is None
        # Lista osób w grupie jest ucięta (PEOPLE_PER_REASON), a baza testów
        # ma też innych klientów, więc sprawdzamy licznik klienta w grupie.
        # Ten sam powód może mieć dwie grupy (u jednego klienta blokuje, u innego
        # ostrzega), więc licznik klienta sumujemy po kluczu.
        counts: dict[str, int] = {}
        for r in out["reasons"]:
            counts[r["key"]] = counts.get(r["key"], 0) + next(
                (c["count"] for c in r["clients"] if c["client_id"] == client_id), 0
            )
        assert counts.get(month_close.MISSING_REASON) == 1
        decided = {
            k: n for k, n in counts.items() if n and k != month_close.MISSING_REASON
        }
        assert sum(decided.values()) == 1
        missing = next(
            r for r in out["reasons"] if r["key"] == month_close.MISSING_REASON
        )
        if len(missing["people"]) < month_close.PEOPLE_PER_REASON:
            assert any(p["contract_id"] == missing_id for p in missing["people"])
        assert out["can_see_amounts"] is True
    finally:
        await _cleanup(client_id)


async def test_bez_uprawnienia_do_kwot_nie_ma_kwot() -> None:
    client_id, contract_id, _ = await _world()
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("17"),
                md_extra=None,
                actor=ACTOR,
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            out = await month_close.overview(db, month, amounts=False)
        assert out["can_see_amounts"] is False
        assert _entry(out, client_id)["revenue_ready"] is None
    finally:
        await _cleanup(client_id)


async def test_klient_z_raportem_t4t_poza_kolejka_osob() -> None:
    client_id, _, _ = await _world()
    await _contract(client_id, await _candidate())  # osoba bez raportu
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            found = await service._rule_set(db, client_id, month)
            found.rules = {
                **(found.rules or {}),
                month_close.T4T_RULE: {"level": "warn", "params": {}},
            }
            await db.commit()
        async with AsyncSessionLocal() as db:
            out = await month_close.overview(db, month, amounts=True)
        entry = _entry(out, client_id)
        assert entry["client_report"] is not None
        assert all(
            c["client_id"] != client_id for r in out["reasons"] for c in r["clients"]
        )
    finally:
        await _cleanup(client_id)
