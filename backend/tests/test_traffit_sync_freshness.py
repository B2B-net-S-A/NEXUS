"""Świeżość PER FAZA syncu Traffita (INT-09).

`checks.traffit` w `/api/health` czyta wyłącznie `__daily__` — to sonda
świeżości BIEGU, nie kompletności: faza budżetowana, która od tygodni nie
przesuwa kursora, wygląda w health identycznie jak zdrowa (tak luka w plikach
przeżyła miesiące). `GET /api/admin/traffit/sync/status` dostaje werdykt
`fresh|stale|never|advisory` per faza i zbiorcze `phases_stale`.

Dwie grupy: czysta funkcja (progi po typie fazy) i endpoint na bazie
(werdykt naprawdę trafia do odpowiedzi — `checks.traffit` bez zmian).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.tasks.traffit_sync import (
    ADVISORY_PHASES,
    DAILY_MARKER,
    FULL_MARKER,
    PHASE_NAMES,
    annotate_freshness,
    phase_freshness,
    phase_stale_after,
)

_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


# ── czysta funkcja ──────────────────────────────────────────────────────────


def test_never_when_the_phase_has_no_finished_run():
    assert phase_freshness("users", finished_at=None, now=_NOW) == "never"


def test_daily_phase_is_fresh_within_36h_and_stale_after():
    assert (
        phase_freshness("users", finished_at=_NOW - timedelta(hours=30), now=_NOW)
        == "fresh"
    )
    assert (
        phase_freshness("users", finished_at=_NOW - timedelta(hours=40), now=_NOW)
        == "stale"
    )


def test_cursored_phase_has_a_looser_threshold_than_a_daily_one():
    """Faza budżetowana przemiata wycinek i bywa ucięta deployem — 72 h, nie 36."""
    assert phase_stale_after("candidate_files") > phase_stale_after("users")
    assert (
        phase_freshness(
            "candidate_files", finished_at=_NOW - timedelta(hours=40), now=_NOW
        )
        == "fresh"
    )
    assert (
        phase_freshness(
            "candidate_files", finished_at=_NOW - timedelta(hours=80), now=_NOW
        )
        == "stale"
    )


@pytest.mark.parametrize(
    "phase",
    [
        "candidate_files",
        "candidates_cv",
        "candidates",
        "candidate_activities",
        "pipelines",
    ],
)
def test_every_cursored_phase_uses_the_looser_threshold(phase):
    assert phase_stale_after(phase) == timedelta(hours=72)


def test_full_marker_is_weekly_plus_slack():
    """Pełny reconcile to tydzień; 8 dni świeże, 9 — nie."""
    assert (
        phase_freshness(
            FULL_MARKER, finished_at=_NOW - timedelta(days=7, hours=20), now=_NOW
        )
        == "fresh"
    )
    assert (
        phase_freshness(FULL_MARKER, finished_at=_NOW - timedelta(days=9), now=_NOW)
        == "stale"
    )


def test_daily_marker_mirrors_the_health_probe_threshold():
    """`checks.traffit` degraduje po 36 h — ten sam próg dla `__daily__`."""
    assert phase_stale_after(DAILY_MARKER) == timedelta(hours=36)


@pytest.mark.parametrize("phase", sorted(ADVISORY_PHASES))
def test_advisory_phase_never_reports_stale(phase):
    """Faza doradcza nie blokuje watermarku — przeterminowana = `advisory`."""
    assert (
        phase_freshness(phase, finished_at=_NOW - timedelta(days=30), now=_NOW)
        == "advisory"
    )
    assert (
        phase_freshness(phase, finished_at=_NOW - timedelta(hours=1), now=_NOW)
        == "fresh"
    )


def test_every_known_phase_has_a_threshold():
    for phase in PHASE_NAMES + (DAILY_MARKER, FULL_MARKER):
        assert phase_stale_after(phase) >= timedelta(hours=36)


def test_annotate_writes_verdicts_and_collects_only_stale_non_advisory():
    states = [
        {
            "phase": "users",
            "last_run_finished_at": (_NOW - timedelta(days=3)).isoformat(),
        },
        {
            "phase": "clients",
            "last_run_finished_at": (_NOW - timedelta(hours=5)).isoformat(),
        },
        {
            "phase": "cortex",
            "last_run_finished_at": (_NOW - timedelta(days=30)).isoformat(),
        },
        {"phase": "talents", "last_run_finished_at": None},
    ]
    stale = annotate_freshness(states, _NOW)
    assert stale == ["users"]
    by_phase = {s["phase"]: s for s in states}
    assert by_phase["users"]["freshness"] == "stale"
    assert by_phase["clients"]["freshness"] == "fresh"
    assert by_phase["cortex"]["freshness"] == "advisory"
    assert by_phase["talents"]["freshness"] == "never"
    assert by_phase["users"]["stale_after_hours"] == 36
    assert by_phase["cortex"]["stale_after_hours"] == 36


# ── endpoint (na bazie) ─────────────────────────────────────────────────────


async def _upsert_phase(phase: str, finished_at: datetime | None, status: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO traffit_sync_state (phase, last_run_finished_at, "
                "last_status, created_at, updated_at) "
                "VALUES (:phase, :finished_at, :status, NOW(), NOW()) "
                "ON CONFLICT (phase) DO UPDATE SET "
                "last_run_finished_at = EXCLUDED.last_run_finished_at, "
                "last_status = EXCLUDED.last_status, updated_at = NOW()"
            ),
            {"phase": phase, "finished_at": finished_at, "status": status},
        )
        await db.commit()


async def _delete_phases(*phases: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM traffit_sync_state WHERE phase = ANY(:phases)"),
            {"phases": list(phases)},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_status_endpoint_reports_freshness_per_phase(
    app_client, app_auth_headers
):
    now = datetime.now(timezone.utc)
    await _upsert_phase("candidate_sources", now - timedelta(days=3), "ok")
    await _upsert_phase("contacts", now - timedelta(hours=2), "ok")
    await _upsert_phase("candidates_cv_fields", now - timedelta(days=10), "ok")
    try:
        resp = await app_client.get(
            "/api/admin/traffit/sync/status", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        by_phase = {s["phase"]: s for s in body["states"]}
        assert by_phase["candidate_sources"]["freshness"] == "stale"
        assert by_phase["contacts"]["freshness"] == "fresh"
        assert by_phase["candidates_cv_fields"]["freshness"] == "advisory"
        assert "candidate_sources" in body["phases_stale"]
        assert "candidates_cv_fields" not in body["phases_stale"]
        assert "contacts" not in body["phases_stale"]
    finally:
        await _delete_phases("candidate_sources", "contacts", "candidates_cv_fields")
