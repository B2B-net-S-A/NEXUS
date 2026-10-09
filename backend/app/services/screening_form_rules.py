"""Formularz screeningu — czyste reguły (0424), bez bazy.

Jeden formularz na parę (kandydat, rekrutacja): arkusz pytań Championa, pola
karty rekomendacji i stawka kandydata (decyzje Artura D1–D10 z 07.10.2026).
Tu żyją reguły, które nie potrzebują bazy: kiedy formularz jest tylko do
odczytu, migawka stanu pary (to, co zapisuje historia wersji), porównanie
migawek i lista zmian „przed → po” po polsku. Zapis i odczyt z bazy:
``screening_form.py``.

Migawka (``SNAPSHOT_SCHEMA``):

* ``sheet`` — treść arkusza bez znaczników „kto i kiedy” (``None`` = pusty),
* ``card`` — pola karty widoczne w formularzu (``FORM_CARD_FIELDS``):
  ``{raw, source, origin, keywords}``,
* ``rate`` — stawka kandydata pary ``{amount, unit, currency}`` albo ``None``.

Porównanie (``comparable``) bierze tylko to, co widzi człowiek: odpowiedzi,
sprawdzenia, ocenę, notatki, wartości pól i stawkę. Pochodzenie odpowiedzi
i hasła to metadane — sama ich zmiana nie jest nową wersją.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence

from app.services.candidate_rate_change import (
    DECISION_COLUMNS,
    NOTIFY_COLUMNS,
    format_rate,
)
from app.services.recommendation_card_rules import (
    CARD_ORIGINS,
    DISPLAY_LABELS,
    EDITABLE_FIELDS,
    PHRASABLE_FIELDS,
)

SNAPSHOT_SCHEMA = 1

# ── Tylko do odczytu ─────────────────────────────────────────────────────────

JOB_CLOSED = "job_closed"
PROCESS_CLOSED = "process_closed"
PROCESS_VOIDED = "process_voided"
NO_STAGE = "no_stage"

READ_ONLY_MESSAGES: dict[str, str] = {
    JOB_CLOSED: "Rekrutacja jest zamknięta — formularz screeningu jest tylko do odczytu.",
    PROCESS_CLOSED: (
        "Proces tej osoby w rekrutacji jest zakończony — formularz screeningu "
        "jest tylko do odczytu."
    ),
    PROCESS_VOIDED: (
        "Ta osoba została usunięta z rekrutacji — formularz screeningu jest "
        "tylko do odczytu."
    ),
    NO_STAGE: "Tej osoby nie ma w rekrutacji — nie ma gdzie zapisać screeningu.",
}
# Kolumny Tablicy, w których proces jest już rozstrzygnięty: zatrudnienie
# (także „Onboarding”, który procesu nie zamyka) i pasek zamkniętych.
CLOSED_COLUMNS = frozenset({"hired", "closed"})


def _value(raw: object) -> Optional[str]:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def read_only_reason(
    *,
    job_status: object,
    has_stage: bool,
    process_status: object,
    column: Optional[str],
) -> Optional[str]:
    """Dlaczego formularz pary jest tylko do odczytu — albo ``None``.

    Edycja trwa na każdym etapie, dopóki proces trwa (D8). Proces pary
    rozstrzyga jego status; para bez procesu (wiersze sprzed procesów, import)
    — kolumna najnowszego wiersza etapu.
    """
    if _value(job_status) == "closed":
        return JOB_CLOSED
    status = _value(process_status)
    if status == "voided":
        return PROCESS_VOIDED
    if not has_stage:
        return NO_STAGE
    if status == "closed" or column in CLOSED_COLUMNS:
        return PROCESS_CLOSED
    return None


# ── Treść arkusza ────────────────────────────────────────────────────────────

# Pola karty w formularzu — stawka ma własne pole (kwota, jednostka, waluta).
FORM_CARD_FIELDS: tuple[str, ...] = tuple(
    key for key in EDITABLE_FIELDS if key != "rate"
)
# „Ocena rekrutera” (sekcja 3) — reszta pól karty to „Warunki kandydata”.
ASSESSMENT_CARD_FIELDS: tuple[str, ...] = PHRASABLE_FIELDS
TERMS_CARD_FIELDS: tuple[str, ...] = tuple(
    key for key in FORM_CARD_FIELDS if key not in ASSESSMENT_CARD_FIELDS
)
# Te same napisy co w formularzu i w widoku „Screening” na froncie
# (`SCREENING_FIT_LABEL` w `lib/screening-conversations.ts`) — pilnuje test.
FIT_LABELS: dict[str, str] = {
    "fit": "Pasuje",
    "uncertain": "Niepewne",
    "miss": "Nie pasuje",
}
EXPERIENCE_STATUS_LABELS: dict[str, str] = {
    "confirmed": "potwierdził",
    "not_confirmed": "nie potwierdził",
    "unknown": "nie wiadomo",
}
DEFAULT_FIT = "uncertain"
# Odpowiedzi, przy których rekruter zostawia hasła (zdanie z haseł, notatka).
KEYWORD_ORIGINS = ("phrased", "note_import")


def _as_dict(sheet: Any) -> Optional[dict[str, Any]]:
    if sheet is None:
        return None
    if hasattr(sheet, "model_dump"):
        return sheet.model_dump(mode="json")
    if isinstance(sheet, Mapping):
        return dict(sheet)
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def answer_has_content(item: Mapping[str, Any]) -> bool:
    return (
        bool(_text(item.get("response")))
        or bool(item.get("skipped"))
        or bool(item.get("deal_breaker_hit"))
    )


def _check_has_content(item: Mapping[str, Any]) -> bool:
    return (item.get("status") or "unknown") != "unknown" or bool(
        _text(item.get("note"))
    )


def sheet_has_content(sheet: Any) -> bool:
    """Czy arkusz niesie cokolwiek z rozmowy — odpowiedź albo sprawdzenie.

    Pusty arkusz (same puste odpowiedzi) nie jest zapisywany: ``sheet_filled``
    liczy każdą pozycję odpowiedzi, więc spełniłby bramkę „Zweryfikowany”.
    Sama ocena i stara notatka z arkusza to nie rozmowa.
    """
    data = _as_dict(sheet)
    if not data:
        return False
    answers = data.get("answers")
    if isinstance(answers, list) and any(
        isinstance(item, Mapping) and answer_has_content(item) for item in answers
    ):
        return True
    checks = data.get("experience_checks")
    return isinstance(checks, list) and any(
        isinstance(item, Mapping) and _check_has_content(item) for item in checks
    )


# ── Migawka ──────────────────────────────────────────────────────────────────


def decimal_text(value: Any) -> Optional[str]:
    """Kwota jako tekst bez zbędnych zer („150”, „150.5”) — porównywalna."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not amount.is_finite():
        return None
    return f"{amount.normalize():f}"


