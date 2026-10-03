"""Uwaga dla rekrutera zapisana przy ruchu karty (03.10.2026).

Delivery Lead wysyła CV do klienta, cofa kartę do poprawy albo odrzuca
kandydata i zostawia rekruterowi jedno zdanie. Do tej zmiany robił to wpisem
w notatkach („@osoba dopisz Spring do CV”), którego rekruter nie miał jak
odróżnić od reszty historii.

Uwaga jest zwykłą notatką pary (kandydat, rekrutacja) o pochodzeniu
``note_kinds.REMARK_SOURCE``, przypiętą do wiersza etapu (``external_id``):

* rodzaj ``dl_review`` wynika z pochodzenia, nie z treści — modele jej nie
  czytają, a kwota w treści nie robi z niej wpisu o stawce do klienta;
* jedna uwaga na wiersz etapu (częściowy UNIQUE ``ux_notes_external_source_id``);
* stawka do klienta ma własne pole przy ruchu i NIGDY nie jest tu dopisywana.
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note, NoteType
from app.models.recruitment_pipeline import CandidateStage
from app.services import note_kinds

MAX_CHARS = 2000
# Dzwonek i wiersz listy na pulpicie niosą początek uwagi; całość jest w notatce.
SHORT_CHARS = 160


def clean(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip()
    return value or None


def short(value: Optional[str]) -> Optional[str]:
    """Uwaga w jednej linii, przycięta do rozmiaru dzwonka i wiersza listy."""

    line = " ".join((value or "").split())
    if not line:
        return None
    if len(line) <= SHORT_CHARS:
        return line
    return line[: SHORT_CHARS - 1].rstrip() + "…"


def record(
    db: AsyncSession, *, stage: CandidateStage, author_id: int, text: Optional[str]
) -> Optional[Note]:
    """Dopisuje uwagę do sesji; pusta treść = nic."""

    content = clean(text)
    if content is None:
        return None
    note = Note(
        content=content,
        note_type=NoteType.general,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        author_id=author_id,
        external_source=note_kinds.REMARK_SOURCE,
        external_id=str(stage.id),
        kind=note_kinds.DL_REVIEW,
    )
    db.add(note)
    return note


async def for_stages(db: AsyncSession, stage_ids: Iterable[int]) -> dict[int, str]:
    """Treść uwag dla wierszy etapu — jedno zapytanie."""

    keys = sorted({str(stage_id) for stage_id in stage_ids})
    if not keys:
        return {}
    rows = await db.execute(
        select(Note.external_id, Note.content).where(
            Note.external_source == note_kinds.REMARK_SOURCE,
            Note.external_id.in_(keys),
        )
    )
    return {
        int(external_id): content
        for external_id, content in rows.all()
        if content and (external_id or "").isdigit()
    }


async def for_stage(db: AsyncSession, stage_id: int) -> Optional[str]:
    return (await for_stages(db, [stage_id])).get(stage_id)


__all__ = [
    "MAX_CHARS",
    "SHORT_CHARS",
    "clean",
    "for_stage",
    "for_stages",
    "record",
    "short",
]
