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

Wzmianki „@” w uwadze (22.10.2026): do tej zmiany uwaga zapisywała się bez
``NoteMention`` i bez dzwonka, więc rekruter oznaczony w uwadze przy
akceptacji Nordei („do Cpro”) nic nie dostawał — dzwonek ruchu idzie wtedy do
osoby od Cpro. Teraz oznaczeni dostają dzwonek i mail jak przy notatce
(`mention_dispatch`), po commicie ruchu (`/move` → ``run_move_effects``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note, NoteType
from app.models.note_mention import NoteMention
from app.models.notification import Notification
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
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


@dataclass(frozen=True)
class RemarkMentions:
    """Dzwonki wzmianek dodane w sesji i to, czego potrzebuje mail po commicie."""

    pairs: list[tuple[User, Notification]]
    author_name: str
    snippet: str
    deep_link_path: str
    context_label: str
    notification_title: str


async def enqueue_mentions(
    db: AsyncSession, *, note: Note, author: User, stage_name: Optional[str]
) -> Optional[RemarkMentions]:
    """Oznaczeni „@” w uwadze: ``NoteMention`` i dzwonki w sesji (bez commita).

    Zakres jak w notatce rekrutacji (`parse_mentions`), bez autora. ``None`` =
    nikogo nie oznaczono.
    """

    from app.services.mention_dispatch import (  # noqa: PLC0415
        build_note_context_label,
        build_note_deep_link,
        enqueue_mention_notifications,
        trim_snippet,
    )
    from app.services.mention_parser import parse_mentions  # noqa: PLC0415

    if note.job_id is None or not note.content:
        return None
    mentioned = [
        uid
        for uid in await parse_mentions(db, note.content, note.job_id)
        if uid != author.id
    ]
    if not mentioned:
        return None
    for uid in mentioned:
        db.add(NoteMention(note_id=note.id, user_id=uid))
    author_name = author.name or author.email
    where = f" przy przesunięciu na „{stage_name}”" if stage_name else ""
    title = f"{author_name} oznaczył(a) Cię w uwadze{where}"
    snippet = trim_snippet(note.content)
    deep_link = build_note_deep_link(note)
    pairs = await enqueue_mention_notifications(
        db,
        mentioned_user_ids=mentioned,
        author=author,
        deep_link_path=deep_link,
        snippet=snippet,
        notification_title=title,
        related_entity_type="note",
        related_entity_id=note.id,
    )
    return RemarkMentions(
        pairs=pairs,
        author_name=author_name,
        snippet=snippet,
        deep_link_path=deep_link,
        context_label=await build_note_context_label(db, note),
        notification_title=title,
    )


async def send_mentions(mentions: RemarkMentions) -> None:
    """Po commicie: WS i mail do oznaczonych (best-effort, jak przy notatce)."""

    from app.services.mention_dispatch import send_mention_side_effects  # noqa: PLC0415

    await send_mention_side_effects(
        mentions.pairs,
        author_name=mentions.author_name,
        snippet=mentions.snippet,
        deep_link_path=mentions.deep_link_path,
        context_label=mentions.context_label,
        notification_title=mentions.notification_title,
    )


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


async def with_author(db: AsyncSession, stage_id: int) -> Optional[dict]:
    """Uwaga wiersza etapu z autorem i czasem — ``{text, author_name,
    created_at}`` albo ``None`` (przegląd Delivery Leada, 14.10.2026)."""

    from app.models.user import User  # noqa: PLC0415

    row = (
        await db.execute(
            select(Note.content, Note.created_at, User.name)
            .outerjoin(User, User.id == Note.author_id)
            .where(
                Note.external_source == note_kinds.REMARK_SOURCE,
                Note.external_id == str(stage_id),
            )
            .limit(1)
        )
    ).first()
    if row is None or not clean(row.content):
        return None
    return {
        "text": row.content.strip(),
        "author_name": row.name,
        "created_at": row.created_at,
    }


__all__ = [
    "MAX_CHARS",
    "SHORT_CHARS",
    "RemarkMentions",
    "clean",
    "enqueue_mentions",
    "for_stage",
    "for_stages",
    "record",
    "send_mentions",
    "short",
    "with_author",
]