def sheet_snapshot(sheet: Any) -> Optional[dict[str, Any]]:
    """Treść arkusza do historii (``None`` = arkusz bez żadnej treści)."""
    data = _as_dict(sheet)
    if not data:
        return None
    answers = []
    for item in data.get("answers") or []:
        if not isinstance(item, Mapping):
            continue
        question_id = _text(item.get("question_id"))
        if not question_id:
            continue
        answers.append(
            {
                "question_id": question_id,
                "response": _text(item.get("response")),
                "deal_breaker_hit": bool(item.get("deal_breaker_hit")),
                "skipped": bool(item.get("skipped")),
                "origin": item.get("origin") or "manual",
                "keywords": _text(item.get("keywords")) or None,
                "question_text": _text(item.get("question_text")) or None,
            }
        )
    checks = [
        {
            "kind": item.get("kind") or "domains",
            "name": _text(item.get("name")),
            "status": item.get("status") or "unknown",
            "note": _text(item.get("note")),
        }
        for item in data.get("experience_checks") or []
        if isinstance(item, Mapping) and _text(item.get("name"))
    ]
    out = {
        "answers": answers,
        "experience_checks": checks,
        "overall_fit": data.get("overall_fit") or DEFAULT_FIT,
        "notes": _text(data.get("notes")),
        "internal_note": _text(data.get("internal_note")) or None,
    }
    if not sheet_has_content(out) and not out["notes"] and not out["internal_note"]:
        return None
    return out


