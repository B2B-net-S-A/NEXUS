"""„Prowadzi” — ręczne przypisanie osoby prowadzącej kandydata (0519).

Decyzje Artura z 25.10.2026: przypisuje admin albo Head of Recruitment,
prowadzić może aktywna osoba z rolą rekrutera (także DL z tą rolą),
a przypisana osoba zastępuje pierwszego weryfikującego w karcie, „Moich
ludziach”, Lidze i celach oraz premii rekrutera.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.candidate_job_owner import CandidateJobOwner, CandidateJobOwnerEvent
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import my_people, pair_owner
from app.services.hr import placement_bonuses
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0519_candidate_job_owners.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration():
    spec = importlib.util.spec_from_file_location("m0519", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── bez bazy ────────────────────────────────────────────────────────────────


def test_migration_chains_after_autofill_quality_report() -> None:
    module = _migration()
    assert module.revision == "0519_candidate_job_owners"
    assert module.down_revision == "0518_autofill_quality_report"


def test_ddl_is_idempotent_and_mirrored_in_entrypoint() -> None:
    from app.services.pair_owner_schema import TABLE_DDL

    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "pair_owner_schema" in entrypoint
    assert "*_PAIR_OWNER_DDL," in entrypoint
    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in _collapse(statement), statement


def test_deep_health_probes_the_owner_table() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    block = main[main.index("    core_checks = [") :]
    block = block[: block.index("\n    ]")]
    assert '("candidate_job_owners", CandidateJobOwner)' in block


def test_league_and_goals_credit_the_assigned_person() -> None:
    cte = _collapse(VERIFIER_ANCHORED_CTE)
    assert "COALESCE(o.owner_user_id, d.credit_user) AS credit_user" in cte
    assert "LEFT JOIN candidate_job_owners o" in cte


def test_my_people_scope_includes_assigned_pairs() -> None:
    single = _collapse(my_people._owned_pairs_cte(single_user=True))
    assert "FROM candidate_job_owners WHERE owner_user_id = :uid" in single
    assert "COALESCE(o.owner_user_id, v.moved_by, s.moved_by) = :uid" in single


def _person(*roles: str, active: bool = True) -> User:
    return User(
        email="x@example.com",
        role=UserRole(roles[0]),
        roles=list(roles),
        is_active=active,
    )


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (("admin",), True),
        (("head_of_recruitment",), True),
        (("delivery_lead", "head_of_recruitment"), True),
        (("delivery_lead",), False),
        (("recruiter",), False),
        (("finance",), False),
    ],
)
def test_only_admin_and_head_of_recruitment_assign(roles, expected) -> None:
    assert pair_owner.may_assign(_person(*roles)) is expected


@pytest.mark.parametrize(
    ("roles", "active", "expected"),
    [
        (("recruiter",), True, True),
        (("delivery_lead", "recruiter"), True, True),
        (("delivery_lead",), True, False),
        (("recruiter",), False, False),
        (("finance",), True, False),
    ],
)
def test_only_active_people_with_recruiter_role_can_lead(roles, active, expected):
    assert pair_owner.can_own(_person(*roles, active=active)) is expected


# ── z bazą (CI) ─────────────────────────────────────────────────────────────


async def _user(db, *roles: str, active: bool = True) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"owner-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Owner"),
        name=f"Osoba Przykładowa {tag}",
        role=UserRole(roles[0]),
        roles=list(roles),
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _world() -> dict:
    """Rekrutacja z DL-em, który rekrutuje; kandydata dodał i zweryfikował
    rekruter, potem CV wysłał DL."""

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        dl = await _user(db, "delivery_lead", "recruiter")
        dl_only = await _user(db, "delivery_lead")
        hor = await _user(db, "head_of_recruitment")
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
            delivery_lead_id=dl.id,
        )
        db.add(job)
        await db.flush()
        for stage, mover in (
            (PipelineStage.new, recruiter),
            (PipelineStage.verified, recruiter),
            (PipelineStage.cv_sent, dl),
        ):
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=stage,
                    moved_by=mover.id,
                )
            )
        await db.commit()
        return {
            "candidate": candidate.id,
            "client": client.id,
            "job": job.id,
            "recruiter": recruiter.id,
            "dl": dl.id,
            "dl_only": dl_only.id,
            "hor": hor.id,
        }


async def _assign(world: dict, owner: int, *, actor: str = "hor") -> None:
    async with AsyncSessionLocal() as db:
        actor_user = await db.get(User, world[actor])
        previous = await pair_owner.implicit_owner_id(
            db, candidate_id=world["candidate"], job_id=world["job"]
        )
        await pair_owner.assign_owner(
            db,
            candidate_id=world["candidate"],
            job_id=world["job"],
            owner_user_id=owner,
            reason="Prowadzi DL od rozmów u klienta",
            actor=actor_user,
            previous_owner_id=previous,
        )
        await db.commit()


@pytest.mark.asyncio
async def test_assignment_keeps_history_and_previous_owner() -> None:
    world = await _world()
    await _assign(world, world["dl"])
    async with AsyncSessionLocal() as db:
        owners = await pair_owner.owners_for_job(db, world["job"])
        assigned = owners[world["candidate"]]
        assert assigned.owner_user_id == world["dl"]
        assert assigned.previous_owner_name is not None  # weryfikujący rekruter
    await _assign(world, world["recruiter"])
    async with AsyncSessionLocal() as db:
        row = await db.get(CandidateJobOwner, (world["candidate"], world["job"]))
        assert row.owner_user_id == world["recruiter"]
        assert row.previous_owner_id == world["dl"]
        events = (
            await db.scalars(
                select(CandidateJobOwnerEvent).where(
                    CandidateJobOwnerEvent.job_id == world["job"]
                )
            )
        ).all()
        assert [e.owner_user_id for e in events] == [world["dl"], world["recruiter"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["recruiter", "dl"])
async def test_only_admin_or_head_of_recruitment_may_assign(actor) -> None:
    world = await _world()
    with pytest.raises(HTTPException) as denied:
        await _assign(world, world["dl"], actor=actor)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_dl_without_recruiter_role_cannot_lead() -> None:
    world = await _world()
    with pytest.raises(HTTPException) as refused:
        await _assign(world, world["dl_only"])
    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_assigned_person_takes_my_people_from_the_verifier() -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        assert world["candidate"] in await my_people.owned_candidate_ids(
            db, world["recruiter"]
        )
    await _assign(world, world["dl"])
    async with AsyncSessionLocal() as db:
        assert world["candidate"] in await my_people.owned_candidate_ids(
            db, world["dl"]
        )
        assert world["candidate"] not in await my_people.owned_candidate_ids(
            db, world["recruiter"]
        )


@pytest.mark.asyncio
async def test_assigned_dl_with_recruiter_role_gets_both_bonuses() -> None:
    world = await _world()
    await _assign(world, world["dl"])
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=world["candidate"],
            client_id=world["client"],
            job_id=world["job"],
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=40),
            rate_client=Decimal("150"),
            rate_candidate=Decimal("104"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
        )
        context = await placement_bonuses.load_context(db, [contract])
        assert context.people(contract) == (world["dl"], world["dl"], "job")


@pytest.mark.asyncio
async def test_correction_removing_the_pair_forgets_the_assignment() -> None:
    world = await _world()
    await _assign(world, world["dl"])
    async with AsyncSessionLocal() as db:
        await pair_owner.forget_pair(
            db, candidate_id=world["candidate"], job_id=world["job"]
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (
            await pair_owner.owner_ids(db, [(world["candidate"], world["job"])]) == {}
        )


@pytest.mark.asyncio
async def test_route_assigns_for_head_of_recruitment_and_refuses_recruiter(
    app_client: AsyncClient,
) -> None:
    world = await _world()
    url = f"/api/pipeline/jobs/{world['job']}/candidates/{world['candidate']}/owner"
    body = {"owner_user_id": world["dl"], "reason": "Prowadzi Marlena od początku"}
    recruiter = {
        "Authorization": f"Bearer {create_access_token(world['recruiter'], 'recruiter')}"
    }
    assert (await app_client.put(url, json=body, headers=recruiter)).status_code == 403
    hor = {
        "Authorization": "Bearer "
        + create_access_token(world["hor"], "head_of_recruitment")
    }
    response = await app_client.put(url, json=body, headers=hor)
    assert response.status_code == 200, response.text
    assert response.json()["owner_user_id"] == world["dl"]
