"""Security matrix for the recruitment-pipeline module (M4 audit PR-01).

Verifies the P0.3 containment contracts:

- **M4-SEC-01** — the read-only viewer role ``user`` gets 403 on every
  lifecycle surface: scorecard read/submit, screening notes, SLA overview,
  funnel/TTH reports, calendar (list + CRUD), interview feedback,
  rejection-email preview/cancel/timeline, expected-rate PATCH.
- **M4-SEC-02** — ``sourcer`` cannot execute terminal moves (``hired`` /
  ``rejected`` / ``withdrawn``, single and bulk) nor the rate-bearing move to
  ``verified``, nor edit expected rate; non-terminal moves keep working.
- **M4-SEC-03** — capability checks evaluate the UNION of primary and
  secondary roles (sourcer with secondary recruiter passes terminal guard;
  TAC with secondary delivery_lead can cancel a foreign rejection email).
- **M4-P1.16** — deleting a user referenced by a ``specific_user``
  stage-notification rule no longer violates the CHECK constraint (FK is
  ON DELETE CASCADE after migration 0175); the rule row is removed.

Pattern follows ``test_candidate_module_access.py``: status-code asymmetry —
for denied roles we assert exactly 403; for allowed roles we assert *not*
403 (404/409/422/500 from missing fixtures are acceptable — the guard is
what's under test).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

ROLES = [
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.user,
]

OPERATIONAL_ROLES = {
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
}
TERMINAL_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
}
RATE_EDIT_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
}


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _seed_user(
    role: UserRole, secondary: list[str] | None = None
) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"m4acc-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!M4"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"M4 Access {role.value}",
                role=role,
                roles=secondary or [role.value],
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def m4_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def headers_by_role(m4_client: AsyncClient) -> dict[UserRole, dict[str, str]]:
    out: dict[UserRole, dict[str, str]] = {}
    for role in ROLES:
        email, password = await _seed_user(role)
        out[role] = await _login(m4_client, email, password)
    return out


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="M4",
            lastname=f"Acc-{uuid.uuid4().hex[:6]}",
            email=f"m4acc-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"M4Client-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"M4-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(candidate_id: int, job_id: int, stage_value: str) -> int:
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=datetime.now(timezone.utc),
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


# ── M4-SEC-01: viewer 403 na całej powierzchni lifecycle ─────────────────────

VIEWER_BLOCKED_ENDPOINTS = [
    ("GET", "/api/pipeline-stages/999999/scorecard", None),
    (
        "PATCH",
        "/api/pipeline/999999/scorecard",
        {"answers": [], "overall_rating": 3, "notes": None},
    ),
    ("GET", "/api/pipeline/overview-sla", None),
    ("GET", "/api/candidates/999999/pipelines", None),
    ("GET", "/api/reports/funnel", None),
    ("GET", "/api/reports/time-to-hire", None),
    ("GET", "/api/candidates/999999/screenings", None),
    ("POST", "/api/screenings", {"candidate_id": 999999, "note": "x"}),
    (
        "GET",
        "/api/calendar/events?start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z",
        None,
    ),
    (
        "POST",
        "/api/calendar/events",
        {"title": "x", "start_time": "2026-01-01T10:00:00Z"},
    ),
    ("PATCH", "/api/calendar/events/999999", {"title": "y"}),
    ("DELETE", "/api/calendar/events/999999", None),
    ("GET", "/api/interview-feedback", None),
    (
        "POST",
        "/api/interview-feedback",
        {"calendar_event_id": 999999, "rating": 3},
    ),
    ("GET", "/api/rejection-emails/999999", None),
    ("POST", "/api/rejection-emails/999999/cancel", None),
    ("GET", "/api/rejection-emails/by-candidate/999999", None),
    (
        "PATCH",
        "/api/candidates/999999/recruitments/999999/expected-rate",
        {"rate_value": 100},
    ),
]


@pytest.mark.parametrize("method,url,body", VIEWER_BLOCKED_ENDPOINTS)
async def test_viewer_blocked_everywhere(
    m4_client: AsyncClient, headers_by_role, method, url, body
):
    r = await m4_client.request(
        method, url, json=body, headers=headers_by_role[UserRole.user]
    )
    assert r.status_code == 403, f"{method} {url} -> {r.status_code} (viewer)"


@pytest.mark.parametrize("role", sorted(OPERATIONAL_ROLES, key=lambda r: r.value))
async def test_operational_roles_not_blocked_on_reads(
    m4_client: AsyncClient, headers_by_role, role
):
    """Read surfaces stay available to internal roles (guard-asymmetry)."""
    for url in (
        "/api/pipeline/overview-sla",
        "/api/reports/funnel",
        "/api/interview-feedback",
    ):
        r = await m4_client.get(url, headers=headers_by_role[role])
        assert r.status_code != 403, f"{url} blocked for {role.value}"


# ── M4-SEC-02: sourcer bez terminal/verified/rate ────────────────────────────


async def test_sourcer_cannot_terminal_move(m4_client: AsyncClient, headers_by_role):
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening")
    r = await m4_client.post(
        "/api/pipeline/move",
        json={"candidate_id": cand, "job_id": job, "stage": "hired"},
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text

    r = await m4_client.post(
        "/api/pipeline/move",
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "rejected",
            "rejection_reason": "nope",
        },
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text


async def test_sourcer_cannot_verified_move_nor_rate(
    m4_client: AsyncClient, headers_by_role
):
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening")
    r = await m4_client.post(
        "/api/pipeline/move",
        json={
            "candidate_id": cand,
            "job_id": job,
            "stage": "verified",
            "expected_rate_value": 100,
            "expected_rate_unit": "hourly",
        },
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text

    r = await m4_client.patch(
        f"/api/candidates/{cand}/recruitments/{job}/expected-rate",
        json={"rate_value": 120, "rate_unit": "hourly"},
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text


async def test_sourcer_can_still_do_nonterminal_move(
    m4_client: AsyncClient, headers_by_role
):
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "new")
    r = await m4_client.post(
        "/api/pipeline/move",
        json={"candidate_id": cand, "job_id": job, "stage": "screening"},
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 200, r.text


async def test_sourcer_bulk_hired_blocked(m4_client: AsyncClient, headers_by_role):
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "screening")
    r = await m4_client.post(
        "/api/pipeline/bulk-move",
        json={"candidate_ids": [cand], "job_id": job, "stage": "hired"},
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text
    r = await m4_client.post(
        "/api/pipeline/bulk-move",
        json={"candidate_ids": [cand], "job_id": job, "stage": "verified"},
        headers=headers_by_role[UserRole.sourcer],
    )
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("role", sorted(TERMINAL_ROLES, key=lambda r: r.value))
async def test_terminal_roles_not_blocked_on_hired(
    m4_client: AsyncClient, headers_by_role, role
):
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "onboarding")
    r = await m4_client.post(
        "/api/pipeline/move",
        json={"candidate_id": cand, "job_id": job, "stage": "hired"},
        headers=headers_by_role[role],
    )
    assert r.status_code != 403, f"hired blocked for {role.value}: {r.text}"


# ── M4-SEC-03: union primary + secondary roles ───────────────────────────────


async def test_secondary_role_grants_terminal(m4_client: AsyncClient):
    email, password = await _seed_user(
        UserRole.sourcer, secondary=["sourcer", "recruiter"]
    )
    headers = await _login(m4_client, email, password)
    cand, job = await _seed_candidate(), await _seed_job()
    await _seed_stage(cand, job, "onboarding")
    r = await m4_client.post(
        "/api/pipeline/move",
        json={"candidate_id": cand, "job_id": job, "stage": "hired"},
        headers=headers,
    )
    assert r.status_code != 403, r.text


async def test_secondary_dl_can_cancel_foreign_rejection_email(
    m4_client: AsyncClient, headers_by_role
):
    """TAC z dodatkową rolą delivery_lead anuluje cudzy zaplanowany mail —
    primary-role-only porównanie (stary kod) dawało tu 403."""
    from app.models.rejection_email import (
        RejectionEmailStatus,
        ScheduledRejectionEmail,
    )

    cand, job = await _seed_candidate(), await _seed_job()
    stage_id = await _seed_stage(cand, job, "rejected")

    async with AsyncSessionLocal() as db:
        owner = await db.scalar(
            select(User).where(User.role == UserRole.admin).limit(1)
        )
        row = ScheduledRejectionEmail(
            candidate_stage_id=stage_id,
            candidate_id=cand,
            job_id=job,
            recruiter_id=owner.id,
            to_email="m4-reject@example.com",
            subject="x",
            body_html="<p>x</p>",
            status=RejectionEmailStatus.pending,
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        row_id = row.id

    # Zwykły TAC (nie-owner, bez oversight) → 403.
    r = await m4_client.post(
        f"/api/rejection-emails/{row_id}/cancel",
        headers=headers_by_role[UserRole.tac],
    )
    assert r.status_code == 403, r.text

    # TAC + secondary delivery_lead → 200.
    email, password = await _seed_user(UserRole.tac, secondary=["tac", "delivery_lead"])
    headers = await _login(m4_client, email, password)
    r = await m4_client.post(f"/api/rejection-emails/{row_id}/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"


# ── M4-P1.16: DELETE użytkownika z regułą specific_user nie łamie CHECK ──────


async def test_user_delete_cascades_notification_rule(m4_client: AsyncClient):
    from sqlalchemy import delete as sa_delete

    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )
    from app.models.stage_notification import (
        RecipientType,
        StageNotificationRule,
    )

    email, _ = await _seed_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        target = await db.scalar(select(User).where(User.email == email))
        tpl = PipelineTemplate(name=f"M4-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        stage_def = PipelineStageDef(
            template_id=tpl.id,
            name="M4 Stage",
            order=1,
            category=StageCategoryEnum.internal,
        )
        db.add(stage_def)
        await db.flush()
        rule = StageNotificationRule(
            stage_def_id=stage_def.id,
            recipient_type=RecipientType.specific_user,
            specific_user_id=target.id,
        )
        db.add(rule)
        await db.commit()
        rule_id, target_id = rule.id, target.id

    async with AsyncSessionLocal() as db:
        # Przed migracją 0175 ten DELETE wywalał się na CHECK
        # ck_stage_notif_specific_user (SET NULL vs non-NULL requirement).
        await db.execute(sa_delete(User).where(User.id == target_id))
        await db.commit()

    async with AsyncSessionLocal() as db:
        gone = await db.scalar(
            select(StageNotificationRule).where(StageNotificationRule.id == rule_id)
        )
        assert gone is None, "reguła powinna zniknąć razem z użytkownikiem"


# ── Resolver: reguła role-based widzi secondary roles ────────────────────────


async def test_role_rule_resolver_includes_secondary_roles():
    from app.services.stage_notification_resolver import (
        _resolve_user_ids_for_rule,
        _RuleSnapshot,
    )
    from app.models.stage_notification import RecipientType

    email, _ = await _seed_user(UserRole.tac, secondary=["tac", "delivery_lead"])
    async with AsyncSessionLocal() as db:
        hybrid = await db.scalar(select(User).where(User.email == email))
        rule = _RuleSnapshot(
            recipient_type=RecipientType.role,
            specific_user_id=None,
            role="delivery_lead",
            notify_inapp=True,
            notify_email=False,
        )
        ids = await _resolve_user_ids_for_rule(db, rule=rule, job=None, candidate=None)
        assert hybrid.id in ids, (
            "hybrydowy TAC+DL powinien być odbiorcą reguły delivery_lead"
        )
