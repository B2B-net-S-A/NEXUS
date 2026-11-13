"""Dodatki do rozliczenia kontraktora na bazie (potrzeba Finansów z 13.11.2026).

Faktura = godziny + zatwierdzony dodatek przechodzi kontrolę ``ci.amount``,
zgłoszony dodatek daje uwagę, odrzucenie wymaga powodu, dodatek niefakturowany
klientowi nie trafia do pozycji klienta, panel konsultanta widzi zatwierdzone
dodatki w danych do faktury i sam zgłasza delegację z dokumentem, back office
zgłasza dodatek z karty. Osoby i kwoty fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.back_office import BoCard, BoCardEvent
from app.models.client_settlement import ClientContractorInvoice
from app.models.client_settlement_extra import (
    ClientSettlementExtra,
    ClientSettlementExtraDocument,
)
from app.services.back_office import settlement_extras as card_extras
from app.services.client_settlements import client_invoice, consultant, extras
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import service
from tests.test_client_settlements_client_invoice_db import _accept, _month, _rules
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def _bind_invoice(contract_id: int, month: str, net: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientContractorInvoice(
                ksef_number=f"998-{uuid.uuid4().hex[:16]}",
                seller_nip="9980000000",
                seller_name="Fikcyjna firma",
                invoice_number=f"FV {uuid.uuid4().hex[:4]}",
                issue_date=business_today(),
                acquired_at=local_now(),
                net_amount=Decimal(net),
                vat_amount=Decimal(net) * Decimal("0.23"),
                gross_amount=Decimal(net) * Decimal("1.23"),
                contract_id=contract_id,
                period_month=month,
                nip_state=ci.KNOWN,
            )
        )
        await db.commit()


async def _add(contract_id: int, month: str, **kw) -> int:
    async with AsyncSessionLocal() as db:
        extra = await extras.create(
            db,
            contract_id,
            month,
            kind=kw.pop("kind", "referral"),
            amount=kw.pop("amount", "500"),
            description=kw.pop("description", None),
            source=kw.pop("source", extras.SOURCE_FINANCE),
            actor_id=None,
            now=local_now(),
            **kw,
        )
        await db.commit()
        return extra.id


async def _card(contract_id: int, month: str) -> dict:
    async with AsyncSessionLocal() as db:
        return await service.detail(db, contract_id, month, amounts=True)


async def test_faktura_godziny_plus_zatwierdzony_dodatek_przechodzi() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        await _rules(client_id, {"ci.amount": {"level": "block", "params": {}}})
        await _accept(contract_id, month, "10")  # 10 MD × 1000 zł kosztu
        await _add(contract_id, month, kind="tech_check", amount="200", approve=True)
        await _bind_invoice(contract_id, month, "10200.00")

        card = await _card(contract_id, month)
        assert card["contractor_invoice"]["state"] == ci.IN_KSEF
        titles = [c["title"] for c in card["contractor_invoice"]["checks"]]
        assert "Kwota równa wyliczeniu z RCP i dodatkom" in titles
        assert card["extras"]["approved_total"] == "200.00"
        assert card["extras"]["items"][0]["kind_label"] == "Weryfikacja techniczna"

        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["contractor_invoice"] == ci.IN_KSEF
        assert row["extras_pending"] == 0
        # Zatwierdzony dodatek to koszt miesiąca: 11 000 − (10 000 + 200).
        assert row["margin"] == "800.00"
    finally:
        await _cleanup(client_id)


async def test_zgloszony_dodatek_daje_uwage_a_odrzucenie_wymaga_powodu() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        await _rules(client_id, {"ci.amount": {"level": "block", "params": {}}})
        await _accept(contract_id, month, "10")
        extra_id = await _add(
            contract_id, month, kind="referral", amount="500", source="back_office"
        )
        await _bind_invoice(contract_id, month, "10500.00")

        card = await _card(contract_id, month)
        block = card["contractor_invoice"]
        assert block["state"] == ci.EXTRA_PENDING
        check = next(c for c in block["checks"] if "dodatku" in c["title"])
        assert check == {
            "state": "warn",
            "title": "Czeka na zatwierdzenie dodatku",
            "detail": "Faktura 10 500,00 zł netto, wyliczenie 10 000,00 zł; "
            "różnica 500,00 zł to zgłoszony dodatek.",
        }
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert (row["contractor_invoice"], row["extras_pending"]) == (
            ci.EXTRA_PENDING,
            1,
        )

        # Koszt dodatkowy odrzuca rozliczający, zawsze z powodem.
        async with AsyncSessionLocal() as db:
            with pytest.raises(extras.ExtraError):
                await extras.reject(
                    db, extra_id, contract_id, actor_id=1, now=local_now(), reason=""
                )
        async with AsyncSessionLocal() as db:
            await extras.reject(
                db,
                extra_id,
                contract_id,
                actor_id=None,
                now=local_now(),
                reason="Brak zlecenia weryfikacji od rekrutera",
            )
            await db.commit()
        assert (await _card(contract_id, month))["contractor_invoice"]["state"] == (
            ci.DIFFERS
        )

        # Zatwierdzony po odrzuceniu (decyzja zmieniona): kwota się zgadza.
        async with AsyncSessionLocal() as db:
            await extras.approve(
                db, extra_id, contract_id, actor_id=None, now=local_now()
            )
            await db.commit()
        card = await _card(contract_id, month)
        assert card["contractor_invoice"]["state"] == ci.IN_KSEF
        assert card["extras"]["items"][0]["decision_note"] is None
    finally:
        await _cleanup(client_id)


async def test_dodatek_niefakturowany_klientowi_nie_trafia_do_pozycji_klienta() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        await _rules(
            client_id,
            {
                "cl.extra_costs_on_invoice": {
                    "level": "warn",
                    "params": {"item": "Koszty delegacji"},
                }
            },
        )
        await _accept(contract_id, month, "10")
        await _add(contract_id, month, kind="travel", amount="300", approve=True)

        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert [p["kind"] for p in row["positions"]] == ["base"]
        assert row["net"] == "11000.00"
        # Koszt naszej zgody obniża marżę: 11 000 − (10 000 + 300).
        assert (row["cost"], row["margin"]) == ("10300.00", "700.00")

        await _add(
            contract_id,
            month,
            kind="travel",
            amount="450",
            approve=True,
            bill_to_client=True,
        )
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert [(p["name"], p["net"]) for p in row["positions"]][1:] == [
            ("Koszty delegacji", "450.00")
        ]
        assert (row["net"], row["cost"], row["margin"]) == (
            "11450.00",
            "10750.00",
            "700.00",
        )
    finally:
        await _cleanup(client_id)


async def test_integracji_nie_zatwierdzaja_finanse() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        async with AsyncSessionLocal() as db:
            with pytest.raises(extras.ExtraError):
                await extras.create(
                    db,
                    contract_id,
                    month,
                    kind="integration",
                    amount="100",
                    description="Wyjście zespołu",
                    source="finance",
                    actor_id=None,
                    now=local_now(),
                )
            extra = ClientSettlementExtra(
                client_id=client_id,
                contract_id=contract_id,
                period_month=month,
                kind="integration",
                amount=Decimal("100"),
                description="Integracja",
            )
            db.add(extra)
            await db.commit()
            with pytest.raises(extras.ExtraError) as err:
                await extras.approve(
                    db, extra.id, contract_id, actor_id=None, now=local_now()
                )
        assert err.value.status == 403
    finally:
        await _cleanup(client_id)


async def test_panel_konsultanta_dodatki_w_danych_do_faktury_i_delegacja(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    previous = await _module(True)
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    try:
        await _accept(contract_id, month, "10")
        await _add(contract_id, month, kind="referral", amount="1000", approve=True)
        await _add(contract_id, month, kind="training", amount="250")  # zgłoszony

        async with AsyncSessionLocal() as db:
            view = await consultant.view(db, contract_id, client_id, year, mon)
        invoice = view["invoice"]
        assert invoice["amount_net"] == "11000.00"
        assert invoice["item"]["net"] == "10000.00"
        assert [i["net"] for i in invoice["extra_items"]] == ["1000.00"]

        # Delegacja bez dokumentu: odmowa; z dokumentem — zgłoszona.
        async with AsyncSessionLocal() as db:
            with pytest.raises(extras.ExtraError):
                await consultant.add_travel(
                    db,
                    contract_id,
                    year=year,
                    month=mon,
                    amount="420",
                    description="Kraków, 3–4.11",
                    files=[],
                    now=local_now(),
                )
            extra = await consultant.add_travel(
                db,
                contract_id,
                year=year,
                month=mon,
                amount="420,50",
                description="Kraków, 3–4.11",
                files=[(PDF, "hotel.pdf")],
                now=local_now(),
            )
            await db.commit()
            assert (extra.status, extra.kind, extra.source) == (
                "pending",
                "travel",
                "portal",
            )
            docs = (
                await db.scalars(
                    select(ClientSettlementExtraDocument).where(
                        ClientSettlementExtraDocument.extra_id == extra.id
                    )
                )
            ).all()
        assert [d.file_name for d in docs] == ["hotel.pdf"]
        assert (tmp_path / docs[0].file_path).is_file()

        async with AsyncSessionLocal() as db:
            own = await consultant.own_extras(db, contract_id, year, mon)
        assert [(e["kind_label"], e["status"], e["documents"]) for e in own] == [
            ("Premia za polecenie", "approved", 0),
            ("Szkolenie", "pending", 0),
            ("Delegacja", "pending", 1),
        ]
        assert all("bill_to_client" not in e and "source" not in e for e in own)
    finally:
        await _cleanup(client_id)
        await _restore(previous)


async def test_back_office_zglasza_dodatek_z_karty() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        async with AsyncSessionLocal() as db:
            card = BoCard(
                team="care",
                lane="help",
                source_kind="case",
                source_key=f"case:test-{uuid.uuid4().hex[:8]}",
                title="Doliczę weryfikację techniczną",
                contract_id=contract_id,
                client_id=client_id,
            )
            db.add(card)
            await db.commit()
            extra = await card_extras.add(
                db,
                card,
                contract_id=contract_id,
                month=month,
                kind="tech_check",
                amount="200",
                description=None,
                actor_id=None,
                now=local_now(),
            )
            await db.commit()
            assert (extra.status, extra.source, extra.bo_card_id) == (
                "pending",
                "back_office",
                card.id,
            )
            assert extra.description == "Weryfikacja techniczna"
            event = await db.scalar(
                select(BoCardEvent).where(BoCardEvent.card_id == card.id)
            )
            assert event.action == "settlement_extra"
            assert "200" not in event.details["note"]  # kwoty tylko dla Płac

            hidden = await card_extras.card_view(
                db, card, SimpleNamespace(sees_amounts=False, user_id=-1)
            )
            shown = await card_extras.card_view(
                db, card, SimpleNamespace(sees_amounts=True, user_id=-1)
            )
        assert hidden["items"][0]["amount"] is None
        assert shown["items"][0]["amount"] == "200.00"
        assert hidden["contract"]["contract_id"] == contract_id

        card_view = await _card(contract_id, month)
        assert card_view["extras"]["pending_count"] == 1
        assert card_view["extras"]["items"][0]["source_label"] == "back office"
        async with AsyncSessionLocal() as db:
            await db.delete(await db.get(BoCard, card.id))
            await db.commit()
    finally:
        await _cleanup(client_id)


async def test_dopasowanie_miesiaca_faktury_po_kwocie_z_dodatkiem() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    try:
        await _accept(contract_id, month, "10")
        await _add(contract_id, month, kind="referral", amount="700", approve=True)
        first = business_today().replace(day=1)
        async with AsyncSessionLocal() as db:
            amounts = await ci.settlement_amounts(
                db, [contract_id], [month, f"{first - timedelta(days=40):%Y-%m}"]
            )
        assert amounts[(contract_id, month)] == Decimal("10700.00")
    finally:
        await _cleanup(client_id)


async def test_koszty_z_keszu_jako_zgloszony_dodatek_bez_nadpisania_decyzji() -> None:
    client_id, contract_id, _ = await _world()
    month = _month(-1)
    vat = Decimal("1.23")

    async def sync(gross: str):
        async with AsyncSessionLocal() as db:
            extra = await extras.sync_from_kesu(
                db,
                contract_id=contract_id,
                client_id=client_id,
                month=month,
                gross=Decimal(gross),
                vat=vat,
                now=local_now(),
            )
            await db.commit()
            return extra

    async def rows() -> list[ClientSettlementExtra]:
        async with AsyncSessionLocal() as db:
            return list(
                (
                    await db.scalars(
                        select(ClientSettlementExtra).where(
                            ClientSettlementExtra.contract_id == contract_id
                        )
                    )
                ).all()
            )

    try:
        await sync("205.00")
        await sync("205.00")  # ponowny odczyt tego samego KEŚU
        [row] = await rows()
        assert (row.kind, row.status, row.source, row.bill_to_client) == (
            "travel",
            "pending",
            "kesu",
            True,
        )
        assert row.amount == Decimal("166.67")
        await sync("246.00")  # poprawiony KEŚU przed decyzją
        assert (await rows())[0].amount == Decimal("200.00")
        async with AsyncSessionLocal() as db:
            await extras.approve(
                db, row.id, contract_id, actor_id=None, now=local_now()
            )
            await db.commit()
        await sync("0")  # decyzji Finansów KEŚU nie cofa
        [after] = await rows()
        assert (after.status, after.amount) == ("approved", Decimal("200.00"))
    finally:
        await _cleanup(client_id)
