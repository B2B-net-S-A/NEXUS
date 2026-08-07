"""Testy jawnego okna `[start, end)` w compute_team_panel (PR 2 sekcji
„Statystyki rekrutacji").

Kontrakt: `bounds=(start, end)` ma pierwszeństwo nad `period`; default
(`period=...`) zachowuje się identycznie jak przed zmianą (end = teraz).
Granice są half-open — zdarzenie dokładnie na `end` NIE liczy się.
Asercje celują w wiersz konkretnego (świeżo zaseedowanego) usera, bo panel
zwraca cały zespół, a baza testowa jest współdzielona między plikami.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_team import compute_team_panel

WARSAW = ZoneInfo("Europe/Warsaw")

# Stały „teraz" w środku miesiąca — okna testów są deterministyczne.
T_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=WARSAW)
CURR_MONTH_START = datetime(2026, 8, 1, 0, 0, tzinfo=WARSAW)
PREV_MONTH_START = datetime(2026, 7, 1, 0, 0, tzinfo=WARSAW)


async def _seed_user_with_verifications(moved_ats: list[datetime]) -> int:
    """User (recruiter) + po jednym kandydacie×job na każde `verified`."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"bounds-{unique}@example.com",
            password_hash=hash_password("x"),
            name=f"Bounds {unique}",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Bounds Client {unique}")
        db.add_all([user, client])
        await db.flush()

        for i, moved_at in enumerate(moved_ats):
            job = Job(title=f"Bounds Job {unique}-{i}", client_id=client.id)
            candidate = Candidate(
                name="Bo",
                lastname=f"Unds-{unique}-{i}",
                created_by=user.id,
                created_at=moved_at,
            )
            db.add_all([job, candidate])
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=moved_at,
                    moved_by=user.id,
                )
            )
        await db.commit()
        return user.id


def _row_for(result, user_id: int):
    for row in result.rows:
        if row.user_id == user_id:
            return row
    return None


@pytest.mark.asyncio
async def test_bounds_window_is_half_open_and_excludes_outside():
    """Zdarzenie z poprzedniego miesiąca nie liczy się w bieżącym oknie —
    i odwrotnie; zdarzenie dokładnie na `end` odpada (half-open)."""
    prev_mid = PREV_MONTH_START + timedelta(days=14)
    # Dokładnie początek bieżącego miesiąca == end poprzedniego okna.
    on_boundary = CURR_MONTH_START
    uid = await _seed_user_with_verifications([prev_mid, on_boundary])

    async with AsyncSessionLocal() as db:
        prev_window = await compute_team_panel(
            db,
            bounds=(PREV_MONTH_START, CURR_MONTH_START),
            period_label="2026-07",
            now=T_NOW,
        )
        curr_window = await compute_team_panel(
            db,
            bounds=(CURR_MONTH_START, T_NOW),
            now=T_NOW,
        )
        both = await compute_team_panel(
            db,
            bounds=(PREV_MONTH_START, T_NOW),
            now=T_NOW,
        )

    assert prev_window.period == "2026-07"
    assert curr_window.period == "custom"
    prev_row = _row_for(prev_window, uid)
    curr_row = _row_for(curr_window, uid)
    both_row = _row_for(both, uid)
    assert prev_row is not None and curr_row is not None and both_row is not None
    # half-open: zdarzenie o 00:00 1.08 NIE wpada do okna lipca…
    assert prev_row.weryfikacje == 1
    # …ale wpada do okna sierpnia (start inkluzywny).
    assert curr_row.weryfikacje == 1
    assert both_row.weryfikacje == 2

    # cv_to_base honoruje to samo okno (created_at kandydatów = moved_at).
    assert prev_row.cv_to_base == 1
    assert curr_row.cv_to_base == 1


@pytest.mark.asyncio
async def test_default_period_equals_bounds_to_now():
    """`period=month` ≡ `bounds=(month_start, now)` — stare zachowanie
    zachowane co do wiersza."""
    uid = await _seed_user_with_verifications(
        [CURR_MONTH_START + timedelta(days=3), PREV_MONTH_START + timedelta(days=3)]
    )

    async with AsyncSessionLocal() as db:
        legacy = await compute_team_panel(db, period=KpiPeriod.month, now=T_NOW)
        explicit = await compute_team_panel(
            db,
            bounds=(CURR_MONTH_START, T_NOW),
            period_label=KpiPeriod.month.value,
            now=T_NOW,
        )

    assert legacy.period == "month"
    assert explicit.period == "month"
    legacy_row = _row_for(legacy, uid)
    explicit_row = _row_for(explicit, uid)
    assert legacy_row is not None and explicit_row is not None
    assert legacy_row == explicit_row
    assert legacy_row.weryfikacje == 1  # lipcowe zdarzenie poza oknem


@pytest.mark.asyncio
async def test_requires_period_or_bounds():
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="period.*bounds|bounds.*period"):
            await compute_team_panel(db, now=T_NOW)
