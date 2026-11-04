"""„Mój czas → Premie i stawka” (etap 2, D2–D3): premie „w drodze” od podpisania
umowy, premie anulowane przez automat z powodem, „Moje rozliczenie”.

* prognoza: kontrakt podpisany (``active``) przed startem → pozycja z terminem
  „~ od” = start + 21 dni roboczych i kwotą z reguł automatu; bez stawki
  klienta → pozycja bez kwoty z powodem; szkic, kontrakt kończący się przed
  terminem i kontrakt bez odbiorcy → brak; cudza premia niewidoczna; po
  założeniu propozycji przez automat pozycja przechodzi do premii z postępem,
* ``/me``: anulowane przez automat zostają z kodem powodu, przyznane mówią kto,
* rozliczenie: miesiąc zamknięty z zamrożonych linii (``final``), bieżący jako
  szacunek z „Mojego miesiąca”, tylko o sobie, 403 bez kartoteki.

Dane fikcyjne (repo jest publiczne); kwoty zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import EmployeeRate, HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import CompanyDayOff, EmployeeProfile
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserActionOverride
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hr import placement_bonuses
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.bonus_rules import (
    DEFAULT_RULES,
    eligible_date,
    load_bonus_calendar,
)
from app.services.hr.calendar import WorkCalendar
from app.services.hr.payroll_periods import add_months
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr_settlements_seed import delete_settlement_rows

ME = "/api/hr/payroll/me"
SETTLEMENT = "/api/hr/payroll/me/settlement"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _set_setting(key: str, value) -> None:
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


async def _wipe() -> None:
    async with AsyncSessionLocal() as db:
        await delete_settlement_rows(db)
        await db.execute(delete(PayrollLine))
        await db.execute(delete(PayrollPeriod))
        await db.execute(delete(HrBonus))
        await db.execute(delete(EmployeeRate))
        await db.commit()


@pytest_asyncio.fixture
async def payroll_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        rules = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == RULES_KEY)
        )
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await _set_setting(RULES_KEY, None)
    await _wipe()
    yield
    await _wipe()
    await _set_setting(RULES_KEY, rules)
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


async def _person(db, role: str = "recruiter", *, profile: bool = True) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"me-pay-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
        await db.flush()
    return user


async def _client(db) -> Client:
    client = Client(name=f"Firma Przykładowa {uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    return client


async def _contract(
    db,
    client: Client,
    *,
    start: date,
    job: Optional[Job] = None,
    status: ContractStatus = ContractStatus.active,
    client_rate: Optional[str] = "150",
    end_date: Optional[date] = None,
) -> Contract:
    tag = uuid.uuid4().hex[:8]
    candidate = Candidate(
        name="Jan", lastname=f"Przykładowy-{tag}", email=f"cand-{tag}@example.com"
    )
    db.add(candidate)
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client.id,
        job_id=job.id if job else None,
        status=status,
        start_date=start,
        end_date=end_date,
        rate_client=None if client_rate is None else Decimal(client_rate),
        rate_candidate=Decimal("104"),
        rate_unit=RateUnit.hourly,
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
    )
    db.add(contract)
    if job is not None and job.recruiter_id is not None:
        # Rekruter premii = weryfikujący kandydata (decyzja 18.10.2026);
        # w tych testach weryfikuje prowadzący.
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_by=job.recruiter_id,
            )
        )
    await db.flush()
    return contract


async def _job(db, client: Client, *, recruiter: Optional[User], dl: Optional[User]):
    job = Job(
        title=f"Programista {uuid.uuid4().hex[:6]}",
        client_id=client.id,
        status=JobStatus.published,
        recruiter_id=recruiter.id if recruiter else None,
        delivery_lead_id=dl.id if dl else None,
    )
    db.add(job)
    await db.flush()
    return job


def _by_contract(items: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for item in items:
        out.setdefault(item["contract_id"], []).append(item)
    return out


# ── Prognoza premii „w drodze” ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signed_contract_before_start_is_forecast_with_estimate(
    app_client, payroll_on
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        dl = await _person(db, "delivery_lead")
        client = await _client(db)
        job = await _job(db, client, recruiter=me, dl=dl)
        signed = await _contract(db, client, start=today + timedelta(days=10), job=job)
        no_rate = await _contract(
            db, client, start=today + timedelta(days=5), job=job, client_rate=None
        )
        draft = await _contract(
            db,
            client,
            start=today + timedelta(days=10),
            job=job,
            status=ContractStatus.draft,
        )
        short = await _contract(
            db,
            client,
            start=today + timedelta(days=3),
            job=job,
            end_date=today + timedelta(days=8),
        )
        # Kontrakt bez odbiorcy: bez rekrutacji, klient z dwoma DL bez „głowy”
        # (jednym z nich jestem ja) — reguła automatu nie wskazuje nikogo.
        shared = await _client(db)
        other_dl = await _person(db, "delivery_lead")
        for lead in (me, other_dl):
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead.id, client_id=shared.id, is_head=False
                )
            )
        orphan = await _contract(db, shared, start=today + timedelta(days=4))
        await db.commit()

    response = await app_client.get(ME, headers=_headers(me))
    assert response.status_code == 200, response.text
    body = response.json()
    forecast = _by_contract(body["forecast"])
    assert set(forecast) == {signed.id, no_rate.id}
    assert not {draft.id, short.id, orphan.id} & set(forecast)

    [estimate] = forecast[signed.id]
    start = today + timedelta(days=10)
    assert estimate["role"] == "recruiter"
    assert estimate["amount"] == "1500.00"  # marża 46 zł/h → próg II
    async with AsyncSessionLocal() as db:
        calendar = await load_bonus_calendar(db, start, start, DEFAULT_RULES)
    assert estimate["eligible_on"] == (
        eligible_date(start, DEFAULT_RULES, calendar=calendar).isoformat()
    )
    assert estimate["start_date"] == start.isoformat()
    assert estimate["started"] is False
    assert estimate["business_days_elapsed"] == 0
    assert estimate["business_days_required"] == 21
    assert estimate["description"].startswith("Premia rekrutera — placement: Jan")

    [unknown] = forecast[no_rate.id]
    assert unknown["amount"] is None
    assert unknown["amount_missing_reason"] == "missing_rates"
    assert body["business_days_required"] == 21

    # Delivery Lead widzi swoją część tego samego placementu, nie premię rekrutera.
    theirs = (await app_client.get(ME, headers=_headers(dl))).json()["forecast"]
    assert {(i["contract_id"], i["role"]) for i in theirs} == {
        (signed.id, "dl"),
        (no_rate.id, "dl"),
    }
    assert next(i for i in theirs if i["contract_id"] == signed.id)["amount"] == (
        "772.80"
    )


@pytest.mark.asyncio
async def test_forecast_moves_to_bonuses_once_automat_proposes(
    app_client, payroll_on
) -> None:
    today = business_today()
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        client = await _client(db)
        job = await _job(db, client, recruiter=me, dl=None)
        contract = await _contract(db, client, start=today + timedelta(days=7), job=job)
        await db.commit()

    before = (await app_client.get(ME, headers=_headers(me))).json()
    assert [i["contract_id"] for i in before["forecast"]] == [contract.id]

    async with AsyncSessionLocal() as db:
        await placement_bonuses.reconcile_contract(db, contract.id)
        await db.commit()

    after = (await app_client.get(ME, headers=_headers(me))).json()
    assert after["forecast"] == []
    [proposal] = [b for b in after["bonuses"] if b["contract_id"] == contract.id]
    assert proposal["status"] == "proposed"
    assert proposal["amount"] == "1500.00"
    assert proposal["business_days_elapsed"] == 0
    assert proposal["business_days_required"] == 21
    assert proposal["eligible"] is False


# ── Premie: anulowane przez automat i kto przyznał ────────────────────────────


@pytest.mark.asyncio
async def test_me_keeps_auto_cancelled_with_reason_and_names_assigner(
    app_client, payroll_on
) -> None:
    today = business_today()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        finance = await _person(db, "finance", profile=False)
        stranger = await _person(db, "recruiter")
        base = {
            "currency": "PLN",
            "period_year": today.year,
            "period_month": today.month,
        }
        assigned = HrBonus(
            recipient_user_id=me.id,
            amount=Decimal("1000"),
            category="league",
            status="assigned",
            source="manual",
            proposed_by=finance.id,
            assigned_by=finance.id,
            assigned_at=now,
            **base,
        )
        auto_cancelled = HrBonus(
            recipient_user_id=me.id,
            amount=Decimal("1500"),
            category="recruiter",
            status="cancelled",
            source="contract_placement",
            source_key=f"contract:test-{uuid.uuid4().hex[:8]}:recruiter",
            cancelled_at=now,
            cancel_reason="contract_ended",
            **base,
        )
        manual_cancelled = HrBonus(
            recipient_user_id=me.id,
            amount=Decimal("200"),
            category="custom",
            status="cancelled",
            source="manual",
            proposed_by=finance.id,
            cancelled_by=finance.id,
            cancelled_at=now,
            cancel_reason="manual",
            **base,
        )
        theirs = HrBonus(
            recipient_user_id=stranger.id,
            amount=Decimal("700"),
            category="custom",
            status="assigned",
            source="manual",
            proposed_by=finance.id,
            assigned_by=finance.id,
            assigned_at=now,
            **base,
        )
        db.add_all([assigned, auto_cancelled, manual_cancelled, theirs])
        await db.commit()

    body = (await app_client.get(ME, headers=_headers(me))).json()
    rows = {b["id"]: b for b in body["bonuses"]}
    assert set(rows) == {assigned.id, auto_cancelled.id, manual_cancelled.id}
    assert rows[assigned.id]["assigned_by_name"] == finance.name
    assert rows[assigned.id]["period_closed"] is False
    assert rows[assigned.id]["assigned_at"] is not None
    assert rows[auto_cancelled.id]["status"] == "cancelled"
    assert rows[auto_cancelled.id]["cancel_reason"] == "contract_ended"
    assert rows[manual_cancelled.id]["cancel_reason"] == "manual"
    assert "rule_snapshot" not in rows[assigned.id]


# ── Moje rozliczenie ──────────────────────────────────────────────────────────


async def _timesheet(db, user_id: int, year: int, month: int, status: str, days):
    timesheet_id = (
        await db.execute(
            text(
                "INSERT INTO timesheets (user_id, year, month, status) "
                "VALUES (:u, :y, :m, :s) RETURNING id"
            ),
            {"u": user_id, "y": year, "m": month, "s": status},
        )
    ).scalar_one()
    for day in days:
        await db.execute(
            text(
                "INSERT INTO timesheet_entries (timesheet_id, work_date, hours, "
                "description) VALUES (:t, :d, 8, 'Praca w projekcie')"
            ),
            {"t": timesheet_id, "d": date(year, month, day)},
        )


@pytest.mark.asyncio
async def test_settlement_closed_month_is_final_current_is_estimate(
    app_client, payroll_on
) -> None:
    today = business_today()
    closed_year, closed_month = add_months(today.year, today.month, -2)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        finance = await _person(db, "finance", profile=False)
        other = await _person(db, "recruiter")
        db.add(
            EmployeeRate(
                user_id=me.id,
                hourly_rate=Decimal("100"),
                currency="PLN",
                effective_from=date(closed_year, 1, 1),
            )
        )
        period = PayrollPeriod(
            year=closed_year,
            month=closed_month,
            status="closed",
            closed_at=now,
            closed_by=finance.id,
        )
        db.add(period)
        await db.flush()
        for user, total in ((me, "16500"), (other, "99999")):
            db.add(
                PayrollLine(
                    period_id=period.id,
                    user_id=user.id,
                    person_name=user.name,
                    employment_type="b2b",
                    currency="PLN",
                    hours=Decimal("160"),
                    hourly_rate=Decimal("100"),
                    hours_amount=Decimal("16000"),
                    bonus_total=Decimal("500"),
                    total=Decimal(total),
                    timesheet_status="approved",
                )
            )
        await _timesheet(db, me.id, today.year, today.month, "draft", (1, 2, 3))
        db.add(
            HrBonus(
                recipient_user_id=me.id,
                amount=Decimal("300"),
                currency="PLN",
                category="custom",
                period_year=today.year,
                period_month=today.month,
                status="assigned",
                source="manual",
                proposed_by=finance.id,
                assigned_by=finance.id,
                assigned_at=now,
            )
        )
        await db.commit()

    closed = await app_client.get(
        SETTLEMENT, params={"year": closed_year}, headers=_headers(me)
    )
    assert closed.status_code == 200, closed.text
    frozen = next(m for m in closed.json()["months"] if m["month"] == closed_month)
    assert frozen["final"] is True
    assert frozen["hours_source"] == "frozen"
    assert frozen["lines"] == [
        {
            "currency": "PLN",
            "hourly_rate": "100.00",
            "hours_amount": "16000.00",
            "bonus_total": "500.00",
            "total": "16500.00",
        }
    ]
    # R11 (etap 4): przy włączonym module rozliczeń premia jest wypłacona
    # dopiero z opłaconym rozliczeniem — sam zamknięty miesiąc już nie wystarcza
    # (stara reguła przy wyłączonym module: test_hr_settlements_service).
    assert closed.json()["bonuses_rule"] == "paid_settlement"
    assert closed.json()["bonuses_paid"] == {}

    current = (await app_client.get(SETTLEMENT, headers=_headers(me))).json()
    assert current["year"] == today.year
    head = current["months"][0]
    assert (head["year"], head["month"]) == (today.year, today.month)
    assert head["final"] is False
    assert head["hours_source"] == "entered"
    assert head["timesheet_status"] == "draft"
    assert Decimal(head["hours"]) == Decimal("24")
    assert head["lines"] == [
        {
            "currency": "PLN",
            "hourly_rate": "100.00",
            "hours_amount": "2400.00",
            "bonus_total": "300.00",
            "total": "2700.00",
        }
    ]
    # Cudza linia (99 999 zł) nie trafia do mojego rozliczenia.
    assert all(
        line["total"] != "99999.00"
        for month in closed.json()["months"]
        for line in month["lines"]
    )


@pytest.mark.asyncio
async def test_settlement_without_own_profile_is_forbidden(
    app_client, payroll_on
) -> None:
    async with AsyncSessionLocal() as db:
        outsider = await _person(db, "recruiter", profile=False)
        finance = await _person(db, "finance", profile=False)
        db.add(
            UserActionOverride(user_id=finance.id, action="payroll", access="manage")
        )
        await db.commit()

    denied = await app_client.get(SETTLEMENT, headers=_headers(outsider))
    assert denied.status_code == 403
    # Płace bez własnej kartoteki przechodzą bramkę, ale nie mają rozliczenia.
    payroll = await app_client.get(SETTLEMENT, headers=_headers(finance))
    assert payroll.status_code == 403
    assert payroll.json()["detail"] == "Rozliczenie widzą osoby z kartoteką w NEXUSIE."
    bad_year = await app_client.get(
        SETTLEMENT, params={"year": 1999}, headers=_headers(finance)
    )
    assert bad_year.status_code == 422


@pytest.mark.asyncio
async def test_settlement_hidden_when_payroll_module_is_off(
    app_client, payroll_on
) -> None:
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        await db.commit()
    await _set_setting(
        HR_MODULES_SETTING, {**{k: True for k in HR_MODULE_KEYS}, "payroll": False}
    )
    for path in (ME, SETTLEMENT):
        response = await app_client.get(path, headers=_headers(me))
        assert response.status_code == 404, path


# ── Termin premii a dni wolne firmy (decyzja 17.10.2026) ─────────────────────


async def _free_working_day(db, plain: WorkCalendar, after: date) -> date:
    """Pierwszy dzień roboczy po ``after``, który nie jest jeszcze dniem wolnym."""

    day = plain.next_working_day_after(after)
    while await db.scalar(select(CompanyDayOff.id).where(CompanyDayOff.day == day)):
        day = plain.next_working_day_after(day)
    return day


@pytest.mark.asyncio
async def test_company_day_off_moves_bonus_deadline_and_progress_like_leave(
    app_client, payroll_on
) -> None:
    """Termin premii z placementu (21 dni roboczych) liczy kalendarz firmy z dniami
    wolnymi firmy, tak samo jak urlop: dzień wolny w oknie = termin dzień później,
    a pasek postępu nie liczy tego dnia. Dotąd liczyły się tylko święta ustawowe."""

    today = business_today()
    plain = WorkCalendar()
    started_on = today - timedelta(days=6)
    upcoming_on = today + timedelta(days=5)
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        client = await _client(db)
        job = await _job(db, client, recruiter=me, dl=None)
        started = await _contract(db, client, start=started_on, job=job)
        upcoming = await _contract(db, client, start=upcoming_on, job=job)
        past_off = await _free_working_day(db, plain, started_on)
        future_off = await _free_working_day(db, plain, upcoming_on)
        days_off = {past_off: "Dzień firmy (test)", future_off: "Dzień firmy (test)"}
        for day, name in days_off.items():
            db.add(CompanyDayOff(day=day, name=name, kind="company"))
        await db.commit()
    company = WorkCalendar(company_days_off=days_off)
    assert past_off <= today

    try:
        async with AsyncSessionLocal() as db:
            await placement_bonuses.reconcile_contract(db, started.id)
            await db.commit()
        body = (await app_client.get(ME, headers=_headers(me))).json()

        [proposal] = [b for b in body["bonuses"] if b["contract_id"] == started.id]
        deadline = eligible_date(started_on, DEFAULT_RULES, calendar=company)
        assert deadline > eligible_date(started_on, DEFAULT_RULES, calendar=plain)
        assert proposal["eligible_on"] == deadline.isoformat()
        assert proposal["business_days_elapsed"] == (
            len(plain.working_days(started_on + timedelta(days=1), today)) - 1
        )

        [estimate] = _by_contract(body["forecast"])[upcoming.id]
        plain_deadline = eligible_date(upcoming_on, DEFAULT_RULES, calendar=plain)
        assert estimate["eligible_on"] == (
            plain.next_working_day_after(plain_deadline).isoformat()
        )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CompanyDayOff).where(CompanyDayOff.day.in_(list(days_off)))
            )
            await db.commit()


async def _forecast_statements(contracts: int) -> tuple[int, int]:
    """(liczba pozycji, liczba zapytań SQL) prognozy osoby z ``contracts`` kontraktami."""

    from sqlalchemy import event

    from app.core.database import engine
    from app.services.hr.my_settlement import bonus_forecast

    today = business_today()
    async with AsyncSessionLocal() as db:
        me = await _person(db, "recruiter")
        for offset in range(contracts):
            # Każdy kontrakt z innym klientem i rekrutacją (bez DL — DL z klienta).
            client = await _client(db)
            job = await _job(db, client, recruiter=me, dl=None)
            await _contract(
                db, client, start=today + timedelta(days=3 + offset), job=job
            )
        await db.commit()

    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args, **_kwargs) -> None:  # noqa: ANN001
        statements.append(statement)

    async with AsyncSessionLocal() as db:
        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            items = await bonus_forecast(db, user_id=me.id, today=today)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)
    return len(items), len(statements)


@pytest.mark.asyncio
async def test_forecast_reads_jobs_leads_and_names_in_bulk(payroll_on) -> None:
    """Prognoza premii nie pyta bazy osobno o rekrutację, DL klienta, konsultanta
    i klienta każdego kontraktu — liczba zapytań nie rośnie z liczbą kontraktów."""

    one_items, one = await _forecast_statements(1)
    five_items, five = await _forecast_statements(5)
    assert (one_items, five_items) == (1, 5)
    assert five == one
