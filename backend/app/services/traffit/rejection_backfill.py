"""Backfill `candidate_stages.rejection_note` from imported Traffit activities.

Background
----------
Traffit stored the *reason* a candidate was rejected (e.g. "Po CV",
"Po Interview", "Rezygnacja przez Kandydata", "Rezygnacja przez Klienta") on
the stage-change event, NOT on the recruitment_history record. During the
migration:

* `recruitment_history` → ``candidate_stages`` (carries job + stage + moved_at,
  but the payload has **no** rejection reason).
* `/employees/activities` → ``activities`` (the "Zmiana etapu" activity holds
  ``details.content.rejection.name`` — the actual reason).

So every rejected ``candidate_stages`` row landed with ``rejection_note = NULL``
and the candidates list could only show a bare "Odrzucony · job (client)".

This helper joins the two sources back together. The importer sets
``candidate_stages.moved_at`` to the Traffit ``activity_date`` verbatim, so a
rejected stage and its reason-bearing activity share an **exact** timestamp for
the same candidate — that (candidate_id, moved_at) pair is the join key.

Properties
----------
* **Idempotent** — only fills rows where ``rejection_note`` is currently empty;
  re-running is a no-op for already-populated rows. Reason text entered by a
  recruiter in NEXUS is never overwritten.
* **Read-of-activities / write-of-stages only** — additive; the original value
  was NULL.
* Caller owns the transaction (commit / rollback), mirroring the other
  ``scripts/backfill_*.py`` helpers — this lets the CLI offer ``--dry-run``.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Single idempotent UPDATE. The reason lives in `activities.details.content`
# which is a JSON-encoded *string* (double-encoded), hence the `->>'content'`
# then `::jsonb` re-parse. We dedupe to one reason per (candidate, timestamp)
# via DISTINCT ON so a target stage row joins to exactly one source row.
_BACKFILL_SQL = text(
    """
    UPDATE candidate_stages AS cs
    SET rejection_note = rej.reason,
        updated_at = NOW()
    FROM (
        SELECT DISTINCT ON (a.entity_id, (a.details ->> 'activity_date')::timestamp)
            a.entity_id AS candidate_id,
            ((a.details ->> 'activity_date')::timestamp AT TIME ZONE 'UTC') AS ts,
            (((a.details ->> 'content')::jsonb) -> 'rejection' ->> 'name') AS reason
        FROM activities AS a
        WHERE a.entity_type = 'candidate'
          AND a.action = 'traffit:Zmiana etapu'
          -- content is a JSON-encoded object string; guard the ::jsonb cast
          AND left(a.details ->> 'content', 1) = '{'
          -- jsonb_exists() rather than the `?` operator: `?` trips up some
          -- DBAPI param styles, the function form is unambiguous.
          AND jsonb_exists((a.details ->> 'content')::jsonb, 'rejection')
          AND (((a.details ->> 'content')::jsonb) -> 'rejection' ->> 'name') IS NOT NULL
          AND a.details ->> 'activity_date' IS NOT NULL
        ORDER BY
            a.entity_id,
            (a.details ->> 'activity_date')::timestamp,
            a.id DESC
    ) AS rej
    WHERE cs.candidate_id = rej.candidate_id
      AND cs.moved_at = rej.ts
      AND cs.stage = 'rejected'
      AND (cs.rejection_note IS NULL OR btrim(cs.rejection_note) = '')
    """
)


async def backfill_rejection_notes_from_activities(db: AsyncSession) -> int:
    """Populate empty ``rejection_note`` on rejected stages from Traffit
    activity reasons. Returns the number of rows updated.

    The caller is responsible for committing (or rolling back, for a dry-run).
    """
    result = await db.execute(_BACKFILL_SQL)
    return result.rowcount or 0
