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


def test_dl_portfolio_scope_keeps_placements_of_neutral_closures() -> None:
    """Neutralne wypadają z requestów, nie z zatrudnień — jak w lidze.

    `jobs_scoped` łączą też zapytania o placementy; WHERE w CTE wyciąłby
    zatrudnienie z rekrutacji zamkniętej jako „wstrzymana” tylko w Portfelach
    DL, a liga by je liczyła.
    """
    from app.services.insights_dl_scope import JOBS_SCOPED_CTE

    assert "AS in_demand" in JOBS_SCOPED_CTE
    assert "WHERE" not in JOBS_SCOPED_CTE
    assert "'duplicate'" in JOBS_SCOPED_CTE


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
    # `/publish` odpowiada stanem bramki, nie rekrutacją — czytamy ją osobno.
    fetched = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["status"] == "published"
    assert body["close_reason"] is None
    assert body["close_notes"] is None


@pytest.mark.asyncio
async def test_tenders_win_rate_skips_neutral_closures() -> None:
    from app.analytics import metrics
    from app.analytics.periods import Period, PeriodKind
    from app.core.database import AsyncSessionLocal

    year = _year()
    async with AsyncSessionLocal() as db:
        await _closed_jobs(
            db,
            year=year,
            reasons=[JobCloseReason.filled_by_us, JobCloseReason.duplicate],
        )
        await db.commit()
        result = await metrics.tenders(
            db,
            Period(PeriodKind.custom, _at(year, 8, 1), _at(year, 9, 1)),
            include_values=False,
        )
    assert result["closed_total"] == 2
    assert result["won"] == 1
    assert result["win_rate_pct"] == 100.0


# ── Okno zamykania: wybór powodu i „Zmień powód” (PR 2, CI) ───────────────


async def _job_via_api(app_client: AsyncClient, headers: dict[str, str]) -> int:
    from tests.test_job_close import _create_draft_job

    return await _create_draft_job(app_client, headers, "pytest-hit-ratio-choice")


def _code(resp) -> str:
    return resp.json()["detail"]["code"]


@pytest.mark.asyncio
async def test_neutral_close_requires_notes_and_other_is_retired(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    url = f"/api/jobs/{job_id}/close"
    no_notes = await app_client.post(
        url, json={"reason": "duplicate", "notes": "  "}, headers=app_auth_headers
    )
    assert no_notes.status_code == 422, no_notes.text
    assert _code(no_notes) == "close_notes_required"
    other = await app_client.post(
        url, json={"reason": "other"}, headers=app_auth_headers
    )
    assert other.status_code == 422
    assert _code(other) == "close_reason_other_retired"
    wrong_pair = await app_client.post(
        url,
        json={"reason": "competitor", "duplicate_of_job_id": job_id},
        headers=app_auth_headers,
    )
    assert wrong_pair.status_code == 422
    assert _code(wrong_pair) == "duplicate_of_requires_duplicate"
    itself = await app_client.post(
        url,
        json={"reason": "duplicate", "notes": "x", "duplicate_of_job_id": job_id},
        headers=app_auth_headers,
    )
    assert itself.status_code == 422
    assert _code(itself) == "duplicate_of_self"


@pytest.mark.asyncio
async def test_duplicate_close_keeps_the_remaining_job(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    keep_id = await _job_via_api(app_client, app_auth_headers)
    dup_id = await _job_via_api(app_client, app_auth_headers)
    resp = await app_client.post(
        f"/api/jobs/{dup_id}/close",
        json={
            "reason": "duplicate",
            "notes": "Ten sam request z maila klienta",
            "duplicate_of_job_id": keep_id,
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["close_reason"] == "duplicate"
    assert body["duplicate_of_job_id"] == keep_id
    assert body["close_notes"] == "Ten sam request z maila klienta"


@pytest.mark.asyncio
async def test_neutral_close_refused_when_we_hired_someone(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    job_id = await _job_via_api(app_client, app_auth_headers)
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Hit", lastname=f"Ratio-{uuid.uuid4().hex[:8]}")
        db.add(cand)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "budget",
            "notes": "Klient zamknął projekt",
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert _code(resp) == "close_reason_has_hire"


@pytest.mark.asyncio
async def test_change_close_reason_keeps_the_close_date_and_logs_it(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity

    job_id = await _job_via_api(app_client, app_auth_headers)
    url = f"/api/jobs/{job_id}/close-reason"
    still_open = await app_client.patch(
        url, json={"reason": "competitor"}, headers=app_auth_headers
    )
    assert still_open.status_code == 409
    assert _code(still_open) == "job_not_closed"

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    closed_at = closed.json()["closed_at"]

    no_notes = await app_client.patch(
        url, json={"reason": "internal_hire"}, headers=app_auth_headers
    )
    assert no_notes.status_code == 422
    assert _code(no_notes) == "close_notes_required"

    changed = await app_client.patch(
        url,
        json={"reason": "internal_hire", "notes": "Klient przesunął swoją osobę"},
        headers=app_auth_headers,
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["close_reason"] == "internal_hire"
    assert body["closed_at"] == closed_at
    async with AsyncSessionLocal() as db:
        logged = (
            await db.execute(
                select(Activity.details).where(
                    Activity.entity_type == "job",
                    Activity.entity_id == job_id,
                    Activity.action == "close_reason_changed",
                )
            )
        ).scalar_one()
    assert logged["from"]["reason"] == "competitor"
    assert logged["to"]["reason"] == "internal_hire"


# ── Lista kontrolna i liczniki DL (PR 3, CI) ──────────────────────────────


@pytest.mark.asyncio
async def test_closures_list_groups_rows_and_counts() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.hit_ratio_closures import hit_ratio_closures

    year = _year()
    async with AsyncSessionLocal() as db:
        client_id = await _closed_jobs(
            db,
            year=year,
            reasons=[
                JobCloseReason.competitor,
                JobCloseReason.duplicate,
                JobCloseReason.paused,
                JobCloseReason.other,
                None,
            ],
        )
        await db.commit()
        result = await hit_ratio_closures(
            db, start=_at(year, 8, 1), end=_at(year, 9, 1)
        )
    mine = [r for r in result["neutral"] + result["unreviewed"] if r["client_name"]]
    assert client_id
    assert result["counts"] == {"won": 0, "lost": 1, "neutral": 2, "unreviewed": 2}
    assert {r["close_reason"] for r in result["neutral"]} == {"duplicate", "paused"}
    assert {r["close_reason"] for r in result["unreviewed"]} == {"other", None}
    assert len(mine) == 4
    # „Zmień powód” w Insights zna klienta — lista rekrutacji przy duplikacie.
    assert {r["client_id"] for r in mine} == {client_id}
    # 0 wygranych z 3 liczonych (konkurencja + dwa do przejrzenia).
    assert result["hit_ratio"] == 0.0


@pytest.mark.asyncio
async def test_dl_neutral_closed_counts_mirror_the_league_denominator() -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from app.services import competitions

    year = _year()
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"hr-neutral-cnt-{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password("x"),
            name="DL liczniki",
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
                JobCloseReason.duplicate,
                JobCloseReason.budget,
            ],
        )
        await db.commit()
        start, end = competitions.quarter_bounds(year, 3)
        neutral = await competitions.dl_neutral_closed_counts(db, start=start, end=end)
        _p, requests = await competitions.dl_portfolio_counts(db, start=start, end=end)
    assert neutral.get(dl.id) == 2
    assert requests.get(dl.id) == 1
