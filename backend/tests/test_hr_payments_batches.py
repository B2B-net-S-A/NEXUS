"""Rozliczenia — paczka przelewów (R9, opcja domyślnie wyłączona).

Zakres: wyłączona = 409 z kodem; włączona bierze tylko zatwierdzone faktury
B2B w PLN z rachunkiem sprawdzonym w wykazie VAT w dniu paczki („NIE” albo
brak odpowiedzi = pozycja wstrzymana, chyba że rachunek spoza listy uznały
dwie osoby); rozliczenie z czekającej paczki nie wchodzi do kolejnej; plik
Elixir-O ma pełny rachunek tylko w pliku; zmiana rachunku po utworzeniu
paczki blokuje pobranie; „bank wykonał” = opłacone, anulowanie zwalnia.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import hr_payments
from app.core.database import AsyncSessionLocal
from app.core.encryption import get_token_cipher
from app.core.scheduling import business_today, local_now
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.user import User
from app.services.hr import white_list
from app.services.hr_foundation_schema import HR_MODULES_SETTING
from tests.hr import payments_fixtures as fx

PREFIX = "/api/hr/payments"
COMPANY = fx.account("99990001", "1234")
LISTED = fx.account("99990002", "4521")
UNLISTED = fx.account("99990005", "1180")
UNCHECKED = fx.account("99990006", "2222")
OVERRIDE = fx.account("99990007", "3333")


@pytest_asyncio.fixture
async def client():
    from app.main import app

    mounted = any(getattr(r, "path", "").startswith(PREFIX) for r in app.routes)
    target = app
    if not mounted:
        target = FastAPI()
        target.include_router(hr_payments.router, prefix=PREFIX)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def env(monkeypatch):
    modules = await fx.get_setting(HR_MODULES_SETTING)
    payments = await fx.get_setting(fx.SETTING_KEY)
    await fx.modules(True)
    await fx.set_setting(fx.SETTING_KEY, None)
    await fx.wipe()
    checked: list[str] = []

    async def fake_check(
        db, nip, account, on_date, *, actor_id=None, subject_user_id=None
    ):
        checked.append(account[-4:])
        if account == UNCHECKED:
            raise white_list.WhiteListError("unavailable")
        return white_list.WhiteListCheck(
            nip=nip,
            account_last4=account[-4:],
            listed=account == LISTED,
            request_id=f"sim-{account[-4:]}",
            requested_at=None,
            on_date=on_date,
        )

    monkeypatch.setattr(white_list, "check", fake_check)
    yield checked
    await fx.wipe()
    await fx.set_setting(fx.SETTING_KEY, payments)
    await fx.set_setting(HR_MODULES_SETTING, modules)


async def _enable(fmt: str = "elixir") -> None:
    await fx.set_setting(
        fx.SETTING_KEY,
        {
            "payout_day": 10,
            "transfer_batch": {
                "enabled": True,
                "format": fmt,
                "sender_account": COMPANY,
                "sender_name": "Spółka Przykładowa S.A. ul. Testowa 1 00-001 Warszawa",
            },
        },
    )


async def _people():
    """Płace + cztery faktury B2B (na liście, spoza listy, niesprawdzona, uznana) + zlecenie."""

    async with AsyncSessionLocal() as db:
        finance = await fx.make_user(db, "finance")
        second = await fx.make_user(db, "finance")
        period = await fx.closed_period(db, 2026, 10)
        made = {}
        for label, account, base in (
            ("listed", LISTED, "123456321"),
            ("unlisted", UNLISTED, "777777777"),
            ("unchecked", UNCHECKED, "555000000"),
            ("override", OVERRIDE, "111222333"),
        ):
            person = await fx.make_user(
                db,
                "employee",
                name=f"Osoba {label.capitalize()}",
                profile={"employment_type": "b2b"},
            )
            nip = fx.nip(base)
            await fx.set_billing(
                db,
                person,
                nip_value=nip,
                account_value=account,
                registry_name=f"Firma {label}",
            )
            row = await fx.settlement(
                db,
                period,
                person,
                employment_type="b2b",
                expected="1000.00",
                approver=finance,
                due_on=date(2026, 11, 18),
                override_white_list_by=(finance, second)
                if label == "override"
                else None,
            )
            await fx.invoice(
                db,
                row,
                seller_nip=nip,
                invoice_number=f"FV {label}/10/2026",
                ksef_number=f"{nip}-20261104-5F2A9C0D71B{len(made)}-4E",
                net="1000.00",
                gross="1230.00",
            )
            made[label] = row
        mandate = await fx.make_user(
            db,
            "employee",
            name="Osoba Zlecenie",
            profile={"employment_type": "zlecenie"},
        )
        await fx.set_billing(
            db, mandate, account_value=fx.account("99990003", "937"), source="manual"
        )
        made["mandate"] = await fx.settlement(
            db,
            period,
            mandate,
            employment_type="zlecenie",
            expected="900.00",
            approver=finance,
        )
        await db.commit()
    return finance, made


@pytest.mark.asyncio
async def test_batch_is_disabled_by_default(client, env):
    finance, _made = await _people()
    response = await client.post(
        f"{PREFIX}/batches", json={}, headers=fx.headers(finance)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "transfer_batch_disabled"
    listing = (
        await client.get(f"{PREFIX}/batches", headers=fx.headers(finance))
    ).json()
    assert listing["enabled"] is False
    assert env == []  # bez paczki nikt nie pyta wykazu


@pytest.mark.asyncio
async def test_batch_takes_only_checked_b2b_and_explains_the_rest(client, env):
    finance, made = await _people()
    await _enable()
    preview = await client.post(
        f"{PREFIX}/batches/preview", json={}, headers=fx.headers(finance)
    )
    assert preview.status_code == 200, preview.text
    items = {item["settlement_id"]: item for item in preview.json()["items"]}
    assert items[made["listed"].id]["included"] is True
    assert items[made["override"].id]["included"] is True
    assert items[made["unlisted"].id]["reason"] == "not_listed"
    assert items[made["unchecked"].id]["reason"] == "unchecked"
    assert items[made["mandate"].id]["reason"] == "not_b2b"
    assert all(LISTED not in str(item) for item in items.values())

    created = await client.post(
        f"{PREFIX}/batches", json={}, headers=fx.headers(finance)
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert batch["count"] == 2
    assert batch["total"] == "2460.00"
    key = batch["batch_key"]

    file = await client.get(f"{PREFIX}/batches/{key}/file", headers=fx.headers(finance))
    assert file.status_code == 200
    assert ".pli" in file.headers["content-disposition"]
    text = file.content.decode("windows-1250")
    lines = text.strip().split("\r\n")
    assert len(lines) == 2
    assert all(
        line.startswith(f"110,{business_today():%Y%m%d},123000,99990001,0,")
        for line in lines
    )
    assert f'"{LISTED}"' in text and f'"{OVERRIDE}"' in text
    assert UNLISTED not in text and UNCHECKED not in text
    assert "Spółka Przykładowa" in text

    # Ta sama paczka drugi raz: już czekające nie wchodzą, reszta jest wstrzymana.
    again = await client.post(f"{PREFIX}/batches", json={}, headers=fx.headers(finance))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "batch_empty"
    finance_list = (
        await client.get(f"{PREFIX}/finance", headers=fx.headers(finance))
    ).json()
    in_batch = {
        row["settlement_id"] for row in finance_list["rows"] if row["batch_key"]
    }
    assert in_batch == {made["listed"].id, made["override"].id}


@pytest.mark.asyncio
async def test_confirm_marks_paid_and_cancel_releases(client, env):
    finance, made = await _people()
    await _enable(fmt="csv")
    key = (
        await client.post(
            f"{PREFIX}/batches",
            json={"settlement_ids": [made["listed"].id]},
            headers=fx.headers(finance),
        )
    ).json()["batch_key"]
    csv_file = await client.get(
        f"{PREFIX}/batches/{key}/file", headers=fx.headers(finance)
    )
    assert csv_file.content.decode("utf-8-sig").startswith("Rachunek odbiorcy;")

    future = await client.post(
        f"{PREFIX}/batches/{key}/confirm",
        json={"paid_on": (business_today() + timedelta(days=1)).isoformat()},
        headers=fx.headers(finance),
    )
    assert future.status_code == 422
    confirmed = await client.post(
        f"{PREFIX}/batches/{key}/confirm", json={}, headers=fx.headers(finance)
    )
    assert confirmed.json() == {"batch_key": key, "paid": 1, "count": 1}
    async with AsyncSessionLocal() as db:
        paid = await db.get(PayrollSettlement, made["listed"].id)
    assert paid.status == "paid" and paid.paid_source == "transfer_batch"
    # Wszystko w paczce opłacone — nie ma czego anulować.
    nothing = await client.post(
        f"{PREFIX}/batches/{key}/cancel", headers=fx.headers(finance)
    )
    assert nothing.status_code == 409

    other = (
        await client.post(
            f"{PREFIX}/batches",
            json={"settlement_ids": [made["override"].id]},
            headers=fx.headers(finance),
        )
    ).json()["batch_key"]
    cancelled = await client.post(
        f"{PREFIX}/batches/{other}/cancel", headers=fx.headers(finance)
    )
    assert cancelled.json()["released"] == 1
    async with AsyncSessionLocal() as db:
        rows = list(
            await db.scalars(
                select(PayrollPayment).where(PayrollPayment.batch_key == other)
            )
        )
    assert [row.match_status for row in rows] == ["ignored"]
    # Zwolnione rozliczenie może wejść do nowej paczki.
    renewed = await client.post(
        f"{PREFIX}/batches",
        json={"settlement_ids": [made["override"].id]},
        headers=fx.headers(finance),
    )
    assert renewed.status_code == 201
    listing = (
        await client.get(f"{PREFIX}/batches", headers=fx.headers(finance))
    ).json()
    assert {item["status"] for item in listing["batches"]} == {
        "paid",
        "cancelled",
        "created",
    }


@pytest.mark.asyncio
async def test_changed_account_blocks_download(client, env):
    finance, made = await _people()
    await _enable()
    key = (
        await client.post(
            f"{PREFIX}/batches",
            json={"settlement_ids": [made["listed"].id]},
            headers=fx.headers(finance),
        )
    ).json()["batch_key"]
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == made["listed"].user_id
            )
        )
        replacement = fx.account("99990008", "8888")
        details.account_encrypted = get_token_cipher().encrypt(replacement)
        details.account_last4 = "8888"
        await db.commit()
    response = await client.get(
        f"{PREFIX}/batches/{key}/file", headers=fx.headers(finance)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "batch_account_changed"
    assert replacement not in response.text


@pytest.mark.asyncio
async def test_selected_settlement_no_longer_approved_is_refused(client, env):
    finance, made = await _people()
    await _enable()
    async with AsyncSessionLocal() as db:
        row = await db.get(PayrollSettlement, made["listed"].id)
        row.status = "ready"
        row.approved_by = None
        row.approved_at = None
        await db.commit()
    response = await client.post(
        f"{PREFIX}/batches",
        json={"settlement_ids": [made["listed"].id]},
        headers=fx.headers(finance),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_payable"


@pytest.mark.asyncio
async def test_execution_date_must_be_within_thirty_days(client, env):
    finance, made = await _people()
    await _enable()
    response = await client.post(
        f"{PREFIX}/batches",
        json={"execution_date": (business_today() - timedelta(days=1)).isoformat()},
        headers=fx.headers(finance),
    )
    assert response.status_code == 422
    assert "Data wykonania" in response.text


# ── Po przeglądzie (17.10): nieaktualna paczka, ponowne zamknięcie, uznanie po zmianie rachunku ──


async def _batch_for(client, finance, settlement_id: int) -> str:
    created = await client.post(
        f"{PREFIX}/batches",
        json={"settlement_ids": [settlement_id]},
        headers=fx.headers(finance),
    )
    assert created.status_code == 201, created.text
    return created.json()["batch_key"]


@pytest.mark.asyncio
async def test_batch_of_cancelled_settlement_refuses_file_and_confirm(client, env):
    finance, made = await _people()
    await _enable()
    key = await _batch_for(client, finance, made["listed"].id)
    async with AsyncSessionLocal() as db:
        row = await db.get(PayrollSettlement, made["listed"].id)
        row.status = "cancelled"
        row.cancelled_at = local_now()
        await db.commit()
    file = await client.get(f"{PREFIX}/batches/{key}/file", headers=fx.headers(finance))
    assert file.status_code == 409
    assert file.json()["detail"]["code"] == "batch_stale"
    assert LISTED not in file.text
    confirm = await client.post(
        f"{PREFIX}/batches/{key}/confirm", json={}, headers=fx.headers(finance)
    )
    assert confirm.status_code == 409
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(PayrollSettlement, made["listed"].id)
        ).status == "cancelled"
    released = await client.post(
        f"{PREFIX}/batches/{key}/cancel", headers=fx.headers(finance)
    )
    assert released.json()["released"] == 1


@pytest.mark.asyncio
async def test_batch_with_changed_invoice_amount_is_stale(client, env):
    finance, made = await _people()
    await _enable()
    key = await _batch_for(client, finance, made["listed"].id)
    async with AsyncSessionLocal() as db:
        row = await db.get(PayrollSettlement, made["listed"].id)
        await fx.invoice(
            db,
            row,
            seller_nip=fx.nip("123456321"),
            invoice_number="FVK 1/10/2026",
            ksef_number=f"{fx.nip('123456321')}-20261106-0B91E4C2A7D8-1F",
            net="-100.00",
            gross="-123.00",
            kind="correction",
        )
        await db.commit()
    file = await client.get(f"{PREFIX}/batches/{key}/file", headers=fx.headers(finance))
    assert file.status_code == 409
    assert file.json()["detail"]["code"] == "batch_stale"


@pytest.mark.asyncio
async def test_reclosed_month_settlement_does_not_go_to_second_batch(client, env):
    finance, made = await _people()
    await _enable()
    await _batch_for(client, finance, made["listed"].id)
    async with AsyncSessionLocal() as db:
        old = await db.get(PayrollSettlement, made["listed"].id)
        old.status = "cancelled"
        old.cancelled_at = local_now()
        await db.flush()
        period = await db.get(PayrollPeriod, old.period_id)
        person = await db.get(User, old.user_id)
        approver = await db.get(User, old.approved_by)
        renewed = await fx.settlement(
            db,
            period,
            person,
            employment_type="b2b",
            expected="1000.00",
            approver=approver,
            due_on=date(2026, 11, 18),
        )
        await fx.invoice(
            db,
            renewed,
            seller_nip=fx.nip("123456321"),
            invoice_number="FV listed/10/2026 bis",
            ksef_number=f"{fx.nip('123456321')}-20261107-0B91E4C2A7D8-2F",
            net="1000.00",
            gross="1230.00",
        )
        await db.commit()
        renewed_id = renewed.id
    preview = await client.post(
        f"{PREFIX}/batches/preview",
        json={"settlement_ids": [renewed_id]},
        headers=fx.headers(finance),
    )
    (item,) = preview.json()["items"]
    assert item["included"] is False
    assert item["reason"] == "in_batch"


@pytest.mark.asyncio
async def test_white_list_override_is_void_after_account_change(client, env):
    finance, made = await _people()
    await _enable()
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == made["override"].user_id
            )
        )
        details.account_encrypted = get_token_cipher().encrypt(UNLISTED)
        details.account_last4 = UNLISTED[-4:]
        await db.commit()
    preview = await client.post(
        f"{PREFIX}/batches/preview",
        json={"settlement_ids": [made["override"].id]},
        headers=fx.headers(finance),
    )
    (item,) = preview.json()["items"]
    assert item["included"] is False
    assert item["reason"] == "override_stale"
