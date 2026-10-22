"""Mail „Nowy placement” do Rady nadzorczej (decyzja Artura 22.10.2026).

Reguły pod ochroną: bez danych kandydata; jeden mail na parę (kandydat,
rekrutacja); tylko placementy po dacie „wysyłaj od” i nie starsze niż
`LOOKBACK`; marża/h tylko, gdy da się ją policzyć.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.kpi_email_report_run import KpiEmailReportRun
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import board_placement_alerts as alerts


def _facts(**over) -> alerts.PlacementFacts:
    base = dict(
        client_name="Bank Przykładowy",
        job_title="Senior Java Developer",
        recruiter_name="Ola K.",
        delivery_lead_name="Kasia P.",
        reached_on=date(2026, 10, 22),
        start_date=date(2026, 11, 3),
        margin_per_hour=42.5,
        month_number=7,
        open_acceptances=10,
        forecast_low=8,
        forecast_high=9,
    )
    base.update(over)
    return alerts.PlacementFacts(**base)


def test_mail_names_client_job_people_start_margin_and_what_is_in_flight():
    subject, body = alerts.render_placement_alert(
        _facts(), "https://x/insights?tab=firma"
    )
    assert subject == "Nowy placement: Bank Przykładowy · Senior Java Developer"
    assert "Nowy placement — 22 października 2026." in body
    assert "Rekruter: Ola K." in body
    assert "Delivery Lead: Kasia P." in body
    assert "Start: 3 listopada 2026" in body
    assert "Marża na godzinę: 42,50 zł" in body
    assert "To 7. placement w październiku." in body
    assert (
        "W drodze: 10 akceptacji do domknięcia — przy dotychczasowej skuteczności "
        "ok. 8–9 kolejnych placementów." in body
    )
    assert "https://x/insights?tab=firma" in body
    assert "Bez danych kandydata" in body


def test_mail_without_margin_contract_start_or_forecast_says_so_plainly():
    _, body = alerts.render_placement_alert(
        _facts(
            margin_per_hour=None,
            start_date=None,
            forecast_low=None,
            forecast_high=None,
            open_acceptances=2,
        ),
        "/insights?tab=firma",
    )
    assert "Marża na godzinę" not in body
    assert "Start: do ustalenia" in body
    assert "W drodze: 2 akceptacje do domknięcia." in body


def test_mail_without_open_acceptances_skips_the_line():
    _, body = alerts.render_placement_alert(_facts(open_acceptances=0), "/x")
    assert "W drodze" not in body


def test_pair_key_is_stable():
    assert alerts.pair_key(12, 34) == "12:34"


# ── Z bazy ───────────────────────────────────────────────────────────────────

_YEAR = 2059


@pytest.mark.asyncio
async def test_pending_placements_skip_old_ones_and_pairs_already_mailed():
    tag = uuid.uuid4().hex[:8]
    now = datetime(_YEAR, 5, 10, 12, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Alert-{tag}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Alert {tag}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cands = [
            Candidate(
                name=f"A{i}", lastname=f"T-{tag}", email=f"alert-{tag}-{i}@example.com"
            )
            for i in range(3)
        ]
        db.add_all([job, *cands])
        await db.flush()
        fresh, mailed, old = cands
        for cand, when in (
            (fresh, now - timedelta(hours=2)),
            (mailed, now - timedelta(hours=1)),
            (old, now - alerts.LOOKBACK - timedelta(hours=1)),
        ):
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=when,
                    external_source="manual",
                )
            )
        db.add(
            KpiEmailReportRun(
                kind=alerts.KIND,
                period_key=alerts.pair_key(mailed.id, job.id),
                status="sent",
            )
        )
        await db.commit()

        pending = await alerts.pending_placements(
            db, since=now - timedelta(days=30), now=now
        )
    mine = [p for p in pending if p.job_id == job.id]
    assert [p.candidate_id for p in mine] == [fresh.id]


@pytest.mark.asyncio
async def test_pending_placements_respect_the_send_not_before_cutoff():
    now = datetime(_YEAR, 6, 10, 12, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        pending = await alerts.pending_placements(db, since=now, now=now)
    assert pending == []
