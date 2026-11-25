"""Lata doświadczenia w formularzu CV klienta liczy kod, nie model (19.11.2026).

DL CEZ: „nie daje rady odczytać lat doświadczenia w danej technologii i trzeba
ręcznie”. Pomiar na stagingu („Tester” CEZ, trzy osoby): 0 z 9 pól „Liczba lat
doświadczenia” u każdej — model nie liczy dat, a pole bez wyliczenia pomija.
Decyzja Artura (wariant B z makiet 19.11.2026):

* model oddaje STANOWISKA z CV (firma, rola, okres, cytat z datami) i przy
  każdym polu lat — które stanowiska tę kompetencję wymieniają: „wprost”
  (opis roli nazywa kompetencję) albo „pośrednio” (praca roli jej wymaga),
  z cytatem; sama lista umiejętności lat nie daje,
* KOD sprawdza cytaty i daty (jak ``client_form_fill``), liczy miesiące jak
  ``cv_tenure_checks`` (nakładki raz, „obecnie” do bieżącego miesiąca, rok bez
  miesiąca od stycznia do grudnia) i wpisuje „3 lata 8 mies.”,
* domyślnie liczą się role „wprost” i „pośrednio” — rekruter zdejmuje rolę
  w siatce okna formularza (``recompute``),
* punkty tabeli punktowej z lat: progi z zasad oceny („od 3 lat — 3 pkt”),
  których liczby muszą stać w cytacie z zasad.

Pole bez żadnej roli zostaje puste z pytaniem do screeningu (``question``).
Wynik siedzi w ``fields[id]["years"]`` — bez nowej kolumny w bazie.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from app.services.cv_ongoing import ONGOING_WORDS
from app.services.cv_tenure_checks import months_text, union_months

LEVEL_ROLE = "role"
LEVEL_IMPLIED = "implied"
LEVELS = (LEVEL_ROLE, LEVEL_IMPLIED)
KIND_TOTAL = "total"
KIND_COMPETENCY = "competency"
KIND_POINTS = "points"

ROLES_MAX = 30
TEXT_MAX = 200
QUOTE_MAX = 600
THRESHOLDS_MAX = 10

YEARS_LABEL = re.compile(r"liczba\s+lat|\blat\w*\s+do[sś]wiadcz", re.IGNORECASE)
TOTAL_LABEL = re.compile(r"[łl][aą]czn", re.IGNORECASE)
# Wiersz testu u klienta i wolny wiersz tabeli to nie lata z CV.
NOT_YEARS_ROW = re.compile(r"^\s*(?:test\b|wiersz\s+\d)", re.IGNORECASE)
# „Staż pracy liczony w latach ponad minimalne wymagania opisane w OPZ”.
OVER_MINIMUM = re.compile(r"\bponad\s+minim", re.IGNORECASE)
_MONTH = re.compile(r"^\s*((?:19|20)\d{2})(?:\s*-\s*(0[1-9]|1[0-2]))?\s*$")
_ONGOING_END = re.compile(rf"^\s*{ONGOING_WORDS}\s*$", re.IGNORECASE)
_KEY = re.compile(r"^[\w-]{1,20}$")

YearMonth = tuple[int, Optional[int]]


def years_fields(structure: dict[str, Any]) -> dict[str, str]:
    """Pola lat wzoru: id → ``total`` (łączny staż) albo ``competency``.

    Bez wiersza testu u klienta („Test sprawdzający wiedzę”) i wolnych wierszy
    „Wiersz N” — tam nazwę kompetencji i lata wpisuje model jak dotąd.
    """
    found: dict[str, str] = {}
    for item in structure.get("fields") or []:
        label = item.get("label") or ""
        if not YEARS_LABEL.search(label) or NOT_YEARS_ROW.match(
            item.get("row_label") or ""
        ):
            continue
        found[item["id"]] = KIND_TOTAL if TOTAL_LABEL.search(label) else KIND_COMPETENCY
    return found


def _month(value: Any) -> Optional[YearMonth]:
    if not isinstance(value, str):
        return None
    match = _MONTH.match(value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def _text(value: Any) -> str:
    return (
        re.sub(r"\s+", " ", value).strip()[:TEXT_MAX] if isinstance(value, str) else ""
    )


def _bounds(
    start: YearMonth, end: Optional[YearMonth], today: date
) -> Optional[tuple[int, int]]:
    """Numery miesięcy roli; ``None`` przy odwróconych datach. Jak ``cv_tenure_checks``."""
    now = today.year * 12 + today.month - 1
    first = start[0] * 12 + (start[1] or 1) - 1
    last = now if end is None else end[0] * 12 + (end[1] or 12) - 1
    last = min(last, now)
    return (first, last) if last >= first else None


def _iso(value: Optional[YearMonth]) -> Optional[str]:
    if value is None:
        return None
    year, month = value
    return f"{year}-{month:02d}" if month else str(year)


def period_text(start: Optional[str], end: Optional[str]) -> str:
    """„12.2021 – 09.2022”, „2022 – obecnie” — jak okres w formularzu."""

    def show(value: Optional[str]) -> str:
        parsed = _month(value)
        if parsed is None:
            return "obecnie"
        year, month = parsed
        return f"{month:02d}.{year}" if month else str(year)

    return f"{show(start)} – {show(end)}"


def check_roles(
    raw_roles: Any, grounded: Any, date_in_quote: Any, ongoing: re.Pattern[str]
) -> dict[str, dict[str, Any]]:
    """Stanowiska od modelu, które przeszły kontrolę: cytat w CV, daty w cytacie.

    ``grounded(quote) -> (źródło, cytat)``, ``date_in_quote(month, year, quote)``
    i ``ongoing`` to kontrole z ``client_form_fill`` — te same co okres pracy.
    """
    roles: dict[str, dict[str, Any]] = {}
    for item in (raw_roles if isinstance(raw_roles, list) else [])[:ROLES_MAX]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        start = _month(item.get("start"))
        end_raw = item.get("end")
        end = _month(end_raw)
        current = isinstance(end_raw, str) and bool(_ONGOING_END.match(end_raw))
        if not _KEY.match(key) or key in roles or start is None:
            continue
        if end is None and not current:
            continue
        _, quote = grounded(item.get("quote"))
        if quote is None:
            continue
        month = lambda v: f"{v[1]:02d}" if v[1] else None  # noqa: E731
        if not date_in_quote(month(start), str(start[0]), quote):
            continue
        if end is not None and not date_in_quote(month(end), str(end[0]), quote):
            continue
        if current and not ongoing.search(quote):
            continue
        roles[key] = {
            "key": key,
            "employer": _text(item.get("employer")),
            "title": _text(item.get("title")),
            "start": _iso(start),
            "end": _iso(end),
            "period": period_text(_iso(start), _iso(end)),
            "quote": quote[:QUOTE_MAX],
        }
    return roles


def months_of(basis: list[dict[str, Any]], today: date) -> int:
    bounds = []
    for item in basis:
        if not item.get("on"):
            continue
        start = _month(item.get("start"))
        if start is None:
            continue
        found = _bounds(start, _month(item.get("end")), today)
        if found is not None:
            bounds.append(found)
    return union_months(bounds)


def points_for(months: int, thresholds: list[dict[str, int]], max_points: int) -> int:
    """Najwyższy próg, który staż osiąga; nigdy ponad maksimum wiersza."""
    best = 0
    for item in thresholds:
        if months >= item["years"] * 12:
            best = max(best, item["points"])
    return min(best, max_points)


def _number_in(number: int, quote: str) -> bool:
    return bool(re.search(rf"(?<!\d){number}(?!\d)", quote))


def _thresholds(
    item: dict[str, Any], rules_quote: Optional[str]
) -> list[dict[str, int]]:
    if rules_quote is None:
        return []
    kept = []
    for row in (item.get("thresholds") or [])[:THRESHOLDS_MAX]:
        if not isinstance(row, dict):
            continue
        years, points = row.get("years"), row.get("points")
        if not all(
            isinstance(v, int) and not isinstance(v, bool) for v in (years, points)
        ):
            continue
        if not (0 <= years <= 40 and 0 <= points <= 100):
            continue
        if _number_in(years, rules_quote) and _number_in(points, rules_quote):
            kept.append({"years": years, "points": points})
    return kept


def question(row_label: str) -> str:
    name = row_label.strip().rstrip(";.") or "tej kompetencji"
    return f"{name} — w której firmie i od kiedy do kiedy?"


def value_of(years: dict[str, Any], today: date) -> Optional[str]:
    """Wartość pola z zapisanej siatki: lata, lata ponad minimum albo punkty."""
    months = months_of(years.get("basis") or [], today)
    years["months"] = months
    if not months or years.get("minimum_unknown"):
        return None
    if years.get("kind") == KIND_POINTS:
        return str(
            points_for(months, years.get("thresholds") or [], years["max_points"])
        )
    minimum = years.get("minimum_months")
    if minimum:
        over = months - minimum
        return months_text(over) if over > 0 else None
    return months_text(months)


def build(
    data: dict[str, Any],
    *,
    structure: dict[str, Any],
    grounded: Any,
    grounded_rules: Any,
    date_in_quote: Any,
    ongoing: re.Pattern[str],
    today: date,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Pola lat (i punktów z lat) do wpisania w ``fields`` + liczba odrzuconych.

    Każde pole lat dostaje wpis — także bez wartości, żeby okno formularza
    pokazało siatkę i pytanie do screeningu.
    """
    by_id = {item["id"]: item for item in structure.get("fields") or []}
    kinds = years_fields(structure)
    roles = check_roles(data.get("roles"), grounded, date_in_quote, ongoing)
    dropped = 0
    items: dict[str, dict[str, Any]] = {}
    for item in data.get("years") or []:
        if isinstance(item, dict) and item.get("id") in by_id:
            items.setdefault(item["id"], item)
        else:
            dropped += 1
    out: dict[str, dict[str, Any]] = {}
    for field_id, field in by_id.items():
        kind = kinds.get(field_id)
        item = items.get(field_id) or {}
        max_points = field.get("max_points")
        if kind is None and (max_points is None or not item.get("thresholds")):
            continue
        thresholds: list[dict[str, int]] = []
        if kind is None:
            _, rules_quote = grounded_rules(item.get("rules_quote"))
            thresholds = _thresholds(item, rules_quote)
            if not thresholds:
                dropped += 1
                continue
            kind = KIND_POINTS
        basis: list[dict[str, Any]] = []
        if kind == KIND_TOTAL and not item.get("roles"):
            basis = [
                {**role, "level": LEVEL_ROLE, "evidence": None, "on": True}
                for role in roles.values()
            ]
        for ref in item.get("roles") or []:
            if not isinstance(ref, dict) or ref.get("key") not in roles:
                dropped += 1
                continue
            level = ref.get("level") if ref.get("level") in LEVELS else None
            _, quote = grounded(ref.get("quote"))
            if level is None or (quote is None and kind != KIND_TOTAL):
                dropped += 1
                continue
            if any(b["key"] == ref["key"] for b in basis):
                continue
            basis.append(
                {**roles[ref["key"]], "level": level, "evidence": quote, "on": True}
            )
        _, skills = grounded(item.get("skills_quote"))
        minimum_months = None
        years_min = item.get("minimum_years")
        # Minimum odejmuje się tylko w wierszu „ponad minimalne wymagania”;
        # „Minimum 3-letnie doświadczenie w …” to próg wymagania, nie odjemnik.
        over_minimum = bool(OVER_MINIMUM.search(field.get("row_label") or ""))
        if (
            over_minimum
            and kind == KIND_COMPETENCY
            and isinstance(years_min, int)
            and not isinstance(years_min, bool)
            and 0 < years_min <= 20
        ):
            # „Staż ponad minimum z OPZ”: minimum musi stać w cytacie z zasad,
            # wymagań wzoru albo w nazwie wiersza — model go nie wymyśla.
            _, min_quote = grounded_rules(item.get("minimum_quote"))
            own = field.get("row_label") or ""
            if (
                min_quote is not None and _number_in(years_min, min_quote)
            ) or re.search(rf"(?<!\d){years_min}\s*(?:-\s*letni|lat|rok)", own):
                minimum_months = years_min * 12
            else:
                dropped += 1
        years = {
            "kind": kind,
            "basis": basis,
            "skills": skills,
            "minimum_months": minimum_months,
            # Wiersz „ponad minimum” bez znanego minimum nie dostaje całego stażu.
            "minimum_unknown": over_minimum and minimum_months is None,
            "thresholds": thresholds,
            "max_points": max_points,
            "question": question(field.get("row_label") or field.get("label") or ""),
            "ask": False,
            "months": 0,
        }
        value = value_of(years, today)
        quote = " … ".join(b["quote"] for b in basis if b["on"]) or None
        out[field_id] = {
            "value": value,
            "source": "cv" if value else None,
            "quote": quote if value else None,
            "years": years,
        }
    return out, dropped


