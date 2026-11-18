"""„Ostatnio z osobą” na liście kandydatów (18.11.2026).

Linia pod wierszem listy: dwie ostatnie informacje o osobie, najnowsza
pierwsza, każda z datą — rozmowa, notatka albo odrzucenie. Zastępuje kolumnę
„Ostatnie odrzucenie”, w której cytat z lipca („nie jest zainteresowany, nie
wydzwaniać”) wyglądał na dzisiejszy, choć 02.11 była rozmowa z „dostępny
ASAP” (zgłoszenie rekrutera, decyzja Artura 18.11.2026, makiety:
https://claude.ai/artifact/Lk3LqawjifGhmJwn59Wrg3).

Bez zgadywania, co notatka znaczy: „nie jest zainteresowany Nordeą” to
odmowa jednej oferty, nie szukania pracy, więc niczego nie wnioskujemy —
pokazujemy kolejność, decyduje rekruter.

Źródła:

* notatki z zakładki „Rozmowy” (``note_kinds.talks_clause``) z widocznością
  stawki do klienta jak w „Ostatniej notatce” — bez prób kontaktu, maili,
  wpisów Delivery Leada i automatu, bez odpowiedzi w wątku i usuniętych;
* ostatnie odrzucenie (``candidate_last_rejection.page_rows``). Import
  Traffita zapisywał ten sam opis i w notatce statusu, i przy odrzuceniu —
  taki dubel pokazujemy raz.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.services import candidate_last_rejection as last_rejection
from app.services import note_kinds

FACTS_PER_CANDIDATE = 2
TEXT_MAX_CHARS = 160
# Rozmowa = karta z rozmowy albo fakty ze screeningu (zakładka „Rozmowy”).
_TALK_KINDS = frozenset({note_kinds.CARD, note_kinds.SCREENING_FACTS})
_TALK_MARK_RE = re.compile(r"^\s*notatka z rozmowy", re.I)
_FIELD_RE = {
    "availability": re.compile(r"^\s*dost[eę]pno[sś][cć]\s*:\s*(.+?)\s*$", re.I | re.M),
    "rate": re.compile(r"^\s*stawka\s*:\s*(\d{2,4}(?:[.,]\d{1,2})?)\s*$", re.I | re.M),
}
_BR_RE = re.compile(r"<\s*(?:br|/p|/div|/li)\s*/?\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Fact:
    at: datetime
    kind: str  # "talk" | "note" | "rejection"
    text: str
    client_name: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "kind": self.kind,
            "text": self.text,
            "client_name": self.client_name,
        }


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > TEXT_MAX_CHARS:
        return text[: TEXT_MAX_CHARS - 1].rstrip() + "…"
    return text


def _lines(content: Optional[str]) -> str:
    """Treść z zachowanymi liniami (karta ma pola „Etykieta: wartość” w liniach)."""
    raw = _BR_RE.sub("\n", (content or "").replace("&nbsp;", " "))
    return html.unescape(_TAG_RE.sub(" ", raw))


def note_fact(
    at: datetime, kind: Optional[str], content: Optional[str]
) -> Optional[Fact]:
    """Fakt z notatki albo ``None`` (pusta treść). Czysta — bez bazy."""
    lines = _lines(content)
    text = " ".join(lines.split())
    if not text:
        return None
    if kind in _TALK_KINDS or _TALK_MARK_RE.match(text):
        availability = _FIELD_RE["availability"].search(lines)
        rate = _FIELD_RE["rate"].search(lines)
        parts = [
            f"dostępność {availability.group(1)}" if availability else None,
            f"{rate.group(1)} zł/h" if rate else None,
        ]
        summary = ", ".join(p for p in parts if p)
        return Fact(at=at, kind="talk", text=_shorten(summary or text))
    return Fact(at=at, kind="note", text=_shorten(text))


def _same_text(a: str, b: str) -> bool:
    def norm(value: str) -> str:
        return " ".join(value.lower().split()).strip(' .„”"…')[:60]

    return bool(norm(a)) and (norm(a) in norm(b) or norm(b) in norm(a))


def merge(notes: Sequence[Fact], rejection: Optional[dict[str, Any]]) -> list[Fact]:
    """Dwie najnowsze informacje: notatki + odrzucenie, bez dubla z Traffita."""
    facts = list(notes)
    if rejection and rejection.get("at"):
        text = rejection.get("note") or rejection.get("label") or ""
        duplicate = any(
            f.at.date() == rejection["at"].date() and _same_text(f.text, text)
            for f in facts
        )
        if not duplicate:
            facts.append(
                Fact(
                    at=rejection["at"],
                    kind="rejection",
                    text=_shorten(text),
                    client_name=rejection.get("client_name"),
                )
            )
    facts.sort(key=lambda f: f.at, reverse=True)
    return facts[:FACTS_PER_CANDIDATE]


async def page_rows(
    db: AsyncSession,
    candidate_ids: Sequence[int],
    *,
    visibility_clause,
) -> dict[int, list[dict[str, Any]]]:
    """„Ostatnio z osobą” dla osób ze strony — dwa zapytania na stronę."""
    if not candidate_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=Note.candidate_id,
            order_by=(Note.created_at.desc(), Note.id.desc()),
        )
        .label("rank")
    )
    ranked = (
        select(Note.candidate_id, Note.created_at, Note.kind, Note.content, rank)
        .where(
            Note.candidate_id.in_(list(candidate_ids)),
            Note.parent_note_id.is_(None),
            Note.source_deleted_at.is_(None),
            note_kinds.talks_clause(),
            visibility_clause,
        )
        .subquery()
    )
    # +1 na wypadek dubla z odrzuceniem, które wtedy wypada.
    rows = (
        await db.execute(select(ranked).where(ranked.c.rank <= FACTS_PER_CANDIDATE + 1))
    ).all()
    notes: dict[int, list[Fact]] = {}
    for row in rows:
        fact = note_fact(row.created_at, row.kind, row.content)
        if fact is not None:
            notes.setdefault(row.candidate_id, []).append(fact)
    rejections = await last_rejection.page_rows(db, candidate_ids)
    return {
        cid: [f.as_dict() for f in merge(notes.get(cid, []), rejections.get(cid))]
        for cid in candidate_ids
    }
