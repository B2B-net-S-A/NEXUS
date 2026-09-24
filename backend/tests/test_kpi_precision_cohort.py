"""Precyzja rekomendacji (30 dni) = kohorta weryfikacji (audyt 24.09.2026).

Insights → Zespół pokazywał precyzję 900% (45 rekomendacji przy 5
weryfikacjach), 200% i 161%: licznik brał każde „CV wysłane" z ostatnich 30
dni, także dla par zweryfikowanych wcześniej. Teraz licznik i mianownik idą
z tych samych par — z par zweryfikowanych w 30 dniach, ile doszło potem do
„CV wysłane" — więc precyzja z definicji nie przekracza 100%.

Pod ochroną oba panele, bo „Mój miesiąc" i tabela Zespołu mają pokazywać
tę samą liczbę: `compute_team_panel` i `compute_my_panel`.
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
from app.services.kpi_panel import compute_my_panel
from app.services.kpi_team import compute_team_panel

WARSAW = ZoneInfo("Europe/Warsaw")
T_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=WARSAW)


async def _seed(*, old_sent: int, fresh_verified: int, fresh_sent: int) -> int:
    """Rekruter z parami:

    * ``old_sent`` par zweryfikowanych 40 dni temu, z „CV wysłane" 10 dni temu
      (rekomendacja w oknie, weryfikacja poza nim — to one dawały >100%);
    * ``fresh_verified`` par zweryfikowanych 5 dni temu, z których pierwsze
      ``fresh_sent`` mają „CV wysłane" 2 dni temu.
    """
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"precision-{unique}@example.com",
            password_hash=hash_password("x"),
            name=f"Precyzja {unique}",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Precyzja Client {unique}")
        db.add_all([user, client])
        await db.flush()

        async def pair(verified_at: datetime, sent_at: datetime | None, i: int):
            job = Job(title=f"Precyzja {unique}-{i}", client_id=client.id)
            cand = Candidate(name="Pre", lastname=f"Cyzja-{unique}-{i}")
            db.add_all([job, cand])
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=verified_at,
                    moved_by=user.id,
                )
            )
            if sent_at is not None:
                db.add(
                    CandidateStage(
                        candidate_id=cand.id,
                        job_id=job.id,
                        stage=PipelineStage.cv_sent,
                        moved_at=sent_at,
                        moved_by=user.id,
                    )
                )

        i = 0
        for _ in range(old_sent):
            await pair(T_NOW - timedelta(days=40), T_NOW - timedelta(days=10), i)
            i += 1
        for n in range(fresh_verified):
            sent = T_NOW - timedelta(days=2) if n < fresh_sent else None
            await pair(T_NOW - timedelta(days=5), sent, i)
            i += 1
        await db.commit()
        return user.id


@pytest.mark.asyncio
async def test_team_precision_counts_only_pairs_verified_in_the_window() -> None:
    # Przypadek z produkcji w małej skali: 40 starych rekomendacji, 5 świeżych
    # weryfikacji, z których jedna ma CV wysłane. Stara reguła: 41/5 = 820%.
    uid = await _seed(old_sent=40, fresh_verified=5, fresh_sent=1)
    async with AsyncSessionLocal() as db:
        panel = await compute_team_panel(
            db, bounds=(T_NOW - timedelta(days=30), T_NOW), now=T_NOW
        )
    row = next(r for r in panel.rows if r.user_id == uid)

    # Rekomendacje w oknie okresu liczą się jak dotąd (tabela ich nie zmienia)…
    assert row.rekomendacje == 41
    # …ale precyzja bierze tylko pary zweryfikowane w 30 dniach.
    assert row.precision_verified_30d == 5
    assert row.precision_sent_30d == 1
    assert row.precision_pct == 20.0


@pytest.mark.asyncio
async def test_precision_never_exceeds_100_percent() -> None:
    uid = await _seed(old_sent=44, fresh_verified=5, fresh_sent=5)
    async with AsyncSessionLocal() as db:
        panel = await compute_team_panel(
            db, bounds=(T_NOW - timedelta(days=30), T_NOW), now=T_NOW
        )
    row = next(r for r in panel.rows if r.user_id == uid)
    assert row.precision_pct == 100.0
    assert panel.totals.precision_pct is None or panel.totals.precision_pct <= 100.0


@pytest.mark.asyncio
async def test_my_panel_uses_the_same_cohort() -> None:
    uid = await _seed(old_sent=40, fresh_verified=5, fresh_sent=1)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        panel = await compute_my_panel(db, user=user, now=T_NOW)
    assert panel.precision.verified == 5
    assert panel.precision.sent == 1
    assert panel.precision.value_pct == 20.0
