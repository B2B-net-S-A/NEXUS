"""Tests for GET /api/reports/recruitment — verifier-anchored per-recruiter credit.

Regresja zgłoszona przez Artura: gdy osoba A przenosi kandydata na „verified"
(Zweryfikowany), a osoba B później na „cv_sent" (CV wysłane), zasługa za wysyłkę
dublowała się — liczyła się i A (weryfikacja) i B (rekomendacja). Oczekiwane:
WSZYSTKIE kamienie milowe pary (kandydat × rekrutacja) — rekomendacja, interview,
placement — dostaje **weryfikator** (osoba, która ruszyła na „verified"),
niezależnie kto klikał późniejsze etapy. Fallback do faktycznego movera tylko gdy
para nigdy nie przeszła przez „verified".

Spójne z panelem „Moje KPI" (app/services/kpi_panel.py, VERIFIER_ANCHORED_CTE).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rep-anchored-{label}-{unique}@example.com"
    password = f"T3st_{unique}!Anchored"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Rep {label} {unique}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_client() -> int:
    async with AsyncSessionLocal() as db:
        c = Client(name=f"Anchored-{uuid.uuid4().hex[:6]}", status=ClientStatus.active)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Role-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            headcount=1,
            client_id=client_id,
            recruitment_type=RecruitmentType.body_leasing,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Jan-{uuid.uuid4().hex[:4]}",
            lastname=f"Test-{uuid.uuid4().hex[:4]}",
            email=f"cand-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_stage(
    *, candidate_id: int, job_id: int, stage: PipelineStage, moved_by: int, moved_at
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_by=moved_by,
                moved_at=moved_at,
            )
        )
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rep_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    await cache_invalidate("reports:recruitment")
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_credited_to_verifier_not_sender(rep_client: AsyncClient):
    """Verifier (Artur) gets the cv_sent/interview credit even when someone else
    (Kasia) physically moved the candidate to those stages."""
    client_id = await _seed_client()
    job_id = await _seed_job(client_id)

    artur_id, _, _ = await _seed_user(UserRole.recruiter, "artur")
    kasia_id, _, _ = await _seed_user(UserRole.recruiter, "kasia")

    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=1)

    # Candidate A: Artur verifies, Kasia sends CV + moves to interview.
    cand_a = await _seed_candidate()
    await _seed_stage(
        candidate_id=cand_a,
        job_id=job_id,
        stage=PipelineStage.verified,
        moved_by=artur_id,
        moved_at=recent,
    )
    await _seed_stage(
        candidate_id=cand_a,
        job_id=job_id,
        stage=PipelineStage.cv_sent,
        moved_by=kasia_id,
        moved_at=recent + timedelta(hours=1),
    )
    await _seed_stage(
        candidate_id=cand_a,
        job_id=job_id,
        stage=PipelineStage.interview,
        moved_by=kasia_id,
        moved_at=recent + timedelta(hours=2),
    )

    # Candidate B (control): never verified — Kasia sends CV directly → fallback
    # credits the actual mover (Kasia).
    cand_b = await _seed_candidate()
    await _seed_stage(
        candidate_id=cand_b,
        job_id=job_id,
        stage=PipelineStage.cv_sent,
        moved_by=kasia_id,
        moved_at=recent,
    )

    admin_id, email, password = await _seed_user(UserRole.admin, "admin")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        "/api/reports/recruitment?period=month", headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = {r["user_id"]: r for r in resp.json()["per_recruiter"]}

    artur = rows.get(artur_id)
    kasia = rows.get(kasia_id)
    assert artur is not None, "verifier missing from per_recruiter breakdown"
    assert kasia is not None, "sender missing from per_recruiter breakdown"

    # Verifier gets the WHOLE funnel of candidate A — including the cv_sent &
    # interview that Kasia clicked.
    assert artur["weryfikacje"] == 1
    assert artur["rekomendacje"] == 1
    assert artur["interviews"] == 1
    assert artur["placements"] == 0

    # Kasia gets NOTHING from candidate A; only the control B's unverified cv_sent.
    assert kasia["weryfikacje"] == 0
    assert kasia["rekomendacje"] == 1  # candidate B only (fallback), NOT A
    assert kasia["interviews"] == 0


@pytest.mark.asyncio
async def test_pure_sender_without_verifications_gets_no_credit(
    rep_client: AsyncClient,
):
    """A recruiter who only ever forwards already-verified candidates (never
    verifies) earns zero funnel credit — it all flows to the verifier."""
    client_id = await _seed_client()
    job_id = await _seed_job(client_id)

    verifier_id, _, _ = await _seed_user(UserRole.recruiter, "ver")
    sender_id, _, _ = await _seed_user(UserRole.recruiter, "snd")

    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=2)

    for _ in range(3):
        cand = await _seed_candidate()
        await _seed_stage(
            candidate_id=cand,
            job_id=job_id,
            stage=PipelineStage.verified,
            moved_by=verifier_id,
            moved_at=recent,
        )
        await _seed_stage(
            candidate_id=cand,
            job_id=job_id,
            stage=PipelineStage.cv_sent,
            moved_by=sender_id,
            moved_at=recent + timedelta(hours=1),
        )

    _, email, password = await _seed_user(UserRole.admin, "admin2")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        "/api/reports/recruitment?period=month", headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = {r["user_id"]: r for r in resp.json()["per_recruiter"]}

    verifier = rows.get(verifier_id)
    assert verifier is not None
    assert verifier["weryfikacje"] == 3
    assert verifier["rekomendacje"] == 3  # all 3 cv_sent anchored to verifier

    # The pure sender either isn't listed at all or shows all zeros.
    sender = rows.get(sender_id)
    if sender is not None:
        assert sender["weryfikacje"] == 0
        assert sender["rekomendacje"] == 0
        assert sender["interviews"] == 0
        assert sender["placements"] == 0


# ── Spójność nagłówka z własnymi wierszami ──────────────────────────────────


@pytest.mark.asyncio
async def test_header_totals_equal_the_sum_of_its_own_rows(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Tabela musi sumować się do własnego nagłówka.

    Do 09.2026 nagłówek czytał surowy `analytics_first_milestones`, a wiersze
    szły przez `VERIFIER_ANCHORED_CTE` — dwie różne populacje w JEDNEJ
    odpowiedzi HTTP. Zmierzone na produkcji (rok 2026): kolumna „interview"
    sumowała się do 3 833 pod nagłówkiem mówiącym 3 339, czyli rozjazd 15%.
    """
    resp = await app_client.get(
        "/api/reports/recruitment?period=year", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    rows = body["per_recruiter"]
    funnel = body["funnel"]
    unattributed = body["unattributed"]
    for header_key, row_key in (
        ("weryfikacje_count", "weryfikacje"),
        ("rekomendacje_count", "rekomendacje"),
        ("interviews_count", "interviews"),
        ("placements_count", "placements"),
    ):
        # Kamienie bez autora są WYSTAWIONE, nie schowane — zawężenie nagłówka
        # do przypisanych po cichu ukryłoby wykonaną pracę.
        assert funnel[header_key] == (
            sum(r[row_key] for r in rows) + unattributed[row_key]
        ), header_key


@pytest.mark.asyncio
async def test_zero_denominator_is_null_not_a_hard_zero(
    app_client: AsyncClient, app_auth_headers: dict
):
    """„Nie było czego dzielić" ≠ „0% skuteczności"."""
    from app.api.reports import _pct_or_none, _safe_pct

    assert _pct_or_none(3, 0) is None
    # Legacy kontrakt ZOSTAJE — trzej konsumenci stoją na nim arytmetycznie.
    assert _safe_pct(3, 0) == 0.0


@pytest.mark.asyncio
async def test_closing_more_than_verifying_is_named_not_left_as_efficiency(
    app_client: AsyncClient, app_auth_headers: dict
):
    """5 850% przy nazwisku czyta się jak skuteczność, a jest masowym domykaniem."""
    resp = await app_client.get(
        "/api/reports/recruitment?period=year", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text

    for row in resp.json()["per_recruiter"]:
        assert "closes_more_than_verifies" in row
        assert row["closes_more_than_verifies"] == (
            row["placements"] > row["weryfikacje"]
        )
