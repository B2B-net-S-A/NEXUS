"""Podpowiedzi stawek pary, która nie ma ich na etapie (12.10.2026).

W Traffit nie było pól stawki: rekruter zapisywał oczekiwanie kandydata
w notatce-karcie, a Delivery Lead cenę wysłania — w zwykłej notatce, często bez
rekrutacji, minutę po ruchu na „Wysłany do Klienta”. Import przenosi etapy bez
kwot, więc zakładka „Rekrutacje” profilu i panel osoby na Tablicy pokazywały
„—”, choć obie liczby leżały w notatkach. Pomiar na produkcji 12.10.2026:
z 2 208 par wysłanych do klienta od 07.2026 stawki kandydata na etapie nie ma
2 182, a 1 762 z nich mają ją w karcie rekomendacji; z 1 531 par bez stawki do
klienta 583 mają notatkę wysyłającego do 30 minut od ruchu.

Ten moduł niczego nie zapisuje i niczego nie zgaduje:

* ``candidate_rates`` — stawka kandydata podana w TEJ rekrutacji, ta sama
  reguła co „W tej rekrutacji” w propozycjach (``candidate_rate_from``);
* ``send_notes`` — notatka osoby, która przesunęła kartę na „CV wysłane”,
  napisana do 30 minut od ruchu i zawierająca kwotę. Treść czyta człowiek
  i sam wpisuje stawkę do klienta — notatka z trzema liczbami („150/100-110”)
  nie jest jednoznaczna. Wołający pokazuje ją wyłącznie rolom
  z ``user_can_view_client_rate``.

Źródłem stawek dla zamówień i umów zostają wiersze etapu
(``recruitment_rates``) — podpowiedź staje się stawką dopiero po zapisie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import candidate_rate_from, client_rate_notes, note_kinds
from app.services.text_cleaning import clean_rich_text

SEND_NOTE_WINDOW = timedelta(minutes=30)
SEND_NOTE_MAX_CHARS = 300
_AMOUNT_RE = re.compile(r"(?<!\d)\d{2,3}(?!\d)")
# Godzina i numer telefonu to nie kwota (audyt 13.10.2026): „rozmowa o 14:50”
# albo „+48 123 456 789” bliżej ruchu wypychały prawdziwą notatkę z wysyłki.
# Godzina z kropką tylko po „o / od / do / godz.” — „85.50” to stawka.
_CLOCK_RE = re.compile(
    r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)"
    r"|\b(?:o|od|do|godz\.?|godzin[aieę])\s*(?:[01]?\d|2[0-3])\.[0-5]\d(?!\d)",
    re.IGNORECASE,
)
# 9 cyfr w grupach 3-3-3 albo 2-3-2-2, opcjonalnie z +48 — z JEDNYM rodzajem
# separatora („512 345 678”, „512-345-678”), więc „150 100-110” zostaje parą
# stawek. Ukośnik obok odcina „150/100-110”.
_PHONE_RE = re.compile(
    r"(?<![\d/])(?:\+\d{2}[\s-]?)?"
    r"(?:\d{3}(?P<s3>[\s-]?)\d{3}(?P=s3)\d{3}"
    r"|\d{2}(?P<s2>[\s-])\d{3}(?P=s2)\d{2}(?P=s2)\d{2})"
    r"(?![\d/])"
)


@dataclass(frozen=True)
class Send:
    """Ruch pary na „CV wysłane”."""

    job_id: int
    moved_at: datetime
    moved_by: int


@dataclass(frozen=True)
class SendNote:
    id: int
    job_id: Optional[int]
    author_id: int
    at: datetime
    text: str
    author_name: Optional[str] = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def shorten(plain: str) -> str:
    """Tekst notatki przycięty do ``SEND_NOTE_MAX_CHARS``."""
    if len(plain) <= SEND_NOTE_MAX_CHARS:
        return plain
    return plain[: SEND_NOTE_MAX_CHARS - 1].rstrip() + "…"


def has_amount(plain: str) -> bool:
    """Czy tekst zawiera liczbę z zakresu stawek godzinowych (40–400).

    Godziny i numery telefonów się nie liczą.
    """
    text_only = _PHONE_RE.sub(" ", _CLOCK_RE.sub(" ", plain))
    return any(
        client_rate_notes.RATE_MIN <= int(found) <= client_rate_notes.RATE_MAX
        for found in _AMOUNT_RE.findall(text_only)
    )


def _belongs_to(note: SendNote, send: Send) -> bool:
    """Notatka autora ruchu, do 30 min od niego, z tej rekrutacji albo bez."""
    return (
        note.author_id == send.moved_by
        and note.job_id in (None, send.job_id)
        and abs(_aware(note.at) - _aware(send.moved_at)) <= SEND_NOTE_WINDOW
    )


def send_note_ids_among(sends: Iterable[Send], notes: Iterable[SendNote]) -> set[int]:
    """Id notatek z wysyłki jednego kandydata (czysta funkcja) — do zakrycia ceny.

    Ta sama reguła co ``pick_send_notes`` (``_belongs_to``) i ``has_amount``, ale
    bez wyboru jednej notatki na rekrutację: cenę dla klienta niesie każda
    (decyzja C po audycie 13.10.2026).
    """
    sends = list(sends)
    return {
        note.id
        for note in notes
        if has_amount(note.text) and any(_belongs_to(note, send) for send in sends)
    }


def pick_send_notes(
    sends: Iterable[Send], notes: Iterable[SendNote]
) -> dict[int, SendNote]:
    """Rekrutacja → notatka z wysyłki (czysta funkcja).

    Notatka należy do wysyłki, gdy napisała ją osoba, która wykonała ruch,
    najwyżej ``SEND_NOTE_WINDOW`` przed albo po nim, i jest przypięta do tej
    rekrutacji albo do żadnej. Liczy się NAJNOWSZA wysyłka pary, która ma taką
    notatkę, a z kilku notatek — najbliższa ruchowi. Notatka bez rekrutacji
    może stać pod dwiema rekrutacjami wysłanymi w tym samym oknie: nie wiemy,
    której dotyczy, a czyta ją człowiek.
    """
    pool = list(notes)
    out: dict[int, SendNote] = {}
    for send in sorted(sends, key=lambda s: _aware(s.moved_at), reverse=True):
        if send.job_id in out:
            continue
        moved_at = _aware(send.moved_at)
        near = [
            (abs(_aware(note.at) - moved_at), note.id, note)
            for note in pool
            if _belongs_to(note, send)
        ]
        if near:
            out[send.job_id] = min(near, key=lambda item: item[:2])[2]
    return out


async def candidate_rates(
    db: AsyncSession, candidate_id: int, job_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """Rekrutacja → stawka kandydata podana w tej rekrutacji (z autorem)."""
    wanted = {int(job_id) for job_id in job_ids}
    if not wanted:
        return {}
    found = {
        job_id: obs
        for job_id, obs in (
            await candidate_rate_from.candidate_job_rates(db, candidate_id)
        ).items()
        if job_id in wanted
    }
    author_ids = sorted(
        {obs.author_id for obs in found.values() if isinstance(obs.author_id, int)}
    )
    names: dict[int, str] = {}
    if author_ids:
        rows = await db.execute(
            text("SELECT id, name FROM users WHERE id = ANY(:ids)"),
            {"ids": author_ids},
        )
        names = {row.id: row.name for row in rows if row.name}
    return {
        job_id: {
            "amount_hourly": float(obs.amount_hourly),
            "raw": obs.raw,
            "at": obs.at.isoformat() if obs.at else None,
            "source": obs.source,
            "author_name": names.get(obs.author_id)
            if isinstance(obs.author_id, int)
            else None,
        }
        for job_id, obs in found.items()
    }


# Tylko rekrutacje, w których para nie ma stawki do klienta na żadnym etapie.
_SENDS_SQL = text(
    """
    SELECT cs.job_id, cs.moved_at, cs.moved_by
      FROM candidate_stages cs
     WHERE cs.candidate_id = :candidate_id
       AND cs.job_id = ANY(:job_ids)
       AND cs.stage::text = 'cv_sent'
       AND cs.moved_by IS NOT NULL
       AND cs.moved_at IS NOT NULL
       AND NOT EXISTS (
               SELECT 1 FROM candidate_stages x
                WHERE x.candidate_id = cs.candidate_id
                  AND x.job_id = cs.job_id
                  AND x.client_rate_value IS NOT NULL
           )
    """
)

# Zwykła notatka liczy się tylko od Delivery Leada albo admina — ta sama bramka
# autora co wpis „X/Y” (``client_rate_notes.dl_pair_from_note``).
_NOTES_SQL = text(
    f"""
    SELECT n.id, n.job_id, n.author_id, n.content, u.name AS author_name,
           COALESCE(n.source_created_at, n.created_at) AS at
      FROM notes n
      LEFT JOIN users u ON u.id = n.author_id
     WHERE n.candidate_id = :candidate_id
       AND n.author_id = ANY(:author_ids)
       AND (n.job_id IS NULL OR n.job_id = ANY(:job_ids))
       AND n.parent_note_id IS NULL
       AND n.source_deleted_at IS NULL
       AND (
               n.kind = :dl_rate
            OR ((n.kind IS NULL OR n.kind = :human)
                AND {client_rate_notes.DL_PAIR_AUTHOR_SQL})
           )
       AND n.content ~ '[0-9]{{2,3}}'
       AND COALESCE(n.source_created_at, n.created_at) BETWEEN :start AND :end
    """
)


async def send_notes(
    db: AsyncSession, candidate_id: int, job_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """Rekrutacja → notatka wysyłającego z okolic ruchu na „CV wysłane”.

    Zwraca treść notatki, która może nieść stawkę do klienta — wołający
    odpowiada za ``user_can_view_client_rate``.
    """
    wanted = sorted({int(job_id) for job_id in job_ids})
    if not wanted:
        return {}
    sends = [
        Send(row.job_id, row.moved_at, row.moved_by)
        for row in await db.execute(
            _SENDS_SQL, {"candidate_id": candidate_id, "job_ids": wanted}
        )
    ]
    if not sends:
        return {}
    moves = [_aware(send.moved_at) for send in sends]
    notes: list[SendNote] = []
    for row in await db.execute(
        _NOTES_SQL,
        {
            "candidate_id": candidate_id,
            "job_ids": sorted({send.job_id for send in sends}),
            "author_ids": sorted({send.moved_by for send in sends}),
            "dl_rate": note_kinds.DL_RATE,
            "human": note_kinds.HUMAN,
            "start": min(moves) - SEND_NOTE_WINDOW,
            "end": max(moves) + SEND_NOTE_WINDOW,
        },
    ):
        plain = clean_rich_text(row.content)
        if has_amount(plain):
            notes.append(
                SendNote(
                    id=row.id,
                    job_id=row.job_id,
                    author_id=row.author_id,
                    at=row.at,
                    text=shorten(plain),
                    author_name=row.author_name,
                )
            )
    return {
        job_id: {
            "note_id": note.id,
            "text": note.text,
            "at": _aware(note.at).isoformat(),
            "author_name": note.author_name,
        }
        for job_id, note in pick_send_notes(sends, notes).items()
    }


# Notatki, które MOGĄ być notatką z wysyłki: zwykła (albo nieoznaczona) notatka
# kandydata od Delivery Leada albo admina z liczbą — ta sama bramka autora co
# w ``_NOTES_SQL``. Wpis `dl_rate` jest zakryty już przez rodzaj.
_SEND_NOTE_SUSPECTS_SQL = text(
    f"""
    SELECT n.id, n.candidate_id, n.job_id, n.author_id, n.content,
           COALESCE(n.source_created_at, n.created_at) AS at
      FROM notes n
      JOIN users u ON u.id = n.author_id
     WHERE n.id = ANY(:ids)
       AND n.candidate_id IS NOT NULL
       AND (n.kind IS NULL OR n.kind = :human)
       AND {client_rate_notes.DL_PAIR_AUTHOR_SQL}
       AND n.content ~ '[0-9]{{2,3}}'
    """
)

_CV_SENT_MOVES_SQL = text(
    """
    SELECT cs.candidate_id, cs.job_id, cs.moved_at, cs.moved_by
      FROM candidate_stages cs
     WHERE cs.candidate_id = ANY(:candidate_ids)
       AND cs.moved_by = ANY(:author_ids)
       AND cs.stage::text = 'cv_sent'
       AND cs.moved_at BETWEEN :start AND :end
    """
)


async def send_note_ids(db: AsyncSession, note_ids: Iterable[int]) -> frozenset[int]:
    """Które z podanych notatek są notatką z wysyłki z ceną dla klienta.

    Decyzja C (14.10.2026): „Wysłany 150/100-110” Delivery Leada to zwykła
    notatka, więc rekruter czytał w niej cenę dla klienta. Rozpoznanie jak
    w podpowiedzi stawki do klienta (``send_notes``), także dla pary, która
    stawkę na etapie już ma — kwota w treści jest ta sama. Dwa zapytania na
    całą listę, niezależnie od liczby notatek.
    """
    wanted = sorted({int(note_id) for note_id in note_ids})
    if not wanted:
        return frozenset()
    notes_by_candidate: dict[int, list[SendNote]] = {}
    for row in await db.execute(
        _SEND_NOTE_SUSPECTS_SQL, {"ids": wanted, "human": note_kinds.HUMAN}
    ):
        plain = clean_rich_text(row.content)
        if row.at is None or not has_amount(plain):
            continue
        notes_by_candidate.setdefault(row.candidate_id, []).append(
            SendNote(
                id=row.id,
                job_id=row.job_id,
                author_id=row.author_id,
                at=row.at,
                text=plain,
            )
        )
    if not notes_by_candidate:
        return frozenset()
    suspects = [note for notes in notes_by_candidate.values() for note in notes]
    moments = [_aware(note.at) for note in suspects]
    sends_by_candidate: dict[int, list[Send]] = {}
    for row in await db.execute(
        _CV_SENT_MOVES_SQL,
        {
            "candidate_ids": sorted(notes_by_candidate),
            "author_ids": sorted({note.author_id for note in suspects}),
            "start": min(moments) - SEND_NOTE_WINDOW,
            "end": max(moments) + SEND_NOTE_WINDOW,
        },
    ):
        sends_by_candidate.setdefault(row.candidate_id, []).append(
            Send(row.job_id, row.moved_at, row.moved_by)
        )
    hidden: set[int] = set()
    for candidate_id, notes in notes_by_candidate.items():
        hidden |= send_note_ids_among(sends_by_candidate.get(candidate_id, []), notes)
    return frozenset(hidden)
