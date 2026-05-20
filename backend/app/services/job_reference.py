"""Human-readable reference numbers for jobs (Traffit parity follow-up).

Generates a stable, quotable reference like ``BP/007/2026`` on job creation
so recruiters can reference an opening in emails / phone calls without
pasting a database id. Format:

    {CLIENT_INITIALS}/{SEQ:03d}/{YEAR}

- CLIENT_INITIALS — derived from the client name (see ``client_initials``).
  Falls back to ``NXS`` for client-less jobs.
- SEQ — per-(initials, year) running counter, zero-padded to 3 digits.
  Computed as max(existing seq for this prefix+year) + 1, so deleting a
  job never causes the next number to collide.
- YEAR — the year the job was created.

The ``jobs.reference_number`` column has a UNIQUE constraint; the bounded
availability loop here makes a same-transaction collision impossible, and
the DB constraint is the final backstop against a concurrent double-create
(rare for an internal recruiting tool — the caller surfaces a retryable
error in that case).
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job import Job

_FALLBACK_INITIALS = "NXS"
_MAX_INITIALS_LEN = 4
# Upper bound on the availability probe loop. With max+1 seeding we expect to
# succeed on the first try; the loop only spins on deletion-gap edge cases.
_MAX_SEQ_PROBES = 50


def client_initials(client_name: Optional[str]) -> str:
    """Derive an uppercase initials prefix from a client name.

    Rules:
    - No / blank name → ``NXS`` (Nexus internal fallback).
    - Single word → first 4 alphanumerics, uppercased ("ATOS" → "ATOS",
      "Allegro" → "ALLE").
    - Multiple words → first alphanumeric char of each word, max 4
      ("Bank Pocztowy" → "BP", "Roche - Square One" → "RSO").
    """
    if not client_name or not client_name.strip():
        return _FALLBACK_INITIALS
    words = [w for w in re.split(r"\s+", client_name.strip()) if w]
    if len(words) == 1:
        letters = re.sub(r"[^A-Za-z0-9]", "", words[0]).upper()
        return letters[:_MAX_INITIALS_LEN] or _FALLBACK_INITIALS
    initials = "".join(
        re.sub(r"[^A-Za-z0-9]", "", w)[:1] for w in words
    ).upper()
    return initials[:_MAX_INITIALS_LEN] or _FALLBACK_INITIALS


def format_reference(initials: str, seq: int, year: int) -> str:
    """Compose the final reference string, e.g. ``BP/007/2026``."""
    return f"{initials}/{seq:03d}/{year}"


def _parse_seq(reference: Optional[str]) -> Optional[int]:
    """Extract the numeric SEQ from a reference like ``BP/007/2026`` → 7.

    Returns None when the reference doesn't match our 3-segment shape — so
    Traffit-imported refs (e.g. ``71/5/2026/AT/4537``) are ignored when
    seeding the next sequence, which is correct: our generated namespace is
    separate from the imported one.
    """
    if not reference:
        return None
    parts = reference.split("/")
    if len(parts) == 3 and parts[1].isdigit():
        return int(parts[1])
    return None


async def generate_job_reference_number(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    year: int,
) -> str:
    """Compute the next free reference number for a job.

    Reads committed jobs sharing the same ``{initials}/%/{year}`` prefix,
    takes max(seq)+1, then probes upward until the candidate is free (guards
    against any pattern edge cases). The UNIQUE constraint on
    ``jobs.reference_number`` is the final guarantee under concurrency.
    """
    name: Optional[str] = None
    if client_id is not None:
        name = await db.scalar(select(Client.name).where(Client.id == client_id))
    initials = client_initials(name)

    pattern = f"{initials}/%/{year}"
    existing_refs = (
        await db.execute(
            select(Job.reference_number).where(Job.reference_number.like(pattern))
        )
    ).scalars().all()

    used_seqs = {
        seq for seq in (_parse_seq(ref) for ref in existing_refs) if seq is not None
    }
    seq = (max(used_seqs) + 1) if used_seqs else 1

    # Defensive upward probe — with max+1 seeding the first candidate is
    # already free, but this keeps us correct if the data ever contains a
    # surprising shape.
    for _ in range(_MAX_SEQ_PROBES):
        if seq not in used_seqs:
            return format_reference(initials, seq, year)
        seq += 1
    # Exhausted the probe window (pathological) — fall back to a value past
    # the max so the UNIQUE constraint still protects us.
    return format_reference(initials, (max(used_seqs) + 1) if used_seqs else 1, year)
