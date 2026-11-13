"""Rozliczenia E4 na bazie: faktury kontraktorów z KSeF.

NIP z kontraktu wiąże fakturę od razu; nieznany NIP z imieniem i nazwiskiem
osoby daje podpowiedź dla Finansów (E4.0); kwota faktury kontra wyliczenie
z RCP daje „W KSeF” albo „Inna kwota”. Osoby, NIP-y, numery i kwoty fikcyjne.
"""

from __future__ import annotations

import random
import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.candidate import Candidate
from app.models.client_settlement import (
    ClientContractorInvoice,
    ClientSettlement,
    ClientSettlementRuleSet,
)
from app.models.contract import Contract
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import service
from app.services.hr.ksef import sync
from tests.test_client_audit_2026_09_24 import _client, _contract

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
COMPANY_NIP = "9990000001"


def _nip() -> str:
    return "998" + "".join(random.choice("0123456789") for _ in range(7))


def _months() -> tuple[str, str, date]:
    """(miesiąc rozliczenia, miesiąc wystawienia, 3. dzień miesiąca wystawienia)."""

    today = business_today()
    issue = today.replace(day=3)
    previous = issue - timedelta(days=5)
    return (
        f"{previous.year}-{previous.month:02d}",
        f"{issue.year}-{issue.month:02d}",
        issue,
    )


def _item(
    nip: str, name: str, net: str, issue: date, *, buyer: str = COMPANY_NIP
) -> dict[str, Any]:
    gross = (Decimal(net) * Decimal("1.23")).quantize(Decimal("0.01"))
    return {
        "ksefNumber": f"{nip}-{issue:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}-AB",
        "invoiceNumber": f"FV {uuid.uuid4().hex[:4]}/{issue:%m/%Y}",
        "issueDate": issue.isoformat(),
        "acquisitionDate": f"{issue.isoformat()}T10:00:00+00:00",
        "seller": {"nip": nip, "name": name},
        "buyer": {"identifier": {"type": "Nip", "value": buyer}, "name": "Spółka"},
        "netAmount": net,
        "vatAmount": str(gross - Decimal(net)),
        "grossAmount": str(gross),
        "currency": "PLN",
        "invoiceType": "Vat",
    }


async def _person(
    client_id: int, *, first: str, last: str, nip: Optional[str] = None
) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        cand = Candidate(name=first, lastname=last, nip=nip)
        db.add(cand)
        await db.commit()
        candidate_id = cand.id
    return await _contract(client_id, candidate_id), candidate_id


async def _settlement(client_id: int, contract_id: int, month: str, cost: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlement(
                contract_id=contract_id,
                client_id=client_id,
                period_month=month,
                status="accepted",
                md_regular=Decimal("20"),
                md_charged=Decimal("20"),
                amount_cost=Decimal(cost),
                amount_revenue=Decimal(cost) * 2,
            )
        )
        await db.commit()


async def _rules(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={
                    "ci.amount": {"level": "block", "params": {"tolerance": "0,00"}},
                    "ci.buyer_nip": {"level": "block", "params": {"nip": COMPANY_NIP}},
                    "ci.payment_days": {"level": "warn", "params": {"days": "14"}},
                },
            )
        )
        await db.commit()


async def _consider(item: dict[str, Any]) -> Optional[str]:
    async with AsyncSessionLocal() as db:
        index = await ci.load_index(db, business_today())
        state = await ci.consider(db, index, item, item["ksefNumber"])
        await db.commit()
        return state


async def _invoice(ksef_number: str) -> ClientContractorInvoice:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        return await db.scalar(
            select(ClientContractorInvoice).where(
                ClientContractorInvoice.ksef_number == ksef_number
            )
        )


async def _cleanup(client_id: int, candidate_ids: list[int]) -> None:
    from sqlalchemy import delete, select

    async with AsyncSessionLocal() as db:
        contracts = select(Contract.id).where(Contract.client_id == client_id)
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.contract_id.in_(contracts)
            )
        )
        await db.execute(
            delete(ClientSettlement).where(ClientSettlement.client_id == client_id)
        )
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.commit()
    from tests.test_client_audit_2026_09_24 import _cleanup as base_cleanup

    await base_cleanup(client_id)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.commit()


def _tag() -> str:
    return uuid.uuid4().hex[:6]


