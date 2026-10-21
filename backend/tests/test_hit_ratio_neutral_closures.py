"""Zamknięcia „nie liczy się” poza hit ratio (decyzja Artura 21.10.2026).

Przegraną jest tylko rekrutacja, którą wzięła inna firma. Duplikat, zatrudnienie
wewnętrzne, anulowany projekt, wstrzymanie, milczenie klienta i „nie
znaleźliśmy kandydata” nie wchodzą do mianownika Ligi DL, celu DL ani Insights.
Do tego dnia zamknięcie zdublowanej rekrutacji obniżało hit ratio jak przegrana.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.job import Job, JobCloseReason, JobStatus
from app.services.hit_ratio_scope import (
    close_reason_group,
    counts_in_hit_ratio,
    counts_in_hit_ratio_sql,
)
from app.services.metric_definitions import (
    HIT_RATIO_LOST_CLOSE_REASONS,
    HIT_RATIO_NEUTRAL_CLOSE_REASONS,
    HIT_RATIO_WON_CLOSE_REASONS,
)


# ── Bez bazy ──────────────────────────────────────────────────────────────


def test_every_close_reason_has_exactly_one_group() -> None:
    """Nowy powód bez grupy liczyłby się po cichu jak przegrana."""
    groups = (
        HIT_RATIO_WON_CLOSE_REASONS,
        HIT_RATIO_LOST_CLOSE_REASONS,
        HIT_RATIO_NEUTRAL_CLOSE_REASONS,
    )
    for reason in JobCloseReason:
        hits = [g for g in groups if reason.value in g]
        if reason is JobCloseReason.other:
            assert hits == [], "„Inny” czeka na przegląd — nie ma grupy"
            continue
        assert len(hits) == 1, reason
    known = {r.value for r in JobCloseReason}
    for group in groups:
        assert group <= known


def test_only_competitor_is_a_loss() -> None:
    assert HIT_RATIO_LOST_CLOSE_REASONS == {"competitor"}
    assert close_reason_group(JobCloseReason.competitor) == "lost"
    assert close_reason_group(JobCloseReason.filled_by_us) == "won"
    for reason in (
        JobCloseReason.duplicate,
        JobCloseReason.internal_hire,
        JobCloseReason.budget,
        JobCloseReason.paused,
        JobCloseReason.client_ghosted,
        JobCloseReason.no_match,
    ):
        assert close_reason_group(reason) == "neutral", reason
    assert close_reason_group(JobCloseReason.other) == "unreviewed"
    assert close_reason_group(None) == "unreviewed"
    assert close_reason_group("duplicate") == "neutral"


def test_sql_condition_keeps_null_and_drops_every_neutral_reason() -> None:
    sql = counts_in_hit_ratio_sql("jj")
    assert sql.startswith("(jj.close_reason IS NULL OR jj.close_reason::text NOT IN (")
    for value in HIT_RATIO_NEUTRAL_CLOSE_REASONS:
        assert f"'{value}'" in sql
    assert "'competitor'" not in sql and "'other'" not in sql


def test_orm_condition_keeps_null_and_drops_every_neutral_reason() -> None:
    from sqlalchemy.dialects import postgresql

    compiled = str(
        counts_in_hit_ratio().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "jobs.close_reason IS NULL" in compiled
    for value in HIT_RATIO_NEUTRAL_CLOSE_REASONS:
        assert f"'{value}'" in compiled
    assert "'competitor'" not in compiled


# ── Na bazie (CI) ─────────────────────────────────────────────────────────


def _year() -> int:
    return 3000 + int(uuid.uuid4().hex[:6], 16) % 900


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


async def _closed_jobs(db, *, year: int, reasons, dl_id=None) -> int:
    from app.models.client import Client

    client = Client(name=f"Hit ratio {uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    for i, reason in enumerate(reasons):
        db.add(
            Job(
                title=f"Hit ratio {i}",
                client_id=client.id,
                delivery_lead_id=dl_id,
                status=JobStatus.closed,
                closed_at=_at(year, 8, 1 + i),
                close_reason=reason,
            )
        )
    await db.flush()
    return client.id


@pytest.mark.asyncio
async def test_league_denominator_skips_neutral_closures() -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from app.services import competitions

    year = _year()
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"hr-neutral-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("x"),
            name="DL hit ratio",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add(dl)
        await db.flush()
        await _closed_jobs(
            db,
            year=year,
            dl_id=dl.id,
            reasons=[
                JobCloseReason.competitor,
                None,
                JobCloseReason.other,
                JobCloseReason.duplicate,
                JobCloseReason.internal_hire,
                JobCloseReason.budget,
                JobCloseReason.paused,
                JobCloseReason.client_ghosted,
                JobCloseReason.no_match,
            ],
        )
        await db.commit()

        start, end = competitions.quarter_bounds(year, 3)
        _placements, requests = await competitions.dl_portfolio_counts(
            db, start=start, end=end
        )
    # Konkurencja + dwa nieprzejrzane (NULL, „Inny”); sześć neutralnych poza.
    assert requests.get(dl.id) == 3


@pytest.mark.asyncio
async def test_board_closed_jobs_skip_neutral_closures() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.insights_board_yoy import _jobs_closed_by_month

    year = _year()
    async with AsyncSessionLocal() as db:
        await _closed_jobs(
            db,
            year=year,
            reasons=[
                JobCloseReason.competitor,
                JobCloseReason.filled_by_us,
                JobCloseReason.duplicate,
                JobCloseReason.paused,
            ],
        )
        await db.commit()
        by_month = await _jobs_closed_by_month(db, _at(year, 8, 1), _at(year, 9, 1))
    assert by_month[(year, 8)][0] == 2


@pytest.mark.asyncio
async def test_reopening_clears_the_close_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Stary powód przy otwartej rekrutacji wyciąłby ją z hit ratio po
    ponownym zamknięciu bez powodu („Edytuj rekrutację”)."""
    from tests.test_job_close import _create_draft_job

    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-hit-ratio-reopen"
    )
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "paused", "notes": "Klient wraca w styczniu"},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.post(
        f"/api/jobs/{job_id}/publish", headers=app_auth_headers
    )
    assert reopened.status_code == 200, reopened.text
    body = reopened.json()
    assert body["status"] == "published"
    assert body["close_reason"] is None
    assert body["close_notes"] is None
