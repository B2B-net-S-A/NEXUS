"""Skąd „✓” przy wymaganiu: źródła i cytaty dla podglądu osoby (10.11.2026).

Zgłoszenie Delivery Leada z 09.11.2026: NEXUS polecił do rekrutacji Java +
Angular osobę, która Angulara w CV nie ma. „✓ angular” pochodził z profilu
(firmowe CV sprzed miesięcy, notatka „nie jestem mega mocny na frontendzie”),
ale ekran tego nie mówił. Decyzja Artura: przy każdym „✓” widać źródło
(CV, profil, notatka), a klik pokazuje cytaty i prowadzi do miejsca w CV.
Ocena dopasowania się nie zmienia.

Reguła słowa jest ta sama co w bramce must i przeglądzie DL
(``must_text_evidence.mention_snippet``: całe słowo, aliasy ze słownika),
notatki-dowody te same co w bramce (rodzaje, bez maili, bez wpisów automatu,
przeczenia z karty odpadają przez ``evidence_note_text``).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional, Sequence

from app.services import conversation_facts
from app.services import must_text_evidence as mte
from app.services.must_gate_terms import gate_requirement

MAX_LABELS = 30
NOTES_SHOWN = 3
PROFILE_SHOWN = 3
_NOTES_LIMIT = 300

SOURCE_CV = "cv"
SOURCE_PROFILE = "profile"
SOURCE_NOTE = "note"

_TAG_RE = re.compile(r"<[^>]+>")
_TRAFFIT_KEYS = (
    "traffit_technologie",
    "traffit_Position",
    "traffit_certificates",
    "traffit_previous_employers",
)
_CV_READ_KEYS = ("skills", "certifications", "projects", "profile_about")


@dataclass(frozen=True)
class EvidenceNote:
    id: int
    noted_on: Optional[date]
    author: Optional[str]
    kind: Optional[str]
    content: str


def plain_text(value: Optional[str]) -> str:
    """Treść notatki bez znaczników HTML i encji, w jednej linii."""
    return " ".join(html.unescape(_TAG_RE.sub(" ", value or "")).split())


def _names(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("skill") or item.get("value")
            if name:
                out.append(str(name))
        elif item:
            out.append(str(item))
    return ", ".join(out)


def _experience_text(value: Any) -> str:
    if not isinstance(value, list):
        return _names(value)
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            if item:
                lines.append(str(item))
            continue
        head = " · ".join(
            str(item[k]) for k in ("role", "title", "company") if item.get(k)
        )
        tech = _names(item.get("technologies"))
        desc = str(item.get("desc") or item.get("description") or "")
        lines.append(" — ".join(part for part in (head, tech, desc) if part))
    return "\n".join(lines)


def _any_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def profile_parts(candidate: Any) -> list[tuple[str, str]]:
    """Części profilu z nazwą, którą DL rozpozna. Razem pokrywają to samo co
    ``must_text_evidence.profile_text`` (źródło „profil” bramki)."""
    data = getattr(candidate, "cv_extracted_data", None)
    data = data if isinstance(data, dict) else {}
    skills = ", ".join(
        part
        for part in (
            _names(getattr(candidate, "skills", None)),
            _names(getattr(candidate, "verified_tech", None)),
        )
        if part
    )
    facts = mte._notes_insights_evidence(data.get("_notes_insights")) + list(
        conversation_facts.evidence_names(candidate)
    )
    position = " · ".join(
        str(v)
        for v in (
            getattr(candidate, a, None)
            for a in ("current_position", "headline", "title")
        )
        if isinstance(v, str) and v
    )
    return [
        ("Lista umiejętności", skills),
        (
            "Historia stanowisk",
            _experience_text(getattr(candidate, "experience", None)),
        ),
        ("Pola z Traffita", "\n".join(_any_text(data.get(k)) for k in _TRAFFIT_KEYS)),
        ("Odczyt CV", "\n".join(_any_text(data.get(k)) for k in _CV_READ_KEYS)),
        ("Fakty z rozmów", ", ".join(str(f) for f in facts if f)),
        ("Stanowisko", position),
        ("Tagi", _any_text(getattr(candidate, "tags", None))),
    ]


def _quote(label: str, text: str) -> Optional[dict[str, Any]]:
    """Cytat wokół trafienia; ``via`` = nazwa, którą trafienie stoi w tekście,
    gdy to nie samo słowo wymagania (PostgreSQL przy SQL, powiązanie z mapy
    wiedzy) — DL widzi wtedy, czemu cytat nie zawiera „sql”."""
    from app.services.skill_normalize import implied_forms

    snippet = mte.mention_snippet(label, text) if text else None
    if not snippet:
        return None
    via = None
    if mte.word_snippet(label, snippet) is None:
        via = next(
            (form for form in implied_forms(label) if mte.word_snippet(form, snippet)),
            None,
        )
    return {"snippet": snippet, "via": via}


def collect(
    candidate: Any, labels: Sequence[str], notes: Iterable[EvidenceNote]
) -> dict[str, dict[str, Any]]:
    """``{etykieta: {sources, cv, notes, notes_more, profile}}``.

    Etykieta-zdanie (``gate_requirement`` = None) nie trafia do wyniku — tak
    jak w przeglądzie DL, słowem jej się nie sprawdzi. Puste ``sources`` przy
    „✓” = ocena uznała wymaganie po wariancie nazwy z listy umiejętności, a
    dosłownej wzmianki nie ma.
    """
    notes = list(notes)
    cv = mte.cv_text(candidate)
    parts = profile_parts(candidate)
    note_texts = [
        (n, plain_text(mte.evidence_note_text(n.kind, n.content))) for n in notes
    ]
    out: dict[str, dict[str, Any]] = {}
    for label in dict.fromkeys(labels):
        if gate_requirement(label) is None:
            continue
        cv_quote = _quote(label, cv)
        note_hits = [
            {
                "id": note.id,
                "date": note.noted_on.isoformat() if note.noted_on else None,
                "author": note.author,
                **quote,
            }
            for note, text in note_texts
            if (quote := _quote(label, text))
        ]
        profile = [
            {"where": where, **quote}
            for where, text in parts
            if (quote := _quote(label, text))
        ]
        sources = [
            source
            for source, present in (
                (SOURCE_CV, cv_quote),
                (SOURCE_PROFILE, profile),
                (SOURCE_NOTE, note_hits),
            )
            if present
        ]
        out[label] = {
            "sources": sources,
            "cv": cv_quote,
            "notes": note_hits[:NOTES_SHOWN],
            "notes_more": max(0, len(note_hits) - NOTES_SHOWN),
            "profile": profile[:PROFILE_SHOWN],
        }
    return out


async def load_notes(
    db, candidate_id: int, labels: Sequence[str]
) -> list[EvidenceNote]:
    """Notatki-dowody osoby, w których stoi któraś z technologii (filtr jak
    w bramce), najnowsze pierwsze. Data notatki z Traffita = data źródła."""
    from sqlalchemy import text

    from app.core.scheduling import business_date
    from app.services import note_kinds

    pattern = mte._loose_pg_pattern(list(labels))
    if not pattern:
        return []
    rows = await db.execute(
        text(
            "SELECT n.id, n.at, u.name, n.kind, n.content FROM ("
            "  SELECT id, author_id, kind, content,"
            "         coalesce(source_created_at, created_at) AS at"
            "  FROM notes"
            "  WHERE candidate_id = :cid AND source_deleted_at IS NULL"
            "    AND note_type::text = ANY(:types) AND content ~* :pattern"
            f"    AND {note_kinds.ai_readable_sql()}"
            "  ORDER BY at DESC LIMIT :lim"
            ") n LEFT JOIN users u ON u.id = n.author_id ORDER BY n.at DESC"
        ),
        {
            "cid": candidate_id,
            "types": list(mte.EVIDENCE_NOTE_TYPES),
            "pattern": pattern,
            "lim": _NOTES_LIMIT,
        },
    )
    out: list[EvidenceNote] = []
    for note_id, at, author, kind, content in rows:
        noted_on = business_date(at) if isinstance(at, datetime) else None
        out.append(
            EvidenceNote(
                id=note_id,
                noted_on=noted_on,
                author=author,
                kind=kind,
                content=content or "",
            )
        )
    return out
