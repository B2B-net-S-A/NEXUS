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
# Na ekranie „Notatka” ze wzoru działu nazywa się tak, jak rozumie ją
# rekruter. `LABELS` zostaje dla tekstu w starym formacie (do skopiowania);
# listy braków, podpowiedzi i komunikaty biorą nazwy stąd.
DISPLAY_LABELS: dict[str, str] = {**LABELS, "recommendation": "Dlaczego ten kandydat"}


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


# Skąd pochodzi pole wpisane w NEXUSIE (0421): przyjęte z notatki odczytanej
# przez AI albo regułą wzoru, albo zdanie ułożone z haseł rekrutera. Każda
# późniejsza zwykła edycja zapisuje pole bez pochodzenia (plakietka znika).
CARD_ORIGINS: tuple[str, ...] = ("note_ai", "note_rule", "phrased")
# Pola opisowe karty, które przyjmują „Ułóż w zdanie” (D4).
PHRASABLE_FIELDS: tuple[str, ...] = ("recommendation", "motivation", "red_flags")
KEYWORDS_MAX = 2000


def manual_value(
    key: str,
    raw: str,
    *,
    user_id: int,
    now: datetime,
    provenance: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Pole wpisane w NEXUSIE — znormalizowane tą samą regułą co notatka.

    ``provenance`` (opcjonalnie): ``origin`` z ``CARD_ORIGINS``, ``keywords``
    (hasła, z których powstało zdanie) i ``note_id`` (notatka-źródło).
    Nieznane klucze i wartości są pomijane.
    """
    value: dict[str, Any] = {
        **normalize_field(key, raw),
        "by": user_id,
        "at": _aware(now).isoformat(),
    }
    if provenance:
        origin = provenance.get("origin")
        if origin in CARD_ORIGINS:
            value["origin"] = origin
            keywords = str(provenance.get("keywords") or "").strip()
            if origin == "phrased" and keywords:
                value["keywords"] = keywords[:KEYWORDS_MAX]
            note_id = provenance.get("note_id")
            if isinstance(note_id, int) and not isinstance(note_id, bool):
                value["note_id"] = note_id
    return value


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


def merge_questions(
    question_texts: Mapping[str, str],
    sheet_answers: Sequence[Mapping[str, Any]],
    note_items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pytania z Profilu Championa z odpowiedzią kandydata.

    Odpowiedź z arkusza screeningu wygrywa (to ona liczy się w dopasowaniu
    i wychodzi do klienta); gdy arkusza nie ma — odpowiedź z notatki, po
    numerze pytania. Rekrutacja bez pytań w profilu pokazuje pytania zapisane
    w notatce.
    """
    by_question = {
        str(item.get("question_id") or "").strip(): item
        for item in sheet_answers
        if isinstance(item, Mapping) and not item.get("skipped")
    }
    by_number: dict[int, Mapping[str, Any]] = {}
    for index, item in enumerate(note_items, start=1):
        if not isinstance(item, Mapping):
            continue
        number = item.get("number")
        by_number[number if isinstance(number, int) and number > 0 else index] = item
    if not question_texts:
        return [
            {
                "number": number,
                "question": str(item.get("question") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "source": "note" if str(item.get("answer") or "").strip() else None,
            }
            for number, item in sorted(by_number.items())
        ]
    merged: list[dict[str, Any]] = []
    for number, (question_id, text) in enumerate(question_texts.items(), start=1):
        from_sheet = str(
            (by_question.get(question_id) or {}).get("response") or ""
        ).strip()
        from_note = str((by_number.get(number) or {}).get("answer") or "").strip()
        item: dict[str, Any] = {
            "number": number,
            "question": text,
            "answer": from_sheet or from_note,
            "source": "sheet" if from_sheet else "note" if from_note else None,
        }
        if from_sheet:
            # Pochodzenie odpowiedzi z arkusza (0421): „zdanie z haseł” albo
            # „z notatki” — plakietka w karcie i w przeglądzie DL.
            sheet_item = by_question.get(question_id) or {}
            origin = sheet_item.get("origin")
            if origin in ("note_import", "phrased"):
                item["origin"] = origin
                keywords = str(sheet_item.get("keywords") or "").strip()
                if keywords:
                    item["keywords"] = keywords
        merged.append(item)
    return merged


def attach_deal_breakers(
    merged: Sequence[Mapping[str, Any]],
    champion_questions: Sequence[Any],
    sheet_answers: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pytania karty z warunkiem „Odpada, gdy…” i trafieniem z arkusza (04.10.2026).

    ``merged`` to wynik ``merge_questions``; numer pytania = pozycja pytania
    z treścią i identyfikatorem w Profilu Championa (ta sama kolejność co
    ``screening_sheets.question_texts``). Do każdego pytania dochodzą:
    ``question_id`` (identyfikator z profilu — nim zapisuje się trafienie),
    ``deal_breaker`` (tekst albo ``None``) i ``deal_breaker_hit`` (z arkusza
    screeningu pary). Pytania z samej notatki (bez profilu) mają
    ``question_id = None`` — trafienia nie da się do nich przypiąć.
    """
    meta: list[tuple[str, Optional[str]]] = []
    for question in champion_questions:
        if not isinstance(question, Mapping):
            continue
        question_id = str(question.get("id") or "").strip()
        text = str(question.get("question") or "").strip()
        if not question_id or not text:
            continue
        condition = str(question.get("deal_breaker") or "").strip()
        meta.append((question_id, condition or None))
    hits = {
        str(item.get("question_id") or "").strip()
        for item in sheet_answers
        if isinstance(item, Mapping) and item.get("deal_breaker_hit") is True
    }
    out: list[dict[str, Any]] = []
    for item in merged:
        number = item.get("number")
        question_id, condition = (
            meta[number - 1]
            if meta and isinstance(number, int) and 0 < number <= len(meta)
            else (None, None)
        )
        out.append(
            {
                **item,
                "question_id": question_id,
                "deal_breaker": condition,
                "deal_breaker_hit": bool(question_id and question_id in hits),
            }
        )
    return out


# ── Karty jednej osoby w profilu kandydata (etap 6, 03.10.2026) ────────────

# Ustalenia pokazywane w pasku faktów profilu obok wartości z profilu.
PROFILE_FACT_FIELDS: tuple[str, ...] = (
    "rate",
    "availability",
    "work_mode",
    "english",
    "nationality",
)


def _has_text(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(str(value.get("raw") or "").strip())


def latest_facts(cards: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Najświeższa wartość każdego ustalenia spośród wszystkich kart osoby.

    Rozstrzyga data pola (notatki albo wpisu ręcznego); przy tej samej dacie
    wygrywa wpis ręczny — jak na samej karcie. Wartość bez daty przegrywa
    z każdą datowaną.
    """
    best: dict[str, tuple[tuple[bool, datetime, int], dict[str, Any]]] = {}
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for card in cards:
        for rank, source in enumerate(("note", "manual")):
            fields = card.get("fields_notes" if source == "note" else "fields_manual")
            if not isinstance(fields, Mapping):
                continue
            for key in PROFILE_FACT_FIELDS:
                value = fields.get(key)
                if not _has_text(value):
                    continue
                at = _moment(value.get("at"))
                order = (at is not None, at or floor, rank)
                if key not in best or order > best[key][0]:
                    best[key] = (
                        order,
                        {**value, "source": source, "job_id": card.get("job_id")},
                    )
    return {key: value for key, (_, value) in best.items()}


def note_answer_rows(
    question_texts: Mapping[str, str], note_answers: Any
) -> list[dict[str, Any]]:
    """Odpowiedzi zapisane w notatce — tylko te z treścią.

    Pytanie bierzemy z notatki; gdy notatka niesie samą odpowiedź, z Profilu
    Championa po numerze pytania.
    """
    champion = list(question_texts.values())
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(_answers_items(note_answers), start=1):
        answer = str(item.get("answer") or "").strip()
        if not answer:
            continue
        number = item.get("number")
        number = number if isinstance(number, int) and number > 0 else index
        question = str(item.get("question") or "").strip()
        if not question and number <= len(champion):
            question = champion[number - 1]
        rows.append({"number": number, "question": question, "answer": answer})
    return rows


def note_contributions(
    cards: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Co z każdej notatki trafiło do karty: pola i liczba odpowiedzi."""
    links: dict[int, dict[str, Any]] = {}

    def _link(note_id: Any, job_id: Any) -> Optional[dict[str, Any]]:
        if not isinstance(note_id, int):
            return None
        return links.setdefault(
            note_id, {"note_id": note_id, "job_id": job_id, "fields": [], "answers": 0}
        )

    for card in cards:
        job_id = card.get("job_id")
        fields = card.get("fields_notes")
        if isinstance(fields, Mapping):
            for key in LABELS:
                value = fields.get(key)
                if _has_text(value):
                    link = _link(value.get("note_id"), job_id)
                    if link is not None:
                        link["fields"].append(key)
        answers = card.get("note_answers")
        if isinstance(answers, Mapping):
            link = _link(answers.get("note_id"), job_id)
            if link is not None:
                link["answers"] = sum(
                    1
                    for item in _answers_items(answers)
                    if str(item.get("answer") or "").strip()
                )
    return links
