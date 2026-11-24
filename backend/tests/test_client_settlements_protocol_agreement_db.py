"""Protokół CeZ z innym imieniem niż kartoteka: osobę wskazuje numer umowy. Na bazie.

Dane fikcyjne. CeZ zawiera umowę wykonawczą na osobę i pisze jej numer w protokole
(próba IX–X 2026: CeZ/177, w protokole inne imię niż w kontrakcie). Numer wskazuje
kontrakt, gdy w miesiącu rozliczenia na umowie pracuje tylko ta osoba
(``service._sole_agreements``). Linia anulowana i linia spoza miesiąca się nie
liczą; druga osoba na tej samej umowie w miesiącu = numer nikogo nie wskazuje.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.services.client_settlements import protocol_collective, service
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract
from tests.test_client_settlements_client_invoice_db import _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_protocol_collective import CEZ_PIVOT
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

RULES = {
    "proof.month": {"level": "block", "params": {}},
    "proof.name_match": {"level": "block", "params": {}},
    "fields.md_hours": {"level": "block", "params": {"hours": "8"}},
    "fields.md_month_limit": {"level": "off", "params": {}},
}


async def _group(client_id: int, number: str, start: date) -> int:
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=client_id,
            order_number=number,
            start_date=start,
            status="active",
            order_type="md",
            is_cost_based=False,
            is_md_budget_based=False,
        )
        db.add(group)
        await db.commit()
        return group.id


async def _line(
    client_id: int,
    contract_id: int,
    group_id: int,
    start: date,
    *,
    end: date | None = None,
    status: ClientOrderStatus = ClientOrderStatus.active,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                order_group_id=group_id,
                title="linia MD",
                status=status,
                start_date=start,
                end_date=end,
                md_total=Decimal("100"),
                md_remaining=Decimal("100"),
                md_input_mode="md",
                md_input_value=Decimal("100"),
                md_rate_cost=Decimal("1000"),
                md_rate_revenue=Decimal("1100"),
            )
        )
        await db.commit()


async def test_numer_umowy_tylko_osoby_z_miesiaca() -> None:
    client_id = await _client()
    one = await _contract(client_id, await _candidate())
    two = await _contract(client_id, await _candidate())
    october = date(2026, 10, 1)
    try:
        solo = await _group(client_id, "CeZ/97/2026", october)
        shared = await _group(client_id, "CeZ/96/2026", october)
        await _line(client_id, one, solo, october)
        # Anulowana linia drugiej osoby i jej zastępstwo od listopada.
        await _line(client_id, two, solo, october, status=ClientOrderStatus.cancelled)
        await _line(client_id, two, solo, date(2026, 11, 5))
        await _line(client_id, one, shared, october)
        await _line(client_id, two, shared, october)
        # Umowa skończona przed miesiącem rozliczenia.
        ended = await _group(client_id, "CeZ/95/2026", date(2026, 1, 1))
        await _line(client_id, two, ended, date(2026, 1, 1), end=date(2026, 9, 30))

        async with AsyncSessionLocal() as db:
            assert await service._sole_agreements(db, one, "2026-10") == frozenset(
                {"CEZ/97/2026"}
            )
            assert await service._sole_agreements(db, two, "2026-10") == frozenset()
            # W listopadzie na umowie 97 pracują dwie osoby.
            assert await service._sole_agreements(db, one, "2026-11") == frozenset()
            assert await service._sole_agreements(db, two, "2026-09") == frozenset(
                {"CEZ/95/2026"}
            )
    finally:
        await _cleanup(client_id)


def _protocol_text(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    last = calendar.monthrange(year, mon)[1]
    return CEZ_PIVOT.replace(
        "w okresie od 05.10.2026 do 31.10.2026",
        f"w okresie od 01.{mon:02d}.{year} do {last}.{mon:02d}.{year}",
    )


async def _store_protocol(contract_id: int, month: str, content: bytes) -> None:
    from app.services.consultant_portal import documents

    year, mon = (int(x) for x in month.split("-"))
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=contract_id,
            kind="report",
            year=year,
            month=mon,
            content=content,
            file_name="Protokół odbioru do CeZ_97_2026-sig.pdf",
            channel="mailbox",
            now=local_now(),
        )
        await db.commit()


async def _row(client_id: int, contract_id: int, month: str) -> dict:
    async with AsyncSessionLocal() as db:
        view = await service.month_view(db, client_id, month, amounts=True)
    return next(r for r in view["rows"] if r["contract_id"] == contract_id)


@pytest.mark.parametrize("second_person", [False, True])
async def test_protokol_z_innym_imieniem_daje_md_po_numerze_umowy(
    tmp_path, monkeypatch, second_person: bool
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    month = _month(-1)
    content = b"%PDF-1.4 protokol przestawny " + month.encode()
    text = _protocol_text(month)
    monkeypatch.setattr(
        protocol_collective, "pdf_text", lambda data: text if data == content else None
    )
    client_id, contract_id, line_id = await _world(md_total="60")
    previous = await _module(True)
    try:
        await _rules(client_id, RULES)
        async with AsyncSessionLocal() as db:
            line = await db.get(ClientOrder, line_id)
            group = await db.get(ClientOrderGroup, line.order_group_id)
            group.order_number = "CeZ/97/2026"
            group_id, start = group.id, line.start_date
            await db.commit()
        if second_person:
            other = await _contract(client_id, await _candidate())
            await _line(client_id, other, group_id, start)

        await _store_protocol(contract_id, month, content)

        row = await _row(client_id, contract_id, month)
        if second_person:
            # Umowa dwóch osób nie wskazuje, czyj jest wiersz protokołu.
            assert row["md_regular"] is None, row
        else:
            assert row["md_regular"] == "20.000", row  # 160 h / 8
            assert row["status"] == "ok", row
    finally:
        await _restore(previous)
        await _cleanup(client_id)
