"""Jednorazowo: powód z treści maila dla starych odrzuceń z CPro (B7, 19.11.2026).

Od 02.11 automat poczty CPro wpisywał każde odrzucenie przez klienta jako
„Inne (rejected)”, z tekstem klienta w notatce „Z CPro: …”. Na produkcji to
108 wpisów (stan z 19.11). Decyzja Artura z 19.11.2026: przepiąć je tym samym
słownikiem, który od tego wdrożenia wybiera powód dla nowych maili
(`cpro_reason_map`), żeby Insights i weto hiring managera widziały prawdziwe
powody także wstecz. Weto działa jak przy ręcznym odrzuceniu (decyzja Artura).

Zmienia się tylko ``rejection_reason_id``; notatka zostaje. Tekst bez trafienia
i szablon bez powodu ze słownika zostają przy „Inne”. Paragon pod kluczem
``REPAIR_MARKER``: liczniki i trójki ``[id wiersza, stary powód, nowy powód]``,
z których da się cofnąć zmianę. Bez treści notatek i nazwisk.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.recruitment_pipeline import CandidateStage
from app.services.cpro_reason_map import reason_name_for

logger = logging.getLogger(__name__)

REPAIR_MARKER = "cpro_rejection_reason_repair_2026_11_19"

_CANDIDATES = text(
    """
    SELECT cs.id, cs.rejection_reason_id, rr.template_id, cs.notes
    FROM candidate_stages cs
    JOIN rejection_reasons rr ON rr.id = cs.rejection_reason_id
    WHERE cs.stage::text = 'rejected'
      AND cs.ended_by = 'client'
      AND rr.category::text = 'rejected'
      AND rr.name = 'Inne (rejected)'
      AND cs.notes LIKE 'Z CPro%'
    ORDER BY cs.id
    FOR UPDATE OF cs
    """
)

_TEMPLATE_REASONS = text(
    """
    SELECT template_id, name, id FROM rejection_reasons
    WHERE category::text = 'rejected' AND template_id = ANY(:templates)
    """
)


async def run_cpro_rejection_reason_repair(
    db: AsyncSession, *, marker: str = REPAIR_MARKER
) -> Optional[dict[str, Any]]:
    """Przepnij powody; ``None`` = już wykonane. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = (await db.execute(_CANDIDATES)).all()
    templates = sorted({row.template_id for row in rows})
    reason_ids: dict[tuple[int, str], int] = {}
    if templates:
        for template_id, name, reason_id in (
            await db.execute(_TEMPLATE_REASONS, {"templates": templates})
        ).all():
            reason_ids[(template_id, name)] = reason_id

    moved: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    receipt: list[list[int]] = []
    for row in rows:
        name = reason_name_for(row.notes)
        if name is None:
            kept["no_match"] += 1
            continue
        new_id = reason_ids.get((row.template_id, name))
        if new_id is None:
            kept["not_in_template"] += 1
            continue
        # Przez ORM, nie surowym SQL-em (strażnik
        # `test_priority_work_writer_architecture`); powód nie jest polem
        # cyklu życia procesu, więc nie idzie przez `recruitment_process_commands`.
        stage = await db.get(CandidateStage, row.id)
        if stage is None or stage.rejection_reason_id != row.rejection_reason_id:
            kept["changed_meanwhile"] += 1
            continue
        stage.rejection_reason_id = new_id
        moved[name] += 1
        receipt.append([row.id, row.rejection_reason_id, new_id])

    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "scanned": len(rows),
        "moved": dict(sorted(moved.items())),
        "kept_other": dict(sorted(kept.items())),
        "rows": receipt,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("cpro rejection reason repair: %s/%s moved", len(receipt), len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    moved = ", ".join(f"{name}={n}" for name, n in summary["moved"].items())
    kept = ", ".join(f"{why}={n}" for why, n in summary["kept_other"].items())
    return (
        f"moved {len(summary['rows'])}/{summary['scanned']}"
        + (f" ({moved})" if moved else "")
        + (f"; kept as other: {kept}" if kept else "")
    )
