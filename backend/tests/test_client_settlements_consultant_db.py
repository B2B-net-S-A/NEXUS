"""E3: rozliczenie w panelu konsultanta — lista dozwolonych pól, zadania, termin."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.app_setting import AppSetting
from app.models.client_settlement import ClientSettlementRuleSet
from app.services.client_settlements import consultant, service
from tests.test_client_settlements_service_db import (
    ACTOR,
    _cleanup,
    _previous_month,
    _world,
)

pytestmark = pytest.mark.asyncio

FORBIDDEN = ("amount_revenue", "margin", "rate", "revenue", "1100", "120%", "×")


async def _module(enabled: bool) -> object:
    async with AsyncSessionLocal() as db:
        had = await db.get(AppSetting, "client_settlements")
        previous = had.value if had else None
        await db.execute(
            insert(AppSetting)
            .values(key="client_settlements", value={"enabled": enabled})
            .on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": {"enabled": enabled}}
            )
        )
        await db.commit()
    return previous


async def _restore(previous: object) -> None:
    async with AsyncSessionLocal() as db:
        if previous is None:
            await db.execute(
                AppSetting.__table__.delete().where(
                    AppSetting.key == "client_settlements"
                )
            )
        else:
            await db.execute(
                AppSetting.__table__.update()
                .where(AppSetting.key == "client_settlements")
                .values(value=previous)
            )
        await db.commit()


async def test_konsultant_widzi_stan_md_i_kwote_bez_stawki_klienta_i_marzy() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSettlementRuleSet(
                    client_id=client_id,
                    effective_from="2020-02",
                    rules={
                        "extra.multiplier": {"level": "warn", "params": {"pct": "120"}},
                        "ci.payment_days": {"level": "warn", "params": {"days": "7"}},
                        "order.md_visible": {"level": "warn", "params": {}},
                    },
                )
            )
            await db.commit()
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("17"),
                md_extra=Decimal("4.75"),
                actor=ACTOR,
            )
            await db.commit()
            waiting = await consultant.view(db, contract_id, client_id, year, mon)
            assert waiting is not None and waiting["invoice"] is None
            assert waiting["label"] == "Sprawdzamy RCP"
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
            done = await consultant.view(db, contract_id, client_id, year, mon)
        assert done["invoice"]["amount_net"] == "22700.00"
        assert done["invoice"]["payment_days"] == 7
        assert done["md_regular"] == "17.000" and done["md_extra"] == "4.750"
        assert done["md_remaining_after"] == "7.300"
        assert done["todo"] == []
        assert set(done) == {
            "status",
            "kind",
            "label",
            "fix_reason",
            "checks",
            "todo",
            "md_regular",
            "md_extra",
            "md_remaining_after",
            "invoice",
        }
        text = json.dumps(done, ensure_ascii=False)
        assert not any(word in text for word in FORBIDDEN)
    finally:
        await _restore(previous)
        await _cleanup(client_id)


async def test_do_poprawy_i_brakujacy_mail_to_zadania() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(True)
    try:
        async with AsyncSessionLocal() as db:
            s = await service.needs_fix(
                db,
                contract_id,
                month,
                reason="Brak podpisu klienta",
                actor=ACTOR,
                now=local_now(),
            )
            s.checks = [
                {
                    "title": "Nadgodziny",
                    "checks": [
                        {
                            "state": "fail",
                            "title": "Brak maila z akceptacją pracy dodatkowej",
                        }
                    ],
                },
                {
                    "title": "Zamówienie 1",
                    "checks": [
                        {"state": "ok", "title": "Zejdzie 20 MD, zostanie 1 MD"}
                    ],
                },
            ]
            await db.commit()
            view = await consultant.view(db, contract_id, client_id, year, mon)
        assert view["fix_reason"] == "Brak podpisu klienta"
        assert view["todo"] == ["Dołącz mail z akceptacją pracy dodatkowej"]
        assert all("Zejdzie" not in c["title"] for c in view["checks"])
    finally:
        await _restore(previous)
        await _cleanup(client_id)


async def test_wylaczony_modul_i_brak_reguly_terminu() -> None:
    client_id, contract_id, _line = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    previous = await _module(False)
    try:
        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("10"),
                md_extra=None,
                actor=ACTOR,
            )
            await db.commit()
            assert await consultant.view(db, contract_id, client_id, year, mon) is None
            assert (
                await consultant.payment_days(db, client_id, month)
                == consultant.DEFAULT_PAYMENT_DAYS
            )
            assert (
                await consultant.payment_days(db, None, month)
                == consultant.DEFAULT_PAYMENT_DAYS
            )
    finally:
        await _restore(previous)
        await _cleanup(client_id)


def test_przyjete_rozliczenie_bez_pliku_prowadzi_do_faktury_nie_do_raportu() -> None:
    """Finanse przyjęły MD wpisane ręcznie (bez pliku): konsultant nie może
    dostać „Wyślij raport” obok „RCP przyjęte: wystaw fakturę”."""

    from app.services.consultant_portal import documents

    row = documents.month_row(2026, 10, [])
    documents.apply_settlement(row, {"status": "accepted"})
    assert row["action"] == "send_invoice"
    assert row["issue_invoice"] is True
    assert row["report_label"] == "Raport: zaakceptowany"
    waiting = documents.month_row(2026, 10, [])
    documents.apply_settlement(waiting, {"status": "checking"})
    assert waiting["action"] == "send_report"
    paid_row = documents.month_row(2026, 10, [])
    documents.apply_settlement(paid_row, None)
    assert paid_row["action"] == "send_report"