async def test_znany_nip_wiaze_fakture_z_rozliczeniem_poprzedniego_miesiaca() -> None:
    client_id = await _client()
    month, _, issue = _months()
    nip = _nip()
    first, last = f"Ewa{_tag()}", f"Testowa{_tag()}"
    contract_id, candidate_id = await _person(
        client_id, first=first, last=last, nip=f"PL {nip[:3]}-{nip[3:6]}-{nip[6:]}"
    )
    try:
        await _rules(client_id)
        await _settlement(client_id, contract_id, month, "20000.00")
        item = _item(nip, f"{first} {last} Usługi", "20000.00", issue)
        assert await _consider(item) == ci.KNOWN
        saved = await _invoice(item["ksefNumber"])
        assert (saved.contract_id, saved.period_month) == (contract_id, month)

        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
            card = await service.detail(db, contract_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["contractor_invoice"] == ci.IN_KSEF
        block = card["contractor_invoice"]
        assert block["state"] == ci.IN_KSEF
        titles = [c["title"] for c in block["checks"]]
        assert "Kwota równa wyliczeniu z RCP" in titles
        assert "NIP nabywcy zgodny" in titles
        due = (issue + timedelta(days=14)).strftime("%d.%m.%Y")
        assert f"Termin płatności: {due}" in titles
        assert block["invoices"][0]["net_amount"] == "20000.00"

        # Bez dostępu do kwot: stan zostaje, kwot i porównania nie ma.
        async with AsyncSessionLocal() as db:
            hidden = await service.detail(db, contract_id, month, amounts=False)
        assert hidden["contractor_invoice"]["invoices"][0]["net_amount"] is None
        assert all(
            "wyliczeniu" not in c["title"]
            for c in hidden["contractor_invoice"]["checks"]
        )

        # Ten sam numer KSeF drugi raz: bez drugiego wiersza.
        assert await _consider(item) == ci.KNOWN
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_inna_kwota_i_inny_nabywca() -> None:
    client_id = await _client()
    month, _, issue = _months()
    nip = _nip()
    contract_id, candidate_id = await _person(
        client_id, first=f"Ola{_tag()}", last=f"Próbna{_tag()}", nip=nip
    )
    try:
        await _rules(client_id)
        await _settlement(client_id, contract_id, month, "20000.00")
        item = _item(nip, "Firma bez nazwiska", "21000.00", issue, buyer="9990000002")
        assert await _consider(item) == ci.KNOWN
        async with AsyncSessionLocal() as db:
            card = await service.detail(db, contract_id, month, amounts=True)
        block = card["contractor_invoice"]
        assert block["state"] == ci.DIFFERS
        fails = {c["title"]: c for c in block["checks"] if c["state"] == "fail"}
        assert (
            "różnica 1 000,00 zł" in fails["Inna kwota niż wyliczenie z RCP"]["detail"]
        )
        assert "NIP nabywcy inny niż w regułach klienta" in fails
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_podpowiedz_nip_odrzucona_nie_wraca() -> None:
    client_id = await _client()
    month, _, issue = _months()
    first, last = f"Jan{_tag()}", f"Fikcyjny{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip = _nip()
    try:
        await _settlement(client_id, contract_id, month, "15000.00")
        item = _item(nip, f"{last.upper()} {first.upper()} IT", "15000.00", issue)
        assert await _consider(item) == ci.SUGGESTED
        async with AsyncSessionLocal() as db:
            view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in view["rows"] if r["contract_id"] == contract_id)
        assert row["contractor_invoice"] == ci.NIP_CHECK
        async with AsyncSessionLocal() as db:
            card = await service.detail(db, contract_id, month, amounts=True)
        titles = [c["title"] for c in card["contractor_invoice"]["checks"]]
        assert titles == ["NIP z KSeF do zatwierdzenia"]  # bez „Czeka na fakturę”

        saved = await _invoice(item["ksefNumber"])
        async with AsyncSessionLocal() as db:
            await ci.reject_nip(db, saved.id, ACTOR, local_now())
            await db.commit()
        again = _item(nip, f"{first} {last}", "15000.00", issue)
        assert await _consider(again) is None
        async with AsyncSessionLocal() as db:
            candidate = await db.get(Candidate, candidate_id)
            assert candidate.nip is None
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_zatwierdzony_nip_trafia_do_osoby_i_wiaze_kolejne_faktury() -> None:
    client_id = await _client()
    month, _, issue = _months()
    first, last = f"Iza{_tag()}", f"Wzorcowa{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip = _nip()
    try:
        await _settlement(client_id, contract_id, month, "8640.00")
        item = _item(nip, f"{first} {last}", "8640.00", issue)
        assert await _consider(item) == ci.SUGGESTED
        saved = await _invoice(item["ksefNumber"])
        async with AsyncSessionLocal() as db:
            await ci.approve_nip(db, saved.id, ACTOR, local_now())
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (await db.get(Candidate, candidate_id)).nip == nip
            card = await service.detail(db, contract_id, month, amounts=True)
        assert card["contractor_invoice"]["state"] == ci.IN_KSEF
        assert (await _invoice(item["ksefNumber"])).nip_state == ci.CONFIRMED

        # Druga decyzja o tej samej fakturze: odmowa.
        async with AsyncSessionLocal() as db:
            with pytest.raises(ci.ContractorInvoiceError):
                await ci.approve_nip(db, saved.id, ACTOR, local_now())

        later = _item(nip, "Zupełnie inna nazwa", "100.00", issue + timedelta(days=30))
        assert await _consider(later) == ci.KNOWN
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_zatwierdzenie_odmawia_gdy_osoba_ma_inny_nip() -> None:
    client_id = await _client()
    month, _, issue = _months()
    first, last = f"Ala{_tag()}", f"Sporna{_tag()}"
    contract_id, candidate_id = await _person(client_id, first=first, last=last)
    nip = _nip()
    try:
        item = _item(nip, f"{first} {last}", "500.00", issue)
        assert await _consider(item) == ci.SUGGESTED
        async with AsyncSessionLocal() as db:
            (await db.get(Candidate, candidate_id)).nip = _nip()
            await db.commit()
        saved = await _invoice(item["ksefNumber"])
        async with AsyncSessionLocal() as db:
            with pytest.raises(ci.ContractorInvoiceError) as err:
                await ci.approve_nip(db, saved.id, ACTOR, local_now())
        assert "inny NIP" in err.value.message
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_imiennicy_rozstrzyga_kwota_a_bez_niej_brak_podpowiedzi() -> None:
    client_id = await _client()
    month, _, issue = _months()
    first, last = f"Piotr{_tag()}", f"Dwojak{_tag()}"
    first_id, cand_a = await _person(client_id, first=first, last=last)
    second_id, cand_b = await _person(client_id, first=first, last=last)
    try:
        await _settlement(client_id, first_id, month, "1000.00")
        await _settlement(client_id, second_id, month, "2000.00")
        hit = _item(_nip(), f"{first} {last}", "2000.00", issue)
        assert await _consider(hit) == ci.SUGGESTED
        assert (await _invoice(hit["ksefNumber"])).contract_id == second_id
        miss = _item(_nip(), f"{first} {last}", "3000.00", issue)
        assert await _consider(miss) is None
    finally:
        await _cleanup(client_id, [cand_a, cand_b])


