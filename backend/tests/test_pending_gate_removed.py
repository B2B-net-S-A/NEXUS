"""Bramka „Oczekuje" (migracja 0056) — USUNIĘTA (decyzja Artura 17.09.2026).

Kontrakt po usunięciu:
- ruch na 'verified' ze stawką ponad `Job.salary_max` → status `active`,
  `budget_exceeded=True` w odpowiedzi, ZERO powiadomień `pending_verification`
- stawka w widełkach → `budget_exceeded=False`
- stawka jest OPCJONALNA — jej brak to 200, nie 422
- wiersz `pending` zapisany przed 17.09.2026 nie blokuje kolejnego ruchu
  i jest raportowany jako `active`
- tras kolejki akceptacji NIE MA w aplikacji (sprawdzane po `app.routes`,
  nie po HTTP 404 — 404 dostałaby też literówka w ścieżce)

Kod bramki (flaga `PENDING_VERIFICATION_ENABLED`, trasy akceptacji/odrzucenia,
lista oczekujących) został skasowany 18.09.2026. W bazie zostaje wartość
`pending` w enumie `verificationstatus` — dla wierszy historycznych, bo
`ALTER TYPE … DROP VALUE` w Postgresie nie istnieje.

Bramka członkostwa (P1-PIPE-01, `ensure_job_membership`): rekruter, który
przesuwa kandydata, musi należeć do zespołu rekrutacji — fixture ustawia go
jako `recruiter_id` oferty. Bez tego każdy `/move` odpowiada 403.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

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
from app.models.user import User, UserRole


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pv_client():
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

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
    salary_max: int | None = 20000,
    delivery_lead_id: int | None = None,
    recruiter_id: int | None = None,
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
            delivery_lead_id=delivery_lead_id,
            # Właściciel oferty = członek zespołu (bramka członkostwa pipeline'u).
            recruiter_id=recruiter_id,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


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


# ── Tests: bramki nie ma ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_above_budget_stays_active_and_flags_budget(
    pv_client: AsyncClient,
):
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "off-above")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "25000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Ruch przechodzi, stawka zapisana, przekroczenie tylko jako informacja.
        assert body["verification_status"] == "active"
        assert body["budget_exceeded"] is True
        assert body["budget_max_at_move"] == 20000
        assert body["expected_rate_value"] in ("25000.00", "25000")

        async with AsyncSessionLocal() as db:
            notif = await db.scalar(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.pending_verification,
                    Notification.related_entity_id == body["id"],
                )
            )
            assert notif is None, "przy wyłączonej bramce nie ma komu zgłaszać"

        # Tablica niesie tę samą informację na karcie.
        kanban = await pv_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
        assert kanban.status_code == 200, kanban.text
        cards = [
            item
            for col in kanban.json()["columns"]
            for item in col["items"]
            if item["candidate_id"] == cand_id
        ]
        assert cards and cards[0]["budget_exceeded"] is True
        assert cards[0]["verification_status"] == "active"
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_within_budget_has_no_flag(pv_client: AsyncClient):
    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "off-within")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "15000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "active"
        assert body["budget_exceeded"] is False
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


def test_acceptance_queue_routes_do_not_exist() -> None:
    """Tras kolejki akceptacji nie ma w aplikacji — nie „odpowiadają 404".

    Sprawdzamy `app.routes`, bo 404 dostałaby też literówka w ścieżce: taki
    test przechodziłby również wtedy, gdyby trasy wróciły pod inną nazwą.
    """
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/pipeline/pending-verifications" not in paths
    assert not [
        path
        for path in paths
        if "accept-verification" in path or "reject-verification" in path
    ]


@pytest.mark.asyncio
async def test_stage_stored_as_pending_is_not_stuck(pv_client: AsyncClient):
    """Produkcja ma wiersze `pending` zapisane przed zdjęciem bramki.
    Bez approvera nie mogą blokować kolejnego ruchu ani wyglądać na Pending."""
    from datetime import datetime, timezone

    recr_uid, email, pw = await _seed_user(UserRole.recruiter, "off-stuck")
    headers = await _login(pv_client, email, pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.verified,
                    moved_at=datetime.now(timezone.utc),
                    moved_by=recr_uid,
                    verification_status=VerificationStatus.pending,
                    expected_rate_value=30000,
                    expected_rate_unit="monthly",
                    expected_rate_currency="PLN",
                    budget_max_at_move=20000,
                )
            )
            await db.commit()

        kanban = await pv_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
        assert kanban.status_code == 200, kanban.text
        cards = [
            item
            for col in kanban.json()["columns"]
            for item in col["items"]
            if item["candidate_id"] == cand_id
        ]
        assert cards and cards[0]["verification_status"] == "active"
        assert cards[0]["budget_exceeded"] is True

        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={"candidate_id": cand_id, "job_id": job_id, "stage": "cv_sent"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == "cv_sent"
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
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verification_status"] == "active"
        assert body["expected_rate_value"] is None
    finally:
        await _cleanup(candidate_ids=[cand_id], job_ids=[job_id])


@pytest.mark.asyncio
async def test_verified_move_credits_first_verifier_immediately(
    pv_client: AsyncClient,
):
    """Bez bramki kredyt KPI pierwszego weryfikatora trafia od razu do mover-a."""
    from app.models.recruitment_process import RecruitmentProcess

    recr_uid, recr_email, recr_pw = await _seed_user(UserRole.recruiter, "credit")
    recr_headers = await _login(pv_client, recr_email, recr_pw)
    cand_id = await _seed_candidate()
    job_id = await _seed_job(salary_max=20000, recruiter_id=recr_uid)
    try:
        resp = await pv_client.post(
            "/api/pipeline/move",
            headers=recr_headers,
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "verified",
                "expected_rate_value": "40000",
                "expected_rate_unit": "monthly",
            },
        )
        assert resp.status_code == 200, resp.text
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
