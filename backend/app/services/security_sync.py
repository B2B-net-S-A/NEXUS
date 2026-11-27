"""Źródło, które NEXUS czyta sam (0800): biegi ``security-weekly.yml``.

* GitHub Actions: lista ukończonych biegów workflow z publicznego API (token
  opcjonalny, tylko dla limitu 5000/h zamiast 60/h). Każdy bieg zostaje
  zdarzeniem (``ref`` = id biegu, więc ponowny odczyt nic nie dubluje),
  ostatni wynik idzie do ``security_source_states`` (kafelek i tabela źródeł),
  a rutyna z ``auto_source = 'ci'`` odhacza się sama. Do tego wynik jobów
  ostatniego biegu (Semgrep, audyt zależności, zizmor, Trivy obrazów) — same
  nazwy i wyniki, bo treść znalezisk przychodzi przez DefectDojo.

DefectDojo stoi za WireGuardem (decyzja Artura 27.11.2026), więc NEXUS go nie
czyta: serwer bezpieczeństwa wypycha znaleziska webhookiem (``run_id``
i ``complete`` w ostatniej paczce).

Błąd zapisuje krótki opis (klasa, status HTTP) — nigdy treści odpowiedzi
ani tokenu.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_date
from app.models.security import SecurityRoutine, SecuritySourceState
from app.services.security_ingest import IngestEvent, store_events
from app.services.security_screen import mark_routine_done

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0)
_RUN_LABEL = {"success": "zielony", "failure": "czerwony", "cancelled": "przerwany"}


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _state(db: AsyncSession, source: str) -> SecuritySourceState:
    state = await db.get(SecuritySourceState, source)
    if state is None:
        state = SecuritySourceState(source=source, detail={})
        db.add(state)
    return state


def _error_label(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__[:300]


def runs_to_events(runs: list[dict[str, Any]]) -> list[IngestEvent]:
    events = []
    for run in runs:
        started = _parse_time(run.get("run_started_at") or run.get("created_at"))
        if started is None or run.get("status") != "completed":
            continue
        conclusion = run.get("conclusion") or "unknown"
        label = _RUN_LABEL.get(conclusion, conclusion)
        trigger = "z harmonogramu" if run.get("event") == "schedule" else "ręcznie"
        events.append(
            IngestEvent(
                occurred_at=started,
                kind="ci_run",
                severity="info" if conclusion == "success" else "high",
                summary=f"Tygodniowy skan {label} ({trigger}), bieg #{run.get('run_number')}",
                ref=f"gh:run:{run['id']}",
            )
        )
    return events


def run_done_on(started: datetime) -> date:
    """Dzień wykonania rutyny = dzień kalendarza firmy, nie data z UTC."""
    return business_date(started)


async def _run_jobs(
    client: httpx.AsyncClient, run: dict[str, Any], headers: dict[str, str]
) -> list[dict[str, Optional[str]]]:
    """Nazwy i wyniki jobów biegu; błąd = pusta lista (bieg i tak jest znany)."""
    url = run.get("jobs_url")
    prefix = f"https://api.github.com/repos/{settings.SECURITY_GITHUB_REPO}/"
    if not isinstance(url, str) or not url.startswith(prefix):
        return []
    try:
        response = await client.get(url, params={"per_page": 50}, headers=headers)
        response.raise_for_status()
        jobs = response.json().get("jobs") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("security_sync: github jobs failed (%s)", _error_label(exc))
        return []
    return [
        {"name": str(j.get("name", ""))[:80], "conclusion": j.get("conclusion")}
        for j in jobs[:30]
    ]


async def sync_github_runs(db: AsyncSession, client: httpx.AsyncClient) -> None:
    state = await _state(db, "ci")
    state.last_run_at = datetime.now(timezone.utc)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.SECURITY_GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.SECURITY_GITHUB_TOKEN}"
    url = (
        f"https://api.github.com/repos/{settings.SECURITY_GITHUB_REPO}/actions/workflows/"
        f"{settings.SECURITY_GITHUB_WORKFLOW}/runs"
    )
    try:
        response = await client.get(
            url, params={"per_page": 10, "status": "completed"}, headers=headers
        )
        response.raise_for_status()
        runs = response.json().get("workflow_runs") or []
    except Exception as exc:  # noqa: BLE001 — stan źródła mówi o błędzie, pętla żyje
        state.last_error = _error_label(exc)
        logger.warning("security_sync: github runs failed (%s)", state.last_error)
        return
    events = runs_to_events(runs)
    links = {f"gh:run:{r['id']}": r.get("html_url") for r in runs if r.get("html_url")}
    await store_events(db, "ci", events, links=links)
    state.last_error = None
    state.last_ok_at = datetime.now(timezone.utc)
    completed = [r for r in runs if r.get("status") == "completed"]
    if not completed:
        return
    latest = completed[0]
    state.detail = {
        "conclusion": latest.get("conclusion"),
        "run_started_at": latest.get("run_started_at") or latest.get("created_at"),
        "html_url": latest.get("html_url"),
        "run_number": latest.get("run_number"),
        "jobs": await _run_jobs(client, latest, headers),
    }
    started = _parse_time(state.detail["run_started_at"])
    if started is None:
        return
    done_on = run_done_on(started)
    for routine in await db.scalars(
        select(SecurityRoutine).where(SecurityRoutine.auto_source == "ci")
    ):
        if routine.last_done_on is None or routine.last_done_on < done_on:
            mark_routine_done(
                routine, done_on, note=f"bieg #{latest.get('run_number')}"
            )


async def sync_all(db: AsyncSession) -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        await sync_github_runs(db, client)
        await db.commit()
