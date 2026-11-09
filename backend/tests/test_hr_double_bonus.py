"""Automat premii: stała premia TCM, gwarancja DL i premia 200% (decyzje 05.11.2026).

* TCM jako weryfikujący dostaje stałą kwotę zamiast progu marży,
* zastępstwo osoby, którą zatrudnił ten sam DL i która odeszła przed rokiem:
  bez premii DL, rekruter dostaje swoją,
* zapisana decyzja 200% podwaja premie kontraktu podpisanego w miesiącu
  programu i przenosi je na miesiąc podpisu; koniec przed terminem jej nie zabiera.

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.hr import double_bonus
from app.services.hr.bonus_rules import SETTING_KEY as RULES_KEY
from app.services.hr.bonus_rules import load_rules
from tests.test_hr_bonus_automation import (  # noqa: F401  (fikstura)
    _bonuses,
    _person,
    _placement,
    _reconcile,
    _set_setting,
    _update_contract,
    payroll_on,
)


# Fikstura z ``test_hr_bonus_automation``: moduł Płac włączony, czyste premie.
pytestmark = pytest.mark.usefixtures("payroll_on")


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


@pytest_asyncio.fixture
async def results_clean():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == double_bonus.RESULTS_KEY)
        )
    await _set_setting(double_bonus.RESULTS_KEY, None)
    yield
    await _set_setting(double_bonus.RESULTS_KEY, previous)


def _decision(key: str, world: dict, *, recruiter: bool, dl: bool) -> dict:
    """Zapisana decyzja miesiąca w kształcie ``store_result``."""

    contract = str(world["contract"])
    return {
        key: {
            "recruiters": [world["recruiter"]] if recruiter else [],
            "dls": [world["dl"]] if dl else [],
            "recruiter_contracts": {contract: world["recruiter"]} if recruiter else {},
            "dl_contracts": {contract: world["dl"]} if dl else {},
        }
    }


async def _set_role(user_id: int, role: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.role = UserRole(role)
        user.roles = [role]
        await db.commit()


async def _set_job_dl(contract_id: int, dl_id: int) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        job = await db.get(Job, contract.job_id)
        job.delivery_lead_id = dl_id
        await db.commit()


@pytest.mark.asyncio
async def test_tcm_verifier_gets_fixed_amount_instead_of_tier() -> None:
    await _set_setting(
        RULES_KEY,
        {
            "fixed_role_amounts": [
                {"role": "talent_community_manager", "amount": "1000"}
            ]
        },
    )
    world = await _placement(started_days_ago=40, client_rate="160", cost_rate="105")
    await _set_role(world["recruiter"], "talent_community_manager")
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["recruiter"].amount == Decimal("1000.00")  # próg III dałby 2000
    assert found["recruiter"].rule_snapshot["fixed_amount"] == "1000.00"
    assert found["dl"].amount == Decimal("924.00")


async def _replacement(*, replaced_days: int, same_dl: bool) -> tuple[dict, dict]:
    today = business_today()
    replaced = await _placement(
        started_days_ago=replaced_days + 60,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=60),
    )
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        is_replacement=True,
        replaced_contract_id=replaced["contract"],
    )
    if same_dl:
        await _set_job_dl(world["contract"], replaced["dl"])
        world = {**world, "dl": replaced["dl"]}
    return replaced, world


@pytest.mark.asyncio
async def test_guarantee_drops_dl_bonus_of_the_same_dl_only() -> None:
    _replaced, world = await _replacement(replaced_days=200, same_dl=True)
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert "dl" not in found
    assert found["recruiter"].recipient_user_id == world["recruiter"]
    assert found["recruiter"].status == "proposed"

    _replaced, other = await _replacement(replaced_days=200, same_dl=False)
    await _reconcile(other["contract"])
    assert (await _bonuses(other["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_replaced_contract_over_a_year_keeps_dl_bonus() -> None:
    _replaced, world = await _replacement(replaced_days=400, same_dl=True)
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"


@pytest.mark.asyncio
async def test_stored_decision_doubles_bonus_in_signing_month(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=10)
    # Kontrakt bez umowy z Generatora: miesiąc podpisu = dzień założenia.
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    await _set_setting(
        double_bonus.RESULTS_KEY,
        _decision(key, world, recruiter=True, dl=True),
    )
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["dl"].amount == Decimal("1545.60")  # 2 × 10% × 46 × 168
    assert found["recruiter"].amount == Decimal("3000.00")  # 2 × próg II
    for bonus in found.values():
        assert (bonus.period_year, bonus.period_month) == signed
        assert bonus.rule_snapshot["double_bonus"] == {"month": key, "multiplier": "2"}

    # Konsultant odchodzi przed terminem: premia 200% zostaje (ryzyko firmy).
    await _update_contract(
        world["contract"], end_date=business_today() - timedelta(days=2)
    )
    await _reconcile(world["contract"])
    assert {b.status for b in (await _bonuses(world["contract"])).values()} == {
        "proposed"
    }


@pytest.mark.asyncio
async def test_only_qualified_role_is_doubled(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    await _set_setting(
        double_bonus.RESULTS_KEY, _decision(key, world, recruiter=True, dl=False)
    )
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["recruiter"].amount == Decimal("3000.00")
    assert found["dl"].amount == Decimal("772.80")
    assert "double_bonus" not in found["dl"].rule_snapshot


@pytest.mark.asyncio
async def test_month_outside_program_is_not_doubled(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": ["2020-01"]}})
    await _set_setting(
        double_bonus.RESULTS_KEY, _decision(key, world, recruiter=True, dl=True)
    )
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_decision_is_frozen_to_contracts_and_people(results_clean) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    world = await _placement(started_days_ago=40)
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    # Osoba z wynikiem, ale kontraktu nie ma w zapisanej decyzji: bez 200%.
    await _set_setting(
        double_bonus.RESULTS_KEY,
        {key: {"recruiters": [world["recruiter"]], "dls": [world["dl"]]}},
    )
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")
    # Kontrakt w decyzji, ale z innym rekruterem: 200% nie przechodzi na nowego.
    decision = _decision(key, world, recruiter=True, dl=False)
    decision[key]["recruiter_contracts"][str(world["contract"])] = world["dl"]
    await _set_setting(double_bonus.RESULTS_KEY, decision)
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["recruiter"].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_settle_month_stores_dl_above_threshold_and_doubles(
    results_clean,
) -> None:
    signed = _previous_month(business_today())
    key = f"{signed[0]}-{signed[1]:02d}"
    # Marża 160 − 105 = 55 zł/h > 50: DL zrobił cel; rekruter bez KPI — nie.
    world = await _placement(started_days_ago=10, client_rate="160", cost_rate="105")
    await _update_contract(
        world["contract"],
        created_at=datetime(*signed, 3, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": [key]}})
    async with AsyncSessionLocal() as db:
        rules = await load_rules(db)
        evaluation, ids = await double_bonus.settle_month(
            db, *signed, rules, today=business_today()
        )
        await db.commit()
    assert world["contract"] in ids
    assert evaluation["stored"]["dl_contracts"] == {str(world["contract"]): world["dl"]}
    assert world["recruiter"] not in evaluation["stored"]["recruiters"]
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    assert found["dl"].amount == Decimal("1848.00")  # 2 × 10% × 55 × 168
    assert found["recruiter"].amount == Decimal("2000.00")


async def _verified_earlier_by_departed(world: dict) -> None:
    """Tę osobę u tego klienta zweryfikował wcześniej rekruter, który odszedł."""

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        old_job = await db.get(Job, contract.job_id)
        departed = User(
            email=f"odszedl-{world['contract']}@example.com",
            name="Osoba Odeszła",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=False,
        )
        db.add(departed)
        await db.flush()
        earlier = Job(
            title="Wcześniejsza rekrutacja",
            client_id=old_job.client_id,
            status=old_job.status,
            recruiter_id=departed.id,
        )
        db.add(earlier)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=contract.candidate_id,
                job_id=earlier.id,
                stage=PipelineStage.verified,
                moved_by=departed.id,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_recruiter_closing_after_departed_recruiter_gets_no_bonus() -> None:
    """Domknięcie po osobie, która odeszła = bez premii rekrutera (06.11.2026)."""

    world = await _placement(started_days_ago=40)
    await _verified_earlier_by_departed(world)
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert "recruiter" not in found
    assert found["dl"].status == "proposed"


# ── Dzień podpisu z pliku zamiast kliknięcia (decyzja Artura 06.11.2026) ──────

_WAW = ZoneInfo("Europe/Warsaw")


async def _signed_agreement(
    contract_id: int,
    *,
    signed_at: datetime,
    signed_on: date | None,
    source: str | None,
) -> int:
    """Umowa z Generatora podpisana obustronnie, powiązana z kontraktem."""

    from app.models.b2b_generated_contract import B2BGeneratedContract

    marker = uuid.uuid4().int
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2098,
            seq=marker % 10_000_000,
            contract_number=f"{marker % 10_000_000}/2098",
            partner_name="Jan Przykładowy",
            client_name="Firma Przykładowa",
            language="pl",
            signature_status="signed_both",
            signature_source="manual_confirmation",
            contract_status="active",
            contract_id=contract_id,
            signed_at=signed_at,
            signed_on=signed_on,
            signed_on_source=source,
            created_at=datetime(2026, 10, 1, 9, 0, tzinfo=_WAW),
        )
        db.add(row)
        await db.commit()
        return row.id


async def _month_ids(year: int, month: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        return {c.id for c in await double_bonus.month_contracts(db, year, month)}


@pytest.mark.asyncio
async def test_signing_day_decides_the_month_not_the_click() -> None:
    # Przypadek z 06.11.2026: DL oznaczył podpis 30.10, konsultant podpisał 02.11 07:32.
    world = await _placement(started_days_ago=3)
    await _signed_agreement(
        world["contract"],
        signed_at=datetime(2026, 10, 30, 14, 0, tzinfo=_WAW),
        signed_on=date(2026, 11, 2),
        source="pdf",
    )
    async with AsyncSessionLocal() as db:
        dates = await double_bonus.signed_dates(db, [world["contract"]])
    assert dates[world["contract"]] == (date(2026, 11, 2), "pdf")
    assert world["contract"] in await _month_ids(2026, 11)
    assert world["contract"] not in await _month_ids(2026, 10)


@pytest.mark.asyncio
async def test_without_signing_day_the_click_day_counts() -> None:
    world = await _placement(started_days_ago=3)
    await _signed_agreement(
        world["contract"],
        signed_at=datetime(2026, 10, 30, 14, 0, tzinfo=_WAW),
        signed_on=None,
        source=None,
    )
    async with AsyncSessionLocal() as db:
        dates = await double_bonus.signed_dates(db, [world["contract"]])
    assert dates[world["contract"]] == (date(2026, 10, 30), "signed")
    assert world["contract"] in await _month_ids(2026, 10)


async def _payroll_headers() -> dict[str, str]:
    from app.core.security import create_access_token
    from app.models.section_permission import UserActionOverride
    from tests.test_hr_bonus_automation import _person

    async with AsyncSessionLocal() as db:
        person = await _person(db, "recruiter")
        db.add(UserActionOverride(user_id=person.id, action="payroll", access="manage"))
        await db.commit()
    return {
        "Authorization": f"Bearer {create_access_token(subject=person.id, role='recruiter')}"
    }


@pytest.mark.asyncio
async def test_payroll_corrects_signing_day_with_reason_and_trace(
    app_client, results_clean
) -> None:
    from app.models.activity import Activity
    from app.models.b2b_generated_contract import B2BGeneratedContract

    world = await _placement(started_days_ago=3)
    generated_id = await _signed_agreement(
        world["contract"],
        signed_at=datetime(2026, 10, 30, 14, 0, tzinfo=_WAW),
        signed_on=date(2026, 10, 30),
        source=None,
    )
    await _set_setting(RULES_KEY, {"double_bonus": {"months": ["2026-10", "2026-11"]}})
    await _set_setting(
        double_bonus.RESULTS_KEY,
        {"2026-10": {"recruiters": [], "dls": [], "recruiter_contracts": {}}},
    )
    headers = await _payroll_headers()

    response = await app_client.post(
        f"/api/hr/payroll/double-bonus/agreements/{generated_id}/signed-on",
        json={"signed_on": "2026-11-02", "reason": "podpis konsultanta 02.11 07:32"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_signed_on"] == "2026-10-30"
    assert body["signed_on"] == "2026-11-02"
    # Październik ma zapisany wynik — trzeba go przeliczyć; listopad jeszcze nie.
    assert body["settle_months"] == ["2026-10"]
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, generated_id)
        assert (row.signed_on, row.signed_on_source) == (date(2026, 11, 2), "manual")
        assert row.signed_on_reason == "podpis konsultanta 02.11 07:32"
        assert row.signed_on_set_by is not None
        trace = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "b2b_generated_contract",
                Activity.entity_id == generated_id,
                Activity.action == "signed_on_corrected",
            )
        )
        assert trace is not None
        assert trace.details["before"]["signed_on"] == "2026-10-30"
    assert world["contract"] in await _month_ids(2026, 11)

    month = await app_client.get(
        "/api/hr/payroll/double-bonus/2026/11", headers=headers
    )
    assert month.status_code == 200, month.text
    items = [
        item
        for row in month.json()["recruiters"]
        for item in row["contracts"]
        if item["contract_id"] == world["contract"]
    ]
    assert items and items[0]["agreement"]["signed_on_source"] == "manual"
    assert items[0]["agreement"]["generated_contract_id"] == generated_id


@pytest.mark.asyncio
async def test_signing_day_correction_needs_payroll_and_a_reason(app_client) -> None:
    from app.core.security import create_access_token
    from tests.test_hr_bonus_automation import _person

    world = await _placement(started_days_ago=3)
    generated_id = await _signed_agreement(
        world["contract"],
        signed_at=datetime(2026, 10, 30, 14, 0, tzinfo=_WAW),
        signed_on=date(2026, 10, 30),
        source=None,
    )
    async with AsyncSessionLocal() as db:
        other = await _person(db, "delivery_lead")
        await db.commit()
    path = f"/api/hr/payroll/double-bonus/agreements/{generated_id}/signed-on"
    denied = await app_client.post(
        path,
        json={"signed_on": "2026-11-02", "reason": "podpis 02.11"},
        headers={
            "Authorization": "Bearer "
            + create_access_token(subject=other.id, role="delivery_lead")
        },
    )
    assert denied.status_code == 403, denied.text

    headers = await _payroll_headers()
    no_reason = await app_client.post(
        path, json={"signed_on": "2026-11-02", "reason": " "}, headers=headers
    )
    assert no_reason.status_code == 422, no_reason.text
    future = await app_client.post(
        path,
        json={
            "signed_on": (business_today() + timedelta(days=1)).isoformat(),
            "reason": "podpis jutro",
        },
        headers=headers,
    )
    assert future.status_code == 422, future.text
    async with AsyncSessionLocal() as db:
        dates = await double_bonus.signed_dates(db, [world["contract"]])
    assert dates[world["contract"]] == (date(2026, 10, 30), "signed")


@pytest.mark.asyncio
async def test_dl_default_hours_change_main_and_extra_dl_bonus() -> None:
    """Od listopada każdy DL: 160 h × 10%, także dodatkowa premia (decyzja 09.11.2026)."""

    world = await _placement(started_days_ago=40)
    async with AsyncSessionLocal() as db:
        extra = await _person(db, "delivery_lead")
        extra_id = extra.id
        await db.commit()
    await _set_setting(
        RULES_KEY,
        {
            "dl_default_hours": 160,
            "extra_dl": [{"dl_user_id": world["dl"], "recipient_user_id": extra_id}],
        },
    )
    await _reconcile(world["contract"])

    found = await _bonuses(world["contract"])
    assert found["dl"].amount == Decimal("736.00")  # 10% × 46 zł/h × 160 h
    assert found["dl_extra"].amount == Decimal("736.00")
    assert found["dl"].rule_snapshot["dl_hours"] == 160
    assert found["recruiter"].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_bonus_signature_gives_agreement_outside_program_month() -> None:
    """„Popraw datę podpisu” przy premii: data sprzed programu też ma gdzie być poprawiona."""

    from app.api.hr_payroll import _bonus_signatures

    world = await _placement(started_days_ago=40)
    generated_id = await _signed_agreement(
        world["contract"],
        signed_at=datetime(2026, 10, 30, 14, 0, tzinfo=_WAW),
        signed_on=date(2026, 10, 30),
        source="manual",
    )
    await _reconcile(world["contract"])
    found = await _bonuses(world["contract"])
    async with AsyncSessionLocal() as db:
        signatures = await _bonus_signatures(db, list(found.values()))

    signature = signatures[world["contract"]]
    assert signature["signed_on"] == "2026-10-30"
    assert signature["signed_source"] == "manual"
    assert signature["agreement"]["generated_contract_id"] == generated_id
