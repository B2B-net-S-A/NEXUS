"""Filtr doświadczenia w rekrutacji: czyste funkcje na odczytanym CV.

Progi i wzorce zmierzone na kopii produkcji z 09.11.2026. Filtr nie decyduje
o odrzuceniu: rozdziela zakładki, a człowiek widzi każdą z nich.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

_RECRUITER_ROLE = re.compile(
    r"rekrut|recruit|talent acq|talent partner|sourcer|sourcing|headhunt", re.I
)
_HR_ROLE = re.compile(r"(^|[^a-z])(hr|kadr|personal|human res|people partner)", re.I)
_RECRUITING_DUTY = re.compile(r"rekrut|recruit|sourcing|headhunt", re.I)
_IT_CONTEXT = re.compile(
    r"\bIT\b|\b(tech|technical|developer|programist\w*|software|devops)\b"
)
_PRESENT = {"", "present", "obecnie", "now", "current", "teraz"}
_MONTH = re.compile(r"^(\d{4})(?:-(\d{1,2}))?$")


@dataclass(frozen=True)
class Verdict:
    bucket: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _month_index(value: Any, *, today: date, is_end: bool) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text in _PRESENT:
        return today.year * 12 + today.month - 1 if is_end else None
    match = _MONTH.match(text)
    if match is None:
        return None
    month = int(match.group(2) or (12 if is_end else 1))
    if not 1 <= month <= 12:
        return None
    return int(match.group(1)) * 12 + month - 1


def _merged_months(spans: list[tuple[int, int]]) -> int:
    """Suma miesięcy bez podwójnego liczenia równoległych stanowisk."""
    total = 0
    current: Optional[tuple[int, int]] = None
    for start, end in sorted(spans):
        if current is None or start > current[1]:
            if current is not None:
                total += current[1] - current[0] + 1
            current = (start, end)
        else:
            current = (current[0], max(current[1], end))
    if current is not None:
        total += current[1] - current[0] + 1
    return total


def _text(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def _evidence(entries: list[dict[str, Any]], today: date) -> dict[str, Any]:
    spans: list[tuple[int, int]] = []
    for entry in entries:
        start = _month_index(entry.get("start"), today=today, is_end=False)
        end = _month_index(entry.get("end"), today=today, is_end=True)
        if start is not None and end is not None and end >= start:
            spans.append((start, end))
    first = entries[0]
    end_text = _text(first, "end").strip()
    return {
        "role": _text(first, "role")[:160],
        "company": _text(first, "company")[:160],
        "months": _merged_months(spans) if spans else None,
        "until": None if end_text.lower() in _PRESENT else end_text[:20],
        "is_it": any(
            _IT_CONTEXT.search(f"{_text(e, 'role')} {_text(e, 'desc')}")
            for e in entries
        ),
    }


def classify(experience: Any, today: date) -> Verdict:
    """Zakładka zgłoszenia na podstawie ``candidates.experience``."""
    entries = (
        [e for e in experience if isinstance(e, dict)]
        if isinstance(experience, list)
        else []
    )
    if not entries:
        return Verdict("review", "cv_unread")

    recruiter = [e for e in entries if _RECRUITER_ROLE.search(_text(e, "role"))]
    if recruiter:
        return Verdict("match", "role", _evidence(recruiter, today))

    with_duty = [e for e in entries if _RECRUITING_DUTY.search(_text(e, "desc"))]
    hr_duty = [e for e in with_duty if _HR_ROLE.search(_text(e, "role"))]
    if hr_duty:
        return Verdict("match", "hr_duty", _evidence(hr_duty, today))
    if with_duty:
        return Verdict("review", "mention", _evidence(with_duty, today))
    return Verdict("filtered", "none")


_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_OFFER_NOTE = re.compile(
    r"^Źródło:\s*(?P<source>.*?)\s*[—-]\s*oferta:\s*(?P<title>.+)$"
)


def normalize_title(value: str) -> str:
    """Tytuł ogłoszenia do porównania: portale wklejają znaki niewidoczne."""
    return " ".join(_INVISIBLE.sub("", value).split()).casefold()


def parse_offer_note(note: Optional[str]) -> Optional[tuple[str, str]]:
    """Notatka scrapera → (źródło, tytuł ogłoszenia)."""
    match = _OFFER_NOTE.match((note or "").strip())
    if match is None:
        return None
    return match.group("source").strip(), match.group("title").strip()
