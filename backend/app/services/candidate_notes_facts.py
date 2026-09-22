"""Fakty z notatek rekruterów pokazane na profilu kandydata (22.09.2026).

Czyta wynik cyklicznej ekstrakcji (`cv_extracted_data._notes_insights`,
`notes_insights_extractor`) i układa go w widok „co notatki mówią, a co jest
w profilu”, z wartością gotową do zapisania jednym kliknięciem. Zero wywołań
modelu: to przeliczenia deterministyczne na już zapisanych faktach.

Trzy reguły, których pilnują testy:

- **Stawka jest PRZELICZANA, ale nigdy nie zapisywana sama.** Stawka za dzień
  (÷ 8) i miesięczna (÷ 168 — ta sama stała co `lib/rate-to-hourly.ts`) daje
  godzinowy odpowiednik do potwierdzenia. Inna waluta niż PLN nie jest
  przeliczana wcale (kurs z dnia rozmowy nie jest nam znany).
- **Tryb pracy liczy się z dni w biurze.** Kandydat, który akceptuje N dni
  w biurze, akceptuje każdą pracę wymagającą co najwyżej N dni: 0 = zdalnie,
  1–4 = też hybrydowo, 5+ = też stacjonarnie. Ta sama reguła co bramka dni
  w biurze w wyszukiwaniu (`max_onsite_days_per_week >= wymóg oferty`), więc
  tryb zapisany z notatek nie odrzuci oferty, którą bramka przepuszcza.
- **Zapis nadpisuje profil tylko na wyraźne kliknięcie** (`apply_notes_fact`),
  a wartość zawsze wylicza serwer z zapisanych faktów — przeglądarka wskazuje
  wyłącznie POLE, nigdy wartość.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, Optional

from sqlalchemy.orm.attributes import flag_modified

WORK_MODES: tuple[str, ...] = ("remote", "hybrid", "onsite")
# Godziny w miesiącu i w dniu — lustro `frontend/src/lib/rate-to-hourly.ts`.
HOURS_PER_MONTH = Decimal("168")
HOURS_PER_DAY = Decimal("8")
MAX_HOURLY_PLN = Decimal("2000")
FULL_OFFICE_DAYS = 5

NotesFactField = Literal[
    "rate", "work_mode", "contract_form", "availability", "office_cities"
]
NOTES_FACT_FIELDS: tuple[str, ...] = (
    "rate",
    "work_mode",
    "contract_form",
    "availability",
    "office_cities",
)

_CONTRACT_TYPES = {"b2b": ["b2b"], "uop": ["uop"], "any": ["b2b", "uop"]}
_NOTICE_RE = re.compile(
    r"(\d+)\s*(tydz|tyg|week|mies|miesiąc|miesiec|month|dni|dzień|dzien|day|mc)",
    re.I,
)
_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_MAX_TEXT = 300


def notes_insights(candidate: Any) -> Optional[dict]:
    """`cv_extracted_data._notes_insights` albo None (dane bywają listą)."""
    data = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(data, dict):
        return None
    insights = data.get("_notes_insights")
    return insights if isinstance(insights, dict) else None


def _text(value: Any, limit: int = _MAX_TEXT) -> Optional[str]:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean[:limit] if clean else None


def _texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item, 120)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def _int_days(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 7 else None


# ── Stawka ────────────────────────────────────────────────────────────────


def hourly_from_notes_rate(rate: Any) -> Optional[dict]:
    """Stawka z notatek + godzinowy odpowiednik PLN (albo None, gdy nie ma liczby).

    ``hourly_pln`` jest ``None`` dla innej waluty, nieznanej jednostki albo
    wyniku poza rozsądnym zakresem — wtedy profil dostaje tylko tekst notatki.
    """
    if not isinstance(rate, dict):
        return None
    raw_value = rate.get("value")
    if isinstance(raw_value, bool) or raw_value is None:
        return None
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    currency = (_text(rate.get("currency"), 8) or "").upper() or None
    period = rate.get("period") if rate.get("period") in ("h", "md", "month") else None
    hourly: Optional[Decimal] = None
    if currency == "PLN" and period is not None:
        divisor = {
            "h": Decimal("1"),
            "md": HOURS_PER_DAY,
            "month": HOURS_PER_MONTH,
        }[period]
        candidate_value = (value / divisor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if Decimal("0") < candidate_value < MAX_HOURLY_PLN:
            hourly = candidate_value
    return {
        "value": value,
        "currency": currency,
        "period": period,
        "raw": _text(rate.get("raw")),
        "as_of": _text(rate.get("as_of"), 10),
        "hourly_pln": hourly,
    }


# ── Tryb pracy ────────────────────────────────────────────────────────────


def modes_for_office_days(days: int) -> list[str]:
    """Tryby akceptowane przy limicie N dni w biurze (domknięcie w dół)."""
    modes = ["remote"]
    if days >= 1:
        modes.append("hybrid")
    if days >= FULL_OFFICE_DAYS:
        modes.append("onsite")
    return modes


def _ordered_modes(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    wanted = {str(v).strip().lower() for v in values if isinstance(v, str)}
    return [mode for mode in WORK_MODES if mode in wanted]


def work_mode_from_insights(insights: Any) -> Optional[dict]:
    """``{"modes": [...], "max_onsite_days": int|None}`` z faktów notatek.

    Dni: liczba podana wprost > „tylko zdalnie” (0) > „stacjonarnie” (5).
    Tryby: z dni, gdy są znane; inaczej z trybów nazwanych w notatkach,
    domkniętych w dół (hybrydowo ⇒ także zdalnie, stacjonarnie ⇒ wszystkie).
    Brak jakiegokolwiek sygnału = None.
    """
    if not isinstance(insights, dict):
        return None
    prefs = insights.get("preferences")
    prefs = prefs if isinstance(prefs, dict) else {}
    named = _ordered_modes(prefs.get("work_modes"))
    remote_only = prefs.get("remote_only") is True
    days = _int_days(prefs.get("max_onsite_days_per_week"))
    if days is None and remote_only:
        days = 0
    if days is None and "onsite" in named:
        days = FULL_OFFICE_DAYS
    if days is not None:
        return {"modes": modes_for_office_days(days), "max_onsite_days": days}
    if not named:
        return None
    if "hybrid" in named:
        return {"modes": ["remote", "hybrid"], "max_onsite_days": None}
    return {"modes": named, "max_onsite_days": None}


def profile_work_mode(candidate: Any) -> dict:
    """Tryb pracy zapisany w profilu (preferencje + kolumna dni w biurze)."""
    prefs = getattr(candidate, "preferences", None)
    prefs = prefs if isinstance(prefs, dict) else {}
    return {
        "modes": _ordered_modes(prefs.get("remote_modes")),
        "max_onsite_days": _int_days(
            getattr(candidate, "max_onsite_days_per_week", None)
        ),
    }


def _set_preference(candidate: Any, key: str, value: Any) -> None:
    prefs = getattr(candidate, "preferences", None)
    merged = dict(prefs) if isinstance(prefs, dict) else {}
    if value in (None, []):
        merged.pop(key, None)
    else:
        merged[key] = value
    candidate.preferences = merged
    flag_modified(candidate, "preferences")


def set_profile_work_mode(
    candidate: Any, *, modes: list[str], max_onsite_days: Optional[int]
) -> dict:
    """Zapisz tryb pracy (preferencje + kolumna). Zwraca stan przed/po do audytu."""
    before = profile_work_mode(candidate)
    _set_preference(candidate, "remote_modes", _ordered_modes(modes) or None)
    candidate.max_onsite_days_per_week = max_onsite_days
    return {"before": before, "after": profile_work_mode(candidate)}


def fill_work_mode_from_notes(candidate: Any, insights: Any) -> dict[str, int]:
    """FILL_EMPTY z ekstrakcji: tryby do `preferences.remote_modes`, dni do kolumny.

    Wartość wpisaną przez człowieka zostawiamy zawsze — każde pole osobno.
    """
    stats = {"remote_modes_filled": 0, "onsite_days_filled": 0}
    derived = work_mode_from_insights(insights)
    if derived is None:
        return stats
    current = profile_work_mode(candidate)
    if not current["modes"] and derived["modes"]:
        _set_preference(candidate, "remote_modes", derived["modes"])
        stats["remote_modes_filled"] = 1
    if (
        getattr(candidate, "max_onsite_days_per_week", None) is None
        and derived["max_onsite_days"] is not None
    ):
        candidate.max_onsite_days_per_week = derived["max_onsite_days"]
        stats["onsite_days_filled"] = 1
    return stats


# ── Dostępność ────────────────────────────────────────────────────────────


def parse_notice(raw: Any) -> Optional[tuple[int, str]]:
    if not isinstance(raw, str):
        return None
    match = _NOTICE_RE.search(raw)
    if not match:
        return None
    number, unit = int(match.group(1)), match.group(2).lower()
    if unit.startswith(("tydz", "tyg", "week")):
        return number, "weeks"
    if unit.startswith(("mies", "month", "mc")):
        return number, "months"
    return number, "days"


def parse_available_from(raw: Any) -> Optional[date]:
    match = _ISO_RE.search(str(raw or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _availability_from_insights(insights: dict) -> Optional[dict]:
    availability = insights.get("availability")
    if not isinstance(availability, dict):
        return None
    raw = _text(availability.get("raw"))
    notice_text = _text(availability.get("notice_period"))
    from_text = _text(availability.get("available_from"))
    if not (raw or notice_text or from_text):
        return None
    notice = parse_notice(notice_text) or parse_notice(raw)
    available_from = parse_available_from(from_text)
    return {
        "raw": raw,
        "notice_period_text": notice_text,
        "available_from_text": from_text,
        "notice_period": notice[0] if notice else None,
        "notice_period_unit": notice[1] if notice else None,
        "available_from": available_from,
    }


# ── Widok ─────────────────────────────────────────────────────────────────


def _engagement(insights: dict) -> Optional[dict]:
    value = insights.get("current_engagement")
    if not isinstance(value, dict):
        return None
    out = {
        "employer": _text(value.get("employer"), 120),
        "project": _text(value.get("project"), 160),
        "ends_at": _text(value.get("ends_at"), 60),
        "raw": _text(value.get("raw")),
    }
    return out if any(out.values()) else None


def _relocation(insights: dict) -> Optional[dict]:
    value = insights.get("relocation")
    if not isinstance(value, dict):
        return None
    willing = value.get("willing") if isinstance(value.get("willing"), bool) else None
    targets = _texts(value.get("targets"))
    if willing is None and not targets:
        return None
    return {"willing": willing, "targets": targets}


def _languages(insights: dict) -> list[dict]:
    value = insights.get("languages_observed")
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value:
        if isinstance(item, dict) and _text(item.get("name"), 60):
            out.append(
                {
                    "name": _text(item.get("name"), 60),
                    "level": _text(item.get("level"), 40),
                }
            )
        elif isinstance(item, str) and _text(item, 60):
            out.append({"name": _text(item, 60), "level": None})
    return out[:10]


def _vetoes(insights: dict) -> list[dict]:
    value = insights.get("client_vetoes")
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value:
        if isinstance(item, dict) and _text(item.get("client"), 120):
            out.append(
                {
                    "client": _text(item.get("client"), 120),
                    "reason": _text(item.get("reason"), 200),
                }
            )
    return out[:10]


def build_notes_facts(candidate: Any) -> dict:
    """Pełny widok faktów z notatek + to, co dziś jest w profilu."""
    insights = notes_insights(candidate)
    base: dict[str, Any] = {
        "candidate_id": candidate.id,
        "extracted_at": None,
        "has_facts": False,
        "rate": None,
        "work_mode": None,
        "contract_form": None,
        "availability": None,
        "office_cities": None,
        "relocation": None,
        "current_engagement": None,
        "not_looking_until": None,
        "languages": [],
        "sectors_prefer": [],
        "sectors_avoid": [],
        "client_vetoes": [],
        "matching_facts": None,
    }
    if insights is None:
        return base
    base["extracted_at"] = _text(insights.get("_extracted_at"), 40)

    rate = hourly_from_notes_rate(insights.get("expected_rate"))
    if rate is not None:
        from app.services.candidate_profile_rate import (
            canonical_profile_rate_amount,
        )

        profile_amount = canonical_profile_rate_amount(
            getattr(candidate, "expected_rate_hourly", None),
            getattr(candidate, "expected_rate_currency", None),
        )
        base["rate"] = {
            **rate,
            "profile_amount": profile_amount,
            "profile_rate_version": getattr(candidate, "profile_rate_version", 0) or 0,
            "can_apply": rate["hourly_pln"] is not None
            and profile_amount != rate["hourly_pln"],
            "flexibility": _text(insights.get("rate_flexibility")),
        }

    derived = work_mode_from_insights(insights)
    if derived is not None:
        profile = profile_work_mode(candidate)
        base["work_mode"] = {
            **derived,
            "profile_modes": profile["modes"],
            "profile_max_onsite_days": profile["max_onsite_days"],
            "can_apply": derived["modes"] != profile["modes"]
            or (
                derived["max_onsite_days"] is not None
                and derived["max_onsite_days"] != profile["max_onsite_days"]
            ),
        }

    contract_form = insights.get("contract_form_preference")
    if contract_form in _CONTRACT_TYPES:
        prefs = getattr(candidate, "preferences", None)
        prefs = prefs if isinstance(prefs, dict) else {}
        current = [t for t in prefs.get("contract_types") or [] if isinstance(t, str)]
        base["contract_form"] = {
            "value": contract_form,
            "profile_contract_types": current,
            "can_apply": sorted(current) != sorted(_CONTRACT_TYPES[contract_form]),
        }

    availability = _availability_from_insights(insights)
    if availability is not None:
        profile_notice = getattr(candidate, "notice_period", None)
        profile_unit = getattr(candidate, "notice_period_unit", None)
        profile_date = getattr(candidate, "availability_date", None)
        parsed_differs = (
            availability["available_from"] is not None
            and availability["available_from"] != profile_date
        ) or (
            availability["available_from"] is None
            and availability["notice_period"] is not None
            and (
                availability["notice_period"] != profile_notice
                or availability["notice_period_unit"] != profile_unit
            )
        )
        base["availability"] = {
            **availability,
            "profile_notice_period": profile_notice,
            "profile_notice_period_unit": profile_unit,
            "profile_availability_date": profile_date,
            "can_apply": parsed_differs,
        }

    prefs_ins = insights.get("preferences")
    prefs_ins = prefs_ins if isinstance(prefs_ins, dict) else {}
    cities = _texts(prefs_ins.get("locations"))[:10]
    if cities:
        prefs = getattr(candidate, "preferences", None)
        prefs = prefs if isinstance(prefs, dict) else {}
        current_cities = _texts(prefs.get("office_cities"))
        base["office_cities"] = {
            "cities": cities,
            "profile_office_cities": current_cities,
            "can_apply": [c.casefold() for c in cities]
            != [c.casefold() for c in current_cities],
        }
    base["sectors_prefer"] = _texts(prefs_ins.get("sectors_prefer"))[:10]
    base["sectors_avoid"] = _texts(prefs_ins.get("sectors_avoid"))[:10]
    base["relocation"] = _relocation(insights)
    base["current_engagement"] = _engagement(insights)
    base["not_looking_until"] = _text(insights.get("not_looking_until"), 120)
    base["languages"] = _languages(insights)
    base["client_vetoes"] = _vetoes(insights)
    base["matching_facts"] = _text(insights.get("matching_facts"), 800)
    base["has_facts"] = any(
        base[key]
        for key in (
            "rate",
            "work_mode",
            "contract_form",
            "availability",
            "office_cities",
            "relocation",
            "current_engagement",
            "not_looking_until",
            "languages",
            "sectors_prefer",
            "sectors_avoid",
            "client_vetoes",
            "matching_facts",
        )
    )
    return base


class NotesFactUnavailable(ValueError):
    """Pole nie ma w notatkach wartości, którą da się zapisać w profilu."""


def apply_notes_fact(candidate: Any, field: str) -> dict:
    """Zapisz w profilu wartość wyliczoną z notatek. Zwraca szczegóły do audytu.

    Mutuje obiekt ORM (bez commitu). Stawkę zapisuje przez
    `write_profile_rate` — wołający dopisuje audyt stawki i unieważnia scoring.
    """
    insights = notes_insights(candidate)
    if insights is None:
        raise NotesFactUnavailable(field)
    extracted = dict(candidate.cv_extracted_data)

    if field == "rate":
        rate = hourly_from_notes_rate(insights.get("expected_rate"))
        if rate is None or rate["hourly_pln"] is None:
            raise NotesFactUnavailable(field)
        from app.services.candidate_profile_rate import write_profile_rate

        details = write_profile_rate(
            candidate, rate["hourly_pln"], source="notes_confirmed"
        )
        extracted["_manual_override_rate"] = True
        extracted["_notes_insights"] = {
            key: value
            for key, value in insights.items()
            if key not in {"_rate_from_notes", "_rate_written"}
        }
        candidate.cv_extracted_data = extracted
        flag_modified(candidate, "cv_extracted_data")
        return {"field": field, "rate_audit": details, "period": rate["period"]}

    if field == "work_mode":
        derived = work_mode_from_insights(insights)
        if derived is None:
            raise NotesFactUnavailable(field)
        days = derived["max_onsite_days"]
        if days is None:
            days = getattr(candidate, "max_onsite_days_per_week", None)
        change = set_profile_work_mode(
            candidate, modes=derived["modes"], max_onsite_days=days
        )
        return {"field": field, **change}

    if field == "contract_form":
        value = insights.get("contract_form_preference")
        if value not in _CONTRACT_TYPES:
            raise NotesFactUnavailable(field)
        _set_preference(candidate, "contract_types", list(_CONTRACT_TYPES[value]))
        return {"field": field, "value": value}

    if field == "availability":
        availability = _availability_from_insights(insights)
        if availability is None:
            raise NotesFactUnavailable(field)
        if availability["available_from"] is not None:
            candidate.availability_date = availability["available_from"]
            return {"field": field, "set": "availability_date"}
        if availability["notice_period"] is not None:
            candidate.notice_period = availability["notice_period"]
            candidate.notice_period_unit = availability["notice_period_unit"]
            return {"field": field, "set": "notice_period"}
        raise NotesFactUnavailable(field)

    if field == "office_cities":
        prefs_ins = insights.get("preferences")
        cities = (
            _texts(prefs_ins.get("locations"))[:10]
            if isinstance(prefs_ins, dict)
            else []
        )
        if not cities:
            raise NotesFactUnavailable(field)
        _set_preference(candidate, "office_cities", cities)
        return {"field": field, "count": len(cities)}

    raise NotesFactUnavailable(field)
