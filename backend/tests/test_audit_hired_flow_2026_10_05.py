"""Audyt 05.10.2026 — zatrudnienie z podpisu i ręczne „Zatrudniony”.

1. Potwierdzenie podpisu B2B przesuwa kartę na „Zatrudniony” i robi to samo
   co ``/pipeline/move``: dzwonki z reguł etapu, ``UserActivity`` i podpowiedź
   „komplet obsady”.
2. Status zamówienia zatrudnionego liczy się po osobie i KLIENCIE rekrutacji —
   żywy kontrakt tej osoby z innej rekrutacji u tego klienta też się liczy.
3. Ręczne „Zatrudniony” z umową B2B zakłada szkic w zł/h ze stawką z tej
   rekrutacji; podpis w Generatorze nadal traktuje go jako zaślepkę.
4. Karta w kolumnie „Zatrudniony” na etapie Onboarding też ma status zamówienia.
5. Finanse: „Zatrudnieni bez zamówienia” tylko pary nadal zatrudnione i nie
   wykluczone z placementów.

In-process ``app_client``; baza wspólna i nieczyszczona — asercje wyłącznie na
własnych wierszach (nazwy z UUID).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.placement_exclusion import PlacementExclusion
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.models.user_activity import UserActionType, UserActivity
from tests.test_b2b_signature_automation import (
    _confirm,
    _current_admin_id,
    _seed_bound_scenario,
)


# ── Dane ─────────────────────────────────────────────────────────────────────


async def _client_job_candidate(*, jobs: int = 1) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"HiredFlow-{tag}")
        candidate = Candidate(
            name="Iga",
            lastname=f"Hired-{tag}",
            email=f"hired-flow-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([client, candidate])
        await db.flush()
        job_rows = [
            Job(
                title=f"HiredFlow-{tag}-{i}",
                status=JobStatus.published,
                client_id=client.id,
            )
            for i in range(jobs)
        ]
        db.add_all(job_rows)
        await db.commit()
        return {
            "client_id": client.id,
            "candidate_id": candidate.id,
            "job_ids": [job.id for job in job_rows],
        }


async def _contract(
    *,
    candidate_id: int,
    client_id: int,
    job_id: int | None,
    status: ContractStatus = ContractStatus.active,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            job_id=job_id,
            contract_type=ContractType.b2b,
            status=status,
            start_date=date(2031, 6, 1),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _complete_order(contract_id: int, client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Zamówienie uzupełnione",
            status=ClientOrderStatus.active,
            start_date=date(2031, 6, 1),
            rate_client=Decimal("180"),
        )
        db.add(order)
        await db.commit()
        return order.id


async def _stage(
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    *,
    ago: timedelta,
    **extra,
) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=stage,
            moved_at=datetime.now(timezone.utc) - ago,
            **extra,
        )
        db.add(row)
        await db.commit()
        return row.id


# ── 1. Podpis B2B = te same efekty co /move ─────────────────────────────────


@pytest.mark.asyncio
async def test_signature_hire_runs_the_same_effects_as_a_manual_move(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    from app.services import stage_notification_emitter

    calls: list[dict] = []

    async def _spy(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(stage_notification_emitter, "notify_stage_change", _spy)

    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(
        created_by=admin_id, entry_stage=PipelineStage.cv_sent
    )

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        hired = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == scenario["candidate_id"],
                CandidateStage.job_id == scenario["job_id"],
                CandidateStage.stage == PipelineStage.hired,
            )
        )
        assert hired is not None
        # Ślad ruchu jak w `_record_stage_change` — ranking osób go liczy.
        trace = await db.scalar(
            select(UserActivity).where(
                UserActivity.entity_type == "pipeline",
                UserActivity.entity_id == hired.id,
                UserActivity.action_type == UserActionType.stage_changed,
            )
        )
        assert trace is not None
        assert trace.user_id == admin_id
        # Podpowiedź „komplet obsady” (headcount = 1).
        hint = await db.scalar(
            select(Notification.id).where(
                Notification.related_entity_type == "job",
                Notification.related_entity_id == scenario["job_id"],
                Notification.notification_type == NotificationType.suggest_next_step,
            )
        )
        assert hint is not None
    # Reguły etapu (dzwonek dla rekrutera) dostały nowy wiersz „Zatrudniony”.
    assert [c["new_stage"].id for c in calls] == [hired.id]
    assert calls[0]["job"].id == scenario["job_id"]

    # Replay niczego nie powtarza.
    again = await _confirm(app_client, app_auth_headers, scenario["generated_id"])
    assert again.json()["outcome"] == "already_processed"
    assert len(calls) == 1


# ── 2. Status zamówienia po osobie i kliencie ───────────────────────────────


@pytest.mark.asyncio
async def test_order_status_counts_the_persons_live_contract_from_another_job():
    """Podpis podpina żywy kontrakt tej osoby z innej rekrutacji bez zmiany
    ``job_id`` — jego uzupełnione zamówienie jest zamówieniem nowej pary."""
    from app.services.hired_order_status import order_status_for_pairs

    linked = await _client_job_candidate(jobs=2)
    old_job, new_job = linked["job_ids"]
    contract_id = await _contract(
        candidate_id=linked["candidate_id"],
        client_id=linked["client_id"],
        job_id=old_job,
    )
    await _complete_order(contract_id, linked["client_id"])

    # Zakończony kontrakt z poprzedniej współpracy u klienta się nie liczy.
    ended = await _client_job_candidate(jobs=2)
    e_old, e_new = ended["job_ids"]
    e_contract = await _contract(
        candidate_id=ended["candidate_id"],
        client_id=ended["client_id"],
        job_id=e_old,
        status=ContractStatus.ended,
    )
    await _complete_order(e_contract, ended["client_id"])

    # Kontrakt bez rekrutacji u klienta się liczy.
    no_job = await _client_job_candidate()
    nj_contract = await _contract(
        candidate_id=no_job["candidate_id"],
        client_id=no_job["client_id"],
        job_id=None,
    )
    await _complete_order(nj_contract, no_job["client_id"])

    # Kontrakt u INNEGO klienta się nie liczy.
    other = await _client_job_candidate()
    elsewhere = await _client_job_candidate()
    o_contract = await _contract(
        candidate_id=other["candidate_id"],
        client_id=elsewhere["client_id"],
        job_id=None,
    )
    await _complete_order(o_contract, elsewhere["client_id"])

    async with AsyncSessionLocal() as db:
        result = await order_status_for_pairs(
            db,
            [
                (linked["candidate_id"], new_job),
                (linked["candidate_id"], old_job),
                (ended["candidate_id"], e_new),
                (ended["candidate_id"], e_old),
                (no_job["candidate_id"], no_job["job_ids"][0]),
                (other["candidate_id"], other["job_ids"][0]),
            ],
        )

    assert result == {
        (linked["candidate_id"], new_job): "complete",
        (linked["candidate_id"], old_job): "complete",
        (ended["candidate_id"], e_new): "missing",
        (ended["candidate_id"], e_old): "complete",
        (no_job["candidate_id"], no_job["job_ids"][0]): "complete",
        (other["candidate_id"], other["job_ids"][0]): "missing",
    }


@pytest.mark.asyncio
async def test_case_of_a_contract_without_recruitment_closes_with_its_order():
    from app.core.security import hash_password
    from app.services.hired_order_status import resolve_hired_order_cases_safely

    world = await _client_job_candidate()
    contract_id = await _contract(
        candidate_id=world["candidate_id"],
        client_id=world["client_id"],
        job_id=None,
    )
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        finance = User(
            email=f"hired-flow-fin-{tag}@example.com",
            password_hash=hash_password(f"F1n_{tag}!Pass"),
            name=f"Hired Flow Finance {tag}",
            role=UserRole.finance,
            roles=[UserRole.finance.value],
            is_active=True,
        )
        db.add(finance)
        await db.flush()
        notice = Notification(
            user_id=finance.id,
            title="Nowy kontraktor bez zamówienia",
            message="x",
            notification_type=NotificationType.hired_order_missing,
            related_entity_type="contract",
            related_entity_id=contract_id,
        )
        db.add(notice)
        await db.commit()
        notice_id = notice.id
    await _complete_order(contract_id, world["client_id"])

    async with AsyncSessionLocal() as db:
        closed = await resolve_hired_order_cases_safely(db, contract_ids=[contract_id])
        await db.commit()
    assert closed == 1
    async with AsyncSessionLocal() as db:
        assert (await db.get(Notification, notice_id)).is_read is True


# ── 3. Ręczne „Zatrudniony” z B2B: zł/h i stawka z tej rekrutacji ───────────


@pytest.mark.asyncio
async def test_manual_b2b_hire_drafts_an_hourly_contract_with_this_jobs_rate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    world = await _client_job_candidate()
    job_id = world["job_ids"][0]
    await _stage(
        world["candidate_id"],
        job_id,
        PipelineStage.verified,
        ago=timedelta(days=3),
        expected_rate_value=Decimal("140"),
        expected_rate_unit="hourly",
        expected_rate_currency="PLN",
    )
    await _stage(
        world["candidate_id"], job_id, PipelineStage.cv_sent, ago=timedelta(days=1)
    )

    resp = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": job_id,
            "stage": "hired",
            "hired_signed_via": "b2b_offline",
        },
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract).where(
                Contract.candidate_id == world["candidate_id"],
                Contract.client_id == world["client_id"],
            )
        )
        assert contract is not None
        assert contract.contract_type == ContractType.b2b
        assert contract.rate_unit == RateUnit.hourly
        assert contract.rate_candidate == Decimal("140")
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract.id,
                Activity.action == "auto_drafted_from_pipeline",
            )
        )
        assert audit is not None
        assert Decimal(audit.details["seeded_rate_candidate"]) == Decimal("140")


@pytest.mark.asyncio
async def test_signature_replaces_the_rate_seeded_by_a_manual_hire(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Szkic z ręcznego „Zatrudniony” ze stawką z rekrutacji to nadal zaślepka:
    podpisany dokument (150,50 zł/h) ją zastępuje, bez 409 o różnicy stawek."""
    admin_id = await _current_admin_id(app_client)
    scenario = await _seed_bound_scenario(
        created_by=admin_id, entry_stage=PipelineStage.cv_sent
    )
    await _stage(
        scenario["candidate_id"],
        scenario["job_id"],
        PipelineStage.verified,
        ago=timedelta(days=3),
        expected_rate_value=Decimal("140"),
        expected_rate_unit="hourly",
        expected_rate_currency="PLN",
    )
    moved = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={
            "candidate_id": scenario["candidate_id"],
            "job_id": scenario["job_id"],
            "stage": "hired",
            "hired_signed_via": "b2b_offline",
        },
    )
    assert moved.status_code == 200, moved.text

    response = await _confirm(app_client, app_auth_headers, scenario["generated_id"])

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "linked_existing"
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, response.json()["contract_id"])
        assert contract is not None
        assert contract.rate_candidate == Decimal("150.500")
        assert contract.rate_unit == RateUnit.hourly


