"""Jednorazowa korekta „dodanych” propozycji z kart integracji (07.10.2026).

Do 07.10.2026 każde dodanie do rekrutacji — także karta założona przez
integrację (scraper portali, proces ``entry_source='auto_match'``) — oznaczało
propozycje pary jako ``added``. Na produkcji 16 propozycji nocnego przeglądu
bazy (``full_base``) stało przez to jako „dodane”, choć nikt z zespołu ich nie
dodał. Od tego dnia ``added`` stawia wyłącznie dodanie przez człowieka
(``proposals_bulk.add_candidates_to_job(mark_proposals=True)``).

Korekta: pary z propozycją ``full_base`` w statusie ``added``, których KAŻDY
proces w tej rekrutacji pochodzi z integracji, wracają do ``proposed`` — razem
ze wszystkimi wierszami ``added`` tej pary (status liczy się per para:
``added`` wygrywa, więc sam wiersz ``full_base`` nic by nie zmienił). Osoba,
która nadal jest w pipeline'ie, i tak nie pokaże się w skrzynce.

Warunek SQL, nie lista ID. Marker w ``app_settings`` + advisory lock: drugi
start kończy się od razu. Paragon niesie wyłącznie liczby i ID.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

REPAIR_MARKER = "proposal_added_from_integration_2026_10"

_PAIRS_SQL = text(
    """
    SELECT DISTINCT p.job_id, p.candidate_id
      FROM job_proposals p
     WHERE p.source = 'full_base'
       AND p.status = 'added'
       AND EXISTS (
           SELECT 1 FROM recruitment_processes rp
            WHERE rp.job_id = p.job_id AND rp.candidate_id = p.candidate_id
       )
       AND NOT EXISTS (
           SELECT 1 FROM recruitment_processes rp
            WHERE rp.job_id = p.job_id AND rp.candidate_id = p.candidate_id
              AND rp.entry_source IS DISTINCT FROM 'auto_match'
       )
     ORDER BY p.job_id, p.candidate_id
    """
)

_REVERT_SQL = text(
    """
    UPDATE job_proposals SET status = 'proposed'
     WHERE job_id = :job_id AND candidate_id = :candidate_id
       AND status = 'added'
    RETURNING id
    """
)


async def run_proposal_added_repair(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Cofa ``added`` z kart integracji. ``None`` = już wykonane. Wołający commituje."""
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None
    pairs = [(int(j), int(c)) for j, c in (await db.execute(_PAIRS_SQL)).all()]
    row_ids: list[int] = []
    for job_id, candidate_id in pairs:
        row_ids.extend(
            int(rid)
            for rid in (
                await db.execute(
                    _REVERT_SQL, {"job_id": job_id, "candidate_id": candidate_id}
                )
            )
            .scalars()
            .all()
        )
    summary = {
        "done_at": now.isoformat(),
        "pairs": len(pairs),
        "rows": len(row_ids),
        "pair_ids": [[job_id, candidate_id] for job_id, candidate_id in pairs],
        "row_ids": sorted(row_ids),
    }
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    await db.flush()
    return summary


__all__ = ["REPAIR_MARKER", "run_proposal_added_repair"]
