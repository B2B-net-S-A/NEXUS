"""Podział rozliczenia na zamówienia z maila klienta, z bazą.

Dane fikcyjne (osoby, numery zamówień, stawki, domena ``klient.example``). Układ
jak w próbie IX–X 2026: odpowiedź klienta „Akceptuję” z liniami „<numer>: 40h”
na jedynym dokumencie miesiąca, jedno zamówienie zakończone w NEXUS-ie, drugie
z pulą na wyczerpaniu. Decyzja Artura z 24.11.2026: linie, zejście i faktura idą
jak w mailu, zamówienia dostają uwagę, przyjęcia to nie blokuje.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from email.message import EmailMessage
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.contract import Contract
from app.models.md_consumption import ClientOrderMdConsumption
from app.services import storage_service
from app.services.client_settlements import client_invoice, mail_text, service
from app.services.client_settlements.service import SettlementError
from app.services.consultant_portal import documents
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
DOMAIN = "klient.example"


def _months() -> tuple[str, str]:
    """(rozliczany = poprzedni, wcześniejszy) w kalendarzu firmy."""

    first = business_today().replace(day=1)
    previous = first - timedelta(days=1)
    earlier = previous.replace(day=1) - timedelta(days=1)
    return f"{previous:%Y-%m}", f"{earlier:%Y-%m}"


def _acceptance(person: str, month: str, lines: str) -> bytes:
    """Odpowiedź klienta na naszą prośbę o akceptację, z liniami podziału."""

    year, mon = (int(x) for x in month.split("-"))
    label = mail_text.MONTHS_NOMINATIVE[mon - 1].capitalize()
    message = EmailMessage()
    message["Subject"] = f"RE: Akceptacja czasu {label} {year} - {person}"
    message["From"] = f"Kierownik Klienta <kierownik@{DOMAIN}>"
    message["To"] = "rozliczenia@firma-testowa.example"
    message.set_content(
        "Dzień dobry.\n\nAkceptuję.\n\nProśba o rozliczenie według zamówień:\n"
        f"{lines}\n\nPozdrawiam\n\n"
        "From: rozliczenia@firma-testowa.example <rozliczenia@firma-testowa.example>\n"
        f"Subject: Akceptacja czasu {label} {year} - {person}\n\n"
        f"Proszę o akceptację czasu za {label.lower()} {year} r. - 176 godzin.\n"
    )
    return message.as_bytes()


async def _line(
    db,
    client_id: int,
    contract_id: int,
    number: str,
    *,
    status: ClientOrderStatus,
    md_total: str,
    used_before: str,
    revenue: str,
    earlier: str,
    end_date=None,
    grouped: bool = True,
) -> int:
    start = business_today() - timedelta(days=200)
    group = None
    if grouped:
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
        await db.flush()
    line = ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        order_group_id=group.id if group else None,
        # Linia bez grupy (PKO, Velo) ma numer zamówienia w tytule.
        title="linia MD" if grouped else f"Zamówienie {number}",
        status=status,
        start_date=start,
        end_date=end_date,
        md_total=Decimal(md_total),
        md_remaining=Decimal(md_total) - Decimal(used_before),
        md_input_mode="md",
        md_input_value=Decimal(md_total),
        md_rate_cost=Decimal("800"),
        md_rate_revenue=Decimal(revenue),
    )
    db.add(line)
    await db.flush()
    db.add(
        ClientOrderMdConsumption(
            order_id=line.id,
            period_month=earlier,
            md_reported=Decimal(used_before),
            source="import",
        )
    )
    return line.id


async def _world() -> SimpleNamespace:
    month, earlier = _months()
    client_id = await _client()
    contract_id = await _contract(client_id, await _candidate())
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        person = f"{candidate.name} {candidate.lastname}"
        old_end = business_today().replace(day=1) - timedelta(days=45)
        closed = await _line(
            db,
            client_id,
            contract_id,
            "4500011111",
            status=ClientOrderStatus.completed,
            md_total="4",
            used_before="4",
            revenue="1000",
            earlier=earlier,
            end_date=old_end,
        )
        almost = await _line(
            db,
            client_id,
            contract_id,
            "SAP 4500022222",
            status=ClientOrderStatus.active,
            md_total="10",
            used_before="9",
            revenue="1100",
            earlier=earlier,
        )
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={
                    "order.no_md_holds_invoice": {"level": "warn", "params": {}},
                    "order.charge_on_accept": {"level": "block", "params": {}},
                    # Domena klienta: od niej podział się liczy.
                    "proof.excel_with_mail": {
                        "level": "off",
                        "params": {"domain": DOMAIN},
                    },
                },
            )
        )
        await db.execute(
            insert(AppSetting)
            .values(key="client_settlements", value={"enabled": True})
            .on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": {"enabled": True}}
            )
        )
        await db.commit()
    return SimpleNamespace(
        client_id=client_id,
        contract_id=contract_id,
        person=person,
        month=month,
        closed=closed,
        almost=almost,
    )


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


async def _store_mail(w: SimpleNamespace, content: bytes, name: str) -> None:
    year, mon = (int(x) for x in w.month.split("-"))
    async with AsyncSessionLocal() as db:
        await documents.store(
            db,
            contract_id=w.contract_id,
            kind="report",
            year=year,
            month=mon,
            content=content,
            file_name=name,
            channel="mailbox",
            now=local_now(),
            sender_email=f"kierownik@{DOMAIN}",
        )
        await db.commit()


async def _consumption(order_id: int, month: str) -> Decimal | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(ClientOrderMdConsumption.md_reported).where(
                ClientOrderMdConsumption.order_id == order_id,
                ClientOrderMdConsumption.period_month == month,
            )
        )


async def test_mail_klienta_dzieli_md_zejscie_i_fakture_na_zamowienia(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        await _store_mail(
            w,
            _acceptance(
                w.person,
                w.month,
                "4500011111:      40h          4000,00 PLN\n"
                "4500022222:  136h         14960,00 PLN",
            ),
            "akceptacja.eml",
        )
        async with AsyncSessionLocal() as db:
            s = await service._settlement(db, w.contract_id, w.month)
            # Jedyny dokument miesiąca: MD z godzin zaakceptowanych przez klienta.
            assert s is not None and s.md_regular == Decimal("22.000")
            assert s.status == "warnings"
            assert s.order_id == w.almost  # zamówienie z większą częścią
            parts = {o["order_id"]: o for o in service.split_orders(s)}
            assert {k: v["md"] for k, v in parts.items()} == {
                w.closed: "5.000",
                w.almost: "17.000",
            }
            assert parts[w.closed]["closed"] is True
            assert s.amount_revenue == Decimal("23700.00")  # 5 × 1000 + 17 × 1100
            titles = [
                c["title"] for g in s.checks if "checks" in g for c in g["checks"]
            ]
            assert "Zamówienie zakończone w NEXUS-ie" in titles
            assert "Ponad pulę zamówienia o 16 MD" in titles

            await service.accept(
                db, w.contract_id, w.month, actor=ACTOR, now=local_now()
            )
            await db.commit()
        assert await _consumption(w.closed, w.month) == Decimal("5")
        assert await _consumption(w.almost, w.month) == Decimal("17")
        async with AsyncSessionLocal() as db:
            line = await db.get(ClientOrder, w.almost)
            assert line.md_remaining == Decimal("-16")  # pula poniżej zera, jak w mailu
            data = await client_invoice.invoice_month(
                db, w.client_id, w.month, amounts=True
            )
            view = await service.month_view(db, w.client_id, w.month, amounts=True)
        rows = [r for r in data["rows"] if r["contract_id"] == w.contract_id]
        assert [(r["order_id"], r["order_number"], r["net"]) for r in rows] == [
            (w.closed, "4500011111", "5000.00"),
            (w.almost, "SAP 4500022222", "18700.00"),
        ]
        assert [p["quantity"] for r in rows for p in r["positions"]] == ["5", "17"]
        row = next(r for r in view["rows"] if r["contract_id"] == w.contract_id)
        assert row["order_number"] == "4500011111, SAP 4500022222"
    finally:
        await _cleanup(w.client_id)


async def test_nowy_podzial_zeruje_wlasne_zejscie_a_cudze_dalej_odmawia(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        await _store_mail(
            w,
            _acceptance(w.person, w.month, "4500011111: 40h\n4500022222: 136h"),
            "akceptacja.eml",
        )
        async with AsyncSessionLocal() as db:
            await service.accept(
                db, w.contract_id, w.month, actor=ACTOR, now=local_now()
            )
            await db.commit()
        # Klient poprawia podział: wszystko na drugie zamówienie.
        await _store_mail(
            w,
            _acceptance(w.person, w.month, "4500022222: 176h"),
            "akceptacja-poprawiona.eml",
        )
        async with AsyncSessionLocal() as db:
            s = await service.accept(
                db, w.contract_id, w.month, actor=ACTOR, now=local_now()
            )
            await db.commit()
            assert [o["order_id"] for o in service.split_orders(s)] == [w.almost]
        # Własny wpis z pierwszego podziału zeruje się, MD nie liczą się dwa razy.
        assert await _consumption(w.closed, w.month) == Decimal("0")
        assert await _consumption(w.almost, w.month) == Decimal("22")

        # Wpis z importu na zamówieniu spoza podziału: dalej odmowa (FIN-MD-01).
        async with AsyncSessionLocal() as db:
            db.add(
                ClientOrderMdConsumption(
                    order_id=w.closed,
                    period_month=w.month,
                    md_reported=Decimal("3"),
                    source="import",
                )
            )
            await db.execute(
                ClientOrderMdConsumption.__table__.delete().where(
                    ClientOrderMdConsumption.order_id == w.closed,
                    ClientOrderMdConsumption.period_month == w.month,
                    ClientOrderMdConsumption.source == "settlement",
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            with pytest.raises(SettlementError, match="innym zamówieniu"):
                await service.accept(
                    db, w.contract_id, w.month, actor=ACTOR, now=local_now()
                )
    finally:
        await _cleanup(w.client_id)


async def test_podzial_od_nas_bez_klienta_nie_wchodzi(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        content = _acceptance(w.person, w.month, "4500011111: 40h\n4500022222: 136h")
        # Ten sam tekst wysłany z naszej domeny: zamówień nie wskazał klient.
        content = content.replace(
            f"kierownik@{DOMAIN}".encode(), b"koordynator@firma-testowa.example"
        )
        await _store_mail(w, content, "akceptacja.eml")
        async with AsyncSessionLocal() as db:
            s = await service._settlement(db, w.contract_id, w.month)
            assert s is not None
            assert service.split_orders(s) == []
            assert s.md_regular is None  # bez dowodu od klienta MD wpisują Finanse
    finally:
        await _cleanup(w.client_id)


async def test_numer_spoza_nexusa_zostawia_jedno_zamowienie(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        await _store_mail(
            w,
            _acceptance(w.person, w.month, "4500011111: 40h\n4500099999: 136h"),
            "akceptacja.eml",
        )
        async with AsyncSessionLocal() as db:
            s = await service._settlement(db, w.contract_id, w.month)
            assert s.md_regular == Decimal("22.000")
            assert service.split_orders(s) == []
            titles = [
                c["title"] for g in s.checks if "checks" in g for c in g["checks"]
            ]
            assert "Podział z maila klienta nie wszedł" in titles
    finally:
        await _cleanup(w.client_id)


async def test_linia_bez_grupy_ma_numer_z_tytulu_na_fakturze(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    w = await _world()
    try:
        month, earlier = _months()
        async with AsyncSessionLocal() as db:
            titled = await _line(
                db,
                w.client_id,
                w.contract_id,
                "4500033333",
                status=ClientOrderStatus.active,
                md_total="40",
                used_before="0",
                revenue="1200",
                earlier=earlier,
                grouped=False,
            )
            await db.commit()
        await _store_mail(
            w,
            _acceptance(w.person, month, "4500011111: 40h\n4500033333: 136h"),
            "akceptacja.eml",
        )
        async with AsyncSessionLocal() as db:
            await service.accept(db, w.contract_id, month, actor=ACTOR, now=local_now())
            await db.commit()
            data = await client_invoice.invoice_month(
                db, w.client_id, month, amounts=True
            )
        rows = [r for r in data["rows"] if r["contract_id"] == w.contract_id]
        assert [(r["order_id"], r["order_number"], r["net"]) for r in rows] == [
            (w.closed, "4500011111", "5000.00"),
            (titled, "4500033333", "20400.00"),
        ]
        assert "4500033333" in rows[1]["positions"][0]["name"]
    finally:
        await _cleanup(w.client_id)
