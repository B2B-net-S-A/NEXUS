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
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.kpi_email_report_run import KpiEmailReportRun
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import board_placement_alerts as alerts
from app.tasks import kpi_email_reports as reports

PENDING_PREFIX = f"kpi_email_report_pending:{alerts.KIND}:"


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


def test_loop_kind_mirrors_the_service_kind():
    assert reports.PLACEMENT_KIND == alerts.KIND


def test_one_pair_does_not_drop_another_pairs_deferred_recipients():
    """Przegląd 23.10.2026: sprzątanie przy parze B kasowało ponowienie pary A."""
    assert reports.drops_stale_pending(reports.WEEKLY_KIND) is True
    assert reports.drops_stale_pending(reports.MONTHLY_KIND) is True
    assert reports.drops_stale_pending(alerts.KIND) is False


# ── Z bazy ───────────────────────────────────────────────────────────────────

_YEAR = 2059


@pytest.mark.asyncio
async def test_pending_placements_retry_what_can_be_retried_and_skip_the_rest():
    """Wysłane i stare — poza; bez znacznika, przerwane, padnięte przed
    wysyłką i z odroczonymi — wracają do `_send_report` (przegląd 23.10.2026)."""
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
        names = ["fresh", "sent", "old", "claimed", "build_failed", "deferred"]
        cands = {
            name: Candidate(
                name=name, lastname=f"T-{tag}", email=f"alert-{tag}-{name}@example.com"
            )
            for name in names
        }
        db.add_all([job, *cands.values()])
        await db.flush()
        for name, cand in cands.items():
            when = (
                now - alerts.LOOKBACK - timedelta(hours=1)
                if name == "old"
                else now - timedelta(hours=1)
            )
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=when,
                    external_source="manual",
                )
            )

        def run(name: str, status: str, recipients: int = 1, sent: int = 1) -> None:
            db.add(
                KpiEmailReportRun(
                    kind=alerts.KIND,
                    period_key=alerts.pair_key(cands[name].id, job.id),
                    status=status,
                    recipients=recipients,
                    sent=sent,
                )
            )

        run("sent", "sent")
        run("claimed", "claimed", 0, 0)
        run("build_failed", "failed", 0, 0)
        run("deferred", "sent", 2, 1)
        db.add(
            AppSetting(
                key=PENDING_PREFIX + alerts.pair_key(cands["deferred"].id, job.id),
                value={"to": ["rada@example.com"]},
            )
        )
        await db.commit()

        pending = await alerts.pending_placements(
            db, since=now - timedelta(days=30), now=now, pending_prefix=PENDING_PREFIX
        )
    mine = {p.candidate_id for p in pending if p.job_id == job.id}
    assert mine == {
        cands[n].id for n in ("fresh", "claimed", "build_failed", "deferred")
    }


@pytest.mark.asyncio
async def test_pending_placements_respect_the_send_not_before_cutoff():
    now = datetime(_YEAR, 6, 10, 12, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        pending = await alerts.pending_placements(
            db, since=now, now=now, pending_prefix=PENDING_PREFIX
        )
    assert pending == []
