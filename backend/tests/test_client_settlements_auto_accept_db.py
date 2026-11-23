"""Automat przyjęcia RCP „Bez uwag” na bazie: ta sama ścieżka co przyjęcie
zbiorcze (MD schodzą z zamówienia), ślad automatu, odmowy: reguła wyłączona,
uwagi, „Do poprawy”, moduł zamknięty, przed terminem. Dane fikcyjne."""

from __future__ import annotations

import io
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import openpyxl
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_order_group import ClientOrderGroupEvent
from app.models.client_settlement import ClientSettlementRuleSet
from app.services import storage_service
from app.services.client_settlements import auto_accept, service
from app.services.consultant_portal import documents
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_rcp import _sheet
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _consumption,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio

WAW = ZoneInfo("Europe/Warsaw")


def _morning_on_due_day(month: str) -> datetime:
    """Rano w dniu, od którego automat bierze ``month`` (1. dzień roboczy)."""

    return datetime.combine(auto_accept.due_from(month, 1), time(7, 30), tzinfo=WAW)


async def _rules(client_id: int, level: str, workday: str = "1") -> None:
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        found.rules = {
            **found.rules,
            # Nazwisko z arkusza testowego nie jest nazwiskiem z kontraktu.
            "proof.name_match": {"level": "off", "params": {}},
            # Sam arkusz bez podpisu i maila z akceptacją wystarcza.
            "proof.signed_pdf": {"level": "off", "params": {"issuer": ""}},
            "proof.excel_with_mail": {"level": "off", "params": {"domain": ""}},
            auto_accept.RULE: {"level": level, "params": {"workday": workday}},
        }
        await db.commit()


async def _rcp(
    contract_id: int, month: str, name: str = "rcp.xlsx", work: str = "development"
) -> None:
    year, mon = (int(x) for x in month.split("-"))
    rows = _sheet([[None, work, 7, None, None, "EBI", None, "SX03098"]])
    rows[1][2] = rows[1][2].replace(year=year, month=mon, day=1)
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=mon,
            content=buffer.getvalue(),
            file_name=name,
            channel="portal",
            now=local_now(),
        )
        await db.commit()


async def _status(contract_id: int, month: str) -> str:
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, contract_id, month)
        return s.status


async def _run(now: datetime) -> int:
    async with AsyncSessionLocal() as db:
        accepted = await auto_accept.run(db, now=now)
        await db.commit()
        return accepted


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    previous = await _module(True)
    client_id, contract_id, line_id = await _world()
    try:
        yield client_id, contract_id, line_id
    finally:
        await _cleanup(client_id)
        await _restore(previous)


async def test_wlaczona_przyjmuje_bez_uwag_zdejmuje_md_i_zostawia_slad(world) -> None:
    client_id, contract_id, line_id = world
    month = _previous_month()
    await _rules(client_id, "block")
    await _rcp(contract_id, month)
    assert await _status(contract_id, month) == "ok"
    async with AsyncSessionLocal() as db:
        view = await service.month_view(db, client_id, month, amounts=True)
    assert view["auto_accept"]["count"] == 1
    assert view["auto_accept"]["from"] == auto_accept.due_from(month, 1).isoformat()

    assert await _run(_morning_on_due_day(month)) == 1

    assert await _status(contract_id, month) == "accepted"
    assert await _consumption(line_id, month) == Decimal("7.000")
    async with AsyncSessionLocal() as db:
        s = await service._settlement(db, contract_id, month)
        assert s.accepted_by is None
        card = await service.detail(db, contract_id, month, amounts=False)
        assert card["accepted_auto"] is True
        view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["accepted_auto"] is True
        events = (
            await db.scalars(
                select(ClientOrderGroupEvent.description).where(
                    ClientOrderGroupEvent.order_id == line_id
                )
            )
        ).all()
    assert any("automat" in (e or "") for e in events), events
    # Drugi bieg niczego nie powtarza.
    assert await _run(_morning_on_due_day(month)) == 0


async def test_wylaczona_nie_przyjmuje(world) -> None:
    client_id, contract_id, _line = world
    month = _previous_month()
    await _rules(client_id, "off")
    await _rcp(contract_id, month)
    assert await _status(contract_id, month) == "ok"
    async with AsyncSessionLocal() as db:
        view = await service.month_view(db, client_id, month, amounts=True)
    assert view["auto_accept"] is None
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "ok"


async def test_rcp_z_uwagami_zostaje_dla_finansow(world) -> None:
    client_id, contract_id, _line = world
    month = _previous_month()
    await _rules(client_id, "block")
    async with AsyncSessionLocal() as db:
        # MD wpisane bez pliku RCP: uwaga „MD wpisane bez pliku RCP”.
        await service.set_md(
            db, contract_id, month, md_regular=Decimal("5"), md_extra=None, actor=ACTOR
        )
        await db.commit()
    assert await _status(contract_id, month) == "warnings"
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "warnings"


async def test_uwagi_po_przeliczeniu_zatrzymuja_automat(world) -> None:
    """Zapisany stan „Bez uwag”, ale reguła zmieniona po wpłynięciu pliku:
    przeliczenie przy przyjęciu daje uwagę, więc RCP zostaje dla Finansów."""

    client_id, contract_id, line_id = world
    month = _previous_month()
    await _rules(client_id, "block")
    await _rcp(contract_id, month)
    assert await _status(contract_id, month) == "ok"
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        found.rules = {
            **found.rules,
            "proof.excel_with_mail": {"level": "warn", "params": {"domain": ""}},
        }
        await db.commit()
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "warnings"
    assert await _consumption(line_id, month) is None


async def test_po_do_poprawy_automat_nie_bierze_rozliczenia(world) -> None:
    client_id, contract_id, _line = world
    month = _previous_month()
    await _rules(client_id, "block")
    await _rcp(contract_id, month)
    async with AsyncSessionLocal() as db:
        await service.needs_fix(
            db,
            contract_id,
            month,
            reason="Brak podpisu klienta",
            actor=ACTOR,
            now=local_now(),
        )
        await db.commit()
    # Poprawiony plik: rozliczenie znów „Bez uwag”, ale automat go nie bierze.
    await _rcp(contract_id, month, name="rcp-poprawione.xlsx", work="testy")
    assert await _status(contract_id, month) == "ok"
    async with AsyncSessionLocal() as db:
        view = await service.month_view(db, client_id, month, amounts=True)
    assert view["auto_accept"]["count"] == 0
    assert view["batch_ready"] == 1
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "ok"
    # Finanse przyjmują je same, jak dotąd.
    async with AsyncSessionLocal() as db:
        accepted = await service.accept_batch(
            db, client_id, month, actor=ACTOR, now=local_now()
        )
        await db.commit()
    assert accepted == 1


async def test_modul_rozliczen_zamkniety(world) -> None:
    client_id, contract_id, _line = world
    month = _previous_month()
    await _rules(client_id, "block")
    await _rcp(contract_id, month)
    await _module(False)
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "ok"


async def test_przed_n_tym_dniem_roboczym_czeka(world) -> None:
    client_id, contract_id, _line = world
    month = _previous_month()
    await _rules(client_id, "block", workday="5")
    await _rcp(contract_id, month)
    # Rano pierwszego dnia roboczego, a próg to piąty.
    assert await _run(_morning_on_due_day(month)) == 0
    assert await _status(contract_id, month) == "ok"