def recompute(entry: dict[str, Any], on: set[str], today: date) -> dict[str, Any]:
    """Wpis pola po zmianie ról w siatce (rekruter zdjął albo dodał rolę)."""
    years = dict(entry.get("years") or {})
    years["basis"] = [
        {**item, "on": item["key"] in on} for item in years.get("basis") or []
    ]
    value = value_of(years, today)
    quote = " … ".join(b["quote"] for b in years["basis"] if b["on"]) or None
    return {
        "value": value,
        "source": "cv" if value else None,
        "quote": quote if value else None,
        "years": years,
    }


def _role_identity(role: dict[str, Any]) -> tuple[str, Optional[str], str]:
    """Rola między biegami modelu: okres i początek nazwy firmy (klucz r1/r2 się zmienia)."""
    employer = re.sub(r"\W+", "", (role.get("employer") or "").casefold())[:12]
    return str(role.get("start") or ""), role.get("end"), employer


def carry_selection(
    previous: dict[str, Any], entry: dict[str, Any], today: date
) -> dict[str, Any]:
    """Nowy wpis pola z rolami, które rekruter zdjął w siatce przed „Wypełnij ponownie”.

    Bez tego ponowne wypełnienie (np. po notatce ze screeningu) włączało z powrotem
    zdjętą pracę spoza IT i zawyżone lata szły do przetargu bez sygnału.
    """
    off = {
        _role_identity(role)
        for role in (previous.get("years") or {}).get("basis") or []
        if not role.get("on")
    }
    basis = (entry.get("years") or {}).get("basis") or []
    if not off or not basis:
        return entry
    on = {role["key"] for role in basis if _role_identity(role) not in off}
    if len(on) == len(basis):
        return entry
    return recompute(entry, on, today)
