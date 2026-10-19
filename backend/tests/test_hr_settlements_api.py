"""Rozliczenia zespołu — trasy: bramki, dane do rozliczeń, decyzje Płac, panel osoby.

Ścieżki odmowy: moduł wyłączony (404 poza adminem), bez Płac (403 z nazwą
uprawnienia), przełożony i zespół nie widzą danych do rozliczeń (404),
osoba nie zmienia swoich danych, nikt nie zatwierdza ani nie uznaje różnicy
sam sobie, rachunek nigdy w odpowiedzi ani w śladzie. Dane fikcyjne.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.hr_ops import HrAuditEvent
from app.models.hr_payroll import EmployeeRate
from app.models.hr_settlement import EmployeeBillingDetails, PayrollSettlement
from app.models.notification import Notification, NotificationType
from app.services.hr import settlements, white_list
from app.services.hr.settlements_rules import PAYMENT_SETTINGS_KEY
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr_settlements_seed import (
    PREFIX,
    add_line,
    add_timesheet,
    closed_period,
    fake_account,
    fake_nip,
    headers,
    invoice,
    make_team,
    make_user,
    months_ago,
    set_billing,
    set_setting,
    settlements_on,  # noqa: F401  (fixture)
)


@pytest.fixture(scope="module", autouse=True)
def settlements_routes():
    """Trasy modułu w aplikacji testowej, dopóki koordynator nie wepnie ich w ``main.py``."""

    from app.api import hr_settlements
    from app.main import app

    before = list(app.router.routes)
    added = False
    if f"{PREFIX}/me" not in {getattr(route, "path", "") for route in before}:
        app.include_router(hr_settlements.router, prefix=PREFIX, tags=["hr"])
        added = True
    yield
    if added:
        app.router.routes[:] = before


async def _ensure(period_id: int) -> None:
    from app.models.hr_payroll import PayrollPeriod

    async with AsyncSessionLocal() as db:
        await settlements.ensure_for_period(
            db, await db.get(PayrollPeriod, period_id), actor_id=None
        )
        await db.commit()


async def _match(inv) -> None:
    async with AsyncSessionLocal() as db:
        db.add(inv)
        await db.flush()
        await settlements.match_invoice(db, inv)
        await db.commit()


async def _row(user_id: int) -> PayrollSettlement:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(PayrollSettlement).where(
                PayrollSettlement.user_id == user_id,
                PayrollSettlement.status != "cancelled",
            )
        )
        assert row is not None
        return row


async def _bells(user_id: int, ntype: NotificationType) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                )
            )
            or 0
        )


async def _mismatch_month(team, *, net: str = "15320.00"):
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    nip = fake_nip()
    await set_billing(team.b2b, nip=nip, account=fake_account(), source="white_list")
    await _ensure(period_id)
    await _match(
        invoice(
            nip=nip,
            net=net,
            year=year,
            month=month,
            items=[
                {
                    "name": "Usługi rekrutacyjne",
                    "quantity": "161.26",
                    "unit": "h",
                    "unit_price": "95.00",
                    "net": "15320.00",
                    "vat_rate": "23",
                }
            ],
        )
    )
    return year, month, period_id


# ── Bramki ────────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_module_off_is_404_except_admin(app_client) -> None:
    team = await make_team()
    admin = await make_user("admin", profile=False)
    year, month = months_ago(2)
    await set_setting(
        HR_MODULES_SETTING, {key: key != "settlements" for key in HR_MODULE_KEYS}
    )
    url = f"{PREFIX}/months/{year}/{month}"
    assert (await app_client.get(url, headers=headers(team.finance))).status_code == 404
    assert (
        await app_client.get(f"{PREFIX}/me", headers=headers(team.b2b))
    ).status_code == 404
    assert (await app_client.get(url, headers=headers(admin))).status_code == 200


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_queue_needs_payroll_and_names_the_permission(app_client) -> None:
    team = await make_team()
    year, month = months_ago(2)
    for user in (team.b2b, team.boss, team.hr):
        refused = await app_client.get(
            f"{PREFIX}/months/{year}/{month}", headers=headers(user)
        )
        assert refused.status_code == 403
        assert refused.json()["detail"]["permission"] == "payroll"
    # Bez kartoteki i bez uprawnień — nawet własnego panelu nie ma.
    outsider = await make_user("recruiter", profile=False)
    assert (
        await app_client.get(f"{PREFIX}/me", headers=headers(outsider))
    ).status_code == 403


# ── Dane do rozliczeń (M7) ────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_supervisor_and_colleague_see_no_billing_details(app_client) -> None:
    team = await make_team()
    await set_billing(
        team.b2b, nip=fake_nip(), account=fake_account(), source="white_list"
    )
    url = f"{PREFIX}/billing/{team.b2b.id}"
    # Przełożony — 404, jakby osoby nie było (dane wrażliwe, M7).
    assert (await app_client.get(url, headers=headers(team.boss))).status_code == 404
    assert (await app_client.get(url, headers=headers(team.uop))).status_code == 404
    own = await app_client.get(url, headers=headers(team.b2b))
    assert own.status_code == 200 and own.json()["can_edit"] is False
    for user in (team.hr, team.finance):
        seen = await app_client.get(url, headers=headers(user))
        assert seen.status_code == 200 and seen.json()["can_edit"] is True
    # Osoba nie zmienia własnego rachunku — 403 z nazwą uprawnień.
    refused = await app_client.put(
        url, json={"account": fake_account()}, headers=headers(team.b2b)
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["permissions"] == ["people_admin", "payroll"]
    assert (
        await app_client.put(url, json={"nip": fake_nip()}, headers=headers(team.boss))
    ).status_code == 403


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_account_is_never_in_response_or_audit(app_client) -> None:
    team = await make_team()
    account = fake_account()
    url = f"{PREFIX}/billing/{team.mandate.id}"
    saved = await app_client.put(
        url,
        json={"account": f"PL{account[:2]} {account[2:]}", "payment_terms_days": 10},
        headers=headers(team.hr),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["account_last4"] == account[-4:]
    assert body["account_source"] == "manual"
    assert account[:-4] not in saved.text and account[-10:] not in saved.text
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == team.mandate.id
            )
        )
        assert details.account_encrypted and account not in details.account_encrypted
        events = [
            json.dumps(event.details, ensure_ascii=False)
            for event in await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.subject_user_id == team.mandate.id
                )
            )
        ]
    assert events and not any(account[-10:] in text for text in events)

    # Zły albo za długi numer: 422 bez echa numeru (także bez ``input`` Pydantica).
    bad = account[:-1] + str((int(account[-1]) + 1) % 10)
    for wrong in (bad, account * 3):
        refused = await app_client.put(
            url, json={"account": wrong}, headers=headers(team.hr)
        )
        assert refused.status_code == 422
        assert wrong[2:12] not in refused.text


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_bad_nip_pesel_and_duplicate_nip_are_refused(app_client) -> None:
    team = await make_team()
    url = f"{PREFIX}/billing/{team.b2b.id}"
    good = fake_nip()
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    refused = await app_client.put(url, json={"nip": bad}, headers=headers(team.hr))
    assert refused.status_code == 422
    pesel_like = "9912317654"
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    pesel_like += str(
        (10 - sum(int(d) * w for d, w in zip(pesel_like, weights)) % 10) % 10
    )
    assert (
        await app_client.put(
            url, json={"symfonia_id": pesel_like}, headers=headers(team.hr)
        )
    ).status_code == 422
    assert (
        await app_client.put(
            url, json={"payment_terms_days": 91}, headers=headers(team.hr)
        )
    ).status_code == 422
    assert (
        await app_client.put(url, json={"nip": good}, headers=headers(team.hr))
    ).status_code == 200
    taken = await app_client.put(
        f"{PREFIX}/billing/{team.uop.id}", json={"nip": good}, headers=headers(team.hr)
    )
    assert taken.status_code == 409


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_white_list_pick_saves_account_with_request_id(
    app_client, monkeypatch
) -> None:
    team = await make_team()
    nip = fake_nip()
    first, second = fake_account(), fake_account()
    url = f"{PREFIX}/billing/{team.b2b.id}"
    assert (
        await app_client.put(url, json={"nip": nip}, headers=headers(team.hr))
    ).status_code == 200

    # Wyłączony wykaz (domyślny tryb) — czytelna odmowa, bez zapisu rachunku.
    disabled = await app_client.post(f"{url}/white-list", headers=headers(team.hr))
    assert disabled.status_code == 409
    assert "wyłączone" in json.dumps(disabled.json(), ensure_ascii=False)

    async def fake_search(db, nip_value, on_date, **_kw):
        return white_list.WhiteListEntry(
            nip=nip_value,
            name="Nowak Recruitment Ola Nowak",
            vat_status="active",
            accounts=(first, second),
            has_virtual_accounts=False,
            request_id="Ab12-fikcyjne",
            requested_at=None,
            on_date=on_date,
        )

    async def fake_check(db, nip_value, account, on_date, **_kw):
        return white_list.WhiteListCheck(
            nip=nip_value,
            account_last4=account[-4:],
            listed=account == second,
            request_id="Cd34-fikcyjne",
            requested_at=None,
            on_date=on_date,
        )

    monkeypatch.setattr(white_list, "search", fake_search)
    monkeypatch.setattr(white_list, "check", fake_check)
    lookup = await app_client.post(f"{url}/white-list", headers=headers(team.hr))
    assert lookup.status_code == 200, lookup.text
    assert [a["last4"] for a in lookup.json()["accounts"]] == [first[-4:], second[-4:]]
    assert first[:-4] not in lookup.text and second[:-4] not in lookup.text
    assert lookup.json()["billing"]["vat_status"] == "active"

    # Wykaz nie potwierdził pierwszego — odmowa; drugi przechodzi.
    assert (
        await app_client.post(
            f"{url}/white-list/account", json={"ref": 0}, headers=headers(team.hr)
        )
    ).status_code == 409
    assert (
        await app_client.post(
            f"{url}/white-list/account", json={"ref": 7}, headers=headers(team.hr)
        )
    ).status_code == 409
    picked = await app_client.post(
        f"{url}/white-list/account", json={"ref": 1}, headers=headers(team.hr)
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["account_source"] == "white_list"
    assert picked.json()["needs_second_person"] is False
    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id == team.b2b.id
            )
        )
    assert details.account_check_request_id == "Cd34-fikcyjne"
    # Zmiana NIP-u kasuje rachunek z wykazu (sprawdzenie dotyczyło starego NIP-u).
    changed = await app_client.put(
        url, json={"nip": fake_nip()}, headers=headers(team.hr)
    )
    assert changed.json()["account_last4"] is None


# ── Decyzje Płac (R7, R10) ────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_mismatch_needs_a_second_person_then_approval_and_payment(
    app_client,
) -> None:
    team = await make_team()
    await _mismatch_month(team)
    row = await _row(team.b2b.id)
    base = f"{PREFIX}/{row.id}"

    detail = await app_client.get(base, headers=headers(team.finance))
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "mismatch" and data["discrepancy"] == "120.00"
    assert any("Godziny: 161,26 na fakturze, 160" in line for line in data["explain"])
    assert [item["kind"] for item in data["expected_items"]] == ["hours"]

    # Zgodne nie są — zatwierdzić się nie da.
    assert (
        await app_client.post(f"{base}/approve", headers=headers(team.finance))
    ).status_code == 409

    asked = await app_client.post(
        f"{base}/request-correction", headers=headers(team.finance)
    )
    assert asked.status_code == 200
    assert await _bells(team.b2b.id, NotificationType.hr_settlement_correction) == 1

    assert (
        await app_client.post(
            f"{base}/override", json={"reason": "x"}, headers=headers(team.finance)
        )
    ).status_code == 422
    requested = await app_client.post(
        f"{base}/override",
        json={"reason": "Zaokrąglenie godzin uzgodnione z osobą"},
        headers=headers(team.finance),
    )
    assert requested.status_code == 200
    assert requested.json()["override"]["can_confirm"] is False
    # Dwa dzwonki tego samego dnia: rozbieżność i wniosek o uznanie — dzienny
    # odsiew powiadomień nie może połknąć wniosku o drugą parę oczu.
    assert await _bells(team.finance2.id, NotificationType.hr_settlement_review) == 2
    # Wnioskujący nie potwierdza sam.
    assert (
        await app_client.post(f"{base}/override/confirm", headers=headers(team.finance))
    ).status_code == 403
    confirmed = await app_client.post(
        f"{base}/override/confirm", headers=headers(team.finance2)
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "ready"

    approved = await app_client.post(f"{base}/approve", headers=headers(team.finance))
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    async with AsyncSessionLocal() as db:
        assert [s.id for s in await settlements.payable(db)] == [row.id]

    paid_on = date(*months_ago(1), 18)
    assert (
        await app_client.post(
            f"{base}/mark-paid",
            json={"amount": "18843.60", "paid_on": paid_on.isoformat(), "reason": ""},
            headers=headers(team.finance2),
        )
    ).status_code == 422
    future = date(*months_ago(-1), 1)
    assert (
        await app_client.post(
            f"{base}/mark-paid",
            json={
                "amount": "18843.60",
                "paid_on": future.isoformat(),
                "reason": "Przelew ręczny",
            },
            headers=headers(team.finance2),
        )
    ).status_code == 422
    paid = await app_client.post(
        f"{base}/mark-paid",
        json={
            "amount": "18843.60",
            "paid_on": paid_on.isoformat(),
            "reason": "Przelew ręczny",
        },
        headers=headers(team.finance2),
    )
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert paid.json()["paid_on"] == paid_on.isoformat()
    assert await _bells(team.b2b.id, NotificationType.hr_settlement_paid) == 1
    again = await app_client.post(
        f"{base}/mark-paid",
        json={
            "amount": "18843.60",
            "paid_on": paid_on.isoformat(),
            "reason": "Drugi raz",
        },
        headers=headers(team.finance2),
    )
    assert again.status_code == 409


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_nobody_decides_about_their_own_settlement(app_client) -> None:
    team = await make_team()
    payroll_person = await make_user(
        "recruiter",
        grants=("payroll",),
        employment_type="zlecenie",
        name="Paula Płacowa",
    )
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_line(
        period_id, payroll_person, employment_type="zlecenie", hours="10", rate="40.00"
    )
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="92", rate="32.00"
    )
    await _ensure(period_id)
    own = await _row(payroll_person.id)
    assert (
        await app_client.post(
            f"{PREFIX}/{own.id}/approve", headers=headers(payroll_person)
        )
    ).status_code == 403
    assert (
        await app_client.post(
            f"{PREFIX}/{own.id}/mark-paid",
            json={
                "amount": "400",
                "paid_on": date(*months_ago(1), 10).isoformat(),
                "reason": "Sobie",
            },
            headers=headers(payroll_person),
        )
    ).status_code == 403
    bulk = await app_client.post(
        f"{PREFIX}/months/{year}/{month}/approve-ready", headers=headers(payroll_person)
    )
    assert bulk.json() == {
        "year": year,
        "month": month,
        "approved": 1,
        "skipped_own": 1,
    }
    assert (await _row(payroll_person.id)).status == "ready"
    assert (await _row(team.mandate.id)).status == "approved"
    assert (
        await app_client.post(f"{PREFIX}/999999/approve", headers=headers(team.finance))
    ).status_code == 404


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_queue_sorts_by_urgency_and_prepare_fills_old_months(app_client) -> None:
    team = await make_team()
    year, month, period_id = await _mismatch_month(team)
    await add_line(
        period_id,
        team.mandate,
        employment_type="zlecenie",
        hours="92",
        rate="32.00",
        timesheet_status="submitted",
    )
    await add_line(
        period_id,
        team.uop,
        employment_type="uop",
        hours="0",
        rate=None,
        bonus_total="500",
    )
    queue = await app_client.get(
        f"{PREFIX}/months/{year}/{month}", headers=headers(team.finance)
    )
    assert queue.status_code == 200
    # Zlecenie i UoP dopisane po zamknięciu — „Załóż rozliczenia”.
    assert queue.json()["missing"] == 2
    prepared = await app_client.post(
        f"{PREFIX}/months/{year}/{month}/prepare", headers=headers(team.finance)
    )
    assert prepared.json()["created"] == 2
    data = (
        await app_client.get(
            f"{PREFIX}/months/{year}/{month}", headers=headers(team.finance)
        )
    ).json()
    assert [row["status"] for row in data["rows"]] == ["mismatch", "ready", "ready"]
    assert data["stats"]["hours_unconfirmed"] == 1 and data["missing"] == 0
    mandate = next(row for row in data["rows"] if row["employment_type"] == "zlecenie")
    assert mandate["document"]["label"] == "godziny niepotwierdzone"
    assert mandate["status_label"] == "Kwota policzona"
    # Miesiąc otwarty — nie ma czego zakładać.
    open_year, open_month = months_ago(0)
    assert (
        await app_client.post(
            f"{PREFIX}/months/{open_year}/{open_month}/prepare",
            headers=headers(team.finance),
        )
    ).status_code == 409


# ── Panel osoby (M1, M2) ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_person_sees_items_steps_and_only_own_pdf(app_client) -> None:
    team = await make_team()
    year, month = months_ago(2)
    period_id = await closed_period(year, month)
    await add_timesheet(
        team.mandate, year, month, approved_by=team.boss, work=[(3, "8"), (4, "4")]
    )
    await add_line(
        period_id, team.mandate, employment_type="zlecenie", hours="12", rate="32.00"
    )
    await add_line(
        period_id, team.b2b, employment_type="b2b", hours="160", rate="95.00"
    )
    await _ensure(period_id)

    mine = await app_client.get(
        f"{PREFIX}/me?year={year}", headers=headers(team.mandate)
    )
    assert mine.status_code == 200, mine.text
    entry = next(m for m in mine.json()["months"] if m["month"] == month)
    assert entry["status_label"] == "Kwota policzona" and entry["amount"] == "384.00"
    assert [step["key"] for step in entry["steps"]] == [
        "hours",
        "amount",
        "approved",
        "paid",
    ]
    assert entry["steps"][0]["state"] == "done" and entry["has_pdf"] is True
    assert mine.json()["settlement_word"] == "Potwierdzenie godzin"

    own = await _row(team.mandate.id)
    pdf = await app_client.get(
        f"{PREFIX}/me/{own.id}/pdf", headers=headers(team.mandate)
    )
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "rozliczenie-zlecenia" in pdf.headers["content-disposition"]
    other = await _row(team.b2b.id)
    # Cudze rozliczenie — 404; PDF B2B nie istnieje (faktura jest w KSeF) — 409.
    assert (
        await app_client.get(
            f"{PREFIX}/me/{other.id}/pdf", headers=headers(team.mandate)
        )
    ).status_code == 404
    assert (
        await app_client.get(f"{PREFIX}/{other.id}/pdf", headers=headers(team.finance))
    ).status_code == 409

    b2b = await app_client.get(f"{PREFIX}/me?year={year}", headers=headers(team.b2b))
    entry = next(m for m in b2b.json()["months"] if m["month"] == month)
    assert (
        entry["status_label"] == "Czeka na fakturę" and entry["amount_basis"] == "net"
    )
    assert [step["key"] for step in entry["steps"]] == [
        "hours",
        "document",
        "check",
        "due",
        "paid",
    ]


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_open_month_estimate_shows_items_after_approved_report(
    app_client,
) -> None:
    team = await make_team()
    year, month = months_ago(1)
    async with AsyncSessionLocal() as db:
        db.add(
            EmployeeRate(
                user_id=team.b2b.id,
                hourly_rate=Decimal("95.00"),
                currency="PLN",
                effective_from=date(year, month, 1),
            )
        )
        await db.commit()
    await add_timesheet(
        team.b2b, year, month, approved_by=team.boss, work=[(5, "8")], leave_paid=[6]
    )
    data = (
        await app_client.get(f"{PREFIX}/me?year={year}", headers=headers(team.b2b))
    ).json()
    entry = next(m for m in data["months"] if m["month"] == month)
    assert entry["final"] is False and entry["status"] == "estimate"
    assert [(i["kind"], i["amount"]) for i in entry["items"]] == [
        ("hours", "760.00"),
        ("paid_days", "760.00"),
    ]


# ── Zamknięcie i ponowne otwarcie przez trasy Płac ────────────────────────────


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_payroll_close_creates_and_reopen_cancels(app_client) -> None:
    team = await make_team()
    admin = await make_user("admin", profile=False)
    year, month = months_ago(2)
    async with AsyncSessionLocal() as db:
        db.add(
            EmployeeRate(
                user_id=team.mandate.id,
                hourly_rate=Decimal("32.00"),
                currency="PLN",
                effective_from=date(year, month, 1),
            )
        )
        await db.commit()
    await add_timesheet(
        team.mandate, year, month, approved_by=team.boss, work=[(3, "8")]
    )
    closed = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/close",
        json={"acknowledge_warnings": True},
        headers=headers(team.finance),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["settlements"]["created"] >= 1
    row = await _row(team.mandate.id)
    assert row.status == "ready" and row.expected_amount == Decimal("256.00")

    reopened = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/reopen",
        json={"reason": "Korekta godzin po zamknięciu"},
        headers=headers(admin),
    )
    assert reopened.status_code == 200, reopened.text
    async with AsyncSessionLocal() as db:
        status = await db.scalar(
            select(PayrollSettlement.status).where(PayrollSettlement.id == row.id)
        )
    assert status == "cancelled"


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_reclose_after_paid_refuses_changed_amount(app_client) -> None:
    """Audyt 19.10.2026: premia dopisana po zapłacie nie znika bez przelewu."""

    team = await make_team()
    admin = await make_user("admin", profile=False)
    year, month = months_ago(2)
    async with AsyncSessionLocal() as db:
        db.add(
            EmployeeRate(
                user_id=team.mandate.id,
                hourly_rate=Decimal("32.00"),
                currency="PLN",
                effective_from=date(year, month, 1),
            )
        )
        await db.commit()
    await add_timesheet(
        team.mandate, year, month, approved_by=team.boss, work=[(3, "8")]
    )
    close_url = f"/api/hr/payroll/months/{year}/{month}/close"
    closed = await app_client.post(
        close_url, json={"acknowledge_warnings": True}, headers=headers(team.finance)
    )
    assert closed.status_code == 200, closed.text
    row = await _row(team.mandate.id)
    async with AsyncSessionLocal() as db:
        target = await db.get(PayrollSettlement, row.id)
        await settlements.mark_paid(
            db,
            target,
            source="statement",
            amount=Decimal("230.00"),
            paid_on=date(*months_ago(1), 10),
            actor_id=None,
        )
        await db.commit()
    reopened = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/reopen",
        json={"reason": "Pominięta premia"},
        headers=headers(admin),
    )
    assert reopened.status_code == 200, reopened.text

    # Bez zmian ponowne zamknięcie przechodzi i zostawia opłacone rozliczenie.
    again = await app_client.post(
        close_url, json={"acknowledge_warnings": True}, headers=headers(team.finance)
    )
    assert again.status_code == 200, again.text
    assert again.json()["settlements"]["kept"] == 1
    reopened = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/reopen",
        json={"reason": "Pominięta premia"},
        headers=headers(admin),
    )
    assert reopened.status_code == 200, reopened.text

    bonus = await app_client.post(
        "/api/hr/payroll/bonuses",
        json={
            "recipient_user_id": team.mandate.id,
            "amount": "500.00",
            "category": "custom",
            "period_year": year,
            "period_month": month,
        },
        headers=headers(team.finance),
    )
    assert bonus.status_code in (200, 201), bonus.text
    bonus_id = bonus.json()["id"]
    async with AsyncSessionLocal() as db:
        from app.models.hr_payroll import HrBonus
        from app.services.hr import payroll_bonuses

        added = await db.get(HrBonus, bonus_id)
        # Premia przyznana po zapłacie nie jest „wypłacona”.
        assert (await payroll_bonuses.paid_flags(db, [added])) == {bonus_id: False}

    refused = await app_client.post(
        close_url, json={"acknowledge_warnings": True}, headers=headers(team.finance)
    )
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "paid_settlement_changed"
    assert "opłacone rozliczenie" in detail["message"]
    assert detail["people"][0]["user_id"] == team.mandate.id
    async with AsyncSessionLocal() as db:
        period_status = await db.scalar(
            select(PayrollSettlement.status).where(PayrollSettlement.id == row.id)
        )
    assert period_status == "paid"


@pytest.mark.usefixtures("settlements_on")
@pytest.mark.asyncio
async def test_month_before_settlements_since_closes_without_settlements(
    app_client,
) -> None:
    """Miesiąc sprzed startu rozliczeń w NEXUSIE (archiwum Compassa) — bez rozliczeń."""

    team = await make_team()
    year, month = months_ago(2)
    since = "%04d-%02d" % months_ago(1)
    await set_setting(PAYMENT_SETTINGS_KEY, {"settlements_since": since})
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                EmployeeRate(
                    user_id=team.mandate.id,
                    hourly_rate=Decimal("32.00"),
                    currency="PLN",
                    effective_from=date(year, month, 1),
                )
            )
            await db.commit()
        await add_timesheet(
            team.mandate, year, month, approved_by=team.boss, work=[(3, "8")]
        )
        closed = await app_client.post(
            f"/api/hr/payroll/months/{year}/{month}/close",
            json={"acknowledge_warnings": True},
            headers=headers(team.finance),
        )
        assert closed.status_code == 200, closed.text
        assert "settlements" not in closed.json()
        async with AsyncSessionLocal() as db:
            assert await db.scalar(select(func.count(PayrollSettlement.id))) == 0

        prepared = await app_client.post(
            f"{PREFIX}/months/{year}/{month}/prepare", headers=headers(team.finance)
        )
        assert prepared.status_code == 422, prepared.text
        assert since[:4] in prepared.json()["detail"]
        async with AsyncSessionLocal() as db:
            assert await db.scalar(select(func.count(PayrollSettlement.id))) == 0
    finally:
        await set_setting(PAYMENT_SETTINGS_KEY, None)
