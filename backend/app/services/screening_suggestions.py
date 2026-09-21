"""Podpowiedzi stawki i dostępności do arkusza screeningu (21.09.2026).

Czysty odczyt ``candidates.cv_extracted_data._notes_insights`` — faktów, które
cykliczna ekstrakcja notatek (`notes_insights_extractor`) już wyciągnęła. Zero
wywołań modelu, zero zapisów: to PODPOWIEDŹ do pola, a rekruter ją przyjmuje
albo nie. Jeśli kiedyś ma się zapisywać sama — to osobna decyzja produktowa.

``_notes_insights`` jest agregatem ze WSZYSTKICH notatek kandydata i nie
pamięta, z której notatki pochodzi dana wartość, więc ``source_note_id`` jest
dziś zawsze ``None`` (pole zostaje w kontrakcie dla frontu). ``noted_at`` to
``as_of`` stawki (``RRRR-MM`` z treści notatki), a w jego braku chwila ekstrakcji.
"""

from __future__ import annotations

import math
from typing import Any, Optional

_UNITS = {"h": "hour", "md": "day", "month": "month"}
_MAX_TEXT = 200


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean[:_MAX_TEXT] if clean else None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def suggestions_from_notes(candidate, *, include_rate: bool) -> dict:
    """``{"rate"?: {...}, "availability"?: {...}, "rate_redacted": bool}``.

    Klucz ``rate`` / ``availability`` jest NIEOBECNY, gdy notatki nic nie niosą —
    front nie ma rysować pustej podpowiedzi. ``rate_redacted`` mówi, że stawka
    istnieje, ale ta rola jej nie widzi (inaczej brak wyglądałby jak brak danych).
    """
    extracted = getattr(candidate, "cv_extracted_data", None)
    insights = extracted.get("_notes_insights") if isinstance(extracted, dict) else None
    out: dict = {"rate_redacted": False}
    if not isinstance(insights, dict):
        return out
    extracted_at = _text(insights.get("_extracted_at"))
    source_note_id = insights.get("_source_note_id")
    source_note_id = source_note_id if isinstance(source_note_id, int) else None

    rate = insights.get("expected_rate")
    if isinstance(rate, dict) and (value := _number(rate.get("value"))) is not None:
        if include_rate:
            period = rate.get("period")
            out["rate"] = {
                "value": value,
                "unit": _UNITS.get(period) if isinstance(period, str) else None,
                "currency": (_text(rate.get("currency")) or "").upper() or None,
                "raw": _text(rate.get("raw")),
                "source_note_id": source_note_id,
                "noted_at": _text(rate.get("as_of")) or extracted_at,
            }
        else:
            out["rate_redacted"] = True

    availability = insights.get("availability")
    if isinstance(availability, dict):
        fields = {
            "raw": _text(availability.get("raw")),
            "notice_period": _text(availability.get("notice_period")),
            "available_from": _text(availability.get("available_from")),
        }
        if any(fields.values()):
            out["availability"] = {
                **fields,
                "source_note_id": source_note_id,
                "noted_at": extracted_at,
            }
    return out
