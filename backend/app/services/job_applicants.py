"""Kto aplikował na ogłoszenie tej rekrutacji — i gdzie jeszcze (07.11.2026).

Decyzja Artura z 07.11.2026 (makiety https://claude.ai/artifact/JMTL5qwBym7Twd2dU1uYsb,
rekomendacje 6–7): „Nowi” pokazują głównie pasujących, ale każdy, kto chce,
widzi pełną listę aplikujących na ogłoszenie. Propozycja w innej rekrutacji
mówi, na co osoba aplikowała.

Zgłoszenie = zdarzenie źródła z ``job_id`` na kanale ogłoszenia: strona
kariery i przekierowanie z portalu zapisują ``career_link_job``
(``public_apply``), formularz portalu ``posting`` (``portal_application``).
Starsze aplikacje z JJIT (przed 06.11.2026) nie mają ``job_id``, więc ich tu
nie ma.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.job import Job, JobStatus
from app.models.job_proposal import JobProposal
from app.models.recruitment_pipeline import CandidateStage

APPLICATION_CHANNELS = (SourceChannel.posting, SourceChannel.career_link_job)
LOOKBACK = timedelta(days=90)
LIST_LIMIT = 300
ALSO_FITS_PER_PERSON = 3

_CHANNEL_LABELS = {
    "jjit": "JustJoin.IT",
    "justjoinit": "JustJoin.IT",
    "rocketjobs": "RocketJobs",
    "pracuj": "Pracuj.pl",
}


def channel_label(channel: SourceChannel, utm_source: Optional[str]) -> str:
    """„JustJoin.IT”, „Pracuj.pl”, „Strona kariery” — po polsku, dla wiersza."""
    portal = _CHANNEL_LABELS.get((utm_source or "").strip().lower())
    if portal:
        return portal
    return (
        "Strona kariery" if channel == SourceChannel.career_link_job else "Ogłoszenie"
    )


@dataclass(frozen=True)
class AppliedTo:
    job_id: int
    title: str
    applied_at: datetime


async def applied_elsewhere(
    db: AsyncSession, candidate_ids: list[int], *, exclude_job_id: int
) -> dict[int, list[AppliedTo]]:
    """Na jakie INNE rekrutacje osoby aplikowały w ostatnich 90 dniach."""
    if not candidate_ids:
        return {}
    since = datetime.now(timezone.utc) - LOOKBACK
    rows = (
        await db.execute(
            select(
                CandidateSourceEvent.candidate_id,
                CandidateSourceEvent.job_id,
                Job.title,
                func.max(CandidateSourceEvent.captured_at),
            )
            .join(Job, Job.id == CandidateSourceEvent.job_id)
            .where(
                CandidateSourceEvent.candidate_id.in_(candidate_ids),
                CandidateSourceEvent.job_id.is_not(None),
                CandidateSourceEvent.job_id != exclude_job_id,
                CandidateSourceEvent.channel.in_(APPLICATION_CHANNELS),
                CandidateSourceEvent.captured_at >= since,
            )
            .group_by(
                CandidateSourceEvent.candidate_id,
                CandidateSourceEvent.job_id,
                Job.title,
            )
        )
    ).all()
    out: dict[int, list[AppliedTo]] = {}
    for cid, job_id, title, at in rows:
        out.setdefault(int(cid), []).append(
            AppliedTo(
                job_id=int(job_id), title=title or f"Rekrutacja {job_id}", applied_at=at
            )
        )
    for items in out.values():
        items.sort(key=lambda a: a.applied_at, reverse=True)
    return out


async def list_applicants(db: AsyncSession, job: Job) -> list[dict]:
    """Wszyscy aplikujący na ogłoszenie tej rekrutacji, od najmłodszego zgłoszenia.

    Wiersz: osoba, kanał, data, gdzie jest teraz w tej rekrutacji i do jakich
    innych otwartych rekrutacji ma propozycję (``job_proposals`` ze statusem
    ``proposed``). Bez kontaktu — tożsamość jak w skrzynce propozycji.
    """
    since = datetime.now(timezone.utc) - LOOKBACK
    events = (
        await db.execute(
            select(
                CandidateSourceEvent.candidate_id,
                CandidateSourceEvent.channel,
                CandidateSourceEvent.utm_source,
                CandidateSourceEvent.captured_at,
            )
            .where(
                CandidateSourceEvent.job_id == job.id,
                CandidateSourceEvent.channel.in_(APPLICATION_CHANNELS),
                CandidateSourceEvent.captured_at >= since,
            )
            .order_by(CandidateSourceEvent.captured_at.desc())
        )
    ).all()
    first: dict[int, tuple] = {}
    for cid, channel, utm, at in events:
        first.setdefault(int(cid), (channel, utm, at))
    ids = list(first)[:LIST_LIMIT]
    if not ids:
        return []
    people = {
        c.id: c
        for c in (
            await db.execute(select(Candidate).where(Candidate.id.in_(ids)))
        ).scalars()
    }
    stages = {
        int(cid): stage
        for cid, stage in (
            await db.execute(
                select(CandidateStage.candidate_id, CandidateStage.stage).where(
                    CandidateStage.job_id == job.id,
                    CandidateStage.candidate_id.in_(ids),
                )
            )
        ).all()
    }
    proposals = (
        await db.execute(
            select(
                JobProposal.candidate_id,
                JobProposal.job_id,
                Job.title,
                JobProposal.score,
            )
            .join(Job, Job.id == JobProposal.job_id)
            .where(
                JobProposal.candidate_id.in_(ids),
                JobProposal.job_id != job.id,
                JobProposal.status == "proposed",
                Job.status == JobStatus.published,
            )
            .order_by(JobProposal.score.desc().nulls_last())
        )
    ).all()
    also: dict[int, list[dict]] = {}
    for cid, job_id, title, score in proposals:
        items = also.setdefault(int(cid), [])
        if len(items) < ALSO_FITS_PER_PERSON and all(
            i["job_id"] != job_id for i in items
        ):
            items.append(
                {
                    "job_id": int(job_id),
                    "title": title,
                    "score": float(score) if score is not None else None,
                }
            )
    rows = []
    for cid in ids:
        person = people.get(cid)
        if person is None:
            continue
        channel, utm, at = first[cid]
        stage = stages.get(cid)
        rows.append(
            {
                "candidate_id": cid,
                "name": f"{person.name or ''} {person.lastname or ''}".strip() or None,
                "channel": channel_label(channel, utm),
                "applied_at": at.isoformat() if at else None,
                "stage": getattr(stage, "value", stage),
                "in_job": stage is not None,
                "also_fits": also.get(cid, []),
            }
        )
    return rows
