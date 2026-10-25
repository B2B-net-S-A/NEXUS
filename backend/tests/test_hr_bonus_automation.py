"""„Premie liczą się same” (D5): propozycje z kontraktów NEXUSA i z Ligi.

* placement = kontrakt z datą startu: DL 10% × marża/h × 168, rekruter wg
  progu, termin = start + 21 dni roboczych, okres = miesiąc terminu,
* idempotencja (``source_key``), anulowanie po zakończeniu przed terminem
  i przywrócenie po cofnięciu zakończenia, decyzje ludzi nietknięte,
* dodatkowa premia DL wyłącznie z ustawień (Compass miał ją w kodzie),
* Liga: nagrody z zamrożonych okresów → propozycje, raz.

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competition_period_closure import CompetitionPeriodClosure
from app.models.competition_winner import CompetitionWinner
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserActionOverride
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hr import league_bonuses, placement_bonuses
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.bonus_rules import (
    DEFAULT_RULES,
    eligible_date,
    load_bonus_calendar,
    parse_rules,
)
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr_settlements_seed import delete_settlement_rows


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


async def _person(db, role: str = "recruiter") -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"bonus-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
    await db.flush()
    return user


async def _placement(
    *,
    started_days_ago: int,
    client_rate: str = "150",
    cost_rate: str = "104",
    unit: RateUnit = RateUnit.hourly,
    status: ContractStatus = ContractStatus.active,
    end_date: Optional[date] = None,
    returned_from: Optional[int] = None,
) -> dict:
    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        dl = await _person(db, "delivery_lead")
        recruiter = await _person(db, "recruiter")
        client = Client(name=f"Firma Przykładowa {tag}")
        candidate = Candidate(
            name="Jan", lastname=f"Przykładowy-{tag}", email=f"cand-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Programista {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=recruiter.id,
            delivery_lead_id=dl.id,
        )
        db.add(job)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            status=status,
            start_date=today - timedelta(days=started_days_ago),
            end_date=end_date,
            rate_client=Decimal(client_rate),
            rate_candidate=Decimal(cost_rate),
            rate_unit=unit,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            returned_from_contract_id=returned_from,
        )
        db.add(contract)
        # Rekruter premii = weryfikujący kandydata (decyzja 18.10.2026).
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_by=recruiter.id,
            )
        )
        await db.commit()
        return {"contract": contract.id, "dl": dl.id, "recruiter": recruiter.id}


async def _bonuses(contract_id: int) -> dict[str, HrBonus]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(HrBonus).where(HrBonus.contract_id == contract_id)
        )
        return {row.source_key.rsplit(":", 1)[1]: row for row in rows}


async def _reconcile(contract_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        counts = await placement_bonuses.reconcile_contract(db, contract_id)
        await db.commit()
        return counts


async def _update_contract(contract_id: int, **values) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        for key, value in values.items():
            setattr(contract, key, value)
        await db.commit()


@pytest.mark.asyncio
async def test_contract_start_proposes_dl_and_recruiter_bonus_once(payroll_on) -> None:
    world = await _placement(started_days_ago=40)
    counts = await _reconcile(world["contract"])
    assert counts["created"] == 2

    found = await _bonuses(world["contract"])
    assert set(found) == {"dl", "recruiter"}
    dl, recruiter = found["dl"], found["recruiter"]
    start = business_today() - timedelta(days=40)
    async with AsyncSessionLocal() as db:
        calendar = await load_bonus_calendar(db, start, start, DEFAULT_RULES)
    deadline = eligible_date(start, DEFAULT_RULES, calendar=calendar)
    assert dl.recipient_user_id == world["dl"]
    assert dl.amount == Decimal("772.80")  # 10% × 46 zł/h × 168 h
    assert recruiter.recipient_user_id == world["recruiter"]
    assert recruiter.amount == Decimal("1500.00")  # próg II (40–50 zł/h)
    for bonus in (dl, recruiter):
        assert bonus.status == "proposed"
        assert bonus.proposed_by is None
        assert bonus.eligible_on == deadline
        assert (bonus.period_year, bonus.period_month) == (
            deadline.year,
            deadline.month,
        )
        assert bonus.rule_snapshot["margin_per_hour"] == "46.00"
    assert recruiter.rule_snapshot["tier"] == 2

    again = await _reconcile(world["contract"])
    assert again == {"created": 0, "updated": 0, "cancelled": 0, "restored": 0}
    assert len(await _bonuses(world["contract"])) == 2


async def _legacy_placement(
    *, verified: bool, lead_role: str = "delivery_lead"
) -> dict:
    """Rekrutacja jak sprzed 10.2026: DL w polu „prowadzący”, bez DL rekrutacji,
    DL klienta z przypisania, kandydata weryfikuje trzecia osoba."""

    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        lead = await _person(db, lead_role)
        client_head = await _person(db, "delivery_lead")
        verifier = await _person(db, "recruiter")
        client = Client(name=f"Firma Przykładowa {tag}")
        candidate = Candidate(
            name="Jan", lastname=f"Przykładowy-{tag}", email=f"cand-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=client_head.id, client_id=client.id, is_head=True
            )
        )
        job = Job(
            title=f"Programista {tag}",
            client_id=client.id,
            status=JobStatus.published,
            recruiter_id=lead.id,
            delivery_lead_id=None,
        )
        db.add(job)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            status=ContractStatus.active,
            start_date=today - timedelta(days=40),
            rate_client=Decimal("150"),
            rate_candidate=Decimal("104"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        if verified:
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_by=verifier.id,
                )
            )
        await db.commit()
        return {
            "contract": contract.id,
            "lead": lead.id,
            "client_head": client_head.id,
            "verifier": verifier.id,
        }


@pytest.mark.asyncio
async def test_recruiter_bonus_goes_to_verifier_and_dl_bonus_to_dl_lead(
    payroll_on,
) -> None:
    world = await _legacy_placement(verified=True)
    assert (await _reconcile(world["contract"]))["created"] == 2
    found = await _bonuses(world["contract"])
    assert found["recruiter"].recipient_user_id == world["verifier"]
    # Rekrutacja bez DL: prowadzący z rolą DL wyprzedza DL klienta.
    assert found["dl"].recipient_user_id == world["lead"]
    assert found["dl"].rule_snapshot["people_source"] == "job_lead"


@pytest.mark.asyncio
async def test_lead_without_dl_role_leaves_dl_bonus_to_client_dl(payroll_on) -> None:
    world = await _legacy_placement(verified=True, lead_role="recruiter")
    assert (await _reconcile(world["contract"]))["created"] == 2
    found = await _bonuses(world["contract"])
    assert found["dl"].recipient_user_id == world["client_head"]
    assert found["dl"].rule_snapshot["people_source"] == "client_head"
    assert found["recruiter"].recipient_user_id == world["verifier"]
    recipients = {bonus.recipient_user_id for bonus in found.values()}
    assert world["lead"] not in recipients


@pytest.mark.asyncio
async def test_unverified_candidate_gives_no_recruiter_bonus(payroll_on) -> None:
    world = await _legacy_placement(verified=False)
    assert (await _reconcile(world["contract"]))["created"] == 1
    assert set(await _bonuses(world["contract"])) == {"dl"}


async def _verified_by_dl(world: dict, *, dl_roles: list[str]) -> None:
    """Kandydata zweryfikował DL rekrutacji; ``dl_roles`` — jego role."""

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == contract.candidate_id,
                CandidateStage.job_id == contract.job_id,
            )
        )
        stage.moved_by = world["dl"]
        dl = await db.get(User, world["dl"])
        dl.roles = dl_roles
        await db.commit()


@pytest.mark.asyncio
async def test_dl_who_verified_without_recruiter_role_gets_only_dl_bonus(
    payroll_on,
) -> None:
    world = await _placement(started_days_ago=40)
    await _verified_by_dl(world, dl_roles=["delivery_lead"])
    assert (await _reconcile(world["contract"]))["created"] == 1
    assert set(await _bonuses(world["contract"])) == {"dl"}


@pytest.mark.asyncio
async def test_dl_with_recruiter_role_who_verified_gets_both_bonuses(
    payroll_on,
) -> None:
    # Decyzja Artura 25.10.2026: DL, który rekrutuje i sam zweryfikował osobę.
    world = await _placement(started_days_ago=40)
    await _verified_by_dl(world, dl_roles=["delivery_lead", "recruiter"])
    assert (await _reconcile(world["contract"]))["created"] == 2
    found = await _bonuses(world["contract"])
    assert found["dl"].recipient_user_id == world["dl"]
    assert found["recruiter"].recipient_user_id == world["dl"]


@pytest.mark.asyncio
async def test_recruiter_role_added_later_restores_cancelled_recruiter_bonus(
    payroll_on,
) -> None:
    # Propozycje anulowane regułą z 22.10 wracają przy uzgodnieniu.
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    await _verified_by_dl(world, dl_roles=["delivery_lead"])
    assert (await _reconcile(world["contract"]))["cancelled"] == 1
    await _verified_by_dl(world, dl_roles=["delivery_lead", "recruiter"])
    assert (await _reconcile(world["contract"]))["restored"] == 1
    found = await _bonuses(world["contract"])
    assert found["recruiter"].status == "proposed"
    assert found["recruiter"].recipient_user_id == world["dl"]


@pytest.mark.asyncio
async def test_md_contract_is_converted_before_tiers(payroll_on) -> None:
    world = await _placement(
        started_days_ago=40, client_rate="1000", cost_rate="680", unit=RateUnit.daily
    )
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert found["recruiter"].amount == Decimal("1000.00")  # 40 zł/h → próg I
    assert found["dl"].amount == Decimal("672.00")
    assert found["dl"].rule_snapshot["rate_unit"] == "daily"


@pytest.mark.asyncio
async def test_ending_before_deadline_cancels_and_undo_restores(payroll_on) -> None:
    world = await _placement(started_days_ago=3)
    await _reconcile(world["contract"])
    start = business_today() - timedelta(days=3)

    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=start + timedelta(days=5),
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        result = await placement_bonuses.on_contract_ended(db, contract)
        await db.commit()
    assert result["cancelled"] == 2
    found = await _bonuses(world["contract"])
    assert {b.status for b in found.values()} == {"cancelled"}
    assert {b.cancel_reason for b in found.values()} == {"contract_ended"}
    assert all(b.cancelled_by is None for b in found.values())

    await _update_contract(
        world["contract"], status=ContractStatus.active, end_date=None
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        undone = await placement_bonuses.on_contract_end_undone(db, contract)
        await db.commit()
    assert undone["restored"] == 2
    assert {b.status for b in (await _bonuses(world["contract"])).values()} == {
        "proposed"
    }


@pytest.mark.asyncio
async def test_people_decisions_are_not_overridden_by_automat(payroll_on) -> None:
    world = await _placement(started_days_ago=3)
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    async with AsyncSessionLocal() as db:
        manual = await db.get(HrBonus, found["recruiter"].id)
        manual.status = "cancelled"
        manual.cancel_reason = "manual"
        edited = await db.get(HrBonus, found["dl"].id)
        edited.amount = Decimal("700")
        edited.rule_snapshot = {**edited.rule_snapshot, "edited_amount": True}
        await db.commit()

    await _update_contract(world["contract"], rate_client=Decimal("170"))
    await _reconcile(world["contract"])
    after = await _bonuses(world["contract"])
    assert after["recruiter"].status == "cancelled"  # ręczne anulowanie zostaje
    assert after["dl"].amount == Decimal("700.00")  # ręczna kwota zostaje


@pytest.mark.asyncio
async def test_extra_dl_bonus_only_from_settings(payroll_on) -> None:
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    assert "dl_extra" not in await _bonuses(world["contract"])

    async with AsyncSessionLocal() as db:
        second = await _person(db, "delivery_lead")
        await db.commit()
    await _set_setting(
        RULES_KEY,
        {"extra_dl": [{"dl_user_id": world["dl"], "recipient_user_id": second.id}]},
    )
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert found["dl_extra"].recipient_user_id == second.id
    assert found["dl_extra"].amount == found["dl"].amount


@pytest.mark.asyncio
async def test_return_after_break_and_drafts_are_not_placements(payroll_on) -> None:
    first = await _placement(started_days_ago=200, status=ContractStatus.ended)
    returned = await _placement(started_days_ago=10, returned_from=first["contract"])
    draft = await _placement(started_days_ago=10, status=ContractStatus.draft)
    assert (await _reconcile(returned["contract"]))["skipped"] == "return_after_break"
    assert (await _reconcile(draft["contract"]))["skipped"] == "not_started"
    assert not await _bonuses(returned["contract"])
    assert not await _bonuses(draft["contract"])


@pytest.mark.asyncio
async def test_hooks_do_nothing_when_module_is_off(payroll_on) -> None:
    world = await _placement(started_days_ago=10)
    await _set_setting(HR_MODULES_SETTING, {key: False for key in HR_MODULE_KEYS})
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        result = await placement_bonuses.on_contract_started(db, contract)
    assert result == {"status": "disabled"}
    assert not await _bonuses(world["contract"])


@pytest.mark.asyncio
async def test_refresh_endpoint_runs_the_automat_for_payroll(
    app_client, payroll_on
) -> None:
    world = await _placement(started_days_ago=40)
    async with AsyncSessionLocal() as db:
        finance = await _person(db, "recruiter")
        db.add(
            UserActionOverride(user_id=finance.id, action="payroll", access="manage")
        )
        await db.commit()
    token = create_access_token(subject=finance.id, role="recruiter")
    response = await app_client.post(
        "/api/hr/payroll/proposals/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["placement_created"] >= 2
    assert set(await _bonuses(world["contract"])) == {"dl", "recruiter"}


def _previous_quarter(today: date) -> tuple[str, int, int]:
    quarter = (today.month - 1) // 3 + 1
    year = today.year
    quarter -= 1
    if quarter == 0:
        quarter, year = 4, year - 1
    return f"Q{quarter} {year}", year, quarter


@pytest.mark.asyncio
async def test_league_prizes_become_proposals_once(payroll_on) -> None:
    today = business_today()
    period, year, quarter = _previous_quarter(today)
    kind = "quarterly_champions_recruiter"
    async with AsyncSessionLocal() as db:
        winners = [await _person(db) for _ in range(3)]
        await db.commit()
    inserted: list[int] = []
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(CompetitionPeriodClosure.id).where(
                CompetitionPeriodClosure.competition_type == kind,
                CompetitionPeriodClosure.period == period,
            )
        )
        if existing is not None:
            pytest.skip("okres Ligi zajęty przez inne dane testowe")
        closure = CompetitionPeriodClosure(
            competition_type=kind, period=period, status="frozen"
        )
        rows = [
            CompetitionWinner(
                competition_type=kind,
                period=period,
                user_id=user.id,
                rank=rank,
                points=100 - rank,
                prize_pln=prize,
            )
            for rank, (user, prize) in enumerate(zip(winners, (5000, 3000, 2000)), 1)
        ]
        db.add_all([closure, *rows])
        await db.commit()
        inserted = [closure.id, *(row.id for row in rows)]
    try:
        async with AsyncSessionLocal() as db:
            first = await league_bonuses.sync_league(db, today=today)
            await db.commit()
        async with AsyncSessionLocal() as db:
            second = await league_bonuses.sync_league(db, today=today)
            await db.commit()
            mine = list(
                await db.scalars(
                    select(HrBonus)
                    .where(HrBonus.recipient_user_id.in_([u.id for u in winners]))
                    .order_by(HrBonus.amount.desc())
                )
            )
        assert first["created"] >= 3 and second["created"] == 0
        assert [b.amount for b in mine] == [
            Decimal("5000"),
            Decimal("3000"),
            Decimal("2000"),
        ]
        quarter_end_month = quarter * 3
        expected = (
            (year + 1, 1) if quarter_end_month == 12 else (year, quarter_end_month + 1)
        )
        assert all((b.period_year, b.period_month) == expected for b in mine)
        assert all(b.status == "proposed" and b.category == "league" for b in mine)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CompetitionWinner).where(CompetitionWinner.id.in_(inserted[1:]))
            )
            await db.execute(
                delete(CompetitionPeriodClosure).where(
                    CompetitionPeriodClosure.id == inserted[0]
                )
            )
            await db.commit()


def test_league_period_parsing() -> None:
    assert league_bonuses.period_end("Q3 2026") == date(2026, 9, 30)
    assert league_bonuses.period_end("Q4 2026") == date(2026, 12, 31)
    assert league_bonuses.period_end("2026-02") == date(2026, 2, 28)
    assert league_bonuses.period_end("all_time") is None


def test_monthly_vouchers_are_outside_payroll_by_default() -> None:
    rules = parse_rules({})
    assert "monthly_placements" not in rules.league_types
    assert "quarterly_champions_dl" in rules.league_types


@pytest.mark.asyncio
async def test_approval_rechecks_contract_ended_since_last_run(
    app_client, payroll_on
) -> None:
    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    proposal = (await _bonuses(world["contract"]))["dl"]
    start = business_today() - timedelta(days=40)
    # Kontrakt skończył się przed terminem już po przebiegu automatu.
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=start + timedelta(days=7),
    )
    async with AsyncSessionLocal() as db:
        finance = await _person(db, "recruiter")
        db.add(
            UserActionOverride(user_id=finance.id, action="payroll", access="manage")
        )
        await db.commit()
    token = create_access_token(subject=finance.id, role="recruiter")
    response = await app_client.post(
        f"/api/hr/payroll/bonuses/{proposal.id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert "przed terminem" in response.json()["detail"]
    after = (await _bonuses(world["contract"]))["dl"]
    assert after.status == "cancelled" and after.cancel_reason == "contract_ended"


@pytest.mark.asyncio
async def test_approval_out_of_scope_is_404_without_reconciling(
    app_client, payroll_on
) -> None:
    """Obcy dostaje 404, a uzgodnienie kontraktu nie biegnie (A2, 19.10.2026)."""

    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    proposal = (await _bonuses(world["contract"]))["dl"]
    start = business_today() - timedelta(days=40)
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=start + timedelta(days=7),
    )
    async with AsyncSessionLocal() as db:
        outsider = await _person(db, "recruiter")
        await db.commit()
    token = create_access_token(subject=outsider.id, role="recruiter")
    response = await app_client.post(
        f"/api/hr/payroll/bonuses/{proposal.id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    after = (await _bonuses(world["contract"]))["dl"]
    # Przed poprawką uzgodnienie z commitem anulowało propozycję mimo 404.
    assert after.status == "proposed" and after.cancel_reason is None


@pytest.mark.asyncio
async def test_assigned_bonus_of_contract_ended_before_deadline_is_flagged(
    app_client, payroll_on
) -> None:
    """Decyzja Artura 19.10.2026: przyznanej premii automat nie anuluje, ale
    widok miesiąca Płac i zamknięcie ostrzegają (kontrakt zamknięty datą wsteczną)."""

    world = await _placement(started_days_ago=40)
    await _reconcile(world["contract"])
    async with AsyncSessionLocal() as db:
        finance = await _person(db, "recruiter")
        db.add(
            UserActionOverride(user_id=finance.id, action="payroll", access="manage")
        )
        await db.commit()
    proposal = (await _bonuses(world["contract"]))["dl"]
    async with AsyncSessionLocal() as db:
        bonus = await db.get(HrBonus, proposal.id)
        bonus.status = "assigned"
        bonus.assigned_by = finance.id
        bonus.assigned_at = local_now()
        await db.commit()
    start = business_today() - timedelta(days=40)
    await _update_contract(
        world["contract"],
        status=ContractStatus.ended,
        end_date=start + timedelta(days=7),
    )
    token = create_access_token(subject=finance.id, role="recruiter")
    response = await app_client.get(
        f"/api/hr/payroll/months/{proposal.period_year}/{proposal.period_month}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    flagged = {b["id"]: b["contract_ended_early"] for b in body["bonuses"]}
    assert flagged[proposal.id] is True
    if body["status"] == "open":
        codes = [w["code"] for w in body["warnings"]]
        assert "bonus_contract_ended_early" in codes
    # Automat dalej nie rusza przyznanej premii.
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["dl"].status == "assigned"
