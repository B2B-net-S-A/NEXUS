"""Raporty `/api/reports`: powtórzony etap `hired` to nadal JEDEN placement.

Trzy miejsca liczyły placementy z surowych wierszy `candidate_stages`
(audyt statystyk, 14.09.2026):

* Delivery Lead — filtr `moved_at >= period_start` PRZED deduplikacją
  kandydata: kandydat zatrudniony w sierpniu i ponownie przeniesiony na
  „Zatrudniony" we wrześniu liczył się DL-owi jako wrześniowy placement.
* Wolne wakaty DL — `count(candidate_stages.id)`: jedna osoba z dwoma
  wierszami `hired` zajmowała dwa miejsca.
* Fill rate klienta — to samo `count(id)`: dwa wiersze = dwa zatrudnienia.

Rok fixture'ów (2042) jest CELOWO nieużywany przez inne pliki: baza testowa
jest wspólna dla przebiegu i nie jest czyszczona.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.api.reports import _compute_dl_metrics
from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

HIRED_AUG = datetime(2042, 8, 15, 10, 0, tzinfo=timezone.utc)
HIRED_SEP = datetime(2042, 9, 5, 10, 0, tzinfo=timezone.utc)
SEP_START = datetime(2042, 9, 1, tzinfo=timezone.utc)
AUG_START = datetime(2042, 8, 1, tzinfo=timezone.utc)


async def _seed_job_with_double_hire(
    db,
    *,
    tag: str,
    status: JobStatus,
    headcount: int,
    closed_at: datetime | None = None,
) -> dict:
    """Jeden DL, jeden klient, jedna oferta body-leasing, jeden kandydat
    z DWOMA wierszami `hired` (sierpień i wrzesień 2042)."""
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    dl = User(
        email=f"dedup-dl-{u}@example.com",
        password_hash=hash_password("x"),
        name=f"DL {u}",
        role=UserRole.delivery_lead,
        is_active=True,
    )
    client = Client(name=f"Dedup Client {u}", status=ClientStatus.active)
    db.add_all([dl, client])
    await db.flush()

    job = Job(
        title=f"Dedup Job {u}",
        client_id=client.id,
        delivery_lead_id=dl.id,
        recruitment_type=RecruitmentType.body_leasing,
        status=status,
        headcount=headcount,
        closed_at=closed_at,
    )
    cand = Candidate(name="Dedup", lastname=f"Kandydat-{u}")
    db.add_all([job, cand])
    await db.flush()

    db.add_all(
        [
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=HIRED_AUG,
                moved_by=dl.id,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=HIRED_SEP,
                moved_by=dl.id,
            ),
        ]
    )
    await db.commit()
    return {"dl_id": dl.id, "client_id": client.id, "job_id": job.id}


async def _dl_row(period_start: datetime, dl_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        rows, _ = await _compute_dl_metrics(
            db, period_start=period_start, only_dl_id=dl_id
        )
    assert len(rows) == 1, rows
    return rows[0]


@pytest.mark.asyncio
async def test_dl_report_counts_first_hire_in_its_own_month_only():
    """Sierpień: 1 placement. Wrzesień: 0 — powtórka etapu to nie nowe zatrudnienie.

    Do 09.2026 filtr daty szedł po KAŻDYM wierszu `hired` przed
    `count(DISTINCT candidate_id)`, więc wrześniowa powtórka wchodziła jako
    wrześniowy placement DL-a — a Insights (widok pierwszych wejść) miały
    dla tej samej oferty zero.
    """
    async with AsyncSessionLocal() as db:
        seeded = await _seed_job_with_double_hire(
            db, tag="month", status=JobStatus.published, headcount=1
        )

    september = await _dl_row(SEP_START, seeded["dl_id"])
    assert september["placements"] == 0, (
        "powtórzony `hired` we wrześniu policzony jako wrześniowy placement"
    )
    august = await _dl_row(AUG_START, seeded["dl_id"])
    assert august["placements"] == 1


@pytest.mark.asyncio
async def test_dl_open_vacancies_count_people_not_hired_rows():
    """Headcount 2, jedna osoba z dwoma wierszami `hired` → 1 wolne miejsce."""
    async with AsyncSessionLocal() as db:
        seeded = await _seed_job_with_double_hire(
            db, tag="vacancy", status=JobStatus.published, headcount=2
        )

    row = await _dl_row(SEP_START, seeded["dl_id"])
    assert row["open_requests"] == 1
    assert row["open_vacancies"] == 1, (
        "jedna osoba zajęła dwa miejsca — zajęte liczone po wierszach `hired`"
    )


@pytest.mark.asyncio
async def test_client_fill_rate_counts_people_not_hired_rows(
    app_client, app_auth_headers
):
    """Zamknięta rekrutacja: headcount 2, jedna osoba z dwoma `hired`
    → `placements` 1, `fill_rate` 50%. Ten sam wiersz czyta profil klienta
    (kafel „Zatrudnienia"), więc kontrakt odpowiedzi zostaje bez zmian."""
    async with AsyncSessionLocal() as db:
        seeded = await _seed_job_with_double_hire(
            db,
            tag="fill",
            status=JobStatus.closed,
            headcount=2,
            closed_at=HIRED_SEP,
        )

    await cache_invalidate("reports:clients")
    r = await app_client.get(
        "/api/reports/clients",
        params={"period": "all"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    row = next(c for c in r.json()["clients"] if c["client_id"] == seeded["client_id"])
    assert row["closed_jobs"] == 1
    assert row["filled_jobs"] == 1
    assert row["total_vacancies"] == 2
    assert row["placements"] == 1, "dwa wiersze `hired` jednej osoby = 2 zatrudnienia"
    assert row["fill_rate"] == 50.0
