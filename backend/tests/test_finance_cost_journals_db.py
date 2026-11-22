"""Dzienniki kolejki „Koszty” i wstępna weryfikacja kontraktorów (22.11.2026) — z bazą.

Dziennik z kategorii (filtr i liczniki), kategoria dokumentu wydatku
podpowiadana z dziennika eBI24 i z ręcznej decyzji przy wcześniejszej fakturze
sprzedawcy (ręczna wygrywa, wpis tknięty zostaje), krok „Zweryfikowane” faktur
kontraktorów tylko dla listy „Weryfikujący kontraktorów” albo „Księgowych”
(osoba spoza listy = 403, też przez zmianę kategorii), „Gotowa” tylko dla
„Księgowych”, zgodność faktury z rozliczeniem miesiąca kontraktora i paczka
eksportu jednego dziennika. Osoby, NIP-y i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.api import finance_ledger, finance_posting
from app.core.database import AsyncSessionLocal
from app.models.client_settlement import (
    ClientContractorInvoice,
    ClientSettlement,
    ClientSettlementRuleSet,
)
from app.models.finance_archive import FinanceArchiveDocument
from app.models.finance_ledger import (
    FinanceCostEntry,
    FinanceCostEntryEvent,
    FinanceCounterparty,
)
from app.models.finance_posting import FinancePostingBatch
from app.models.hr_approval import ApprovalDocument
from app.models.user import User
from app.services.finance_ledger import costs as ledger
from app.services.ledger import settings as ledger_settings
from app.services.hr.approvals import cost_invoices
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract
from tests.test_client_audit_2026_09_24 import _cleanup as cleanup_client
from tests.test_finance_ledger_db import (
    COSTS,
    _headers,
    _ksef_number,
    _nip,
    _set,
    _user,
)
from tests.test_finance_ledger_db import world  # noqa: F401  (fixture ``world``)

POSTING = "/api/finance/posting"
MONTH = "2026-11"


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(finance_ledger.costs_router, prefix=COSTS)
    app.include_router(finance_posting.router, prefix=POSTING)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def extra():
    """Własni sprzedawcy, archiwum eBI24 i dwie osoby Finansów (sprząta po sobie)."""

    seed = random.randint(10_000_000, 900_000_000)
    nips = [_nip(seed + step * 3_100) for step in range(1, 5)]
    async with AsyncSessionLocal() as db:
        outsider = await _user(db, "finance")
        verifier = await _user(db, "finance")
        await db.commit()
    state = {
        "nips": nips,
        "outsider": outsider,
        "verifier": verifier,
        "archive": [],
        "clients": [],
    }
    yield state
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceCostEntry).where(FinanceCostEntry.seller_nip.in_(nips))
        )
        await db.execute(
            delete(FinanceCounterparty).where(FinanceCounterparty.id_value.in_(nips))
        )
        await db.execute(
            delete(ApprovalDocument).where(ApprovalDocument.seller_nip.in_(nips))
        )
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.seller_nip.in_(nips)
            )
        )
        await db.execute(
            delete(FinanceArchiveDocument).where(
                FinanceArchiveDocument.id.in_(state["archive"] or [0])
            )
        )
        for client_id in state["clients"]:
            await db.execute(
                delete(ClientSettlement).where(ClientSettlement.client_id == client_id)
            )
            await db.execute(
                delete(ClientSettlementRuleSet).where(
                    ClientSettlementRuleSet.client_id == client_id
                )
            )
        await db.execute(delete(User).where(User.id.in_([outsider.id, verifier.id])))
        await db.commit()
    for client_id in state["clients"]:
        await cleanup_client(client_id)


async def _lists(world, *, verifiers: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        current = await ledger_settings.load(db)
    await _set(
        ledger_settings.SETTING_KEY,
        {
            **ledger_settings.to_json(current),
            "accountants": [world["accountant"].id],
            "cost_verifiers": verifiers,
        },
    )


async def _expense(nip: str, number: str, *, net: str = "100.00") -> int:
    ksef = _ksef_number(nip)
    gross = f"{Decimal(net) * Decimal('1.23'):.2f}"
    item = {
        "ksefNumber": ksef,
        "invoiceNumber": number,
        "issueDate": "2026-11-03",
        "seller": {"nip": nip, "name": "Dostawca Testowy"},
        "netAmount": net,
        "vatAmount": f"{Decimal(gross) - Decimal(net):.2f}",
        "grossAmount": gross,
        "currency": "PLN",
    }
    async with AsyncSessionLocal() as db:
        await cost_invoices.store(
            db, item, ksef_number=ksef, now=datetime.now(timezone.utc), match=False
        )
        await ledger.enqueue_ksef(db, ksef)
        # Koniec przebiegu KSeF: podpowiedź kategorii z historii sprzedawcy.
        await ledger.catch_up(db)
        await db.commit()
        document_id = await db.scalar(
            select(ApprovalDocument.id).where(ApprovalDocument.ksef_number == ksef)
        )
        return await db.scalar(
            select(FinanceCostEntry.id).where(
                FinanceCostEntry.source_type == "approval_document",
                FinanceCostEntry.source_id == document_id,
            )
        )


async def _archive(extra, nip: str, folder: str, day: date) -> None:
    key = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        row = FinanceArchiveDocument(
            source="ebi24",
            source_id=key[:24],
            schema_name="COST_INVOICE",
            kind="cost",
            issue_date=day,
            folder=folder,
            file_type="pdf",
            file_path=f"test/{key}.pdf",
            file_sha256=hashlib.sha256(key.encode()).hexdigest(),
            meta={"_partner": {"officialId": f"PL {nip}", "officialIdType": "NIP"}},
        )
        db.add(row)
        await db.commit()
        extra["archive"].append(row.id)


async def _entry(entry_id: int) -> FinanceCostEntry:
    async with AsyncSessionLocal() as db:
        return await db.get(FinanceCostEntry, entry_id)


async def _act(client, user, ids: list[int], action: str):
    return await client.post(
        f"{COSTS}/actions",
        json={"ids": ids, "action": action},
        headers=_headers(user),
    )


async def _category(client, user, entry_id: int, category: str):
    return await client.patch(
        f"{COSTS}/{entry_id}", json={"category": category}, headers=_headers(user)
    )


# ── Dzienniki ────────────────────────────────────────────────────────────────


async def test_dziennik_z_kategorii_filtr_i_liczniki(world, extra, client) -> None:
    nip = extra["nips"][0]
    office = await _expense(nip, "D/1/11")
    other = await _expense(nip, "D/2/11")
    contractor = await _expense(nip, "D/3/11")
    accountant = world["accountant"]
    assert (await _category(client, accountant, other, "benefit")).status_code == 200
    assert (
        await _category(client, accountant, contractor, "contractor")
    ).status_code == 200

    async def listed(journal: str | None) -> dict:
        params = {"stage": "received", "q": nip}
        if journal:
            params["journal"] = journal
        response = await client.get(COSTS, params=params, headers=_headers(accountant))
        assert response.status_code == 200, response.text
        return response.json()

    every = await listed(None)
    assert {row["id"]: row["journal"] for row in every["items"]} == {
        office: "office",
        other: "purchases",
        contractor: "contractors",
    }
    assert every["journal_counts"] == {"contractors": 1, "purchases": 1, "office": 1}
    assert every["counts"]["received"] == 3
    only = await listed("purchases")
    assert [row["id"] for row in only["items"]] == [other]
    assert only["items"][0]["journal_label"] == "Zakupy pozostałe"
    # Liczniki dzienników nie zależą od wybranego dziennika, etapu — tak.
    assert only["journal_counts"] == every["journal_counts"]
    assert only["counts"]["received"] == 1
    bad = await client.get(
        COSTS, params={"journal": "revenue"}, headers=_headers(accountant)
    )
    assert bad.status_code == 422


async def test_kategoria_z_dziennika_ebi24_i_z_recznej_decyzji(
    world, extra, client
) -> None:
    nip, untouched_nip, none_nip = extra["nips"][:3]
    await _archive(extra, nip, "BIURO", date(2025, 3, 1))
    await _archive(extra, nip, "Kontraktorzy", date(2026, 9, 30))
    first = await _expense(nip, "K/1/11")
    entry = await _entry(first)
    assert entry.category == "contractor"
    card = (
        await client.get(f"{COSTS}/{first}", headers=_headers(world["accountant"]))
    ).json()
    suggestion = card["history"][-1]
    assert suggestion["action"] == "category"
    assert suggestion["detail"]["source"] == "ebi24"
    assert suggestion["detail"]["folder"] == "Kontraktorzy"
    assert suggestion["actor"] == "NEXUS — dziennik sprzedawcy w eBI24"
    assert card["journal"] == "contractors"

    # Finanse poprawiają kategorię: następna faktura sprzedawcy idzie za nimi,
    # mimo że eBI24 trzymało go w „Kontraktorach”.
    changed = await _category(client, world["accountant"], first, "other")
    assert changed.status_code == 200
    second = await _expense(nip, "K/2/11")
    assert (await _entry(second)).category == "other"
    async with AsyncSessionLocal() as db:
        detail = await db.scalar(
            select(FinanceCostEntryEvent.detail).where(
                FinanceCostEntryEvent.entry_id == second,
                FinanceCostEntryEvent.action == "category",
            )
        )
    assert detail == {"from": "office", "to": "other", "source": "history"}

    # Wpis już zweryfikowany nie dostaje podpowiedzi (archiwum doszło później);
    # sprzedawca bez historii zostaje z kategorią źródła.
    kept = await _expense(untouched_nip, "Z/1/11")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == kept)
            .values(stage="verified")
        )
        await db.commit()
    await _archive(extra, untouched_nip, "Zakupy pozostałe", date(2026, 10, 1))
    late = await _expense(none_nip, "N/1/11")
    assert (await _entry(late)).category == "office"
    assert (await _entry(kept)).category == "office"

    # Kolejny przebieg nie rusza wpisu, który ma już zmianę kategorii.
    await _archive(extra, nip, "BENEFITY", date(2026, 11, 1))
    async with AsyncSessionLocal() as db:
        await ledger.catch_up(db)
        await db.commit()
    assert (await _entry(first)).category == "other"
    assert (await _entry(second)).category == "other"


# ── Wstępna weryfikacja kontraktorów i akceptacja księgowej ──────────────────


async def test_weryfikacja_kontraktorow_tylko_dla_listy(world, extra, client) -> None:
    outsider, verifier, accountant = (
        extra["outsider"],
        extra["verifier"],
        world["accountant"],
    )
    await _lists(world, verifiers=[verifier.id])
    nip = extra["nips"][0]
    contractor = await _expense(nip, "K/7/11")
    office = await _expense(extra["nips"][1], "B/7/11")
    assert (
        await _category(client, accountant, contractor, "contractor")
    ).status_code == 200

    # Przyjęcie z poczekalni robi każdy z „Modułem Finanse”.
    assert (
        await _act(client, outsider, [contractor, office], "accept")
    ).status_code == 200

    # Wyjęcie faktury z „Kontraktorów” przed weryfikacją też jest krokiem listy —
    # inaczej PATCH na „Inne” i „Zweryfikuj” omijałyby weryfikującego.
    escaped = await _category(client, outsider, contractor, "other")
    assert escaped.status_code == 403
    assert (await _entry(contractor)).category == "contractor"

    denied = await _act(client, outsider, [contractor], "verify")
    assert denied.status_code == 403
    assert "Weryfikujący kontraktorów" in denied.json()["detail"]
    mixed = await _act(client, outsider, [contractor, office], "verify")
    assert mixed.status_code == 200
    assert mixed.json()["changed"] == 1
    assert mixed.json()["refused"][0]["id"] == contractor
    assert mixed.json()["refused"][0]["status"] == 403

    card = (
        await client.get(f"{COSTS}/{contractor}", headers=_headers(outsider))
    ).json()
    assert card["can"] == {"verify": False, "ready": False}
    card = (
        await client.get(f"{COSTS}/{contractor}", headers=_headers(verifier))
    ).json()
    assert card["can"] == {"verify": True, "ready": False}

    assert (await _act(client, verifier, [contractor], "verify")).status_code == 200
    assert (await _entry(contractor)).stage == "verified"

    # Spoza listy nie cofnie weryfikacji ani nie wyjmie faktury z „Kontraktorów”.
    assert (await _act(client, outsider, [contractor], "back")).status_code == 403
    moved = await _category(client, outsider, contractor, "other")
    assert moved.status_code == 403
    # …ani nie wstawi zweryfikowanej faktury biura do „Kontraktorów”.
    assert (await _category(client, outsider, office, "contractor")).status_code == 403
    assert (await _entry(contractor)).category == "contractor"

    # „Gotowa do księgowania”: weryfikujący i osoba spoza list — 403, „Księgowi” — dalej
    # (tu 409, bo dekret bez reguły jest niekompletny; bramka listy przeszła).
    for user in (verifier, outsider):
        refused = await _act(client, user, [contractor, office], "ready")
        assert refused.status_code == 403
        assert "„Księgowi”" in refused.json()["detail"]
    allowed = await _act(client, accountant, [office], "ready")
    assert allowed.status_code == 409


async def test_liste_weryfikujacych_ustawia_admin(world, extra) -> None:
    from app.api import ledger as ledger_api

    app = FastAPI()
    app.include_router(ledger_api.router, prefix="/api/accounting")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        url = "/api/accounting/config/cost-verifiers"
        body = {"user_ids": [extra["verifier"].id]}
        denied = await c.put(url, json=body, headers=_headers(world["accountant"]))
        assert denied.status_code == 403
        no_module = await c.put(
            url,
            json={"user_ids": [world["recruiter"].id]},
            headers=_headers(world["admin"]),
        )
        assert no_module.status_code == 422
        assert "Modułu Finanse" in no_module.json()["detail"]
        saved = await c.put(url, json=body, headers=_headers(world["admin"]))
        assert saved.status_code == 200, saved.text
        assert saved.json()["cost_verifiers"] == [extra["verifier"].id]
        config = await c.get("/api/accounting/config", headers=_headers(world["admin"]))
        assert config.json()["cost_verifiers"] == [extra["verifier"].id]


# ── Zgodność z rozliczeniem miesiąca kontraktora ─────────────────────────────


async def _contractor_invoice(
    extra,
    nip: str,
    *,
    net: str,
    settlement_cost: str | None,
    contract_id: int | None = None,
    nip_state: str = "known",
) -> int:
    client_id = None
    if contract_id is None:
        client_id = await _client()
        extra["clients"].append(client_id)
        contract_id = await _contract(client_id, await _candidate())
        extra.setdefault("contracts", {})[nip] = contract_id
    async with AsyncSessionLocal() as db:
        if client_id is not None:
            db.add(
                ClientSettlementRuleSet(
                    client_id=client_id, effective_from="2020-01", rules={}
                )
            )
        if settlement_cost is not None and client_id is not None:
            db.add(
                ClientSettlement(
                    contract_id=contract_id,
                    client_id=client_id,
                    period_month="2026-10",
                    status="accepted",
                    amount_cost=Decimal(settlement_cost),
                    checks=[],
                )
            )
        invoice = ClientContractorInvoice(
            ksef_number=_ksef_number(nip),
            seller_nip=nip,
            seller_name="Kontraktor Testowy",
            invoice_number=f"K/{random.randint(1, 99999)}/10/2026",
            issue_date=date(2026, 11, 2),
            net_amount=Decimal(net),
            vat_amount=Decimal(net) * Decimal("0.23"),
            gross_amount=Decimal(net) * Decimal("1.23"),
            contract_id=contract_id,
            period_month="2026-10",
            nip_state=nip_state,
        )
        db.add(invoice)
        await db.commit()
        await ledger.catch_up(db)
        await db.commit()
        return await db.scalar(
            select(FinanceCostEntry.id).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.source_id == invoice.id,
            )
        )


async def test_faktura_kontraktora_a_rozliczenie_miesiaca(world, extra, client) -> None:
    headers = _headers(world["accountant"])
    equal = await _contractor_invoice(
        extra, extra["nips"][0], net="1000.00", settlement_cost="1000.00"
    )
    other = await _contractor_invoice(
        extra, extra["nips"][1], net="1000.00", settlement_cost="900.00"
    )
    missing = await _contractor_invoice(
        extra, extra["nips"][2], net="1000.00", settlement_cost=None
    )
    expense = await _expense(extra["nips"][3], "E/1/11")
    await _category(client, world["accountant"], expense, "contractor")

    card = (await client.get(f"{COSTS}/{equal}", headers=headers)).json()
    assert card["settlement"]["state"] == "match"
    assert card["settlement"]["month"] == "10.2026"
    assert card["settlement"]["rcp"] == "RCP przyjęte"
    assert card["settlement"]["amount_cost"] == "1000.00"
    assert any(
        check["title"] == "Kwota równa wyliczeniu z RCP"
        for check in card["settlement"]["checks"]
    )
    card = (await client.get(f"{COSTS}/{other}", headers=headers)).json()
    assert card["settlement"]["state"] == "differs"
    assert any(
        "różnica" in (check.get("detail") or "")
        for check in card["settlement"]["checks"]
    )

    listed = await client.get(
        COSTS, params={"stage": "received", "journal": "contractors"}, headers=headers
    )
    states = {
        row["id"]: row["settlement"]["state"]
        for row in listed.json()["items"]
        if row["id"] in (equal, other, missing, expense)
    }
    assert states == {
        equal: "match",
        other: "differs",
        missing: "missing",
        expense: "no_contract",
    }
    # Faktura z odrzuconym albo niezatwierdzonym NIP-em przy tym samym kontrakcie
    # nie dostaje „zgodnej” od innej, przypiętej faktury tego miesiąca.
    contract_id = extra["contracts"][extra["nips"][0]]
    for state, expected in (("rejected", "nip_rejected"), ("suggested", "nip_check")):
        foreign = await _contractor_invoice(
            extra,
            extra["nips"][0],
            net="5000.00",
            settlement_cost=None,
            contract_id=contract_id,
            nip_state=state,
        )
        card = (await client.get(f"{COSTS}/{foreign}", headers=headers)).json()
        assert card["settlement"]["state"] == expected, state
        assert not any(
            check["state"] == "ok" for check in card["settlement"].get("checks") or []
        )
    again = (await client.get(f"{COSTS}/{equal}", headers=headers)).json()
    assert again["settlement"]["state"] == "match"
    office_row = await _expense(extra["nips"][3], "E/2/11")
    plain = (await client.get(f"{COSTS}/{office_row}", headers=headers)).json()
    # Po ręcznej decyzji „Kontraktorzy” u tego sprzedawcy — następna też tam.
    assert plain["journal"] == "contractors"


# ── Paczka eksportu jednego dziennika ────────────────────────────────────────


async def test_eksport_dzieli_na_dzienniki(world, extra, client) -> None:
    accountant = world["accountant"]
    headers = _headers(accountant)
    nip = extra["nips"][0]
    office = await _expense(nip, "P/1/11")
    contractor = await _expense(nip, "P/2/11")
    await _category(client, accountant, contractor, "contractor")
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip",
            id_value=nip,
            name="Dostawca Testowy",
            cost_account="201-2-977",
        )
        db.add(party)
        await db.flush()
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.seller_nip == nip)
            .values(counterparty_id=party.id)
        )
        await db.commit()
        party_id = party.id
    for category in ("office", "contractor"):
        rule = await client.post(
            f"{POSTING}/rules",
            json={
                "category": category,
                "counterparty_id": party_id,
                "cost_account": "402-202",
                "vat_account": "221",
                "deduction": "full",
                "register": "purchase",
                "doc_type": "FVZ",
                "service_label": "Usługi",
                "description_template": "{usługa} {MM}/{RRRR}",
            },
            headers=headers,
        )
        assert rule.status_code == 201, rule.text
    for action in ("accept", "verify", "ready"):
        done = await _act(client, accountant, [office, contractor], action)
        assert done.status_code == 200, done.text
        assert done.json()["changed"] == 2

    try:
        preview = (
            await client.get(
                f"{POSTING}/export", params={"month": MONTH}, headers=headers
            )
        ).json()
        mine = {
            entry["id"]: entry["journal"]
            for register in preview["registers"]
            for entry in register["entries"]
            if entry["id"] in (office, contractor)
        }
        assert mine == {office: "office", contractor: "contractors"}
        assert [item["journal"] for item in preview["journals"]] == [
            "contractors",
            "purchases",
            "office",
        ]

        created = await client.post(
            f"{POSTING}/batches",
            json={"month": MONTH, "format": "neutral_csv", "journal": "contractors"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        batch = created.json()
        assert contractor in batch["entry_ids"] and office not in batch["entry_ids"]
        assert "-kontraktorzy-" in batch["file_name"]
        content = (
            await client.get(f"{POSTING}/batches/{batch['id']}/file", headers=headers)
        ).content.decode("utf-8-sig")
        header = content.splitlines()[0].split(";")
        assert header[:2] == ["Rejestr", "Dziennik"]
        assert all(
            line.split(";")[1] == "Kontraktorzy" for line in content.splitlines()[1:]
        )
        # Faktura biura zostaje na liście do następnej paczki.
        again = (
            await client.get(
                f"{POSTING}/export", params={"month": MONTH}, headers=headers
            )
        ).json()
        left = [e["id"] for r in again["registers"] for e in r["entries"]]
        assert office in left and contractor not in left
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(FinanceCostEntry)
                .where(FinanceCostEntry.seller_nip == nip)
                .values(batch_id=None)
            )
            await db.execute(
                delete(FinancePostingBatch).where(
                    FinancePostingBatch.created_by == accountant.id
                )
            )
            await db.commit()
