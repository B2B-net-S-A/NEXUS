"""Migawki szkicu CV etapu (Edytor CV 3, PR 5, migracja 0444).

Podmiana szkicu nową generacją zapisuje najpierw migawkę dotychczasowego
szkicu — „Wróć do poprzedniej” wraca do niej. Powrót też robi migawkę
(``restore``), więc nic nie ginie, ale przycisk przywraca tylko szkice
sprzed podmiany (``replaced``), od najnowszego.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_stage_draft_snapshot import CvStageDraftSnapshot


def snapshot_draft(
    db: AsyncSession,
    csv: CandidateStageCV,
    *,
    user_id: Optional[int],
    reason: Literal["replaced", "restore"],
) -> Optional[CvStageDraftSnapshot]:
    """Migawka bieżącego szkicu; ``None``, gdy etap nie ma jeszcze treści. Bez commitu."""
    if not (csv.branded_draft_html or "").strip():
        return None
    snapshot = CvStageDraftSnapshot(
        candidate_stage_cv_id=csv.id,
        content_html=csv.branded_draft_html,
        generated_document_id=csv.generated_document_id,
        branded_from_generator=bool(csv.branded_from_generator),
        render_metadata=copy.deepcopy(csv.branded_render_metadata),
        edit_revision=csv.edit_revision or 0,
        reason=reason,
        created_by=user_id,
    )
    db.add(snapshot)
    return snapshot


async def latest_restorable(
    db: AsyncSession, csv_id: int
) -> Optional[CvStageDraftSnapshot]:
    """Najnowszy szkic sprzed podmiany, do którego jeszcze nie wrócono."""
    return await db.scalar(
        select(CvStageDraftSnapshot)
        .where(
            CvStageDraftSnapshot.candidate_stage_cv_id == csv_id,
            CvStageDraftSnapshot.reason == "replaced",
            CvStageDraftSnapshot.restored_at.is_(None),
        )
        .order_by(CvStageDraftSnapshot.id.desc())
        .limit(1)
    )


def mark_restored(snapshot: CvStageDraftSnapshot, *, user_id: Optional[int]) -> None:
    snapshot.restored_at = datetime.now(timezone.utc)
    snapshot.restored_by = user_id
