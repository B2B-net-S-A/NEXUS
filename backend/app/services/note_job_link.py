"""Kiedy notatkę meetingową wolno podpiąć do rekrutacji (UAT M03-B13).

Jedna reguła dla obu wejść, które podpinają notatkę i karmią jej treścią
profil Championa: „Powiąż + AI” (`POST /api/notes/{id}/link-job`) i briefing
Delivery Leada (`POST /api/jobs/{id}/champion-profile/briefing`). Dwie kopie
rozjechały się już raz — briefing sprawdzał tylko inną rekrutację, więc
rozmowę z kandydatem innego klienta dało się przenieść do cudzego profilu
jednym wywołaniem API z odgadniętym numerem notatki.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage


async def ensure_note_linkable_to_job(
    db: AsyncSession, note: Note, job_id: int
) -> None:
    """422, gdy notatka należy do innej rekrutacji albo do kandydata spoza
    pipeline'u tej rekrutacji."""
    # Notatka już podpięta do INNEJ rekrutacji nie jest „bez powiązania” —
    # ponowne podpięcie przenosiłoby ją po cichu między rekrutacjami (także
    # różnych klientów) i karmiło jej treścią cudzy profil Championa.
    if note.job_id is not None and note.job_id != job_id:
        raise HTTPException(
            status_code=422,
            detail="Ta notatka jest podpięta do innej rekrutacji.",
        )
    # Notatka kandydata może zasilić Championa tylko tej rekrutacji, w której
    # ten kandydat jest w pipeline — inaczej rozmowa z kandydatem jednego
    # klienta trafiałaby do profilu roli innego klienta.
    if note.candidate_id is None:
        return
    in_pipeline = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == note.candidate_id,
            CandidateStage.job_id == job_id,
        )
        .limit(1)
    )
    if in_pipeline is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Notatki kandydata nie można powiązać z rekrutacją, w której "
                "ten kandydat nie jest w pipeline."
            ),
        )