# ── 4. Karta „Zatrudniony” na etapie Onboarding ─────────────────────────────


@pytest.mark.asyncio
async def test_onboarding_card_carries_the_order_status(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    world = await _client_job_candidate()
    job_id = world["job_ids"][0]
    await _stage(
        world["candidate_id"], job_id, PipelineStage.onboarding, ago=timedelta(hours=1)
    )
    contract_id = await _contract(
        candidate_id=world["candidate_id"],
        client_id=world["client_id"],
        job_id=job_id,
    )
    await _complete_order(contract_id, world["client_id"])

    resp = await app_client.get(
        f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = [i for c in body["columns"] for i in c["items"]]
    if body.get("off_template"):
        items += body["off_template"]["items"]
    [card] = [i for i in items if i["candidate_id"] == world["candidate_id"]]
    assert card["order_status"] == "complete"


# ── 5. Finanse: tylko pary nadal zatrudnione ────────────────────────────────


@pytest.mark.asyncio
async def test_finance_list_skips_pairs_no_longer_hired_and_excluded_placements():
    from app.services.board_flow import _HIRED_SQL

    still = await _client_job_candidate()
    onboarding = await _client_job_candidate()
    left = await _client_job_candidate()
    excluded = await _client_job_candidate()
    for world in (still, onboarding, left, excluded):
        await _stage(
            world["candidate_id"],
            world["job_ids"][0],
            PipelineStage.hired,
            ago=timedelta(days=5),
        )
    await _stage(
        onboarding["candidate_id"],
        onboarding["job_ids"][0],
        PipelineStage.onboarding,
        ago=timedelta(days=2),
    )
    await _stage(
        left["candidate_id"],
        left["job_ids"][0],
        PipelineStage.withdrawn,
        ago=timedelta(days=1),
    )
    async with AsyncSessionLocal() as db:
        db.add(
            PlacementExclusion(
                candidate_id=excluded["candidate_id"],
                job_id=excluded["job_ids"][0],
                reason="test",
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                _HIRED_SQL,
                {"since": datetime.now(timezone.utc) - timedelta(days=30)},
            )
        ).all()
    listed = {(r.candidate_id, r.job_id) for r in rows}

    assert (still["candidate_id"], still["job_ids"][0]) in listed
    assert (onboarding["candidate_id"], onboarding["job_ids"][0]) in listed
    assert (left["candidate_id"], left["job_ids"][0]) not in listed
    assert (excluded["candidate_id"], excluded["job_ids"][0]) not in listed
