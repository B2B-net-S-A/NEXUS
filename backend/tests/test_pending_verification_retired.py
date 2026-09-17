"""Bramka „Oczekuje" (pending verification, migracja 0056) — USUNIĘTA na stałe.

Decyzja Artura 17.09.2026 („żadna bramka nie blokuje przepływu"):
- ruch na 'verified' NIGDY nie ustawia `pending` — ani w widełkach, ani ponad
  `Job.salary_max` — i nie wysyła powiadomień `pending_verification`;
- stawka przy ruchu na 'verified' jest opcjonalna (bez niej → 200, nie 422);
- stary wiersz `pending` nie blokuje kolejnego ruchu;
- trasy kolejki akceptacji (lista / accept / reject) nie istnieją → 404;
- stare karty `pending` są jednorazowo ODBLOKOWANE, a te na „Zweryfikowany"
  ZALICZONE jak ręczna akceptacja — jeden serwis dla migracji 0325
  i `entrypoint.sh`.

Bramka członkostwa (P1-PIPE-01, `ensure_job_membership`): rekruter, który
przesuwa kandydata, musi należeć do zespołu rekrutacji — fixture ustawia go
jako `recruiter_id` oferty.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import pending_verification_promotion as promotion
from app.services.pending_verification_promotion import (
    PROMOTION_MARKER,
    run_pending_verification_promotion,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0325_pending_verification_retired.py"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pv_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, label: str = "pv") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pv-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Pv"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"PV {role.value} {label}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_candidate() -> int:
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Pv",
            lastname=f"Test{unique}",
            email=f"pv-cand-{unique}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    salary_max: int | None = 20000, recruiter_id: int | None = None
) -> int:
    from app.models.client import Client

    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PVClient-{unique}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"PV Job {unique}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            salary_min=10000,
            salary_max=salary_max,
            # Właściciel oferty = członek zespołu (bramka członkostwa pipeline'u).
            recruiter_id=recruiter_id,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_pending_stage(stage: PipelineStage) -> tuple[int, int, int, int]:
    """Wiersz `pending` sprzed usunięcia bramki — `/move` już takiego nie tworzy."""
    recruiter_id, _email, _pw = await _seed_user(UserRole.recruiter, "promo")
    candidate_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=10000, recruiter_id=recruiter_id)
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=stage,
            moved_by=recruiter_id,
            verification_status=VerificationStatus.pending,
            expected_rate_value=30000,
            budget_max_at_move=10000,
        )
        db.add(row)
        await db.commit()
        return row.id, recruiter_id, candidate_id, job_id


async def _force_pending(stage_id: int) -> None:
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        assert stage is not None
        stage.verification_status = VerificationStatus.pending
        stage.approved_by = None
        stage.approved_at = None
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(*, candidate_ids: list[int], job_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        if candidate_ids or job_ids:
            await db.execute(
                delete(CandidateStage).where(
                    CandidateStage.candidate_id.in_(candidate_ids or [-1])
                )
            )
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if job_ids:
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _move(client: AsyncClient, headers: dict[str, str], payload: dict) -> dict:
    resp = await client.post("/api/pipeline/move", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Ruch na „Zweryfikowany" ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_to_verified_within_budget_active(pv_client: AsyncClient):
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "within")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        body = await _move(
            pv_client,
            headers,
            {
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "15000",
                "expected_rate_unit": "monthly",
            },
        )
        assert body["verification_status"] == "active"
        assert body["budget_max_at_move"] == 20000
        assert body["expected_rate_value"] in ("15000.00", "15000")
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_move_to_verified_above_budget_stays_active(pv_client: AsyncClient):
    """Stawka ponad budżet nie parkuje karty i nie pinguje adminów."""
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "above")
    headers = await _login(pv_client, email, pw)
    await _seed_user(UserRole.admin, "approver-admin")
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        body = await _move(
            pv_client,
            headers,
            {
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "25000",
                "expected_rate_unit": "monthly",
            },
        )
        assert body["verification_status"] == "active"
        # Snapshot budżetu zostaje dla audytu i doku karty; „ponad budżet"
        # liczy front z budżetu PLN/h rekrutacji, nie serwer.
        assert body["budget_max_at_move"] == 20000
        assert "budget_exceeded" not in body

        async with AsyncSessionLocal() as db:
            notif = await db.scalar(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.pending_verification,
                    Notification.related_entity_id == body["id"],
                )
            )
            assert notif is None
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_move_to_verified_without_rate_succeeds(pv_client: AsyncClient):
    """Stawka jest opcjonalna — brak stawki to 200, nie 422."""
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "missing")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(recruiter_id=recr_uid)
    try:
        body = await _move(
            pv_client,
            headers,
            {"candidate_id": cand_id, "job_id": job_id, "stage": "verified"},
        )
        assert body["verification_status"] == "active"
        assert body["expected_rate_value"] is None
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_legacy_pending_row_does_not_block_next_move(pv_client: AsyncClient):
    """Stary wiersz `pending` nie zatrzymuje kolejnego ruchu (dawne 409)."""
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "legacy")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        ver = await _move(
            pv_client,
            headers,
            {
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "30000",
                "expected_rate_unit": "monthly",
            },
        )
        await _force_pending(ver["id"])
        nxt = await _move(
            pv_client,
            headers,
            {"candidate_id": cand_id, "job_id": job_id, "stage": "cv_sent"},
        )
        assert nxt["stage"] == "cv_sent"
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_verified_move_credits_first_verifier_immediately(
    pv_client: AsyncClient,
):
    """Bez bramki kredyt KPI pierwszego weryfikatora trafia od razu do mover-a."""
    recr_uid, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "credit")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        await _move(
            pv_client,
            recr_headers,
            {
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "40000",
                "expected_rate_unit": "monthly",
            },
        )
        async with AsyncSessionLocal() as db:
            process = await db.scalar(
                select(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == cand_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .order_by(RecruitmentProcess.id.desc())
                .limit(1)
            )
            assert process is not None
            assert process.credit_user_id == recr_uid
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


# ── Kolejka akceptacji nie istnieje ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_acceptance_queue_routes_are_gone(pv_client: AsyncClient):
    _, admin_email, admin_pw = await _seed_user(UserRole.admin, "gone")
    headers = await _login(pv_client, admin_email, admin_pw)
    stage_id, _recruiter_id, cand_id, job_id = await _seed_pending_stage(
        PipelineStage.verified
    )
    try:
        listing = await pv_client.get(
            "/api/pipeline/pending-verifications", headers=headers
        )
        assert listing.status_code == 404, listing.text
        for suffix in ("accept-verification", "reject-verification"):
            resp = await pv_client.post(
                f"/api/pipeline/{stage_id}/{suffix}",
                headers=headers,
                json={"note": "x"},
            )
            assert resp.status_code in (404, 405), (suffix, resp.status_code)
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


def test_gate_flag_and_queue_code_are_removed():
    from app.api import pipeline
    from app.services import recruitment_process_commands as commands

    assert not hasattr(settings, "PENDING_VERIFICATION_ENABLED")
    for name in (
        "list_pending_verifications",
        "accept_verification",
        "reject_verification",
        "_notify_pending_verification",
    ):
        assert not hasattr(pipeline, name), name
    for name in (
        "accept_pending_verification",
        "reject_pending_verification",
        "_lock_current_pending_verification",
    ):
        assert not hasattr(commands, name), name


# ── Jednorazowe odblokowanie + zaliczenie starych kart ──────────────────────


@pytest.mark.asyncio
async def test_promotion_credits_a_verified_row_like_a_manual_acceptance() -> None:
    stage_id, recruiter_id, candidate_id, job_id = await _seed_pending_stage(
        PipelineStage.verified
    )
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_pending_verification_promotion(
                db, only_stage_ids={stage_id}
            )
            await db.commit()
        assert summary is not None
        assert summary["unblocked"] == 1 and summary["credited"] == 1
        assert summary["failed"] == 0

        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            process = await db.scalar(
                select(RecruitmentProcess)
                .where(
                    RecruitmentProcess.candidate_id == candidate_id,
                    RecruitmentProcess.job_id == job_id,
                )
                .order_by(RecruitmentProcess.id.desc())
                .limit(1)
            )
        assert stage is not None
        assert stage.verification_status == VerificationStatus.active
        assert stage.approved_at is not None
        # Nikt nie podjął tej decyzji — podjęła ją zmiana polityki.
        assert stage.approved_by is None
        assert process is not None and process.credit_user_id == recruiter_id

        # Drugi przebieg nie dotyka już odblokowanej karty.
        async with AsyncSessionLocal() as db:
            again = await run_pending_verification_promotion(
                db, only_stage_ids={stage_id}
            )
            await db.commit()
        assert again is not None and again["found"] == 0
    finally:
        await _cleanup(candidate_ids=[candidate_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_promotion_unblocks_a_non_verified_row_without_credit() -> None:
    """`pending` na innym etapie też jest odblokowany — ale to nie weryfikacja."""
    stage_id, _recruiter_id, candidate_id, job_id = await _seed_pending_stage(
        PipelineStage.cv_sent
    )
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_pending_verification_promotion(
                db, only_stage_ids={stage_id}
            )
            await db.commit()
        assert summary is not None
        assert summary["unblocked"] == 1 and summary["credited"] == 0

        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            credited = await db.scalar(
                select(RecruitmentProcess.credit_user_id).where(
                    RecruitmentProcess.candidate_id == candidate_id,
                    RecruitmentProcess.job_id == job_id,
                )
            )
        assert stage is not None
        assert stage.verification_status == VerificationStatus.active
        assert credited is None
    finally:
        await _cleanup(candidate_ids=[candidate_id], job_ids=[job_id])


def test_promotion_covers_every_pending_row_not_only_verified():
    source = inspect.getsource(promotion.run_pending_verification_promotion)
    assert "CandidateStage.verification_status == VerificationStatus.pending" in source
    assert "PipelineStage.verified" not in source
    # Blokady w kolejności `/move` (kandydat → etap).
    assert source.index("select(Candidate.id)") < source.index("select(CandidateStage)")


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0325", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_auto_match_and_reuses_the_service():
    module = _migration_module()
    assert module.revision == "0325_pending_verification_retired"
    assert module.down_revision == "0324_candidate_auto_match"
    upgrade = inspect.getsource(module.upgrade)
    assert "run_pending_verification_promotion" in upgrade
    # ORM czyta kolumny modeli HEAD — na bazie przed HEAD serwis padałby, więc
    # migracja pomija go i zostawia pracę entrypointowi.
    assert upgrade.index("_missing_model_columns(bind)") < upgrade.index(
        "run_pending_verification_promotion(session)"
    )
    # Brak własnego SQL-a — jeden kod dla alembica i entrypointu.
    assert "UPDATE candidate_stages" not in MIGRATION.read_text()


def test_entrypoint_calls_the_same_service_and_has_no_sql_shortcut():
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert "run_pending_verification_promotion(db)" in entrypoint
    collapsed = re.sub(r"\s+", " ", entrypoint)
    # Dawny skrót SQL `pending → active` biegł przed promocją i zabierał jej
    # wiersze (bez zaliczenia weryfikacji) — nie może wrócić.
    assert "SET verification_status = 'active', approved_at = now()" not in collapsed
    assert PROMOTION_MARKER == "pending_verification_promotion_2026_09_17"
