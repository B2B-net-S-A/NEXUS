"""Źródła, które NEXUS czyta sam (0799): biegi ``security-weekly.yml`` i DefectDojo.

* GitHub Actions: lista ukończonych biegów workflow z publicznego API (token
  opcjonalny, tylko dla limitu 5000/h zamiast 60/h). Każdy bieg zostaje
  zdarzeniem (``ref`` = id biegu, więc ponowny odczyt nic nie dubluje),
  ostatni wynik idzie do ``security_source_states`` (kafelek i tabela źródeł),
  a rutyna z ``auto_source = 'ci'`` odhacza się sama.
* DefectDojo: aktywne znaleziska przez API v2, gdy env ma URL i token. Brak
  konfiguracji to stan „nieskonfigurowane”, nie błąd. Lista jest pełna, więc
  znalezisko, którego DefectDojo już nie zwraca, zamyka się jako naprawione.

Błąd zapisuje krótki opis (klasa, status HTTP) — nigdy treści odpowiedzi
ani tokenu.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.security import SecurityRoutine, SecuritySourceState
from app.services.security_ingest import (
    IngestEvent,
    IngestFinding,
    store_events,
    upsert_findings,
)
from app.services.security_screen import mark_routine_done

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0)
DOJO_PAGE = 200
DOJO_MAX_PAGES = 10
_DOJO_SEVERITY = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
    "informational": "info",
}
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
    }
    started = _parse_time(state.detail["run_started_at"])
    if started is None:
        return
    done_on = started.astimezone(timezone.utc).date()
    for routine in await db.scalars(
        select(SecurityRoutine).where(SecurityRoutine.auto_source == "ci")
    ):
        if routine.last_done_on is None or routine.last_done_on < done_on:
            mark_routine_done(
                routine, done_on, note=f"bieg #{latest.get('run_number')}"
            )


def dojo_to_finding(item: dict[str, Any]) -> IngestFinding:
    where = item.get("file_path")
    if where and item.get("line"):
        where = f"{where}:{item['line']}"
    if not where and item.get("component_name"):
        version = item.get("component_version")
        where = (
            f"{item['component_name']} {version}" if version else item["component_name"]
        )
    steps = [
        line.strip(" -*\t")
        for line in (item.get("mitigation") or "").splitlines()
        if line.strip(" -*\t")
    ][:10]
    return IngestFinding(
        fingerprint=f"defectdojo:{item['id']}",
        severity=_DOJO_SEVERITY.get(str(item.get("severity", "")).lower(), "medium"),
        title=str(item.get("title") or f"Znalezisko {item['id']}")[:200],
        location=(where or None) and str(where)[:300],
        evidence=(item.get("description") or None) and str(item["description"])[:2000],
        impact=(item.get("impact") or None) and str(item["impact"])[:2000],
        steps=[s[:300] for s in steps],
        detected_at=_parse_time(item.get("date") + "T00:00:00+00:00")
        if item.get("date")
        else None,
    )


async def sync_defectdojo(db: AsyncSession, client: httpx.AsyncClient) -> None:
    if not (settings.DEFECTDOJO_URL and settings.DEFECTDOJO_API_TOKEN):
        return
    state = await _state(db, "defectdojo")
    state.last_run_at = datetime.now(timezone.utc)
    base = settings.DEFECTDOJO_URL.rstrip("/")
    headers = {
        "Authorization": f"Token {settings.DEFECTDOJO_API_TOKEN}",
        "Accept": "application/json",
    }
    findings: list[IngestFinding] = []
    url: Optional[str] = f"{base}/api/v2/findings/"
    params: Optional[dict[str, Any]] = {"active": "true", "limit": DOJO_PAGE}
    try:
        for _ in range(DOJO_MAX_PAGES):
            if not url:
                break
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            body = response.json()
            findings.extend(dojo_to_finding(item) for item in body.get("results") or [])
            url, params = body.get("next"), None
            # `next` musi zostać na tym samym serwerze — token nie wychodzi gdzie indziej.
            if url and not url.startswith(base + "/"):
                raise ValueError("next poza DEFECTDOJO_URL")
        complete = not url
    except Exception as exc:  # noqa: BLE001
        state.last_error = _error_label(exc)
        logger.warning("security_sync: defectdojo failed (%s)", state.last_error)
        return
    new, updated, closed = await upsert_findings(
        db, "defectdojo", findings, scanner="defectdojo", complete=complete
    )
    state.last_error = None
    state.last_ok_at = datetime.now(timezone.utc)
    state.detail = {
        "active": len(findings),
        "new": new,
        "updated": updated,
        "closed": closed,
    }


async def sync_all(db: AsyncSession) -> None:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        await sync_github_runs(db, client)
        await db.commit()
        await sync_defectdojo(db, client)
        await db.commit()
