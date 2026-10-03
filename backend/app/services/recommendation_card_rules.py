"""Karta rekomendacji — czyste reguły (0413), bez bazy.

Karta to PROJEKCJA notatek rekrutera plus pola wpisane w NEXUSIE:

* pola z notatek — nowsza notatka wygrywa pole po polu; każde pole pamięta
  notatkę-źródło i jej datę;
* pola wpisane ręcznie — zawsze wygrywają z notatką;
* ponowne dodanie osoby do rekrutacji (kolejna próba procesu): wartości
  sprzed początku bieżącej próby są podpowiedzią (``previous``), a kompletność
  liczy się od nowa. Rozstrzyga data pola, nie osobny licznik.

Zapis i odczyt z bazy: ``recommendation_cards.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from app.services import note_kinds
from app.services.recommendation_card_parser import normalize_field, parse_card

CARD_KINDS: tuple[str, ...] = (note_kinds.CARD, note_kinds.SCREENING_FACTS)

# Pola, których brak liczy się w „brakuje N” — kolejność jak we wzorze działu.
REQUIRED_FIELDS: tuple[str, ...] = (
    "rate",
    "availability",
    "work_mode",
    "location",
    "nationality",
    "worked_at_client",
    "english",
    "red_flags",
    "recommendation",
    "motivation",
)
EDITABLE_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + ("client_manager",)
# Imię i nazwisko bierzemy z profilu kandydata, nie z notatki.
_NOT_STORED = frozenset({"name"})
_MULTILINE = frozenset({"recommendation", "motivation", "red_flags"})
LINE_MAX, TEXT_MAX = 300, 6000

LABELS: dict[str, str] = {
    "rate": "Stawka",
    "availability": "Dostępność",
    "work_mode": "Tryb pracy",
    "location": "Lokalizacja",
    "nationality": "Narodowość",
    "worked_at_client": "Czy pracował u Klienta",
    "english": "Angielski",
    "red_flags": "Red flags",
    "recommendation": "Notatka",
    "motivation": "Motywacja",
    "client_manager": "Manager u Klienta",
}


@dataclass(frozen=True)
class NoteInput:
    id: int
    content: str
    at: datetime


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def project_notes(
    notes: Iterable[NoteInput],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pola i odpowiedzi z notatek pary — nowsza notatka wygrywa pole po polu."""
    fields: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    for note in sorted(notes, key=lambda item: (_aware(item.at), item.id)):
        parsed = parse_card(note.content)
        if not parsed.is_card:
            continue
        source = {"note_id": note.id, "at": _aware(note.at).isoformat()}
        for key, value in parsed.fields.items():
            if key not in _NOT_STORED:
                fields[key] = {**value, **source}
        if parsed.answers:
            answers = {"items": [dict(item) for item in parsed.answers], **source}
    return fields, answers


def max_length(key: str) -> int:
    return TEXT_MAX if key in _MULTILINE else LINE_MAX


def manual_value(key: str, raw: str, *, user_id: int, now: datetime) -> dict[str, Any]:
    """Pole wpisane w NEXUSIE — znormalizowane tą samą regułą co notatka."""
    return {**normalize_field(key, raw), "by": user_id, "at": _aware(now).isoformat()}


def _moment(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def is_current(value: Mapping[str, Any], attempt_started: Optional[datetime]) -> bool:
    if attempt_started is None:
        return True
    at = _moment(value.get("at"))
    return at is not None and at >= _aware(attempt_started)


def split_fields(
    fields_notes: Mapping[str, Any],
    fields_manual: Mapping[str, Any],
    *,
    attempt_started: Optional[datetime] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(pola bieżące, podpowiedzi z poprzedniej próby). Pole ręczne wygrywa."""
    current: dict[str, Any] = {}
    previous: dict[str, Any] = {}
    for source, fields in (("note", fields_notes), ("manual", fields_manual)):
        for key, value in fields.items():
            if (
                not isinstance(value, Mapping)
                or not str(value.get("raw") or "").strip()
            ):
                continue
            target = current if is_current(value, attempt_started) else previous
            target[key] = {**value, "source": source}
    return current, previous


def completeness(current: Mapping[str, Any]) -> dict[str, Any]:
    """Jedna reguła „karta gotowa / brakuje N” dla wszystkich ekranów."""
    missing = [key for key in REQUIRED_FIELDS if key not in current]
    filled = len(REQUIRED_FIELDS) - len(missing)
    status = "complete" if not missing else "partial" if filled else "empty"
    return {
        "status": status,
        "filled": filled,
        "total": len(REQUIRED_FIELDS),
        "missing": missing,
    }


def legacy_text(
    current: Mapping[str, Any],
    answers: Sequence[Mapping[str, Any]],
    *,
    candidate_name: str,
    project: str,
) -> str:
    """Karta w dotychczasowym formacie działu — do skopiowania."""

    def raw(key: str) -> str:
        return str((current.get(key) or {}).get("raw") or "").strip()

    lines = [f"Imię i nazwisko: {candidate_name}".rstrip()]
    lines += [
        f"{LABELS[key]}: {raw(key)}".rstrip()
        for key in (
            "rate",
            "availability",
            "work_mode",
            "location",
            "nationality",
            "worked_at_client",
            "english",
        )
    ]
    lines.append(f"Nazwa projektu: {project}".rstrip())
    lines.append(f"Nazwa pliku CV: {raw('cv_filename')}".rstrip())
    for index, item in enumerate(answers, start=1):
        number = item.get("number") or index
        lines.append(f"P{number}: {str(item.get('question') or '').strip()}".rstrip())
        lines.append(f"Odpowiedź: {str(item.get('answer') or '').strip()}".rstrip())
    lines += [
        f"{LABELS[key]}: {raw(key)}".rstrip()
        for key in ("red_flags", "recommendation", "motivation")
    ]
    return "\n".join(lines)


def _answers_items(note_answers: Any) -> list[dict[str, Any]]:
    if not isinstance(note_answers, Mapping):
        return []
    items = note_answers.get("items")
    return (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )


def current_answers(
    note_answers: Any, *, attempt_started: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Odpowiedzi z notatki bieżącej próby (albo ``None``)."""
    items = _answers_items(note_answers)
    if not items or not is_current(note_answers, attempt_started):
        return None
    return {
        "items": items,
        "note_id": note_answers.get("note_id"),
        "at": note_answers.get("at"),
    }
