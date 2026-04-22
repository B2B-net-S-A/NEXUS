"""Fuzzy match a Fireflies meeting transcript to an open Nexus Job.

Why stdlib difflib instead of rapidfuzz:
  we consciously avoid adding a new runtime dep for a small score-and-rank
  routine that runs at most a few times per `fireflies_sync` tick. `difflib`'s
  token-set ratio approximation below is good enough for first-pass matching —
  the DL still confirms or rejects in the UI.

Scoring
-------
  score = 0.6 * title_ratio + 0.3 * client_ratio + 0.1 * domain_boost

Where:
  title_ratio:   difflib ratio between meeting title and job title
  client_ratio:  difflib ratio between meeting title and client name
  domain_boost:  1.0 if any participant email ends with the client's website
                 host (e.g. "@acme.com"), else 0.0

A hit is returned if score ≥ 0.6. Callers should treat 0.6–0.75 as "suggest,
don't auto-apply" and ≥ 0.75 as confident enough to auto-attach + enrich.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.job import Job, JobStatus

logger = logging.getLogger(__name__)


SCORE_MIN = 0.6
SCORE_AUTO = 0.75


@dataclass(frozen=True)
class MatchCandidate:
    job_id: int
    job_title: str
    client_name: str
    score: float


# ── Utilities ───────────────────────────────────────────────────────────────


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    # Lowercase + collapse non-alphanumeric runs to single space.
    return re.sub(r"[^a-z0-9ąćęłńóśźż]+", " ", s.lower()).strip()


def _token_set_ratio(a: str, b: str) -> float:
    """Approximate rapidfuzz `token_set_ratio` using stdlib difflib.

    Tokens are lowercased and set-compared; we compute SequenceMatcher on the
    sorted intersection vs. the full token set — closer to 1.0 when all tokens
    of the shorter string appear in the longer one, regardless of order.
    """
    ta = set(_norm(a).split())
    tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    # Full ratio on sorted joined tokens — cheap, stable, good enough.
    ja = " ".join(sorted(ta))
    jb = " ".join(sorted(tb))
    return SequenceMatcher(None, ja, jb).ratio()


def _email_domain(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1]


def _client_domain(client: Client) -> str:
    # Pull a plausible domain from `website` (http://x.com/...) if present.
    raw = (getattr(client, "website", None) or "").strip().lower()
    if not raw:
        return ""
    m = re.search(r"(?:https?://)?([^/]+)", raw)
    if not m:
        return ""
    host = m.group(1)
    return host.removeprefix("www.")


def _domain_boost(client: Client, participant_emails: Iterable[str]) -> float:
    cd = _client_domain(client)
    if not cd:
        return 0.0
    for email in participant_emails:
        d = _email_domain(email)
        if d and (d == cd or d.endswith("." + cd)):
            return 1.0
    return 0.0


# ── Public API ──────────────────────────────────────────────────────────────


async def match_meeting_to_jobs(
    db: AsyncSession,
    *,
    meeting_title: str,
    participant_emails: Iterable[str],
) -> List[MatchCandidate]:
    """Return ranked open-Job match candidates for a Fireflies meeting.

    Only jobs in status `draft` or `published` are considered (we don't
    re-match finished work).
    """
    emails = [e for e in (participant_emails or []) if e]

    result = await db.execute(
        select(Job)
        .where(Job.status.in_((JobStatus.draft, JobStatus.published)))
        .options(selectinload(Job.client))
    )
    jobs: List[Job] = list(result.scalars().all())

    hits: List[MatchCandidate] = []
    for job in jobs:
        client = job.client
        title_ratio = _token_set_ratio(meeting_title, job.title or "")
        client_ratio = 0.0
        if client and client.name:
            client_ratio = _token_set_ratio(meeting_title, client.name)
        boost = _domain_boost(client, emails) if client else 0.0

        score = 0.6 * title_ratio + 0.3 * client_ratio + 0.1 * boost
        if score >= SCORE_MIN:
            hits.append(
                MatchCandidate(
                    job_id=job.id,
                    job_title=job.title or "",
                    client_name=client.name if client and client.name else "",
                    score=round(score, 3),
                )
            )

    hits.sort(key=lambda c: c.score, reverse=True)
    if hits:
        logger.info(
            "fireflies_matcher: title=%r -> %d hit(s) (best=%.2f)",
            meeting_title,
            len(hits),
            hits[0].score,
        )
    return hits


__all__ = [
    "MatchCandidate",
    "SCORE_MIN",
    "SCORE_AUTO",
    "match_meeting_to_jobs",
]