def card_snapshot(fields: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Pola karty z formularza: wartość efektywna i jej pochodzenie."""
    out: dict[str, dict[str, Any]] = {}
    for key in FORM_CARD_FIELDS:
        value = fields.get(key)
        if not isinstance(value, Mapping):
            continue
        raw = _text(value.get("raw"))
        if not raw:
            continue
        entry: dict[str, Any] = {"raw": raw, "source": value.get("source")}
        if value.get("origin") in CARD_ORIGINS:
            entry["origin"] = value["origin"]
            if _text(value.get("keywords")):
                entry["keywords"] = _text(value.get("keywords"))
        out[key] = entry
    return out


def rate_snapshot(rate: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Stawka kandydata pary ``{amount, unit, currency}`` (kwota jako tekst)."""
    if not rate or rate.get("amount") is None:
        return None
    amount = decimal_text(rate["amount"])
    if amount is None:
        return None
    return {
        "amount": amount,
        "unit": _value(rate.get("unit")),
        "currency": (_text(rate.get("currency")) or "PLN").upper(),
    }


def build_snapshot(
    *,
    sheet: Any,
    card_fields: Mapping[str, Any],
    rate: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "sheet": sheet_snapshot(sheet),
        "card": card_snapshot(card_fields),
        "rate": rate_snapshot(rate),
    }


EMPTY_SNAPSHOT: dict[str, Any] = {
    "schema": SNAPSHOT_SCHEMA,
    "sheet": None,
    "card": {},
    "rate": None,
}


def snapshot_has_content(snapshot: Optional[Mapping[str, Any]]) -> bool:
    if not snapshot:
        return False
    return bool(snapshot.get("sheet") or snapshot.get("card") or snapshot.get("rate"))


# ── Porównanie ───────────────────────────────────────────────────────────────


def sheet_view(sheet: Any) -> Optional[dict[str, Any]]:
    """To, co z arkusza widzi człowiek — klucz porównania wersji.

    Przyjmuje surowy arkusz z bazy albo migawkę (``sheet_snapshot`` jest
    idempotentne).
    """
    snap = sheet_snapshot(sheet)
    if not snap:
        return None
    return {
        "answers": {
            item["question_id"]: (
                item["response"],
                item["skipped"],
                item["deal_breaker_hit"],
            )
            for item in snap["answers"]
            if answer_has_content(item)
        },
        "experience": {
            (item["kind"], item["name"]): (item["status"], item["note"])
            for item in snap["experience_checks"]
            if _check_has_content(item)
        },
        "overall_fit": snap["overall_fit"],
        "notes": snap["notes"],
        "internal_note": snap["internal_note"],
    }


def rate_view(rate: Optional[Mapping[str, Any]]) -> Optional[tuple[Any, ...]]:
    snap = rate_snapshot(rate)
    if snap is None:
        return None
    return (snap["amount"], snap["unit"], snap["currency"])


def comparable(snapshot: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    snap = snapshot or EMPTY_SNAPSHOT
    card = snap.get("card") or {}
    return {
        "sheet": sheet_view(snap.get("sheet")),
        "card": {key: value.get("raw") for key, value in card.items()},
        "rate": rate_view(snap.get("rate")),
    }


def snapshots_equal(
    a: Optional[Mapping[str, Any]], b: Optional[Mapping[str, Any]]
) -> bool:
    return comparable(a) == comparable(b)


def sheets_equal(a: Any, b: Any) -> bool:
    return sheet_view(a) == sheet_view(b)


def card_field_differs(
    fields: Mapping[str, Any], key: str, value: Optional[str]
) -> bool:
    """Czy wartość z formularza różni się od wartości efektywnej pola.

    Pole z notatki nie staje się „ręczne” od samego zapisu bez zmiany.
    ``None``/pusty tekst zdejmuje wyłącznie pole wpisane ręcznie.
    """
    existing = fields.get(key)
    existing = existing if isinstance(existing, Mapping) else {}
    text = _text(value)
    if not text:
        return existing.get("source") == "manual"
    return text != _text(existing.get("raw"))


def state_token(snapshot: Optional[Mapping[str, Any]]) -> str:
    """Odcisk stanu pary, który widzi człowiek (``comparable``).

    ``GET`` oddaje go razem ze stanem, a zapis i przywrócenie odsyłają odcisk
    stanu, z którego formularz wziął wartości. Inny odcisk pod blokadą = ktoś
    zmienił arkusz, kartę albo stawkę obok formularza (stara trasa, automat,
    Delivery Lead) — zapis dostaje 409 zamiast cofać tę zmianę polem, którego
    rekruter nie ruszył. Sama zmiana pochodzenia pola odcisku nie zmienia.
    """
    view = comparable(snapshot)
    sheet = view["sheet"]
    if sheet is not None:
        sheet = {
            **sheet,
            "answers": sorted(
                [key, list(value)] for key, value in sheet["answers"].items()
            ),
            "experience": sorted(
                [list(key), list(value)] for key, value in sheet["experience"].items()
            ),
        }
    rate = view["rate"]
    payload = {
        "sheet": sheet,
        "card": view["card"],
        "rate": list(rate) if rate is not None else None,
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


# ── Lista zmian ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VersionChange:
    section: str  # answers | terms | assessment | rate
    key: str
    label: str
    before: Optional[str]
    after: Optional[str]

    def as_dict(self) -> dict[str, Optional[str]]:
        return asdict(self)


_QUESTION_NUMBER_RE = re.compile(r"^q(\d+)$", re.IGNORECASE)


def question_label(question_id: str, questions: Sequence[str]) -> str:
    """„Pytanie N” — numer z kolejności pytań w Profilu Championa."""
    if question_id in questions:
        return f"Pytanie {list(questions).index(question_id) + 1}"
    match = _QUESTION_NUMBER_RE.match(question_id)
    if match:
        return f"Pytanie {int(match.group(1))}"
    return f"Pytanie {question_id}"


def _question_order(question_id: str) -> tuple[int, str]:
    match = _QUESTION_NUMBER_RE.match(question_id)
    return (int(match.group(1)) if match else 10**6, question_id)


def _answer_text(item: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not item:
        return None
    text = _text(item.get("response"))
    if item.get("skipped") and not text:
        text = "pominięte"
    if item.get("deal_breaker_hit"):
        text = f"{text} (odpada)" if text else "odpada"
    return text or None


def _check_text(item: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not item or not _check_has_content(item):
        return None
    status = EXPERIENCE_STATUS_LABELS.get(item.get("status") or "unknown", "")
    note = _text(item.get("note"))
    return f"{status} — {note}" if note else status


def _rate_text(rate: Optional[Mapping[str, Any]]) -> Optional[str]:
    snap = rate_snapshot(rate)
    if snap is None:
        return None
    return format_rate(Decimal(snap["amount"]), snap["unit"], snap["currency"])


def diff_snapshots(
    before: Optional[Mapping[str, Any]],
    after: Optional[Mapping[str, Any]],
    *,
    questions: Sequence[str] = (),
) -> list[VersionChange]:
    """Zmiany „przed → po” między dwiema migawkami, po polsku.

    ``questions`` — identyfikatory pytań w kolejności Profilu Championa
    (numer pytania w etykiecie). Kolejność listy: odpowiedzi, sprawdzenia,
    warunki kandydata, ocena rekrutera, stawka.
    """
    old = before or EMPTY_SNAPSHOT
    new = after or EMPTY_SNAPSHOT
    old_sheet = sheet_snapshot(old.get("sheet"))
    new_sheet = sheet_snapshot(new.get("sheet"))
    changes: list[VersionChange] = []

    def answers(sheet: Optional[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        return {
            item["question_id"]: item
            for item in (sheet or {}).get("answers") or []
            if answer_has_content(item)
        }

    old_answers, new_answers = answers(old_sheet), answers(new_sheet)
    ids = list(questions) + sorted(
        (set(old_answers) | set(new_answers)) - set(questions), key=_question_order
    )
    for question_id in ids:
        before_text = _answer_text(old_answers.get(question_id))
        after_text = _answer_text(new_answers.get(question_id))
        if before_text != after_text:
            changes.append(
                VersionChange(
                    "answers",
                    question_id,
                    question_label(question_id, questions),
                    before_text,
                    after_text,
                )
            )

    def checks(
        sheet: Optional[Mapping[str, Any]],
    ) -> dict[tuple[str, str], Mapping[str, Any]]:
        return {
            (item["kind"], item["name"]): item
            for item in (sheet or {}).get("experience_checks") or []
            if _check_has_content(item)
        }

    old_checks, new_checks = checks(old_sheet), checks(new_sheet)
    for kind, name in sorted(set(old_checks) | set(new_checks)):
        before_text = _check_text(old_checks.get((kind, name)))
        after_text = _check_text(new_checks.get((kind, name)))
        if before_text != after_text:
            changes.append(
                VersionChange(
                    "answers",
                    f"experience:{kind}:{name}",
                    f"Sprawdź w rozmowie: {name}",
                    before_text,
                    after_text,
                )
            )

    before_note = (old_sheet or {}).get("internal_note") or None
    after_note = (new_sheet or {}).get("internal_note") or None
    if before_note != after_note:
        changes.append(
            VersionChange(
                "answers",
                "internal_note",
                "Notatka wewnętrzna (przepięcie)",
                before_note,
                after_note,
            )
        )

    old_card, new_card = old.get("card") or {}, new.get("card") or {}

    def card_change(key: str, section: str) -> None:
        before_raw = (old_card.get(key) or {}).get("raw") or None
        after_raw = (new_card.get(key) or {}).get("raw") or None
        if before_raw != after_raw:
            changes.append(
                VersionChange(
                    section, key, DISPLAY_LABELS.get(key, key), before_raw, after_raw
                )
            )

    for key in TERMS_CARD_FIELDS:
        card_change(key, "terms")

    before_fit = (old_sheet or {}).get("overall_fit") or DEFAULT_FIT
    after_fit = (new_sheet or {}).get("overall_fit") or DEFAULT_FIT
    if before_fit != after_fit:
        changes.append(
            VersionChange(
                "assessment",
                "overall_fit",
                "Ocena rekrutera",
                FIT_LABELS.get(before_fit, before_fit),
                FIT_LABELS.get(after_fit, after_fit),
            )
        )
    for key in ASSESSMENT_CARD_FIELDS:
        card_change(key, "assessment")
    before_legacy = (old_sheet or {}).get("notes") or None
    after_legacy = (new_sheet or {}).get("notes") or None
    if before_legacy != after_legacy:
        changes.append(
            VersionChange(
                "assessment", "notes", "Notatka z arkusza", before_legacy, after_legacy
            )
        )

    before_rate = _rate_text(old.get("rate"))
    after_rate = _rate_text(new.get("rate"))
    if rate_view(old.get("rate")) != rate_view(new.get("rate")):
        changes.append(
            VersionChange("rate", "rate", "Stawka kandydata", before_rate, after_rate)
        )
    return changes


def activity_fields(changes: Sequence[VersionChange]) -> list[str]:
    """Nazwy zmienionych pól do dziennika zdarzeń — bez wartości.

    Klucz sprawdzenia niesie nazwę wymagania z Profilu Championa, więc
    w dzienniku stoi samo ``experience``.
    """
    return sorted(
        {
            "experience" if change.key.startswith("experience:") else change.key
            for change in changes
        }
    )


# ── Przywracanie wersji ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RestorePlan:
    """Stan pary z wersji, który ma przywrócić aplikator formularza."""

    sheet: Optional[dict[str, Any]]  # kształt ``ScreeningAnswers`` albo None
    card: dict[str, Optional[str]]
    card_origins: dict[str, dict[str, Any]]
    rate: Optional[dict[str, Any]]
    skipped_answers: tuple[str, ...]


def restore_plan(
    snapshot: Mapping[str, Any],
    *,
    current_sheet: Any,
    questions: Mapping[str, str],
) -> RestorePlan:
    """Co przywrócić z migawki wersji.

    * Arkusz wraca w całości, z jednym wyjątkiem: odpowiedź na pytanie, którego
      treść w Profilu Championa się zmieniła (albo pytania już nie ma),
      zostaje bieżąca — kandydat odpowiadał na inne pytanie
      (``skipped_answers`` = etykiety takich pytań).
    * Pola karty wracają do wartości z wersji; pole, którego w wersji nie było,
      traci wpis ręczny (wartość z notatki zostaje).
    * Stawkę zwraca się jak w wersji — o jej zapisie (kolumna Tablicy)
      decyduje aplikator.
    """
    order = list(questions)
    sheet_plan: Optional[dict[str, Any]] = None
    skipped: list[str] = []
    snap_sheet = snapshot.get("sheet")
    if isinstance(snap_sheet, Mapping):
        current = sheet_snapshot(current_sheet) or {}
        current_answers = {
            item["question_id"]: item for item in current.get("answers") or []
        }
        snap_answers = [
            item
            for item in snap_sheet.get("answers") or []
            if isinstance(item, Mapping)
        ]
        answers: list[dict[str, Any]] = []
        for item in snap_answers:
            question_id = _text(item.get("question_id"))
            text = questions.get(question_id)
            stored = _text(item.get("question_text")) or None
            changed = text is None or (stored is not None and stored != text.strip())
            if changed:
                if answer_has_content(item):
                    skipped.append(question_label(question_id, order))
                kept = current_answers.get(question_id)
                if kept is not None and text is not None:
                    answers.append(_answer_payload(kept))
                continue
            answers.append(_answer_payload(item))
        # Pytanie, którego wersja w ogóle nie znała (dopisane do profilu
        # później), zachowuje bieżącą odpowiedź.
        known = {_text(item.get("question_id")) for item in snap_answers}
        answers.extend(
            _answer_payload(item)
            for question_id, item in current_answers.items()
            if question_id not in known and question_id in questions
        )
        answers.sort(
            key=lambda item: (
                order.index(item["question_id"])
                if item["question_id"] in order
                else len(order)
            )
        )
        sheet_plan = {
            "answers": answers,
            "experience_checks": [
                {
                    "kind": item.get("kind") or "domains",
                    "name": item.get("name"),
                    "status": item.get("status") or "unknown",
                    "note": item.get("note") or "",
                }
                for item in snap_sheet.get("experience_checks") or []
                if isinstance(item, Mapping) and _text(item.get("name"))
            ],
            "overall_fit": snap_sheet.get("overall_fit") or DEFAULT_FIT,
            "notes": snap_sheet.get("notes") or "",
            "internal_note": snap_sheet.get("internal_note") or None,
        }
    snap_card = snapshot.get("card") or {}
    card: dict[str, Optional[str]] = {}
    origins: dict[str, dict[str, Any]] = {}
    for key in FORM_CARD_FIELDS:
        value = snap_card.get(key)
        raw = _text(value.get("raw")) if isinstance(value, Mapping) else ""
        card[key] = raw or None
        if raw and value.get("origin") in CARD_ORIGINS:
            origins[key] = {
                "origin": value["origin"],
                "keywords": value.get("keywords"),
            }
    return RestorePlan(
        sheet=sheet_plan,
        card=card,
        card_origins=origins,
        rate=rate_snapshot(snapshot.get("rate")),
        skipped_answers=tuple(skipped),
    )


RATE_MANAGED_BY_DL = "managed_by_dl"
RATE_NOT_IN_VERSION = "not_in_version"


def rate_not_restored_reason(
    *,
    mode: str,
    target_rate: Optional[Mapping[str, Any]],
    current_rate: Optional[Mapping[str, Any]],
    column: Optional[str],
    rate_differs: bool,
) -> Optional[str]:
    """Czemu przywrócenie zostawia bieżącą stawkę (``None`` = stawka wraca).

    * ``managed_by_dl`` — „Przywróć” od „Zweryfikowany”: zmianą stawki zarządza
      Delivery Lead (0418), formularz jej nie cofa;
    * ``not_in_version`` — wersja nie miała stawki, a stawka już jest: zdjęcie
      stawki z wiersza etapu nie jest zmianą stawki (``change_rate`` zna tylko
      kwoty), więc zostaje i mówimy to wprost.
    """
    if target_rate is None:
        return RATE_NOT_IN_VERSION if current_rate is not None else None
    if mode == "restore" and rate_differs and column in NOTIFY_COLUMNS:
        return RATE_MANAGED_BY_DL
    return None


def restore_rate_reason(*, mode: str, column: Optional[str]) -> str:
    """Powód zmiany stawki przy przywróceniu (``change_rate``).

    „Cofnij” to poprawka pomyłki (``typo`` — bez zadania dla DL), ale nie
    w kolumnach, w których podwyżka czeka na decyzję DL (``DECISION_COLUMNS``):
    tam „Cofnij” podnoszące stawkę musi otworzyć zadanie jak każda podwyżka.
    """
    if mode == "undo" and column not in DECISION_COLUMNS:
        return "typo"
    return "other"


def _answer_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    origin = item.get("origin") or "manual"
    return {
        "question_id": item.get("question_id"),
        "response": item.get("response") or "",
        "deal_breaker_hit": bool(item.get("deal_breaker_hit")),
        "skipped": bool(item.get("skipped")),
        "origin": origin,
        "keywords": (item.get("keywords") or None)
        if origin in KEYWORD_ORIGINS
        else None,
    }
