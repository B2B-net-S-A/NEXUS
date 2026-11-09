"""Ponowne otwarcie rekrutacji zaczyna nowe otwarcie (decyzja Artura 05.11.2026).

Do 05.11.2026 „Otwórz ponownie” zmieniało tylko status. Karty z poprzedniego
otwarcia wracały do „W drodze” i prognozy (symulacja na kopii produkcji: 7 → 92
akceptacji do domknięcia), stary placement zajmował wakat (rekrutacje
otwarte ponownie miały 0 wakatów), a bramka powodu zamknięcia odmawiała
„nie liczy się” z powodu zatrudnienia sprzed lat. Placement w statystykach
zostaje pierwszym „Zatrudniony” pary — ponowne otwarcie go nie zmienia.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.job_champions import PairPlace, _hired_ids
from app.services.job_closed_notices import waiting_cards
from app.services.job_opening import BACKFILL_SQL, in_opening

_YEAR = 2058


def _at(month: int, day: int) -> datetime:
    return datetime(_YEAR, month, day, 12, 0, tzinfo=timezone.utc)


# ── Bez bazy ──────────────────────────────────────────────────────────────


def test_in_opening_counts_moves_from_the_reopening_on() -> None:
    opened = _at(3, 15)
    assert in_opening(_at(3, 15), opened)
    assert in_opening(_at(3, 20), opened)
    assert not in_opening(_at(3, 14), opened)
    # Rekrutacja nigdy nie otwarta ponownie — liczy się cała historia.
    assert in_opening(_at(1, 1), None)


def _stage_row(candidate_id: int, stage: PipelineStage, when: datetime, row_id: int):
    return SimpleNamespace(
        id=row_id,
        candidate_id=candidate_id,
        stage=stage,
        moved_by=7,
        moved_at=when,
        approved_at=None,
        stage_name=None,
        stage_category=None,
        stage_terminal_type=None,
    )


def test_waiting_cards_skip_cards_from_the_previous_opening() -> None:
    rows = [
        _stage_row(1, PipelineStage.acceptance, _at(2, 1), 1),
        _stage_row(2, PipelineStage.cv_sent, _at(2, 1), 2),
        _stage_row(2, PipelineStage.client_interview, _at(3, 20), 3),
    ]
    assert {c.candidate_id for c in waiting_cards(rows)} == {1, 2}
    cards = waiting_cards(rows, since=_at(3, 15))
    assert [(c.candidate_id, c.column) for c in cards] == [(2, "client_interview")]


def test_hired_ids_skip_hires_from_the_previous_opening() -> None:
    places = {
        1: PairPlace(1, "Stara", "hired", None, moved_at=_at(1, 10)),
        2: PairPlace(2, "Nowa", "hired", None, moved_at=_at(3, 20)),
        3: PairPlace(3, "W toku", "contract", None, moved_at=_at(3, 21)),
    }
    assert _hired_ids(places) == {1, 2}
    assert _hired_ids(places, since=_at(3, 15)) == {2}


# ── Z bazą ────────────────────────────────────────────────────────────────


async def _job_via_api(app_client: AsyncClient, headers: dict[str, str]) -> int:
    from tests.test_job_close import _create_draft_job

    return await _create_draft_job(app_client, headers, "pytest-new-opening")


async def _add_stage(
    job_id: int, stage: PipelineStage, when: datetime, candidate_id: int | None = None
) -> int:
    async with AsyncSessionLocal() as db:
        if candidate_id is None:
            cand = Candidate(name="Otwarcie", lastname=f"Test-{uuid.uuid4().hex[:8]}")
            db.add(cand)
            await db.flush()
            candidate_id = cand.id
        db.add(
            CandidateStage(
                candidate_id=candidate_id, job_id=job_id, stage=stage, moved_at=when
            )
        )
        await db.commit()
    return candidate_id


async def _close_and_reopen(
    app_client: AsyncClient, headers: dict[str, str], job_id: int, reason: str
) -> None:
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": reason, "acknowledge_active_cards": True},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.post(
        f"/api/jobs/{job_id}/publish",
        json={"assignment_mode": "keep"},
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text


async def _opening_started_at(job_id: int) -> datetime | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Job.cycle_started_at).where(Job.id == job_id))


@pytest.mark.asyncio
async def test_reopen_starts_a_new_opening_and_old_hire_frees_the_vacancy(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.services.job_fill import filled_by_job, open_vacancies

    job_id = await _job_via_api(app_client, app_auth_headers)
    assert await _opening_started_at(job_id) is None
    await _add_stage(
        job_id, PipelineStage.hired, datetime.now(timezone.utc) - timedelta(days=200)
    )
    async with AsyncSessionLocal() as db:
        assert (await filled_by_job(db, [job_id])).get(job_id) == 1

    await _close_and_reopen(app_client, app_auth_headers, job_id, "filled_by_us")

    assert await _opening_started_at(job_id) is not None
    async with AsyncSessionLocal() as db:
        filled = (await filled_by_job(db, [job_id])).get(job_id, 0)
    assert filled == 0
    assert open_vacancies(1, filled) == 1


@pytest.mark.asyncio
async def test_hire_in_the_new_opening_fills_it_without_a_second_placement(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.services.job_fill import filled_by_job

    job_id = await _job_via_api(app_client, app_auth_headers)
    person = await _add_stage(
        job_id, PipelineStage.hired, datetime.now(timezone.utc) - timedelta(days=200)
    )
    await _close_and_reopen(app_client, app_auth_headers, job_id, "filled_by_us")
    # Ta sama osoba wraca do pracy w nowym otwarciu.
    await _add_stage(job_id, PipelineStage.hired, datetime.now(timezone.utc), person)

    async with AsyncSessionLocal() as db:
        assert (await filled_by_job(db, [job_id])).get(job_id) == 1
        placements = await db.scalar(
            text(
                "SELECT count(*) FROM analytics_first_milestones "
                "WHERE job_id = :job AND stage = 'hired'"
            ),
            {"job": job_id},
        )
    # Placement to pierwsze „Zatrudniony” pary — drugi raz się nie liczy.
    assert placements == 1


@pytest.mark.asyncio
async def test_neutral_close_after_reopen_ignores_the_previous_hire(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _job_via_api(app_client, app_auth_headers)
    await _add_stage(
        job_id, PipelineStage.hired, datetime.now(timezone.utc) - timedelta(days=200)
    )
    await _close_and_reopen(app_client, app_auth_headers, job_id, "filled_by_us")

    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={
            "reason": "budget",
            "notes": "Klient wstrzymał projekt po ponownym otwarciu",
            "acknowledge_active_cards": True,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["close_reason"] == "budget"


@pytest.mark.asyncio
async def test_traffit_transfer_reopen_keeps_the_opening() -> None:
    """Przeniesienie z Traffita to ta sama praca, nie nowe otwarcie."""
    from app.models.user import User
    from app.services import job_lifecycle

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Transfer-{tag}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Transfer {tag}",
            location="Warszawa",
            status=JobStatus.closed,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        db.add(job)
        await db.flush()
        actor = await db.scalar(select(User).where(User.is_active.is_(True)).limit(1))
        await job_lifecycle.publish_core(
            db,
            job,
            actor,
            job_lifecycle.PostCommit(),
            reason="traffit_transfer",
            new_opening=False,
        )
        assert job.status == JobStatus.published
        assert job.cycle_started_at is None
        await db.rollback()


async def _published_job(opened_at: datetime | None) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Otwarcie-{tag}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Otwarcie {tag}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            cycle_started_at=opened_at,
        )
        db.add(job)
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_in_flight_skips_cards_from_the_previous_opening() -> None:
    from app.services.insights_in_flight import compute_in_flight

    job_id = await _published_job(_at(3, 15))
    # Akceptacja sprzed ponownego otwarcia, bez ruchu potem.
    await _add_stage(job_id, PipelineStage.acceptance, _at(3, 2))
    # Akceptacja w nowym otwarciu.
    await _add_stage(job_id, PipelineStage.acceptance, _at(3, 20))
    # Osoba z poprzedniego otwarcia, którą rekruter ruszył w nowym.
    back = await _add_stage(job_id, PipelineStage.cv_sent, _at(2, 1))
    await _add_stage(job_id, PipelineStage.client_interview, _at(3, 18), back)

    async with AsyncSessionLocal() as db:
        result = await compute_in_flight(
            db,
            today=date(_YEAR, 3, 31),
            now=_at(3, 31),
            with_acceptances=True,
            job_ids=[job_id],
        )
    by_col = {c["column"]: c for c in result["columns"]}
    assert by_col["contract"]["count"] == 1
    assert by_col["client_interview"]["count"] == 1
    assert result["forecast"]["open"] == 1
    assert [a["since"] for a in result["acceptances"]] == [f"{_YEAR}-03-20"]


@pytest.mark.asyncio
async def test_stage_breakdown_now_skips_cards_from_the_previous_opening() -> None:
    from app.services.insights_stage_breakdown import compute_stage_breakdown

    job_id = await _published_job(_at(3, 15))
    await _add_stage(job_id, PipelineStage.acceptance, _at(3, 2))
    await _add_stage(job_id, PipelineStage.hired, _at(1, 5))
    await _add_stage(job_id, PipelineStage.acceptance, _at(3, 20))

    async with AsyncSessionLocal() as db:
        result = await compute_stage_breakdown(
            db, start=_at(3, 1), end=_at(4, 1), job_ids=[job_id]
        )
    now = {row["key"]: row["now"] for row in result["rows"]}
    assert now["acceptance"] == 1
    assert now["hired"] == 0


@pytest.mark.asyncio
async def test_close_warning_skips_cards_from_the_previous_opening() -> None:
    from app.services.job_active_cards import load_active_cards

    job_id = await _published_job(_at(3, 15))
    await _add_stage(job_id, PipelineStage.cv_sent, _at(3, 2))
    async with AsyncSessionLocal() as db:
        assert (await load_active_cards(db, job_id)).total == 0
    await _add_stage(job_id, PipelineStage.cv_sent, _at(3, 20))
    async with AsyncSessionLocal() as db:
        assert (await load_active_cards(db, job_id)).total == 1


async def _job_with_reopen_activity(reason: str | None) -> int:
    job_id = await _published_job(None)
    async with AsyncSessionLocal() as db:
        details: dict[str, Any] = {"reopened": True}
        if reason:
            details["reason"] = reason
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="published",
                details=details,
                created_at=_at(3, 15),
            )
        )
        await db.commit()
    return job_id


@pytest.mark.asyncio
async def test_backfill_marks_human_reopens_only() -> None:
    human = await _job_with_reopen_activity("Klient wraca z nowym etatem")
    transfer = await _job_with_reopen_activity("traffit_transfer")
    async with AsyncSessionLocal() as db:
        await db.execute(text(BACKFILL_SQL))
        await db.commit()
    assert await _opening_started_at(human) == _at(3, 15)
    assert await _opening_started_at(transfer) is None
