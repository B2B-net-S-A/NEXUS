"""Przelewy faktur kosztowych (0696, E3) — trasy i serwis z bazą.

Plan paczki (tryb, blokady, biała lista off / brak / zgodny, ``hold_payment``),
paczka z plikiem Elixir i anulowaniem, brak podwójnej paczki przy dwóch
równoległych „Utwórz paczkę”, wyciąg (dokładnie, częściowo, niejednoznacznie
→ do sprawdzenia, ponowny import), ręczne „Opłacono”, rachunek z kartoteki,
filtr „Zapłata” w kolejce, D2 (faktury osób zespołu tylko z Płacami) i 403.
Osoby, NIP-y, rachunki i kwoty fikcyjne.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api import finance_ledger, finance_payments
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.client_settlement import (
    ClientContractorInvoice,
    ClientSettlement,
    ClientSettlementRuleSet,
)
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_payments import (
    FinanceCostPayment,
    FinanceCostPaymentRecord,
    FinanceCounterpartyAccount,
    FinanceCounterpartyAccountEvent,
    FinancePaymentBatch,
)
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import PayrollInvoice
from app.models.user import User, UserRole
from app.services.finance_ledger import costs as ledger
from app.services.finance_ledger import payments as service
from app.services.finance_ledger import settings as module_settings
from app.services.hr import white_list
from app.services.hr.approvals import cost_invoices
from app.services.hr.bank.accounts import iban_check_digits
from tests._permission_grants import grant_permissions
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract
from tests.test_client_audit_2026_09_24 import _cleanup as cleanup_client

PAY = "/api/finance/payments"
COSTS = "/api/finance/costs"


def _nip(seed: int) -> str:
    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for offset in range(1000):
        base = f"{(seed + offset) % 10**9:09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)
    raise AssertionError("brak NIP-u")


def _nrb(seed: int) -> str:
    bban = f"10900000{seed:016d}"
    return iban_check_digits(bban) + bban


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"payments-{marker}@example.com",
        name=f"Osoba Testowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


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


async def _get_setting(key: str):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AppSetting.value).where(AppSetting.key == key))


def _ksef(nip: str) -> str:
    return f"{nip}-20261105-{uuid.uuid4().hex[:12].upper()}-AB"


class World(dict):
    pass


async def _supplier_entry(
    world: World,
    nip: str,
    *,
    gross: str,
    vat: str = "0.00",
    number: str | None = None,
    flags: list[str] | None = None,
    due: date | None = None,
    account: str | None = None,
    currency: str = "PLN",
) -> int:
    ksef = _ksef(nip)
    item = {
        "ksefNumber": ksef,
        "invoiceNumber": number or f"D/{random.randint(1, 99999)}/11/2026",
        "issueDate": "2026-11-03",
        "seller": {"nip": nip, "name": f"Dostawca Testowy {nip[-4:]}"},
        "netAmount": str(Decimal(gross) - Decimal(vat)),
        "vatAmount": vat,
        "grossAmount": gross,
        "currency": currency,
    }
    async with AsyncSessionLocal() as db:
        await cost_invoices.store(
            db, item, ksef_number=ksef, now=datetime.now(timezone.utc), match=False
        )
        await ledger.enqueue_ksef(db, ksef)
        document_id = await db.scalar(
            select(ApprovalDocument.id).where(ApprovalDocument.ksef_number == ksef)
        )
        entry = await db.scalar(
            select(FinanceCostEntry).where(
                FinanceCostEntry.source_type == "approval_document",
                FinanceCostEntry.source_id == document_id,
            )
        )
        entry.stage = "new"
        entry.flags = flags or []
        entry.due_date = due if due is not None else world["today"] - timedelta(days=1)
        if account:
            db.add(FinanceCostPayment(entry_id=entry.id, account=account))
        await db.commit()
        world["ksef"][entry.id] = ksef
        world["number"][entry.id] = item["invoiceNumber"]
        return entry.id


@pytest_asyncio.fixture
async def world(monkeypatch):
    seed = random.randint(10_000_000, 900_000_000)
    nips = {
        "person": _nip(seed),
        "a": _nip(seed + 7_000),
        "b": _nip(seed + 13_000),
        "c": _nip(seed + 21_000),
    }
    previous_module = await _get_setting(module_settings.SETTING_KEY)
    previous_payments = await _get_setting(service.SETTING_KEY)
    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        accountant = await _user(db, "finance")
        recruiter = await _user(db, "recruiter")
        module_only = await _user(db, "recruiter")
        person = await _user(db, "employee")
        ksef = _ksef(nips["person"])
        person_invoice = PayrollInvoice(
            source="ksef",
            ksef_number=ksef,
            ksef_acquired_at=datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc),
            seller_nip=nips["person"],
            user_id=person.id,
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
        db.add(person_invoice)
        await db.commit()
    await grant_permissions(module_only.id, "finance_module")
    await _set(module_settings.SETTING_KEY, {"enabled": True})
    await _set(
        service.SETTING_KEY,
        {"sender_name": "Spółka Przykładowa", "sender_account": _nrb(1)},
    )
    async with AsyncSessionLocal() as db:
        await ledger.catch_up(db)
        payroll_entry = await db.scalar(
            select(FinanceCostEntry).where(
                FinanceCostEntry.source_type == "payroll_invoice",
                FinanceCostEntry.source_id == person_invoice.id,
            )
        )
        payroll_entry.stage = "new"
        payroll_entry.due_date = business_today() - timedelta(days=1)
        await db.commit()
        payroll_entry_id = payroll_entry.id

    listed: set[str] = set()

    async def fake_check(db, nip, account, on_date, **_kwargs):
        if world_state["mode"] == "off":
            raise white_list.WhiteListError("disabled")
        return white_list.WhiteListCheck(
            nip=nip,
            account_last4=account[-4:],
            listed=account in listed,
            request_id=f"test-{account[-4:]}",
            requested_at=None,
            on_date=on_date,
        )

    world_state = {"mode": "on"}
    monkeypatch.setattr(white_list, "check", fake_check)
    data = World(
        admin=admin,
        accountant=accountant,
        recruiter=recruiter,
        module_only=module_only,
        person=person,
        payroll_entry=payroll_entry_id,
        nips=nips,
        listed=listed,
        wl=world_state,
        today=business_today(),
        ksef={},
        number={},
    )
    yield data
    users = [admin.id, accountant.id, recruiter.id, module_only.id, person.id]
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinancePaymentBatch).where(FinancePaymentBatch.created_by.in_(users))
        )
        await db.execute(
            delete(FinanceCostPaymentRecord).where(
                FinanceCostPaymentRecord.created_by.in_(users)
            )
        )
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
        await db.execute(delete(User).where(User.id.in_(users)))
        await db.commit()
    await _set(module_settings.SETTING_KEY, previous_module)
    await _set(service.SETTING_KEY, previous_payments)


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(finance_ledger.costs_router, prefix=COSTS)
    app.include_router(finance_payments.router, prefix=PAY)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


def _items(response, ids) -> dict[int, dict]:
    assert response.status_code == 200, response.text
    return {
        item["entry_id"]: item
        for item in response.json()["items"]
        if item["entry_id"] in set(ids)
    }


async def _state(entry_id: int) -> str:
    async with AsyncSessionLocal() as db:
        payment = await db.get(FinanceCostPayment, entry_id)
        return payment.state if payment else "unpaid"


# ── Plan ─────────────────────────────────────────────────────────────────────


async def test_plan_tryb_blokady_i_biala_lista(world, client) -> None:
    nips = world["nips"]
    big = await _supplier_entry(
        world, nips["a"], gross="20000.00", vat="3739.84", account=_nrb(11)
    )
    small = await _supplier_entry(world, nips["b"], gross="1230.00", account=_nrb(12))
    held = await _supplier_entry(
        world, nips["b"], gross="1230.00", flags=["hold_payment"], account=_nrb(12)
    )
    duplicate = await _supplier_entry(
        world, nips["b"], gross="1230.00", flags=["duplicate"], account=_nrb(12)
    )
    no_account = await _supplier_entry(world, nips["c"], gross="99.00")
    office = await _supplier_entry(
        world, nips["c"], gross="99.00", flags=["tax_office_account"], account=None
    )
    undated = await _supplier_entry(
        world, nips["c"], gross="99.00", account=_nrb(13), due=date(2099, 1, 1)
    )
    world["listed"].add(_nrb(12))
    ids = [big, small, held, duplicate, no_account, office, undated]
    response = await client.post(
        f"{PAY}/plan", json={}, headers=_headers(world["accountant"])
    )
    items = _items(response, ids)
    assert undated not in items  # termin po dacie planu
    assert items[big]["mode"] == "mpp" and items[big]["mode_suggested"] is True
    assert {ack["code"] for ack in items[big]["acks"]} == {
        "white_list",
        "account_manual",
        "mpp_suggested",
    }
    assert items[big]["white_list"]["state"] == "not_listed"
    assert items[big]["title"].startswith("/VAT/3739,84/IDC/")
    assert items[small]["mode"] == "standard"
    assert items[small]["white_list"] == {
        "state": "listed",
        "request_id": f"test-{_nrb(12)[-4:]}",
        "on_date": world["today"].isoformat(),
        "label": "W wykazie VAT",
    }
    assert items[small]["acks"] == [] and items[small]["preselect"] is True
    assert held not in items  # „Wstrzymać płatność” znika z planu
    assert items[duplicate]["block"] == "duplicate"
    assert items[no_account]["block"] == "no_account"
    assert items[office]["block"] == "tax_office_manual"

    # Tryb „off” = „nie sprawdzono”, nie „brak w wykazie”.
    world["wl"]["mode"] = "off"
    off = _items(
        await client.post(
            f"{PAY}/plan", json={}, headers=_headers(world["accountant"])
        ),
        ids,
    )
    assert off[small]["white_list"]["state"] == "off"
    assert off[small]["white_list"]["label"].startswith("Nie sprawdzono")
    # Poniżej 15 000 zł brutto próg wykazu nie działa, ale rachunek wpisany
    # ręcznie i niesprawdzony zawsze wymaga odhaczenia.
    assert [ack["code"] for ack in off[small]["acks"]] == ["account_manual"]
    assert "white_list" in {ack["code"] for ack in off[big]["acks"]}


# ── Paczka ───────────────────────────────────────────────────────────────────


async def test_paczka_plik_elixir_odhaczenie_i_anulowanie(world, client) -> None:
    nips = world["nips"]
    accountant = _headers(world["accountant"])
    big = await _supplier_entry(
        world, nips["a"], gross="20000.00", vat="3739.84", account=_nrb(21)
    )
    small = await _supplier_entry(world, nips["b"], gross="1230.00", account=_nrb(22))
    world["listed"].add(_nrb(22))

    refused = await client.post(
        f"{PAY}/batches", json={"entry_ids": [big, small]}, headers=accountant
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_ack"
    assert await _state(big) == "unpaid"

    created = await client.post(
        f"{PAY}/batches",
        json={"entry_ids": [big, small], "acknowledged": [big]},
        headers=accountant,
    )
    assert created.status_code == 200, created.text
    batch = created.json()
    assert batch["format"] == "elixir" and batch["count"] == 2
    assert batch["total"] == "21230.00"
    assert {await _state(big), await _state(small)} == {"in_batch"}

    again = await client.post(
        f"{PAY}/batches", json={"entry_ids": [small]}, headers=accountant
    )
    assert again.status_code == 409
    assert again.json()["detail"]["items"][0]["block"] == "in_batch"

    file = await client.get(f"{PAY}/batches/{batch['id']}/file", headers=accountant)
    assert file.status_code == 200, file.text
    lines = file.content.decode("windows-1250").strip().split("\r\n")
    assert len(lines) == 2
    by_amount = {line.split(",")[2]: line for line in lines}
    assert by_amount["2000000"].endswith('"53"')  # MPP
    assert "/VAT/3739,84/IDC/" in by_amount["2000000"]
    assert by_amount["123000"].endswith('"51"')
    assert world["ksef"][small] in by_amount["123000"]

    cancelled = await client.post(
        f"{PAY}/batches/{batch['id']}/cancel", headers=accountant
    )
    assert cancelled.status_code == 200 and cancelled.json()["released"] == 2
    assert {await _state(big), await _state(small)} == {"unpaid"}
    assert (
        await client.post(f"{PAY}/batches/{batch['id']}/cancel", headers=accountant)
    ).status_code == 409
    assert (
        await client.get(f"{PAY}/batches/{batch['id']}/file", headers=accountant)
    ).status_code == 409


async def test_dwie_rownolegle_paczki_nie_biora_tej_samej_faktury(
    world, client
) -> None:
    entry = await _supplier_entry(
        world, world["nips"]["b"], gross="500.00", account=_nrb(31)
    )
    world["listed"].add(_nrb(31))
    headers = _headers(world["accountant"])
    first, second = await asyncio.gather(
        client.post(f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers),
        client.post(f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    async with AsyncSessionLocal() as db:
        batches = await db.scalars(
            select(FinancePaymentBatch).where(
                FinancePaymentBatch.created_by == world["accountant"].id
            )
        )
        assert len(list(batches)) == 1


async def test_waluta_obca_tylko_csv(world, client) -> None:
    entry = await _supplier_entry(
        world,
        world["nips"]["c"],
        gross="300.00",
        account="DE89370400440532013000",
        currency="EUR",
    )
    headers = _headers(world["accountant"])
    elixir_refused = await client.post(
        f"{PAY}/batches",
        json={"entry_ids": [entry], "acknowledged": [entry], "format": "elixir"},
        headers=headers,
    )
    assert elixir_refused.status_code == 422
    # Rachunek zagraniczny wpisany ręcznie — wykaz VAT go nie sprawdzi.
    created = await client.post(
        f"{PAY}/batches",
        json={"entry_ids": [entry], "acknowledged": [entry]},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assert created.json()["format"] == "csv" and created.json()["currency"] == "EUR"
    file = await client.get(
        f"{PAY}/batches/{created.json()['id']}/file", headers=headers
    )
    text_ = file.content.decode("utf-8-sig")
    assert "DE89370400440532013000" in text_ and ";EUR;" in text_


# ── Wyciąg ───────────────────────────────────────────────────────────────────


def _mt940(*operations: tuple[str, str, str, str]) -> bytes:
    """Wyciąg MT940: (kwota, tytuł, rachunek odbiorcy, referencja banku)."""

    body = ":20:W1\r\n:25:/PL" + _nrb(1) + "\r\n:60F:C261117PLN100000,00\r\n"
    for amount, title, account, ref in operations:
        body += (
            f":61:2611201120D{amount}NTRFNONREF//{ref}\r\n"
            f":86:020~00TR~20{title}~32Dostawca Testowy~38PL{account}\r\n"
        )
    return (body + ":62F:C261120PLN0,00\r\n-").encode()


async def test_wyciag_dokladnie_czesciowo_niejednoznacznie_i_ponownie(
    world, client
) -> None:
    nips = world["nips"]
    headers = _headers(world["accountant"])
    batched = await _supplier_entry(world, nips["a"], gross="700.00", account=_nrb(41))
    partial = await _supplier_entry(world, nips["b"], gross="1000.00", account=_nrb(42))
    twin_a = await _supplier_entry(
        world, nips["a"], gross="300.00", number="7/11/2026", account=_nrb(41)
    )
    twin_c = await _supplier_entry(
        world, nips["c"], gross="300.00", number="7/11/2026", account=_nrb(43)
    )
    world["listed"].update({_nrb(41), _nrb(42), _nrb(43)})
    created = await client.post(
        f"{PAY}/batches", json={"entry_ids": [batched]}, headers=headers
    )
    assert created.status_code == 200, created.text

    marker = uuid.uuid4().hex[:6].upper()
    raw = _mt940(
        ("700,00", "przelew", _nrb(41), f"A{marker}"),
        ("400,00", world["ksef"][partial], _nrb(42), f"B{marker}"),
        ("300,00", "Faktura 7/11/2026", _nrb(44), f"C{marker}"),
        ("55,00", "czynsz", _nrb(45), f"D{marker}"),
    )
    upload = await client.post(
        f"{PAY}/statements", files={"file": ("w.sta", raw)}, headers=headers
    )
    assert upload.status_code == 200, upload.text
    result = upload.json()
    assert (result["matched"], result["partial"], result["unmatched"]) == (1, 1, 1)
    assert result["skipped"] == 1  # czynsz nie dotyczy żadnej faktury
    assert await _state(batched) == "paid"
    assert await _state(partial) == "partially_paid"
    detail = await client.get(f"{PAY}/batches/{created.json()['id']}", headers=headers)
    assert detail.json()["status"] == "done"

    again = await client.post(
        f"{PAY}/statements", files={"file": ("w.sta", raw)}, headers=headers
    )
    assert again.json()["known"] == 4 - 1 and again.json()["matched"] == 0

    overview = await client.get(f"{PAY}/statements", headers=headers)
    (line,) = [
        row
        for row in overview.json()["unmatched"]
        if row["title"] == "Faktura 7/11/2026"
    ]
    assert {hint["entry_id"] for hint in line["hints"]} == {twin_a, twin_c}
    assigned = await client.post(
        f"{PAY}/records/{line['id']}/assign", json={"entry_id": twin_c}, headers=headers
    )
    assert assigned.status_code == 200, assigned.text
    assert await _state(twin_c) == "paid"
    twice = await client.post(
        f"{PAY}/records/{line['id']}/ignore",
        json={"reason": "duplikat"},
        headers=headers,
    )
    assert twice.status_code == 409

    filtered = await client.get(
        COSTS,
        params={"stage": "new", "payment": "partially_paid", "q": nips["b"]},
        headers=headers,
    )
    assert [item["id"] for item in filtered.json()["items"]] == [partial]
    assert filtered.json()["items"][0]["payment"]["label"] == "Zapłacona częściowo"


# ── Karta: rachunek i ręczne „Opłacono” ──────────────────────────────────────


async def test_rachunek_z_kartoteki_i_reczne_oplacono(world, client) -> None:
    nips = world["nips"]
    headers = _headers(world["accountant"])
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip", id_value=nips["c"], name="Dostawca C"
        )
        db.add(party)
        await db.commit()
    first = await _supplier_entry(world, nips["c"], gross="200.00")
    second = await _supplier_entry(world, nips["c"], gross="300.00")

    bad = await client.put(
        f"{PAY}/entries/{first}", json={"account": "PL123"}, headers=headers
    )
    assert bad.status_code == 422
    saved = await client.put(
        f"{PAY}/entries/{first}",
        json={"account": _nrb(51), "remember": True},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["account_source"] == "manual"
    other = await client.get(f"{PAY}/entries/{second}", headers=headers)
    assert other.json()["account"] == _nrb(51)
    assert other.json()["account_source"] == "counterparty"

    paid_on = world["today"].isoformat()
    too_much = await client.post(
        f"{PAY}/entries/{second}/paid",
        json={"amount": "301.00", "paid_on": paid_on, "reason": "karta firmowa"},
        headers=headers,
    )
    assert too_much.status_code == 422
    part = await client.post(
        f"{PAY}/entries/{second}/paid",
        json={"amount": "100.00", "paid_on": paid_on, "reason": "karta firmowa"},
        headers=headers,
    )
    assert part.status_code == 200, part.text
    assert (
        part.json()["state"] == "partially_paid" and part.json()["to_pay"] == "200.00"
    )
    rest = await client.post(
        f"{PAY}/entries/{second}/paid",
        json={"paid_on": paid_on, "reason": "karta firmowa"},
        headers=headers,
    )
    assert rest.json()["state"] == "paid" and rest.json()["paid_source"] == "manual"


# ── Uprawnienia ──────────────────────────────────────────────────────────────


async def test_faktury_zespolu_w_paczce_tylko_dla_plac(world, client) -> None:
    """D2: faktura osoby zespołu nie pojawia się poza Płacami (plan, sumy, karta),
    a Płace widzą ją zablokowaną — zapłatę prowadzi rozliczenie miesiąca."""

    payroll_entry = world["payroll_entry"]
    supplier = await _supplier_entry(
        world, world["nips"]["b"], gross="100.00", account=_nrb(61)
    )
    world["listed"].add(_nrb(61))
    only = _headers(world["module_only"])
    hidden = await client.post(f"{PAY}/plan", json={}, headers=only)
    assert hidden.status_code == 200
    ids = {item["entry_id"] for item in hidden.json()["items"]}
    assert supplier in ids and payroll_entry not in ids
    names = {item["seller_name"] for item in hidden.json()["items"]}
    assert world["person"].name not in names
    assert (
        await client.get(f"{PAY}/entries/{payroll_entry}", headers=only)
    ).status_code == 404
    refused = await client.post(
        f"{PAY}/batches", json={"entry_ids": [payroll_entry]}, headers=only
    )
    assert refused.status_code == 404

    payroll = _headers(world["accountant"])
    seen = _items(
        await client.post(f"{PAY}/plan", json={}, headers=payroll), [payroll_entry]
    )
    assert seen[payroll_entry]["block"] == "payroll_path"
    card = await client.get(f"{PAY}/entries/{payroll_entry}", headers=payroll)
    assert card.json()["path"] == "payroll"
    paid = await client.post(
        f"{PAY}/entries/{payroll_entry}/paid",
        json={"paid_on": world["today"].isoformat(), "reason": "przelew"},
        headers=payroll,
    )
    assert paid.status_code == 409
    batch = await client.post(
        f"{PAY}/batches", json={"entry_ids": [payroll_entry]}, headers=payroll
    )
    assert batch.status_code == 409
    assert batch.json()["detail"]["items"][0]["block"] == "payroll_path"


async def test_bez_modulu_finanse_403_a_wylaczony_modul_404(world, client) -> None:
    assert (
        await client.post(f"{PAY}/plan", json={}, headers=_headers(world["recruiter"]))
    ).status_code == 403
    await _set(module_settings.SETTING_KEY, {"enabled": False})
    assert (
        await client.get(f"{PAY}/batches", headers=_headers(world["accountant"]))
    ).status_code == 404
    assert (
        await client.get(f"{PAY}/batches", headers=_headers(world["admin"]))
    ).status_code == 200


@pytest.mark.parametrize("account", ["PL00 1090", "abc"])
async def test_rachunek_nadawcy_walidowany(world, client, account) -> None:
    response = await client.put(
        f"{PAY}/settings",
        json={"sender_name": "Spółka", "sender_account": account},
        headers=_headers(world["accountant"]),
    )
    assert response.status_code == 422


# ── Bramka zapłaty z rozliczeń klientów (KEŚU) ───────────────────────────────


async def _contractor_entry(
    world: World, *, rule: str, kesu: str, on_mail: bool = False
) -> tuple[int, int]:
    """Faktura kontraktora klienta z rozliczeniem miesiąca i regułą klienta."""

    client_id = await _client()
    contract_id = await _contract(client_id, await _candidate())
    nip = world["nips"]["c"]
    month = "2026-10"
    meta = {"remaining_after": None, "kesu": {"state": kesu}}
    if on_mail:
        meta["pay_on_mail"] = True
    async with AsyncSessionLocal() as db:
        db.add(
            ClientSettlementRuleSet(
                client_id=client_id,
                effective_from="2020-01",
                rules={"pay.after_client_signature": {"level": rule}},
            )
        )
        db.add(
            ClientSettlement(
                contract_id=contract_id,
                client_id=client_id,
                period_month=month,
                status="accepted",
                checks=[meta],
            )
        )
        invoice = ClientContractorInvoice(
            ksef_number=_ksef(nip),
            seller_nip=nip,
            seller_name="Kontraktor Testowy",
            invoice_number=f"K/{random.randint(1, 99999)}/10/2026",
            issue_date=date(2026, 11, 2),
            gross_amount=Decimal("1230.00"),
            net_amount=Decimal("1000.00"),
            vat_amount=Decimal("230.00"),
            contract_id=contract_id,
            period_month=month,
            nip_state="known",
        )
        db.add(invoice)
        await db.commit()
        await ledger.catch_up(db)
        entry = await db.scalar(
            select(FinanceCostEntry).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.source_id == invoice.id,
            )
        )
        entry.stage = "new"
        entry.due_date = world["today"] - timedelta(days=1)
        db.add(FinanceCostPayment(entry_id=entry.id, account=_nrb(71)))
        await db.commit()
        entry_id = entry.id
    world["listed"].add(_nrb(71))
    world.setdefault("clients", []).append(client_id)
    return entry_id, client_id


async def _drop_client(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.contract_id.in_(
                    select(ClientSettlement.contract_id).where(
                        ClientSettlement.client_id == client_id
                    )
                )
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
    await cleanup_client(client_id)


@pytest.mark.parametrize(
    ("rule", "kesu", "on_mail", "expected"),
    [
        ("block", "awaiting_client", False, "blocked"),
        ("block", "signed", False, "free"),
        ("block", "awaiting_client", True, "free"),
        ("warn", "awaiting_client", False, "ack"),
        ("off", "awaiting_client", False, "free"),
    ],
)
async def test_zaplata_kontraktora_czeka_na_podpis_klienta_na_kesu(
    world, client, rule, kesu, on_mail, expected
) -> None:
    entry, client_id = await _contractor_entry(
        world, rule=rule, kesu=kesu, on_mail=on_mail
    )
    headers = _headers(world["accountant"])
    try:
        plan = _items(
            await client.post(f"{PAY}/plan", json={}, headers=headers), [entry]
        )
        row = plan[entry]
        if expected == "blocked":
            assert row["block"] == "client_signature"
            assert row["block_label"].startswith(
                "Zapłata czeka na podpis klienta na KEŚU"
            )
            refused = await client.post(
                f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers
            )
            assert refused.status_code == 409
            assert refused.json()["detail"]["code"] == "blocked"
            return
        assert row["selectable"] is True
        if expected == "ack":
            assert [ack["code"] for ack in row["acks"]] == ["client_signature"]
            assert row["acks"][0]["label"].startswith("Zapłata czeka na podpis")
            refused = await client.post(
                f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers
            )
            assert refused.json()["detail"]["code"] == "needs_ack"
            created = await client.post(
                f"{PAY}/batches",
                json={"entry_ids": [entry], "acknowledged": [entry]},
                headers=headers,
            )
        else:
            assert row["acks"] == []
            created = await client.post(
                f"{PAY}/batches", json={"entry_ids": [entry]}, headers=headers
            )
        assert created.status_code == 200, created.text
        assert await _state(entry) == "in_batch"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FinanceCostEntry).where(FinanceCostEntry.id == entry)
            )
            await db.commit()
        await _drop_client(client_id)


# ── Przegląd E3: paczka czekająca na bank (1) ────────────────────────────────


async def test_paczka_czekajaca_na_bank_blokuje_oplacono_flage_i_przypisz(
    world, client
) -> None:
    nips = world["nips"]
    headers = _headers(world["accountant"])
    x = await _supplier_entry(world, nips["a"], gross="100.00", account=_nrb(81))
    y = await _supplier_entry(world, nips["b"], gross="200.00", account=_nrb(82))
    z = await _supplier_entry(world, nips["c"], gross="300.00", account=_nrb(83))
    world["listed"].update({_nrb(81), _nrb(82), _nrb(83)})
    created = await client.post(
        f"{PAY}/batches", json={"entry_ids": [x, y, z]}, headers=headers
    )
    assert created.status_code == 200, created.text
    batch = created.json()["id"]
    first = await client.get(f"{PAY}/batches/{batch}/file", headers=headers)
    assert first.status_code == 200, first.text
    assert first.headers["x-batch-file-changed"] == "false"
    assert world["ksef"][x] in first.content.decode("windows-1250")

    today = world["today"].isoformat()
    paid = await client.post(
        f"{PAY}/entries/{x}/paid",
        json={"paid_on": today, "reason": "karta firmowa"},
        headers=headers,
    )
    assert paid.status_code == 409
    assert "paczce czekającej na bank" in paid.json()["detail"]
    partial = await client.post(
        f"{PAY}/entries/{x}/paid",
        json={"amount": "10.00", "paid_on": today, "reason": "karta"},
        headers=headers,
    )
    assert partial.status_code == 409
    patched = await client.patch(
        f"{COSTS}/{x}", json={"flags": ["hold_payment"]}, headers=headers
    )
    assert patched.status_code == 409
    bulk = await client.post(
        f"{COSTS}/actions",
        json={"ids": [x], "action": "flag_add", "flag": "hold_payment"},
        headers=headers,
    )
    assert bulk.status_code == 409
    account = await client.put(
        f"{PAY}/entries/{x}", json={"account": _nrb(84)}, headers=headers
    )
    assert account.status_code == 409

    released = await client.post(
        f"{PAY}/batches/{batch}/items/{x}/release", headers=headers
    )
    assert released.status_code == 200, released.text
    assert released.json()["file_stale"] is True
    detail = await client.get(f"{PAY}/batches/{batch}", headers=headers)
    assert detail.json()["file_stale"] is True
    second = await client.get(f"{PAY}/batches/{batch}/file", headers=headers)
    assert second.headers["x-batch-file-changed"] == "true"
    text_ = second.content.decode("windows-1250")
    assert world["ksef"][x] not in text_ and world["ksef"][y] in text_
    assert await _state(x) == "unpaid"
    # Zdjęta z paczki: „Opłacono” już działa.
    reopened = await client.post(
        f"{PAY}/entries/{x}/paid",
        json={"paid_on": today, "reason": "karta firmowa"},
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text

    marker = uuid.uuid4().hex[:6].upper()
    raw = _mt940(("200,00", "przelew", _nrb(82), f"Y{marker}"))
    upload = await client.post(
        f"{PAY}/statements", files={"file": ("w.sta", raw)}, headers=headers
    )
    assert upload.json()["matched"] == 1, upload.text
    assert await _state(y) == "paid"
    third = await client.get(f"{PAY}/batches/{batch}/file", headers=headers)
    text_ = third.content.decode("windows-1250")
    assert world["ksef"][y] not in text_ and world["ksef"][z] in text_
    assert len(text_.strip().split("\r\n")) == 1


# ── Przegląd E3: zaksięgowana faktura (2) ────────────────────────────────────


async def test_zaksiegowana_faktura_dostaje_wstrzymanie_platnosci(
    world, client
) -> None:
    headers = _headers(world["accountant"])
    entry = await _supplier_entry(
        world, world["nips"]["a"], gross="100.00", account=_nrb(85)
    )
    world["listed"].add(_nrb(85))
    async with AsyncSessionLocal() as db:
        row = await db.get(FinanceCostEntry, entry)
        row.stage = "booked"
        await db.commit()
    before = _items(await client.post(f"{PAY}/plan", json={}, headers=headers), [entry])
    assert before[entry]["selectable"] is True
    held = await client.patch(
        f"{COSTS}/{entry}", json={"flags": ["hold_payment"]}, headers=headers
    )
    assert held.status_code == 200, held.text
    assert held.json()["flags"] == ["hold_payment"]
    assert held.json()["history"][-1]["action"] == "flags"
    after = await client.post(f"{PAY}/plan", json={}, headers=headers)
    assert entry not in {item["entry_id"] for item in after.json()["items"]}
    due = await client.patch(
        f"{COSTS}/{entry}",
        json={"due_date": world["today"].isoformat()},
        headers=headers,
    )
    assert due.status_code == 200
    # Dekret zostaje zamknięty: kategoria i „Duplikat” — nie.
    category = await client.patch(
        f"{COSTS}/{entry}", json={"category": "other"}, headers=headers
    )
    assert category.status_code == 409
    duplicate = await client.patch(
        f"{COSTS}/{entry}",
        json={"flags": ["hold_payment", "duplicate"]},
        headers=headers,
    )
    assert duplicate.status_code == 409


# ── Przegląd E3: rachunek ręcznie, ślad i wykaz (3) ──────────────────────────


async def test_reczny_rachunek_ma_slad_i_wymaga_sprawdzenia_w_wykazie(
    world, client
) -> None:
    nips = world["nips"]
    headers = _headers(world["accountant"])
    async with AsyncSessionLocal() as db:
        party = FinanceCounterparty(
            id_type="nip", id_value=nips["a"], name="Dostawca A"
        )
        db.add(party)
        await db.commit()
        party_id = party.id
    entry = await _supplier_entry(world, nips["a"], gross="50.00")

    saved = await client.put(
        f"{PAY}/entries/{entry}", json={"account": _nrb(86)}, headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["account_note"].startswith(
        f"Rachunek zmieniony ręcznie na karcie przez {world['accountant'].name}"
    )
    card = await client.get(f"{COSTS}/{entry}", headers=headers)
    (event,) = [e for e in card.json()["history"] if e["action"] == "account"]
    assert event["detail"]["from"] is None and event["detail"]["to"] == _nrb(86)
    assert event["actor"] == world["accountant"].name
    async with AsyncSessionLocal() as db:
        # Domyślnie bez „zapamiętaj” — kartoteka nietknięta.
        assert await db.get(FinanceCounterpartyAccount, party_id) is None

    # Mała kwota, rachunek niepotwierdzony w wykazie → odhaczenie mimo progu.
    plan = _items(await client.post(f"{PAY}/plan", json={}, headers=headers), [entry])
    assert [ack["code"] for ack in plan[entry]["acks"]] == ["account_manual"]
    assert plan[entry]["account_note"].startswith("Rachunek zmieniony ręcznie")
    world["listed"].add(_nrb(86))
    plan = _items(await client.post(f"{PAY}/plan", json={}, headers=headers), [entry])
    assert plan[entry]["acks"] == []

    for account in (_nrb(87), _nrb(88)):
        remembered = await client.put(
            f"{PAY}/entries/{entry}",
            json={"account": account, "remember": True},
            headers=headers,
        )
        assert remembered.status_code == 200, remembered.text
    async with AsyncSessionLocal() as db:
        events = list(
            await db.scalars(
                select(FinanceCounterpartyAccountEvent)
                .where(FinanceCounterpartyAccountEvent.counterparty_id == party_id)
                .order_by(FinanceCounterpartyAccountEvent.id)
            )
        )
        assert [(e.old_account, e.new_account) for e in events] == [
            (None, _nrb(87)),
            (_nrb(87), _nrb(88)),
        ]
        assert {e.actor_id for e in events} == {world["accountant"].id}
        payment = await db.get(FinanceCostPayment, entry)
        assert payment.account_changed_by == world["accountant"].id
    card = await client.get(f"{COSTS}/{entry}", headers=headers)
    history = [e for e in card.json()["history"] if e["action"] == "account"]
    assert [e["detail"]["to"] for e in history] == [_nrb(86), _nrb(87), _nrb(88)]


# ── Przegląd E3: faktoring i korekty (4, 5) ──────────────────────────────────


async def _contractor_invoice(
    world: World,
    *,
    gross: str,
    vat: str = "0.00",
    number: str,
    invoice_type: str = "Vat",
    details: dict | None = None,
    entry_account: str | None = None,
) -> tuple[int, str]:
    nip = world["nips"]["c"]
    ksef = _ksef(nip)
    async with AsyncSessionLocal() as db:
        invoice = ClientContractorInvoice(
            ksef_number=ksef,
            seller_nip=nip,
            seller_name="Kontraktor Testowy",
            invoice_number=number,
            invoice_type=invoice_type,
            issue_date=date(2026, 11, 2),
            gross_amount=Decimal(gross),
            net_amount=Decimal(gross) - Decimal(vat),
            vat_amount=Decimal(vat),
            nip_state="known",
            details=details,
        )
        db.add(invoice)
        await db.commit()
        await ledger.catch_up(db)
        entry = await db.scalar(
            select(FinanceCostEntry).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.source_id == invoice.id,
            )
        )
        entry.stage = "new"
        entry.due_date = world["today"] - timedelta(days=1)
        if entry_account:
            db.add(FinanceCostPayment(entry_id=entry.id, account=entry_account))
        await db.commit()
        world["ksef"][entry.id] = ksef
        return entry.id, ksef


async def _drop_contractor_invoices(world: World) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FinanceCostEntry).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.seller_nip == world["nips"]["c"],
            )
        )
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.seller_nip == world["nips"]["c"]
            )
        )
        await db.commit()


async def test_faktoring_platnosc_na_rachunek_faktora(world, client) -> None:
    headers = _headers(world["accountant"])
    seller, factor = _nrb(91), _nrb(92)
    try:
        entry, _number = await _contractor_invoice(
            world,
            gross="20000.00",
            vat="3739.84",
            number="F/1/11/2026",
            details={"state": "ok", "accounts": [seller], "factor_accounts": [factor]},
        )
        async with AsyncSessionLocal() as db:
            row = await db.get(FinanceCostEntry, entry)
            row.flags = ["no_mpp"]
            await db.commit()
        plan = _items(
            await client.post(f"{PAY}/plan", json={}, headers=headers), [entry]
        )
        row = plan[entry]
        assert (row["account"], row["account_source"]) == (factor, "ksef_factor")
        assert row["account_source_label"].startswith("faktor")
        # Faktor nie musi być w wykazie dla NIP-u sprzedawcy — wynik informuje.
        assert row["white_list"]["state"] == "not_listed"
        assert row["white_list"]["informational"] is True
        assert row["acks"] == []
        created = await client.post(
            f"{PAY}/batches",
            json={"entry_ids": [entry], "format": "csv"},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        assert created.json()["items"][0]["account_source"] == "ksef_factor"
        file = await client.get(
            f"{PAY}/batches/{created.json()['id']}/file", headers=headers
        )
        text_ = file.content.decode("utf-8-sig")
        assert "(rachunek faktora)" in text_ and text_.rstrip().endswith(";faktor")
        assert f"PL{factor[:2]} {factor[2:6]}" in text_
    finally:
        await _drop_contractor_invoices(world)


async def test_korekta_ujemna_pomniejsza_fakture_pierwotna(world, client) -> None:
    headers = _headers(world["accountant"])
    world["listed"].add(_nrb(93))
    try:
        root, root_ksef = await _contractor_invoice(
            world,
            gross="10000.00",
            vat="1869.92",
            number="K/7/10/2026",
            entry_account=_nrb(93),
        )
        correction, _k = await _contractor_invoice(
            world,
            gross="-2000.00",
            vat="-373.98",
            number="KOR/1/11/2026",
            invoice_type="Kor",
            details={
                "state": "ok",
                "type": "KOR",
                "corrected": [
                    {"ksef_number": root_ksef, "invoice_number": "K/7/10/2026"}
                ],
            },
        )
        orphan, _k2 = await _contractor_invoice(
            world,
            gross="-500.00",
            number="KOR/2/11/2026",
            invoice_type="Kor",
            details={
                "state": "ok",
                "type": "KOR",
                "corrected": [{"ksef_number": _ksef(world["nips"]["c"])}],
            },
        )
        plan = _items(
            await client.post(f"{PAY}/plan", json={}, headers=headers),
            [root, correction, orphan],
        )
        assert plan[root]["to_pay"] == "8000.00"
        assert plan[root]["amount_note"] == (
            "Pomniejszona o korektę: KOR/1/11/2026 (-2000.00)."
        )
        assert plan[correction]["block"] == "correction"
        assert "K/7/10/2026" in plan[correction]["block_label"]
        assert plan[orphan]["block"] == "correction_orphan"
        created = await client.post(
            f"{PAY}/batches", json={"entry_ids": [root]}, headers=headers
        )
        assert created.status_code == 200, created.text
        assert created.json()["total"] == "8000.00"
        # Korekty nie da się zapłacić osobno.
        refused = await client.post(
            f"{PAY}/batches", json={"entry_ids": [correction]}, headers=headers
        )
        assert refused.status_code == 409
    finally:
        await _drop_contractor_invoices(world)
