"""Rozliczenia E1 na bazie: przyjęcie RCP zdejmuje MD, ponowne nadpisuje, brak MD
wstrzymuje, odesłanie do poprawy, reguły od miesiąca, lista miesiąca."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.md_consumption import ClientOrderMdConsumption
from app.services.client_settlements import service
from app.services.client_settlements.service import SettlementError
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)


def _previous_month() -> str:
    today = business_today()
    first = today.replace(day=1) - timedelta(days=1)
    return f"{first.year}-{first.month:02d}"


async def _world(md_total: str = "30") -> tuple[int, int, int]:
    client_id = await _client()
    contract_id = await _contract(client_id, await _candidate())
    start = business_today() - timedelta(days=90)
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=f"ROZL-{client_id}",
            start_date=start,
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            order_group_id=group.id,
            title="linia MD",
            status=ClientOrderStatus.active,
            start_date=start,
            md_total=Decimal(md_total),
            md_remaining=Decimal(md_total),
            md_input_mode="md",
            md_input_value=Decimal(md_total),
            md_rate_cost=Decimal("1000"),
            md_rate_revenue=Decimal("1100"),
        )
        db.add(line)
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={
                    "extra.multiplier": {"level": "warn", "params": {"pct": "120"}},
                    "order.no_md_holds_invoice": {"level": "block", "params": {}},
                },
            )
        )
        await db.commit()
        return client_id, contract_id, line.id


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientSettlement.__table__.delete().where(
                ClientSettlement.client_id == client_id
            )
        )
        await db.execute(
            ClientSettlementRuleSet.__table__.delete().where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.commit()
    from tests.test_client_audit_2026_09_24 import _cleanup as base_cleanup

    await base_cleanup(client_id)


async def _consumption(line_id: int, month: str) -> Decimal | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ClientOrderMdConsumption.md_reported).where(
                ClientOrderMdConsumption.order_id == line_id,
                ClientOrderMdConsumption.period_month == month,
            )
        )


async def test_przyjecie_zdejmuje_md_a_ponowne_nadpisuje() -> None:
    client_id, contract_id, line_id = await _world()
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            s = await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("17"),
                md_extra=Decimal("4.75"),
                actor=ACTOR,
            )
            assert s.status == "warnings"  # bez pliku RCP
            assert s.md_charged == Decimal("22.700")
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
        assert await _consumption(line_id, month) == Decimal("22.7")

        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("20"),
                md_extra=None,
                actor=ACTOR,
            )
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
        assert await _consumption(line_id, month) == Decimal("20")

        async with AsyncSessionLocal() as db:
            line = await db.get(ClientOrder, line_id)
            assert line.md_remaining == Decimal("10")
            view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["status"] == "accepted"
        assert row["order_number"] == f"ROZL-{client_id}"
        assert row["amount_cost"] == "20000.00"
        assert row["margin"] == "2000.00"
        assert view["counts"]["accepted"] == 1
    finally:
        await _cleanup(client_id)


async def test_brak_md_na_zamowieniu_nie_przyjmuje_i_nie_zdejmuje() -> None:
    client_id, contract_id, line_id = await _world(md_total="10")
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            s = await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("21"),
                md_extra=None,
                actor=ACTOR,
            )
            assert s.status == "no_md"
            with pytest.raises(SettlementError):
                await service.accept(
                    db, contract_id, month, actor=ACTOR, now=local_now()
                )
            await db.commit()
        assert await _consumption(line_id, month) is None
    finally:
        await _cleanup(client_id)


async def test_bez_kwot_dla_konta_bez_dostepu_finansowego() -> None:
    client_id, contract_id, _line_id = await _world()
    month = _previous_month()
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
            view = await service.month_view(db, client_id, month, amounts=False)
            detail = await service.detail(db, contract_id, month, amounts=False)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["amount_cost"] is None and row["margin"] is None
        assert detail["total_net"] is None
        assert all(
            line["rate"] is None and line["net"] is None for line in detail["lines"]
        )
    finally:
        await _cleanup(client_id)


async def test_do_poprawy_wymaga_powodu_i_blokuje_po_przyjeciu() -> None:
    client_id, contract_id, _line_id = await _world()
    month = _previous_month()
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(SettlementError):
                await service.needs_fix(
                    db, contract_id, month, reason=" ", actor=ACTOR, now=local_now()
                )
            s = await service.needs_fix(
                db,
                contract_id,
                month,
                reason="Brak podpisu klienta",
                actor=ACTOR,
                now=local_now(),
            )
            assert s.status == "needs_fix"
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("5"),
                md_extra=None,
                actor=ACTOR,
            )
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            with pytest.raises(SettlementError):
                await service.needs_fix(
                    db,
                    contract_id,
                    month,
                    reason="Za późno na to",
                    actor=ACTOR,
                    now=local_now(),
                )
            await db.commit()
    finally:
        await _cleanup(client_id)


async def test_reguly_od_miesiaca_i_odrzucenie_nieznanej() -> None:
    client_id, _contract_id, _line_id = await _world()
    try:
        async with AsyncSessionLocal() as db:
            await service.save_rules(
                db,
                client_id,
                effective_from="2099-01",
                items=[
                    {
                        "key": "extra.multiplier",
                        "level": "block",
                        "params": {"pct": "150"},
                    }
                ],
                actor=ACTOR,
            )
            await db.commit()
            old = await service.rules_for(db, client_id, "2098-12")
            new = await service.rules_for(db, client_id, "2099-02")
            assert old["extra.multiplier"]["params"]["pct"] == "120"
            assert new["extra.multiplier"] == {
                "level": "block",
                "params": {"pct": "150"},
            }
            # Nowa wersja dziedziczy resztę z poprzedniej.
            assert new["order.no_md_holds_invoice"]["level"] == "block"
            with pytest.raises(SettlementError):
                await service.save_rules(
                    db,
                    client_id,
                    effective_from="2099-03",
                    items=[{"key": "x", "level": "off"}],
                    actor=ACTOR,
                )
    finally:
        await _cleanup(client_id)


async def test_wgrane_rcp_wypelnia_md_a_przyjecie_bierze_tez_mail(
    tmp_path, monkeypatch
) -> None:
    """E2.4: RCP z panelu albo maila liczy rozliczenie od razu; wpis ręczny wygrywa;
    przyjęcie przyjmuje też mail z akceptacją, bez drugiego maila do konsultanta."""

    import io

    import openpyxl
    from sqlalchemy.dialects.postgresql import insert

    from app.models.app_setting import AppSetting
    from app.models.consultant_portal import CpDocument
    from app.services import storage_service
    from app.services.consultant_portal import documents
    from tests.test_client_settlements_rcp import _sheet

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, line_id = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    rows = _sheet([[None, "development", 7, None, None, "EBI", None, "SX03098"]])
    rows[1][2] = rows[1][2].replace(year=year, month=mon, day=1)
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    eml = b"From: a@bank.pl\r\nTo: b@b2b.pl\r\nSubject: Akceptacja\r\nDate: Mon, 2 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n\r\nOK"
    async with AsyncSessionLocal() as db:
        had = await db.get(AppSetting, "client_settlements")
        previous = had.value if had else None
        await db.execute(
            insert(AppSetting)
            .values(key="client_settlements", value={"enabled": True})
            .on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": {"enabled": True}}
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            for content, name in (
                (buffer.getvalue(), "rcp.xlsx"),
                (eml, "akceptacja.eml"),
            ):
                await documents.store(
                    db,
                    contract_id=contract_id,
                    kind="report",
                    year=year,
                    month=mon,
                    content=content,
                    file_name=name,
                    channel="portal",
                    now=local_now(),
                )
            await db.commit()
            s = await service._settlement(db, contract_id, month)
            assert s is not None and s.md_source == "rcp"
            assert s.md_regular == Decimal("7.000")
            # Wpis ręczny wygrywa z odczytem pliku.
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("6"),
                md_extra=None,
                actor=ACTOR,
            )
            await service.refresh_for_document(
                db, await db.get(CpDocument, s.report_document_id)
            )
            assert s.md_regular == Decimal("6") and s.md_source == "manual"
            await service.accept(db, contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
            statuses = (
                await db.scalars(
                    select(CpDocument.status).where(
                        CpDocument.contract_id == contract_id
                    )
                )
            ).all()
        assert sorted(statuses) == ["accepted", "accepted"]
        assert await _consumption(line_id, month) == Decimal("6")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                CpDocument.__table__.delete().where(
                    CpDocument.contract_id == contract_id
                )
            )
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
        await _cleanup(client_id)
