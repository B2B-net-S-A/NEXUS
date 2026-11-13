"""Dekret i eksport do Symfonii FK (E2, 0697) — trasy z bazą.

Zasiew planu kont i reguły kontraktora, reguła kontrahenta przed ogólną,
dekret przy weryfikacji, brak konta kontrahenta blokuje „Gotowa do
księgowania”, ręczna korekta z bilansem, paczka eksportu (zawartość pliku,
neutralizacja formuł, to samo pobranie dwa razy, zaksięgowanie, blokada po
zaksięgowaniu, anulowanie), faktury osób zespołu poza eksportem osoby bez
Płac, 403 bez „Modułu Finanse”. Osoby, NIP-y i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.api import finance_ledger, finance_posting
from app.core.database import AsyncSessionLocal
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.fx_rate import FxRate
from app.models.finance_posting import (
    FinanceAccount,
    FinancePostingBatch,
    FinancePostingRule,
)
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import PayrollInvoice
from app.services.finance_ledger import costs as ledger
from app.services.hr.approvals import cost_invoices
from tests.test_finance_ledger_db import (  # noqa: F401  (fixture ``world``)
    COSTS,
    _entry,
    _headers,
    _ksef_number,
    world,
)

POSTING = "/api/finance/posting"
#: Wpisy testów wpływają w listopadzie 2026 (``received_at`` z KSeF).
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
async def clean_batches():
    """Paczki z tego testu (wpisy giną z ``world``; paczki zostałyby)."""

    async with AsyncSessionLocal() as db:
        before = set(await db.scalars(select(FinancePostingBatch.id)))
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.batch_id.is_not(None))
            .where(FinanceCostEntry.batch_id.not_in(list(before) or [0]))
            .values(batch_id=None)
        )
        await db.execute(
            delete(FinancePostingBatch).where(
                FinancePostingBatch.id.not_in(list(before) or [0])
            )
        )
        await db.commit()


async def _expense(
    world,
    *,
    number: str,
    net: str,
    vat: str,
    gross: str,
    currency: str = "PLN",
    issued: str = "2026-11-03",
) -> int:
    ksef = _ksef_number(world["nips"]["supplier"])
    item = {
        "ksefNumber": ksef,
        "invoiceNumber": number,
        "issueDate": issued,
        "seller": {"nip": world["nips"]["supplier"], "name": "Dostawca Testowy"},
        "netAmount": net,
        "vatAmount": vat,
        "grossAmount": gross,
        "currency": currency,
    }
    async with AsyncSessionLocal() as db:
        await cost_invoices.store(
            db, item, ksef_number=ksef, now=datetime.now(timezone.utc), match=False
        )
        await ledger.enqueue_ksef(db, ksef)
        await db.commit()
        document_id = await db.scalar(
            select(ApprovalDocument.id).where(ApprovalDocument.ksef_number == ksef)
        )
    return (await _entry("approval_document", document_id)).id


async def _supplier(world, *, account: str | None) -> int:
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip",
            id_value=world["nips"]["supplier"],
            name="Dostawca Testowy",
            symfonia_partner_id=f"T{uuid.uuid4().hex[:8]}",
            cost_account=account,
        )
        db.add(party)
        await db.flush()
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.seller_nip == world["nips"]["supplier"])
            .values(counterparty_id=party.id)
        )
        await db.commit()
        return party.id


async def _act(client, headers, ids: list[int], action: str):
    return await client.post(
        f"{COSTS}/actions", json={"ids": ids, "action": action}, headers=headers
    )


async def _to_verified(client, headers, ids: list[int]) -> None:
    for action in ("accept", "verify"):
        response = await _act(client, headers, ids, action)
        assert response.status_code == 200, response.text


async def _office_rule(client, headers, party_id: int) -> int:
    """Reguła tylko dla dostawcy z testu (ogólnej reguły „Biuro” nie ruszamy)."""

    response = await client.post(
        f"{POSTING}/rules",
        json={
            "category": "office",
            "counterparty_id": party_id,
            "cost_account": "402-202",
            "vat_account": "221",
            "deduction": "full",
            "register": "purchase",
            "doc_type": "fvz",
            "service_label": "Usługi biurowe",
            "description_template": "{usługa} {MM}/{RRRR}",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ── Plan kont i reguły ───────────────────────────────────────────────────────


async def test_zasiew_planu_kont_i_reguly_kontraktora(world, client) -> None:
    headers = _headers(world["accountant"])
    accounts = await client.get(f"{POSTING}/accounts", headers=headers)
    assert accounts.status_code == 200, accounts.text
    by_number = {item["number"]: item for item in accounts.json()["items"]}
    assert by_number["402-203"]["kind"] == "cost"
    assert by_number["221"]["kind"] == "vat"
    assert by_number["402-203"]["rules"] >= 1
    rules = await client.get(f"{POSTING}/rules", headers=headers)
    general = [
        item
        for item in rules.json()["items"]
        if item["category"] == "contractor" and item["counterparty_id"] is None
    ]
    assert [
        (r["cost_account"], r["vat_account"], r["register"], r["doc_type"])
        for r in general
    ] == [("402-203", "221", "purchase", "FVZ")]

    used = await client.patch(
        f"{POSTING}/accounts/{by_number['402-203']['id']}",
        json={"active": False},
        headers=headers,
    )
    assert used.status_code == 409
    assert "regule" in used.json()["detail"]


async def test_konto_i_regula_walidacja(world, client) -> None:
    headers = _headers(world["accountant"])
    number = f"409-{uuid.uuid4().int % 10_000:04d}"
    try:
        created = await client.post(
            f"{POSTING}/accounts",
            json={"number": number, "name": "Konto testowe", "kind": "cost"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        twice = await client.post(
            f"{POSTING}/accounts",
            json={"number": number, "name": "Drugi raz", "kind": "cost"},
            headers=headers,
        )
        assert twice.status_code == 409
        bad = await client.post(
            f"{POSTING}/accounts",
            json={"number": "=SUMA(A1)", "name": "Zły", "kind": "cost"},
            headers=headers,
        )
        assert bad.status_code == 422
        party = await _supplier(world, account="201-2-902")
        wrong_kind = await client.post(
            f"{POSTING}/rules",
            json={
                "category": "office",
                "counterparty_id": party,
                "cost_account": "221",
                "vat_account": "221",
                "service_label": "X",
            },
            headers=headers,
        )
        assert wrong_kind.status_code == 422
        assert "rodzaj" in wrong_kind.json()["detail"]
        bad_template = await client.post(
            f"{POSTING}/rules",
            json={
                "category": "office",
                "counterparty_id": party,
                "cost_account": number,
                "vat_account": "221",
                "service_label": "X",
                "description_template": "{miesiac}",
            },
            headers=headers,
        )
        assert bad_template.status_code == 422
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FinanceAccount).where(FinanceAccount.number == number)
            )
            await db.commit()


async def test_regula_kontrahenta_przed_ogolna_kategorii(world, client) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _expense(
        world, number="D/11/21", net="100.00", vat="23.00", gross="123.00"
    )
    party = await _supplier(world, account="201-2-903")
    # Kategoria „Kontraktorzy” ma regułę ogólną (402-203); reguła tego
    # dostawcy w tej kategorii daje 409-906.
    await client.patch(
        f"{COSTS}/{entry_id}", json={"category": "contractor"}, headers=headers
    )
    special = await client.post(
        f"{POSTING}/rules",
        json={
            "category": "contractor",
            "counterparty_id": party,
            "cost_account": "409-906",
            "vat_account": "221",
            "service_label": "Usługi doradcze",
        },
        headers=headers,
    )
    assert special.status_code == 201, special.text
    await _to_verified(client, headers, [entry_id])
    card = (await client.get(f"{COSTS}/{entry_id}", headers=headers)).json()
    decree = card["decree"]
    assert decree["rule"]["id"] == special.json()["id"]
    assert [
        (p["account"], p["side_label"], p["amount"]) for p in decree["positions"]
    ] == [
        ("409-906", "Wn", "100.00"),
        ("221", "Wn", "23.00"),
        ("201-2-903", "Ma", "123.00"),
    ]
    assert decree["description"] == "Usługi doradcze 11/2026"
    assert decree["issues"] == [] and decree["balanced"] is True

    off = await client.patch(
        f"{POSTING}/rules/{special.json()['id']}",
        json={"active": False},
        headers=headers,
    )
    assert off.status_code == 200
    again = await client.post(
        f"{POSTING}/entries/{entry_id}/recalculate", headers=headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["decree"]["positions"][0]["account"] == "402-203"


# ── Dekret na wpisie ─────────────────────────────────────────────────────────


async def test_brak_konta_kontrahenta_blokuje_gotowa(world, client) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _expense(
        world, number="D/11/22", net="10.00", vat="2.30", gross="12.30"
    )
    party = await _supplier(world, account=None)
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [entry_id])

    blocked = await _act(client, headers, [entry_id], "ready")
    assert blocked.status_code == 409
    assert blocked.json()["detail"].startswith("Dekret niekompletny:")
    assert "konta rozrachunkowego" in blocked.json()["detail"]
    assert (await _entry_by_id(entry_id)).stage == "verified"

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCounterparty)
            .where(FinanceCounterparty.id == party)
            .values(cost_account="201-2-904")
        )
        await db.commit()
    done = await _act(client, headers, [entry_id], "ready")
    assert done.status_code == 200, done.text
    entry = await _entry_by_id(entry_id)
    assert entry.stage == "ready"
    assert entry.decree["positions"][-1]["account"] == "201-2-904"


async def _entry_by_id(entry_id: int) -> FinanceCostEntry:
    async with AsyncSessionLocal() as db:
        return await db.get(FinanceCostEntry, entry_id)


async def test_reczna_korekta_bilans_i_blokada_po_gotowej(world, client) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _expense(
        world, number="D/11/23", net="100.00", vat="23.00", gross="123.00"
    )
    party = await _supplier(world, account="201-2-905")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [entry_id])

    def body(credit: str) -> dict:
        return {
            "register": "purchase",
            "doc_type": "FVZ",
            "description": "Biuro 11/2026",
            "positions": [
                {
                    "kind": "cost",
                    "account": "402-202",
                    "side": "debit",
                    "amount": "60.00",
                },
                {
                    "kind": "cost",
                    "account": "409-906",
                    "side": "debit",
                    "amount": "40.00",
                },
                {"kind": "vat", "account": "221", "side": "debit", "amount": "23.00"},
                {
                    "kind": "counterparty",
                    "account": "201-2-905",
                    "side": "credit",
                    "amount": credit,
                },
            ],
        }

    unbalanced = await client.put(
        f"{POSTING}/entries/{entry_id}/decree", json=body("122.99"), headers=headers
    )
    assert unbalanced.status_code == 422
    assert "Suma Wn" in unbalanced.json()["detail"]
    saved = await client.put(
        f"{POSTING}/entries/{entry_id}/decree", json=body("123.00"), headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["decree"]["manual"] is True
    assert len(saved.json()["decree"]["positions"]) == 4

    # Ręczny dekret zostaje przy „Gotowa do księgowania”.
    ready = await _act(client, headers, [entry_id], "ready")
    assert ready.status_code == 200, ready.text
    entry = await _entry_by_id(entry_id)
    assert entry.decree["manual"] is True and len(entry.decree["positions"]) == 4

    locked = await client.put(
        f"{POSTING}/entries/{entry_id}/decree", json=body("123.00"), headers=headers
    )
    assert locked.status_code == 409
    recalc = await client.post(
        f"{POSTING}/entries/{entry_id}/recalculate", headers=headers
    )
    assert recalc.status_code == 409
    history = (await client.get(f"{COSTS}/{entry_id}", headers=headers)).json()[
        "history"
    ]
    assert "decree" in [item["action"] for item in history]


# ── Eksport miesiąca ─────────────────────────────────────────────────────────


async def test_paczka_plik_powtarzalny_zaksiegowanie_i_blokada(
    world, client, clean_batches
) -> None:
    headers = _headers(world["accountant"])
    first = await _expense(
        world, number='=HYPERLINK("x")', net="100.00", vat="23.00", gross="123.00"
    )
    second = await _expense(
        world, number="D/11/25", net="50.00", vat="11.50", gross="61.50"
    )
    party = await _supplier(world, account="201-2-906")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [first, second])
    assert (await _act(client, headers, [first, second], "ready")).status_code == 200

    preview = await client.get(
        f"{POSTING}/export", params={"month": MONTH}, headers=headers
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    purchase = next(r for r in data["registers"] if r["register"] == "purchase")
    ids = [item["id"] for item in purchase["entries"]]
    assert {first, second} <= set(ids)
    assert purchase["balanced"] is True
    assert data["blocked"] == 0 and data["can_export"] is True

    created = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_xlsx"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert batch["status"] == "exported"
    assert batch["number"].startswith(f"{MONTH}/")
    assert {first, second} <= set(batch["entry_ids"])
    assert batch["created_by"] == world["accountant"].name

    one = await client.get(f"{POSTING}/batches/{batch['id']}/file", headers=headers)
    two = await client.get(f"{POSTING}/batches/{batch['id']}/file", headers=headers)
    assert one.status_code == 200
    assert one.content == two.content
    assert hashlib.sha256(one.content).hexdigest() == batch["file_sha256"]
    assert one.headers["x-file-sha256"] == batch["file_sha256"]
    sheet = load_workbook(io.BytesIO(one.content)).active
    header = [cell.value for cell in sheet[1]]
    rows = [
        dict(zip(header, [c.value for c in row])) for row in sheet.iter_rows(min_row=2)
    ]
    mine = [row for row in rows if row["ID Symfonii kontrahenta"]]
    injected = [row for row in mine if str(row["Numer faktury"]).startswith("'=")]
    assert len(injected) == 3  # koszt, VAT, rozrachunek
    assert {row["Konto"] for row in injected} == {"402-202", "221", "201-2-906"}
    assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)
    assert sum(row["Wn"] or 0 for row in mine) == sum(row["Ma"] or 0 for row in mine)
    assert {row["Rejestr"] for row in mine} == {"Zakup"}
    assert {row["NIP"] for row in mine} == {world["nips"]["supplier"]}

    # W paczce: nie cofa się, nie ma na liście miesiąca, druga paczka pusta.
    back = await _act(client, headers, [first], "back")
    assert back.status_code == 409
    assert "paczce" in back.json()["detail"]
    after = (
        await client.get(f"{POSTING}/export", params={"month": MONTH}, headers=headers)
    ).json()
    assert first not in [e["id"] for r in after["registers"] for e in r["entries"]]

    booked = await client.post(f"{POSTING}/batches/{batch['id']}/book", headers=headers)
    assert booked.status_code == 200, booked.text
    assert booked.json()["status"] == "booked"
    assert booked.json()["booked_by"] == world["accountant"].name
    entry = await _entry_by_id(first)
    assert entry.stage == "booked"
    again = await client.post(f"{POSTING}/batches/{batch['id']}/book", headers=headers)
    assert again.status_code == 409
    cancel = await client.post(
        f"{POSTING}/batches/{batch['id']}/cancel", headers=headers
    )
    assert cancel.status_code == 409

    # Zaksięgowana: dekretu i etapu się nie zmienia.
    locked = await client.post(
        f"{POSTING}/entries/{first}/recalculate", headers=headers
    )
    assert locked.status_code == 409
    assert locked.json()["detail"] == ledger.BOOKED_DETAIL
    assert (await _act(client, headers, [first], "back")).status_code == 409
    card = (await client.get(f"{COSTS}/{first}", headers=headers)).json()
    assert card["decree"]["editable"] is False
    assert card["decree"]["batch"]["status"] == "booked"
    assert [h["action"] for h in card["history"]][-2:] == ["export", "book"]

    still = await client.get(f"{POSTING}/batches/{batch['id']}/file", headers=headers)
    assert still.content == one.content


async def test_anulowana_paczka_oddaje_wpisy_i_wada_blokuje_paczke(
    world, client, clean_batches
) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _expense(
        world, number="D/11/26", net="10.00", vat="2.30", gross="12.30"
    )
    party = await _supplier(world, account="201-2-907")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [entry_id])
    assert (await _act(client, headers, [entry_id], "ready")).status_code == 200

    batch = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert batch.status_code == 201, batch.text
    content = (
        await client.get(
            f"{POSTING}/batches/{batch.json()['id']}/file", headers=headers
        )
    ).content
    assert content.startswith("﻿".encode())
    assert "201-2-907" in content.decode("utf-8-sig")
    cancelled = await client.post(
        f"{POSTING}/batches/{batch.json()['id']}/cancel", headers=headers
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await _entry_by_id(entry_id)).batch_id is None
    assert (await _entry_by_id(entry_id)).stage == "ready"

    # Dekret zepsuty po „Gotowa” (tu: bilans) — paczka nie powstaje i mówi,
    # która faktura ma wadę.
    async with AsyncSessionLocal() as db:
        entry = await db.get(FinanceCostEntry, entry_id)
        decree = dict(entry.decree)
        decree["positions"] = [
            {**p, "amount": p["amount"] + 1} if p["kind"] == "cost" else p
            for p in decree["positions"]
        ]
        entry.decree = decree
        await db.commit()
    refused = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert refused.status_code == 409
    assert "Paczka nie powstała" in refused.json()["detail"]
    assert "D/11/26" in refused.json()["detail"]


async def test_faktury_zespolu_poza_eksportem_osoby_bez_plac(
    world, client, clean_batches
) -> None:
    accountant = _headers(world["accountant"])
    only = _headers(world["module_only"])
    payroll_entry = await _entry("payroll_invoice", world["person_invoice"].id)
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip",
            id_value=world["nips"]["person"],
            name="Osoba Testowa",
            cost_account="201-2-908",
        )
        db.add(party)
        await db.flush()
        db.add(
            FinancePostingRule(
                category="team",
                counterparty_id=party.id,
                cost_account="402-202",
                vat_account="221",
                deduction="full",
                register="purchase",
                doc_type="FVZ",
                service_label="Usługi IT",
                description_template="{usługa} {MM}/{RRRR}",
            )
        )
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == payroll_entry.id)
            .values(counterparty_id=party.id)
        )
        await db.commit()
    await _to_verified(client, accountant, [payroll_entry.id])
    assert (
        await _act(client, accountant, [payroll_entry.id], "ready")
    ).status_code == 200

    hidden = (
        await client.get(f"{POSTING}/export", params={"month": MONTH}, headers=only)
    ).json()
    assert payroll_entry.id not in [
        e["id"] for r in hidden["registers"] for e in r["entries"]
    ]
    seen = (
        await client.get(
            f"{POSTING}/export", params={"month": MONTH}, headers=accountant
        )
    ).json()
    assert payroll_entry.id in [
        e["id"] for r in seen["registers"] for e in r["entries"]
    ]
    assert (
        await client.post(
            f"{POSTING}/entries/{payroll_entry.id}/recalculate", headers=only
        )
    ).status_code == 404

    created = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_xlsx"},
        headers=accountant,
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert payroll_entry.id in batch["entry_ids"]
    listed = (await client.get(f"{POSTING}/batches", headers=only)).json()["items"]
    assert batch["id"] not in [item["id"] for item in listed]
    assert (
        await client.get(f"{POSTING}/batches/{batch['id']}/file", headers=only)
    ).status_code == 404
    assert (
        await client.post(f"{POSTING}/batches/{batch['id']}/book", headers=only)
    ).status_code == 404
    cancelled = await client.post(
        f"{POSTING}/batches/{batch['id']}/cancel", headers=accountant
    )
    assert cancelled.status_code == 200


async def test_bez_modulu_finanse_403(world, client) -> None:
    denied = _headers(world["recruiter"])
    for method, path in (
        ("get", f"{POSTING}/accounts"),
        ("get", f"{POSTING}/rules"),
        ("get", f"{POSTING}/export?month={MONTH}"),
        ("get", f"{POSTING}/batches"),
    ):
        response = await getattr(client, method)(path, headers=denied)
        assert response.status_code == 403, path
    created = await client.post(
        f"{POSTING}/accounts",
        json={"number": "409-1", "name": "X", "kind": "cost"},
        headers=denied,
    )
    assert created.status_code == 403


# ── Poprawki po przeglądzie (13.11) ──────────────────────────────────────────


async def _vat23_expense(world, *, number: str, gross: str = "123.00") -> int:
    """Faktura dostawcy z VAT 23% liczonym od brutto (``Do opisu`` po przyjęciu)."""

    vat = (Decimal(gross) * 23 / 123).quantize(Decimal("0.01"))
    return await _expense(
        world,
        number=number,
        net=f"{Decimal(gross) - vat:.2f}",
        vat=f"{vat:.2f}",
        gross=gross,
    )


async def _source_gross(entry_id: int, gross: str, vat: str | None = None) -> None:
    """Źródło zmienia kwoty po dekrecie (jak ``_bind_twin`` przy bliźniaku z KSeF)."""

    values = {"gross_amount": Decimal(gross)}
    if vat is not None:
        values["vat_amount"] = Decimal(vat)
    async with AsyncSessionLocal() as db:
        entry = await db.get(FinanceCostEntry, entry_id)
        await db.execute(
            update(ApprovalDocument)
            .where(ApprovalDocument.id == entry.source_id)
            .values(**values)
        )
        await db.commit()


async def test_kategoria_po_gotowej_i_w_paczce_to_409(
    world, client, clean_batches
) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _vat23_expense(world, number="D/11/31")
    party = await _supplier(world, account="201-2-911")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [entry_id])
    assert (await _act(client, headers, [entry_id], "ready")).status_code == 200

    ready = await client.patch(
        f"{COSTS}/{entry_id}", json={"category": "contractor"}, headers=headers
    )
    assert ready.status_code == 409
    assert "Cofnij" in ready.json()["detail"]
    assert (await _entry_by_id(entry_id)).category == "office"
    # Flagi i notatka po „Gotowa” dalej wolno.
    note = await client.patch(
        f"{COSTS}/{entry_id}", json={"note": "ok"}, headers=headers
    )
    assert note.status_code == 200

    batch = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert batch.status_code == 201, batch.text
    in_batch = await client.patch(
        f"{COSTS}/{entry_id}", json={"category": "contractor"}, headers=headers
    )
    assert in_batch.status_code == 409
    assert "paczk" in in_batch.json()["detail"]


async def test_zmiana_brutto_zrodla_po_dekrecie(world, client, clean_batches) -> None:
    headers = _headers(world["accountant"])
    early = await _vat23_expense(world, number="D/11/32", gross="12300.00")
    party = await _supplier(world, account="201-2-912")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [early])
    assert (await _act(client, headers, [early], "ready")).status_code == 200

    # Paczka powstała, potem źródło zmieniło brutto → zaksięgować nie wolno.
    batch = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert batch.status_code == 201, batch.text
    await _source_gross(early, "12177.00")
    book = await client.post(
        f"{POSTING}/batches/{batch.json()['id']}/book", headers=headers
    )
    assert book.status_code == 409
    assert "D/11/32" in book.json()["detail"]
    assert (await _entry_by_id(early)).stage == "ready"
    cancel = await client.post(
        f"{POSTING}/batches/{batch.json()['id']}/cancel", headers=headers
    )
    assert cancel.status_code == 200

    # Po anulowaniu: wpis z wadą na liście, poza paczką.
    preview = (
        await client.get(f"{POSTING}/export", params={"month": MONTH}, headers=headers)
    ).json()
    skipped = {item["id"]: item for item in preview["skipped"]}
    assert skipped[early]["issues"] == [
        "Kwoty faktury zmieniły się po dekrecie — Cofnij i przelicz."
    ]
    refused = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert refused.status_code == 409
    assert "Paczka nie powstała" in refused.json()["detail"]
    assert (await _entry_by_id(early)).batch_id is None


async def test_paczka_pomija_faktury_z_wada_i_bierze_je_nastepnym_razem(
    world, client, clean_batches
) -> None:
    headers = _headers(world["accountant"])
    good = await _vat23_expense(world, number="D/11/33")
    bad = await _vat23_expense(world, number="D/11/34")
    party = await _supplier(world, account="201-2-913")
    await _office_rule(client, headers, party)
    await _to_verified(client, headers, [good, bad])
    assert (await _act(client, headers, [good, bad], "ready")).json()["changed"] == 2
    await _source_gross(bad, "124.00", vat="24.00")

    preview = (
        await client.get(f"{POSTING}/export", params={"month": MONTH}, headers=headers)
    ).json()
    assert preview["can_export"] is True
    assert [item["id"] for item in preview["skipped"]] == [bad]
    batch = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert batch.status_code == 201, batch.text
    assert good in batch.json()["entry_ids"] and bad not in batch.json()["entry_ids"]
    assert [item["id"] for item in batch.json()["skipped"]] == [bad]
    content = (
        await client.get(
            f"{POSTING}/batches/{batch.json()['id']}/file", headers=headers
        )
    ).content.decode("utf-8-sig")
    assert "D/11/33" in content and "D/11/34" not in content
    left = await _entry_by_id(bad)
    assert (left.stage, left.batch_id) == ("ready", None)

    # Naprawa (Cofnij → przelicz → Gotowa) i następna paczka bierze fakturę.
    assert (await _act(client, headers, [bad], "back")).status_code == 200
    assert (await _act(client, headers, [bad], "ready")).status_code == 200
    second = await client.post(
        f"{POSTING}/batches",
        json={"month": MONTH, "format": "neutral_csv"},
        headers=headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["entry_ids"] == [bad]
    assert second.json()["skipped"] == []


async def test_waluta_obca_po_kursie_nbp_z_dnia_roboczego_przed_wystawieniem(
    world, client
) -> None:
    headers = _headers(world["accountant"])
    entry_id = await _expense(
        world,
        number="EU/11/1",
        net="1000.00",
        vat="230.00",
        gross="1230.00",
        currency="EUR",
        issued="2026-11-04",
    )
    party = await _supplier(world, account="201-2-914")
    await _office_rule(client, headers, party)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FxRate).where(
                FxRate.currency == "EUR", FxRate.effective_date == date(2026, 11, 3)
            )
        )
        # Kurs z dnia wystawienia nie liczy się — tylko z dnia roboczego przed.
        db.add(
            FxRate(
                currency="EUR",
                effective_date=date(2026, 11, 4),
                rate_to_pln=Decimal("9.9"),
            )
        )
        await db.commit()
    try:
        await _to_verified(client, headers, [entry_id])
        blocked = await _act(client, headers, [entry_id], "ready")
        assert blocked.status_code == 409
        assert "Brak kursu NBP EUR z dnia 03.11.2026" in blocked.json()["detail"]

        async with AsyncSessionLocal() as db:
            db.add(
                FxRate(
                    currency="EUR",
                    effective_date=date(2026, 11, 3),
                    rate_to_pln=Decimal("4.2512"),
                )
            )
            await db.commit()
        done = await _act(client, headers, [entry_id], "ready")
        assert done.status_code == 200, done.text
        card = (await client.get(f"{COSTS}/{entry_id}", headers=headers)).json()
        decree = card["decree"]
        assert (decree["currency"], decree["fx_rate"], decree["fx_date"]) == (
            "EUR",
            "4.2512",
            "2026-11-03",
        )
        assert [(p["account"], p["amount"]) for p in decree["positions"]] == [
            ("402-202", "4251.20"),
            ("221", "977.78"),
            ("201-2-914", "5228.98"),
        ]
        assert decree["issues"] == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FxRate).where(
                    FxRate.currency == "EUR",
                    FxRate.effective_date.in_([date(2026, 11, 3), date(2026, 11, 4)]),
                )
            )
            await db.commit()


async def test_pominiete_faktury_zespolu_tylko_dla_plac(world, client) -> None:
    """D2 w liście pominiętych: osoba bez Płac nie widzi faktury zespołu z wadą."""

    accountant = _headers(world["accountant"])
    only = _headers(world["module_only"])
    payroll_entry = await _entry("payroll_invoice", world["person_invoice"].id)
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip",
            id_value=world["nips"]["person"],
            name="Osoba Testowa",
            cost_account="201-2-915",
        )
        db.add(party)
        await db.flush()
        db.add(
            FinancePostingRule(
                category="team",
                counterparty_id=party.id,
                cost_account="402-202",
                vat_account="221",
                deduction="full",
                register="purchase",
                doc_type="FVZ",
                service_label="Usługi IT",
                description_template="{usługa} {MM}/{RRRR}",
            )
        )
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == payroll_entry.id)
            .values(counterparty_id=party.id)
        )
        await db.commit()
    await _to_verified(client, accountant, [payroll_entry.id])
    assert (
        await _act(client, accountant, [payroll_entry.id], "ready")
    ).status_code == 200
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PayrollInvoice)
            .where(PayrollInvoice.id == world["person_invoice"].id)
            .values(gross_amount=Decimal("12177.00"))
        )
        await db.commit()

    seen = (
        await client.get(
            f"{POSTING}/export", params={"month": MONTH}, headers=accountant
        )
    ).json()
    assert payroll_entry.id in [item["id"] for item in seen["skipped"]]
    hidden = (
        await client.get(f"{POSTING}/export", params={"month": MONTH}, headers=only)
    ).json()
    assert payroll_entry.id not in [item["id"] for item in hidden["skipped"]]
