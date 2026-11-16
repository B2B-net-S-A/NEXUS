"""Księgowość w Finansach (0695, E0 i E1) — trasy, hook źródeł i import z bazą.

Kolejka kosztów: wpis powstaje dla faktury ze źródła, przejścia etapów idą
z historią, zły etap to 409, brak uprawnienia „Moduł Finanse” to 403, własna
faktura to 403, wyłączony moduł to 404 (admin widzi). Kartoteka: import pliku
z podglądem, zapis, ponowny import bez zmian, rola z NEXUSA i powiązanie
wpisów z kontrahentem po NIP-ie. Osoby, NIP-y i kwoty fikcyjne.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update

from app.api import finance_ledger
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.finance_ledger import (
    FinanceCostEntry,
    FinanceCostEntryEvent,
    FinanceCounterparty,
)
from app.models.finance_posting import FinancePostingRule
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import EmployeeBillingDetails, PayrollInvoice
from app.models.user import User, UserRole
from app.services.finance_ledger import costs as ledger
from app.services.finance_ledger import settings as module_settings
from app.services.hr.approvals import cost_invoices
from tests._permission_grants import grant_permissions

COSTS = "/api/finance/costs"
PARTIES = "/api/finance/counterparties"


def _nip(seed: int) -> str:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for offset in range(1000):
        base = f"{(seed + offset) % 10**9:09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)
    raise AssertionError("brak NIP-u")


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"ledger-{marker}@example.com",
        name=f"Osoba Testowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _ksef_number(nip: str) -> str:
    return f"{nip}-20261105-{uuid.uuid4().hex[:12].upper()}-AB"


async def _payroll_invoice(db, user: User, nip: str) -> PayrollInvoice:
    ksef = _ksef_number(nip)
    invoice = PayrollInvoice(
        source="ksef",
        ksef_number=ksef,
        ksef_acquired_at=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc),
        seller_nip=nip,
        user_id=user.id,
        invoice_number=f"FV/{random.randint(1, 999)}/11/2026",
        issue_date=date(2026, 11, 4),
        currency="PLN",
        net_amount=Decimal("10000.00"),
        vat_amount=Decimal("2300.00"),
        gross_amount=Decimal("12300.00"),
        items=[],
        xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
        match_status="unmatched",
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def _set(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _with_posting_rule(entry: FinanceCostEntry, nip: str) -> int:
    """Kontrahent z kontem i reguła dekretu tylko dla niego (znika z kontrahentem)."""

    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip", id_value=nip, name="Kontrahent Testowy", cost_account="201-2-901"
        )
        db.add(party)
        await db.flush()
        db.add(
            FinancePostingRule(
                category=entry.category,
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
            .where(FinanceCostEntry.id == entry.id)
            .values(counterparty_id=party.id)
        )
        await db.commit()
        return party.id


async def _entry(source_type: str, source_id: int) -> FinanceCostEntry:
    async with AsyncSessionLocal() as db:
        entry = await db.scalar(
            select(FinanceCostEntry).where(
                FinanceCostEntry.source_type == source_type,
                FinanceCostEntry.source_id == source_id,
            )
        )
        assert entry is not None
        return entry


@pytest_asyncio.fixture
async def world():
    seed = random.randint(10_000_000, 900_000_000)
    nips = {
        "person": _nip(seed),
        "accountant": _nip(seed + 7_000),
        "supplier": _nip(seed + 13_000),
        "client": _nip(seed + 21_000),
    }
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(
                AppSetting.key == module_settings.SETTING_KEY
            )
        )
        admin = await _user(db, "admin")
        accountant = await _user(db, "finance")
        recruiter = await _user(db, "recruiter")
        module_only = await _user(db, "recruiter")
        person = await _user(db, "employee")
        db.add(EmployeeBillingDetails(user_id=person.id, nip=nips["person"]))
        person_invoice = await _payroll_invoice(db, person, nips["person"])
        own_invoice = await _payroll_invoice(db, accountant, nips["accountant"])
        client = Client(name=f"Klient Testowy {seed}", nip=nips["client"])
        db.add(client)
        await db.commit()
    # Sam „Moduł Finanse” bez Płac (D2: faktur osób zespołu nie widzi).
    await grant_permissions(module_only.id, "finance_module")
    await _set(module_settings.SETTING_KEY, {"enabled": True})
    async with AsyncSessionLocal() as db:
        await ledger.catch_up(db)
        await db.commit()
    yield {
        "admin": admin,
        "accountant": accountant,
        "recruiter": recruiter,
        "module_only": module_only,
        "person": person,
        "person_invoice": person_invoice,
        "own_invoice": own_invoice,
        "client": client,
        "nips": nips,
    }
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceCostEntry).where(
                FinanceCostEntry.seller_nip.in_(list(nips.values()))
            )
        )
        await db.execute(
            delete(FinanceCounterparty).where(
                FinanceCounterparty.id_value.in_(list(nips.values()))
            )
        )
        await db.execute(
            delete(PayrollInvoice).where(
                PayrollInvoice.seller_nip.in_(list(nips.values()))
            )
        )
        await db.execute(
            delete(ApprovalDocument).where(
                ApprovalDocument.seller_nip.in_(list(nips.values()))
            )
        )
        await db.execute(
            delete(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == person.id
            )
        )
        await db.execute(delete(Client).where(Client.id == client.id))
        await db.execute(
            delete(User).where(
                User.id.in_(
                    [admin.id, accountant.id, recruiter.id, module_only.id, person.id]
                )
            )
        )
        await db.commit()
    await _set(module_settings.SETTING_KEY, previous)


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(finance_ledger.costs_router, prefix=COSTS)
    app.include_router(finance_ledger.counterparties_router, prefix=PARTIES)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


# ── Hook i backfill ──────────────────────────────────────────────────────────


async def test_wpis_powstaje_dla_faktury_ze_zrodla_i_nie_dubluje_sie(world) -> None:
    entry = await _entry("payroll_invoice", world["person_invoice"].id)
    assert (entry.stage, entry.category, entry.from_ksef) == ("received", "team", True)
    assert entry.seller_nip == world["nips"]["person"]
    assert entry.received_at == datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)

    ksef = _ksef_number(world["nips"]["supplier"])
    item = {
        "ksefNumber": ksef,
        "invoiceNumber": "B/11/0412",
        "issueDate": "2026-11-03",
        "seller": {"nip": world["nips"]["supplier"], "name": "Dostawca Testowy"},
        "netAmount": "100.00",
        "vatAmount": "23.00",
        "grossAmount": "123.00",
        "currency": "PLN",
    }
    async with AsyncSessionLocal() as db:
        state = await cost_invoices.store(
            db, item, ksef_number=ksef, now=datetime.now(timezone.utc), match=False
        )
        await ledger.enqueue_ksef(db, ksef)
        await db.commit()
        document = await db.scalar(
            select(ApprovalDocument).where(ApprovalDocument.ksef_number == ksef)
        )
    assert state == "unmatched" and document.match_reason is None
    expense = await _entry("approval_document", document.id)
    assert (expense.stage, expense.category) == ("received", "office")

    async with AsyncSessionLocal() as db:
        before = await db.scalar(select(func.count()).select_from(FinanceCostEntry))
        await ledger.catch_up(db)
        await ledger.enqueue_ksef(db, ksef)
        await db.commit()
        after = await db.scalar(select(func.count()).select_from(FinanceCostEntry))
    assert before == after


# ── Kolejka i przejścia ──────────────────────────────────────────────────────


async def test_bez_modulu_finanse_403_a_wylaczony_modul_404(world, client) -> None:
    denied = await client.get(COSTS, headers=_headers(world["recruiter"]))
    assert denied.status_code == 403
    await _set(module_settings.SETTING_KEY, {"enabled": False})
    closed = await client.get(COSTS, headers=_headers(world["accountant"]))
    assert closed.status_code == 404
    admin = await client.get(COSTS, headers=_headers(world["admin"]))
    assert admin.status_code == 200
    state = await client.get(f"{COSTS}/module", headers=_headers(world["accountant"]))
    assert state.json() == {"enabled": False, "open": False}
    switch = await client.put(
        f"{COSTS}/module", json={"enabled": True}, headers=_headers(world["accountant"])
    )
    assert switch.status_code == 403


async def test_sciezka_od_poczekalni_do_gotowej_z_historia(world, client) -> None:
    accountant = _headers(world["accountant"])
    entry = await _entry("payroll_invoice", world["person_invoice"].id)

    listed = await client.get(
        COSTS,
        params={"stage": "received", "q": world["nips"]["person"]},
        headers=accountant,
    )
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["items"] if item["id"] == entry.id)
    assert row["concerning"]["person"] == world["person"].name
    assert row["concerning"]["status"] == "unmatched"
    assert row["net_amount"] == "10000.00"
    assert listed.json()["counts"]["received"] >= 1

    wrong = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "verify"},
        headers=accountant,
    )
    assert wrong.status_code == 409
    assert "Z KSeF do przyjęcia" in wrong.json()["detail"]

    # E2 (0698): „Gotowa do księgowania” wymaga kompletnego dekretu — kontrahent
    # z kontem rozrachunkowym i reguła (tu reguła tego kontrahenta).
    await _with_posting_rule(entry, world["nips"]["person"])
    for action, stage in (
        ("accept", "new"),
        ("verify", "verified"),
        ("ready", "ready"),
    ):
        done = await client.post(
            f"{COSTS}/actions",
            json={"ids": [entry.id], "action": action},
            headers=accountant,
        )
        assert done.status_code == 200, done.text
        assert done.json() == {"changed": 1, "refused": []}
        assert (
            await _entry("payroll_invoice", world["person_invoice"].id)
        ).stage == stage

    back = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "back"},
        headers=accountant,
    )
    assert back.status_code == 200
    flagged = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "flag_add", "flag": "mpp"},
        headers=accountant,
    )
    assert flagged.json()["changed"] == 1
    patched = await client.patch(
        f"{COSTS}/{entry.id}",
        json={
            "flags": ["no_mpp", "hold_payment"],
            "category": "contractor",
            "note": "sprawdzić",
        },
        headers=accountant,
    )
    assert patched.status_code == 200, patched.text
    card = patched.json()
    assert card["stage"] == "verified"
    assert card["flags"] == ["no_mpp", "hold_payment"]
    assert card["category"] == "contractor"
    assert [event["action"] for event in card["history"]] == [
        "accept",
        "verify",
        "ready",
        "back",
        "flags",
        "category",
        "flags",
        "note",
    ]
    assert card["history"][0]["actor"] == world["accountant"].name


async def test_odrzucenie_wymaga_powodu_i_wraca_do_poczekalni(world, client) -> None:
    accountant = _headers(world["accountant"])
    entry = await _entry("payroll_invoice", world["person_invoice"].id)
    no_reason = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "reject"},
        headers=accountant,
    )
    assert no_reason.status_code == 422
    rejected = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "reject", "reason": "Nie dotyczy firmy"},
        headers=accountant,
    )
    assert rejected.status_code == 200
    stored = await _entry("payroll_invoice", world["person_invoice"].id)
    assert (stored.stage, stored.reject_reason) == ("rejected", "Nie dotyczy firmy")
    restored = await client.post(
        f"{COSTS}/actions",
        json={"ids": [entry.id], "action": "back"},
        headers=accountant,
    )
    assert restored.status_code == 200
    stored = await _entry("payroll_invoice", world["person_invoice"].id)
    assert (stored.stage, stored.reject_reason) == ("received", None)


async def test_wlasnej_faktury_nie_przyjmujesz_a_zbiorczo_reszta_idzie(
    world, client
) -> None:
    accountant = _headers(world["accountant"])
    own = await _entry("payroll_invoice", world["own_invoice"].id)
    other = await _entry("payroll_invoice", world["person_invoice"].id)
    alone = await client.post(
        f"{COSTS}/actions",
        json={"ids": [own.id], "action": "accept"},
        headers=accountant,
    )
    assert alone.status_code == 403
    both = await client.post(
        f"{COSTS}/actions",
        json={"ids": [own.id, other.id, 999_999_999], "action": "accept"},
        headers=accountant,
    )
    assert both.status_code == 200
    body = both.json()
    assert body["changed"] == 1
    assert [(item["id"], item["status"]) for item in body["refused"]] == [
        (own.id, 403),
        (999_999_999, 404),
    ]
    by_admin = await client.post(
        f"{COSTS}/actions",
        json={"ids": [own.id], "action": "accept"},
        headers=_headers(world["admin"]),
    )
    assert by_admin.status_code == 200
    async with AsyncSessionLocal() as db:
        events = await db.scalar(
            select(func.count())
            .select_from(FinanceCostEntryEvent)
            .where(FinanceCostEntryEvent.entry_id == own.id)
        )
    assert events == 1


# ── Kartoteka ────────────────────────────────────────────────────────────────


def _csv(rows: list[list[str]]) -> bytes:
    return "\n".join(";".join(row) for row in rows).encode("utf-8")


async def test_import_podglad_zapis_rola_i_powiazanie_wpisow(world, client) -> None:
    accountant = _headers(world["accountant"])
    nips = world["nips"]
    bad_nip = nips["supplier"][:9] + str((int(nips["supplier"][9]) + 1) % 10)
    content = _csv(
        [
            ["Nazwa", "NIP", "Symfonia ID", "Konto kosztowe", "Konto przychodowe"],
            ["Osoba Testowa IT", nips["person"], "", "201-2-317", ""],
            ["Klient Testowy", nips["client"], "", "", "200-2-1441"],
            ["Dostawca Testowy", nips["supplier"], "", "201-2-273", ""],
            ["Zły numer", bad_nip, "", "", ""],
        ]
    )
    files = {"file": ("partnerzy.csv", content, "text/csv")}
    preview = await client.post(f"{PARTIES}/import", files=files, headers=accountant)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["saved"], body["created"], body["error_count"]) == (False, 3, 1)
    async with AsyncSessionLocal() as db:
        none_yet = await db.scalar(
            select(func.count())
            .select_from(FinanceCounterparty)
            .where(FinanceCounterparty.id_value.in_(list(nips.values())))
        )
    assert none_yet == 0

    saved = await client.post(
        f"{PARTIES}/import", params={"save": "true"}, files=files, headers=accountant
    )
    assert saved.status_code == 200
    assert saved.json()["created"] == 3
    assert saved.json()["linked_entries"] >= 1
    entry = await _entry("payroll_invoice", world["person_invoice"].id)
    assert entry.counterparty_id is not None

    again = await client.post(f"{PARTIES}/import", files=files, headers=accountant)
    assert (again.json()["created"], again.json()["unchanged"]) == (0, 3)

    listed = await client.get(PARTIES, params={"q": "Testow"}, headers=accountant)
    roles = {
        item["id_value"]: item["role"]
        for item in listed.json()["items"]
        if item["id_value"] in nips.values()
    }
    assert roles == {
        nips["person"]: "team",
        nips["client"]: "client",
        nips["supplier"]: "supplier",
    }

    supplier_id = next(
        item["id"]
        for item in listed.json()["items"]
        if item["id_value"] == nips["supplier"]
    )
    edited = await client.patch(
        f"{PARTIES}/{supplier_id}", json={"cost_account": "402-212"}, headers=accountant
    )
    assert edited.status_code == 200
    assert edited.json()["cost_account"] == "402-212"
    bad = await client.patch(
        f"{PARTIES}/{supplier_id}", json={"cost_account": "40 2 ##"}, headers=accountant
    )
    assert bad.status_code == 422

    denied = await client.post(
        f"{PARTIES}/import", files=files, headers=_headers(world["recruiter"])
    )
    assert denied.status_code == 403


async def test_plik_bez_naglowka_to_422(world, client) -> None:
    response = await client.post(
        f"{PARTIES}/import",
        files={"file": ("x.csv", b"a;b\nc;d\n", "text/csv")},
        headers=_headers(world["accountant"]),
    )
    assert response.status_code == 422
    assert "nagłówka" in response.json()["detail"]


@pytest.mark.parametrize("month", ["2026-11"])
async def test_filtr_miesiaca_wplywu(world, client, month) -> None:
    response = await client.get(
        COSTS,
        params={"stage": "received", "month": month, "q": world["nips"]["person"]},
        headers=_headers(world["accountant"]),
    )
    assert response.json()["total"] == 1
    other = await client.get(
        COSTS,
        params={"stage": "received", "month": "2026-10", "q": world["nips"]["person"]},
        headers=_headers(world["accountant"]),
    )
    assert other.json()["total"] == 0


async def _expense_entry(world) -> FinanceCostEntry:
    ksef = _ksef_number(world["nips"]["supplier"])
    item = {
        "ksefNumber": ksef,
        "invoiceNumber": "D/11/7",
        "issueDate": "2026-11-03",
        "seller": {"nip": world["nips"]["supplier"], "name": "Dostawca Testowy"},
        "netAmount": "10.00",
        "vatAmount": "2.30",
        "grossAmount": "12.30",
        "currency": "PLN",
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
    return await _entry("approval_document", document_id)


async def test_faktury_osob_zespolu_tylko_dla_plac(world, client) -> None:
    """D2: nazwisko i kwotę faktury osoby zespołu widzą Płace i admin, nie sam
    „Moduł Finanse” — ani w liście, ani w licznikach, karcie, akcji i PATCH."""

    payroll_entry = await _entry("payroll_invoice", world["person_invoice"].id)
    expense = await _expense_entry(world)
    only = _headers(world["module_only"])
    nip = world["nips"]["person"]

    hidden = await client.get(
        COSTS, params={"stage": "received", "q": nip}, headers=only
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["items"] == []
    assert hidden.json()["counts"]["received"] == 0
    visible = await client.get(
        COSTS,
        params={"stage": "received", "q": nip},
        headers=_headers(world["accountant"]),
    )
    assert [item["id"] for item in visible.json()["items"]] == [payroll_entry.id]
    assert visible.json()["counts"]["received"] == 1

    supplier = await client.get(
        COSTS,
        params={"stage": "received", "q": world["nips"]["supplier"]},
        headers=only,
    )
    assert [item["id"] for item in supplier.json()["items"]] == [expense.id]

    assert (
        await client.get(f"{COSTS}/{payroll_entry.id}", headers=only)
    ).status_code == 404
    assert (await client.get(f"{COSTS}/{expense.id}", headers=only)).status_code == 200

    mixed = await client.post(
        f"{COSTS}/actions",
        json={"ids": [payroll_entry.id, expense.id], "action": "accept"},
        headers=only,
    )
    assert mixed.status_code == 200, mixed.text
    assert mixed.json()["changed"] == 1
    assert mixed.json()["refused"] == [
        {
            "id": payroll_entry.id,
            "detail": "Nie ma takiej faktury w kolejce.",
            "status": 404,
        }
    ]
    alone = await client.post(
        f"{COSTS}/actions",
        json={"ids": [payroll_entry.id], "action": "accept"},
        headers=only,
    )
    assert alone.status_code == 404
    patched = await client.patch(
        f"{COSTS}/{payroll_entry.id}", json={"note": "x"}, headers=only
    )
    assert patched.status_code == 404
    assert (
        await _entry("payroll_invoice", world["person_invoice"].id)
    ).stage == "received"
