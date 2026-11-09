"""Kto zweryfikował parę (kandydat, rekrutacja) — jedna reguła dla ekranów.

Weryfikujący to autor PIERWSZEGO wiersza „Zweryfikowany” pary, w kolejności
premii rekrutera (``hr.placement_bonuses.load_verifiers``): czas akceptacji
etapu, a bez niej czas ruchu, potem id. Wiersz bez autora (import) nikogo
nie wskazuje.

Najnowszy wiersz „Zweryfikowany” bywa cofnięciem karty z „QC CV” przez
Delivery Leada — to nie weryfikacja (zgłoszenie 21.10.2026: karta Tablicy
i przegląd DL pokazywały DL-a zamiast rekruterki, która zweryfikowała).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Optional, Protocol, TypeVar

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _StageRow(Protocol):
    id: int
    moved_by: Optional[int]
    moved_at: datetime
    approved_at: Optional[datetime]


Row = TypeVar("Row", bound=_StageRow)


def first_verifier(current: Optional[Row], row: Row) -> Optional[Row]:
    """Z dwóch wierszy „Zweryfikowany” ten, który wskazuje weryfikującego."""

    if row.moved_by is None:
        return current
    if current is None:
        return row
    return min(current, row, key=lambda r: (r.approved_at or r.moved_at, r.id))


async def verifier_ids(
    db: "AsyncSession", pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], int]:
    """Pierwszy weryfikujący per (kandydat, rekrutacja), hurtem."""
    from sqlalchemy import select, tuple_

    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    wanted = list(set(pairs))
    if not wanted:
        return {}
    rows = (
        await db.scalars(
            select(CandidateStage).where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
                CandidateStage.stage == PipelineStage.verified,
                CandidateStage.moved_by.isnot(None),
            )
        )
    ).all()
    chosen: dict[tuple[int, int], CandidateStage] = {}
    for row in rows:
        pair = (row.candidate_id, row.job_id)
        best = first_verifier(chosen.get(pair), row)
        if best is not None:
            chosen[pair] = best
    return {pair: row.moved_by for pair, row in chosen.items()}
