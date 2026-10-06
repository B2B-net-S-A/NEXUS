"""Raport „Propozycje AI” — co zespół zrobił z propozycjami (30.09.2026).

Do 30.09.2026 żadna z 57 nocnych propozycji nie miała decyzji, więc nie było
wiadomo, czy propozycje są złe, czy niewidziane. Raport liczy, ile osób
zaproponowano, ile dodano, ile pominięto (z powodem z 0405) i ile czeka.

Jednostki są dwie i to jest świadome:

- ``totals`` i wiersze rekrutacji liczą OSOBY (para rekrutacja × kandydat) —
  ta sama osoba z przeglądu bazy i z nowego CV to jedna decyzja rekrutera;
- ``by_source`` liczy WIERSZE skrzynki per źródło — tylko tak widać, które
  źródło proponuje ludzi, których nikt nie bierze. Suma źródeł bywa więc
  większa niż ``totals``.

Okno: ``first_seen_at`` od północy (Europe/Warsaw) ``days`` dni temu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, local_day_start_utc
from app.models.job import Job
from app.models.job_proposal import JobProposal
from app.services.job_proposal_feedback_schema import DISMISS_REASONS
from app.services.job_working_title import job_display_title_expr

# Pominięcie sprzed 0405 (bez powodu) — osobny kubełek, nigdy „inne”.
NO_REASON = "unknown"
REASON_KEYS = (*DISMISS_REASONS, NO_REASON)
MAX_DAYS = 90


@dataclass(frozen=True)
class ProposalRow:
    job_id: int
    title: Optional[str]
    candidate_id: int
    source: str
    status: str
    dismiss_reason: Optional[str]


def _empty_counts() -> dict:
    return {
        "proposed": 0,
        "added": 0,
        "dismissed": 0,
        "pending": 0,
        # 0422: propozycje zamkniętej rekrutacji — bez decyzji, ale już nie czekają.
        "expired": 0,
        "dismissed_by_reason": {key: 0 for key in REASON_KEYS},
    }


def _bump(counts: dict, status: str, reason: Optional[str]) -> None:
    counts["proposed"] += 1
    if status == "added":
        counts["added"] += 1
    elif status == "dismissed":
        counts["dismissed"] += 1
        key = reason if reason in DISMISS_REASONS else NO_REASON
        counts["dismissed_by_reason"][key] += 1
    elif status == "expired":
        counts["expired"] += 1
    else:
        counts["pending"] += 1


def _pair_status(rows: list[ProposalRow]) -> tuple[str, Optional[str]]:
    """Decyzja o OSOBIE: dodana > czeka > pominięta (powód z pominiętego
    wiersza) > wygasła (0422 — zamknięcie rekrutacji, nikt nie zdecydował)."""
    statuses = {r.status for r in rows}
    if "added" in statuses:
        return "added", None
    if "proposed" in statuses:
        return "proposed", None
    if "dismissed" not in statuses:
        return "expired", None
    reason = next((r.dismiss_reason for r in rows if r.dismiss_reason), None)
    return "dismissed", reason


def summarize(rows: Iterable[ProposalRow]) -> dict:
    """Czysta agregacja — testowana bez bazy."""
    by_source: dict[str, dict] = {}
    pairs: dict[tuple[int, int], list[ProposalRow]] = {}
    titles: dict[int, Optional[str]] = {}
    for row in rows:
        _bump(
            by_source.setdefault(row.source, _empty_counts()),
            row.status,
            row.dismiss_reason,
        )
        pairs.setdefault((row.job_id, row.candidate_id), []).append(row)
        titles.setdefault(row.job_id, row.title)

    totals = _empty_counts()
    per_job: dict[int, dict] = {}
    for (job_id, _cid), pair_rows in pairs.items():
        status, reason = _pair_status(pair_rows)
        _bump(totals, status, reason)
        _bump(per_job.setdefault(job_id, _empty_counts()), status, reason)

    jobs = [
        {"job_id": job_id, "title": titles.get(job_id), **counts}
        for job_id, counts in per_job.items()
    ]
    # Najpierw rekrutacje z największą liczbą propozycji bez decyzji.
    jobs.sort(key=lambda j: (-j["pending"], -j["proposed"], j["job_id"]))
    return {
        "totals": totals,
        "by_source": [
            {"source": source, **counts}
            for source, counts in sorted(
                by_source.items(), key=lambda item: (-item[1]["proposed"], item[0])
            )
        ],
        "jobs": jobs,
    }


def window_start(now: datetime, days: int) -> datetime:
    """Północ (Europe/Warsaw) ``days - 1`` dni przed dniem ``now`` — okno obejmuje dziś."""
    local_day = now.astimezone(ZoneInfo(DEFAULT_TZ)).date()
    return local_day_start_utc(local_day - timedelta(days=max(days, 1) - 1))


async def load_rows(
    db: AsyncSession,
    *,
    since: datetime,
    delivery_lead_id: Optional[int] = None,
    client_ids: Optional[frozenset[int]] = None,
) -> list[ProposalRow]:
    """Wiersze skrzynki z okna. ``delivery_lead_id`` zawęża do rekrutacji DL-a
    (jego rekrutacje ALBO klienci z portfela ``client_ids``)."""
    stmt = (
        select(
            JobProposal.job_id,
            job_display_title_expr(),
            JobProposal.candidate_id,
            JobProposal.source,
            JobProposal.status,
            JobProposal.dismiss_reason,
        )
        .join(Job, Job.id == JobProposal.job_id)
        .where(JobProposal.first_seen_at >= since)
    )
    if delivery_lead_id is not None:
        own = Job.delivery_lead_id == delivery_lead_id
        if client_ids:
            own = own | Job.client_id.in_(sorted(client_ids))
        stmt = stmt.where(own)
    return [ProposalRow(*row) for row in (await db.execute(stmt)).all()]