async def test_dostawca_firmy_nie_jest_kontraktorem() -> None:
    item = _item(_nip(), "Dostawca Prądu S.A.", "120.00", business_today())
    assert await _consider(item) is None


async def test_pobieranie_zapisuje_kontraktora_zamiast_kosztu() -> None:
    client_id = await _client()
    month, _, issue = _months()
    nip = _nip()
    contract_id, candidate_id = await _person(
        client_id, first=f"Kuba{_tag()}", last=f"Pobrany{_tag()}", nip=nip
    )
    try:
        item = _item(nip, "Ktokolwiek", "10.00", issue)
        async with AsyncSessionLocal() as db:
            run = SimpleNamespace(
                db=db,
                contractors=await ci.load_index(db, business_today()),
                counts=Counter(),
            )
            assert await sync._store_contractor(run, item, item["ksefNumber"]) is True
            assert run.counts["contractors"] == 1
            other = _item(_nip(), "Dostawca", "10.00", issue)
            assert (
                await sync._store_contractor(run, other, other["ksefNumber"]) is False
            )
        assert (await _invoice(item["ksefNumber"])).contract_id == contract_id
        assert (await _invoice(item["ksefNumber"])).period_month == month
    finally:
        await _cleanup(client_id, [candidate_id])


async def test_panel_konsultanta_dane_do_faktury_a_potem_faktura_w_ksef() -> None:
    from app.services.client_settlements import consultant
    from tests.test_client_settlements_consultant_db import _module, _restore

    previous = await _module(True)
    client_id = await _client()
    month, _, issue = _months()
    year, mon = (int(x) for x in month.split("-"))
    nip = _nip()
    contract_id, candidate_id = await _person(
        client_id, first=f"Ewa{_tag()}", last=f"Panelowa{_tag()}", nip=nip
    )
    try:
        await _rules(client_id)
        await _settlement(client_id, contract_id, month, "20000.00")
        async with AsyncSessionLocal() as db:
            before = await consultant.view(db, contract_id, client_id, year, mon)
        invoice = before["invoice"]
        assert invoice["item"]["net"] == "20000.00"
        assert invoice["item"]["description"].startswith("Usługi zgodnie z umową za ")
        assert invoice["buyer"]["nip"]
        assert invoice["ksef"] is None

        await _consider(_item(nip, "Ktokolwiek", "20000.00", issue))
        async with AsyncSessionLocal() as db:
            after = await consultant.view(db, contract_id, client_id, year, mon)
        ksef = after["invoice"]["ksef"]
        assert ksef["state"] == ci.IN_KSEF
        due = issue + timedelta(days=14)
        assert after["label"] == f"Faktura w KSeF: płatność do {due:%d.%m.%Y}"
        assert after["todo"] == []

        await _consider(_item(nip, "Ktokolwiek", "500.00", issue))
        async with AsyncSessionLocal() as db:
            wrong = await consultant.view(db, contract_id, client_id, year, mon)
        assert wrong["invoice"]["ksef"]["state"] == ci.DIFFERS
        assert wrong["todo"] == ["Wystaw korektę faktury"]
    finally:
        await _cleanup(client_id, [candidate_id])
        await _restore(previous)


async def test_korekty_z_ksef_ostrzezenia_na_karcie_osoby(monkeypatch) -> None:
    """Przypadek z testu Finansów 13.11.2026 (zanonimizowany) od metadanych KSeF
    przez pobranie XML-a korekt i białą listę do karty osoby."""

    import httpx

    from app.services.client_settlements import contractor_details
    from app.services.hr import white_list
    from app.services.hr.ksef.client import KsefApiError
    from tests.test_client_settlements_invoice_chain import case_for

    client_id = await _client()
    # Biała lista sprawdza sumę kontrolną NIP-u.
    while True:
        digits = [random.randint(0, 9) for _ in range(9)]
        check = sum(w * d for w, d in zip((6, 5, 7, 2, 3, 4, 5, 6, 7), digits)) % 11
        if check < 10:
            nip = "".join(map(str, digits)) + str(check)
            break
    first, last = f"Adam{_tag()}", f"Przykładowy{_tag()}"
    contract_id, candidate_id = await _person(
        client_id, first=first, last=last, nip=nip
    )
    documents = case_for(nip)

    class Source:
        async def download_invoice(self, ksef_number: str) -> bytes:
            for entry in documents:
                if entry[2] == ksef_number:
                    return entry[6]
            raise KsefApiError("not_ready")

    def registry(request: httpx.Request) -> httpx.Response:
        meta = {"requestId": "req-1", "requestDateTime": "13-11-2026 10:00:00"}
        return httpx.Response(200, json={"result": {"subject": None, **meta}})

    transport = httpx.MockTransport(registry)
    monkeypatch.setattr(
        white_list,
        "_http_client",
        lambda base_url: httpx.AsyncClient(base_url=base_url, transport=transport),
    )
    monkeypatch.setattr(white_list.settings, "WHITE_LIST_MODE", "live")
    # Wspólna baza testów: inne wiersze nie mogą zjeść limitów przebiegu.
    monkeypatch.setattr(contractor_details, "MAX_DOWNLOADS", 1000)
    monkeypatch.setattr(contractor_details, "WHITELIST_PER_RUN", 1000)
    monkeypatch.setattr(contractor_details, "WHITELIST_DAILY_SHARE", 1000)
    monkeypatch.setattr(white_list, "DAILY_LIMITS", {"search": 1000, "check": 1000})
    white_list.reset_memory()
    today, now = date(2026, 11, 13), local_now()
    try:
        await _rules(client_id)
        await _settlement(client_id, contract_id, "2026-10", "8400.00")
        for number, issue, ksef, net, vat, gross, _xml in documents:
            item = _item(nip, f"{first} {last}", net, date.fromisoformat(issue))
            item.update(
                ksefNumber=ksef,
                invoiceNumber=number,
                vatAmount=vat,
                grossAmount=gross,
                invoiceType="Kor" if "/K/" in number else "Vat",
            )
            assert await _consider(item) == ci.KNOWN
        async with AsyncSessionLocal() as db:
            counts = await contractor_details.fetch_details(
                db, Source(), today=today, budget=1000
            )
            await contractor_details.check_whitelist(db, today=today, now=now)
            await db.commit()
        assert counts["downloads"] >= 7
        stored = await _invoice(documents[1][2])
        assert stored.details["state"] == "ok"
        assert stored.details["corrected"][0]["ksef_number"] == documents[0][2]
        assert stored.vat_whitelist["status"] == "absent"

        async with AsyncSessionLocal() as db:
            card = await service.detail(db, contract_id, "2026-10", amounts=True)
        block = card["contractor_invoice"]
        assert block["state"] == ci.IN_KSEF
        titles = [c["title"] for c in block["checks"]]
        assert "Kwota równa wyliczeniu z RCP" in titles
        for title in (
            "Korekty zostawiają 72,00 zł VAT",
            "Zły stan przed w korekcie 2/K/11/2026",
            "Zły stan przed w korekcie 3/K/11/2026",
            "Zły numer faktury korygowanej w 5/K/11/2026",
            "Zły numer faktury korygowanej w 6/K/11/2026",
            "Sprzedawca nie jest podatnikiem VAT, VAT nie do odliczenia",
        ):
            assert title in titles
        assert "Korekta 1/K/11/2026 bez zmian kwot" in titles
    finally:
        white_list.reset_memory()
        await _cleanup(client_id, [candidate_id])
