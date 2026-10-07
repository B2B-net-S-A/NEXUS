"""Fakty z notatek do PUSTYCH pól profilu (07.10.2026) — jedna reguła.

Czyta wynik nocnego odczytu notatek (``cv_extracted_data._notes_insights``,
``notes_insights_extractor``) i wylicza, które puste pola profilu można z nich
wypełnić. Tę samą funkcję wołają nocna ekstrakcja (``apply_insights``)
i jednorazowe domknięcie historii (``notes_profile_backfill``), więc obie drogi
nie mogą się rozjechać.

Reguły (decyzje Artura 07.10.2026):

* **Tylko puste pola.** Wartości człowieka i CV zostają zawsze. Wyjątek to
  data dostępności, którą WCZEŚNIEJ wpisały notatki (znacznik
  ``_availability_from_notes`` z tą samą datą) — nowsza notatka ją poprawia.
* **Bez progu czasowego, ale dostępność od DNIA NOTATKI.** „Od zaraz”,
  „miesiąc wypowiedzenia” czy „od listopada” liczymy od dnia najnowszej
  notatki wejścia, która MÓWI O DOSTĘPNOŚCI (``notes_days(rows).availability``),
  nie od dziś i nie od dnia najnowszej notatki w ogóle (przegląd #2062:
  „od zaraz” z 2023 + „zna Pythona” z 30.09.2026 dawało datę 30.09.2026).
  Bez takiej notatki „od zaraz” i okres wypowiedzenia nie dają daty; pełna
  data i miesiąc tak — ich „stan na” to wtedy dzień najnowszej notatki.
  Znacznik ``{"date", "as_of", "basis"}`` — profil pokazuje „stan na DD.MM.RRRR”.
* Do 07.10.2026 data dostępności powstawała WYŁĄCZNIE z pełnej daty ISO
  w ``available_from`` (pomiar: 6 327 z 9 607 osób z dostępnością
  w notatkach miało pustą datę). Okres wypowiedzenia trafiał tylko do
  ``notice_period``, „od zaraz” tylko do statusu, a „11.2026”, „01.11.2026”
  czy „od listopada” nie dawały niczego.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from app.core.scheduling import business_today
from app.services.candidate_notes_facts import (
    parse_notice,
    profile_work_mode,
    set_office_days_limit,
    work_mode_from_insights,
    _set_preference,
)

AVAILABILITY_MARKER = "_availability_from_notes"
REMOTE_MODES_MARKER = "_remote_modes_from_notes"
ONSITE_DAYS_MARKER = "_onsite_days_from_notes"

_ASAP_RE = re.compile(r"od zaraz|asap|natychmiast|od r[eę]ki|immediately", re.I)
# „nie od zaraz”, „niedostępny od zaraz” — to nie jest gotowość.
_NOT_ASAP_RE = re.compile(
    r"\bnie(?:\s+\w+)?\s+(?:od zaraz|od r[eę]ki|natychmiast)", re.I
)
# Notatka, która mówi o dostępności — od jej dnia liczymy „od zaraz”
# i okres wypowiedzenia (``notes_days``).
_AVAILABILITY_TEXT_RE = re.compile(
    r"od zaraz|asap|natychmiast|od r[eę]ki|wypowiedz|dost[eę]pn|notice"
    r"|availab|\bstart",
    re.I,
)
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_PL_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_ISO_MONTH_RE = re.compile(r"(?<![\d-])(\d{4})-(\d{1,2})(?![\d-])")
_PL_MONTH_RE = re.compile(r"(?<![\d./])(\d{1,2})[./](\d{4})(?!\d)")
# Tylko rdzenie, których nie da się pomylić z innym słowem (bez „mar”,
# „dec”, „nov” — te siedzą w „marka”, „decyzja”).
_MONTHS = (
    ("stycz", "january"),
    ("luty", "lutego", "february"),
    ("marz", "marca", "march"),
    ("kwie", "april"),
    ("maj", "may"),
    ("czerw", "june"),
    ("lipi", "lipc", "july"),
    ("sierp", "august"),
    ("wrze", "september"),
    ("pa[zź]dziern", "october"),
    ("listop", "november"),
    ("grud", "december"),
)
_MONTH_RES = tuple(
    re.compile(r"\b(?:" + "|".join(stems) + r")\w*(?:\s+(\d{4}))?", re.I)
    for stems in _MONTHS
)
# Data dostępności daleko poza „teraz” to pomyłka odczytu, nie plan.
_MIN_YEAR = 2000
_MAX_YEARS_AHEAD = 3


def _valid(day: date, as_of: Optional[date]) -> Optional[date]:
    reference = as_of or business_today()
    if day.year < _MIN_YEAR or day.year > reference.year + _MAX_YEARS_AHEAD:
        return None
    return day


def _explicit_date(text: str) -> Optional[date]:
    for regex, order in ((_ISO_DATE_RE, (0, 1, 2)), (_PL_DATE_RE, (2, 1, 0))):
        match = regex.search(text)
        if match:
            parts = match.groups()
            try:
                return date(
                    int(parts[order[0]]), int(parts[order[1]]), int(parts[order[2]])
                )
            except ValueError:
                return None
    return None


def _month_start(text: str, as_of: Optional[date]) -> Optional[date]:
    for regex, order in ((_ISO_MONTH_RE, (0, 1)), (_PL_MONTH_RE, (1, 0))):
        match = regex.search(text)
        if match:
            year, month = int(match.group(order[0] + 1)), int(match.group(order[1] + 1))
            return date(year, month, 1) if 1 <= month <= 12 else None
    for index, regex in enumerate(_MONTH_RES, start=1):
        match = regex.search(text)
        if not match:
            continue
        if match.group(1):
            return date(int(match.group(1)), index, 1)
        if as_of is None:
            return None
        # „od listopada” bez roku: najbliższy taki miesiąc od dnia notatki.
        year = as_of.year if index >= as_of.month else as_of.year + 1
        return date(year, index, 1)
    return None


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _after_notice(as_of: date, notice: tuple[int, str]) -> Optional[date]:
    count, unit = notice
    if count <= 0 or count > 24 * (30 if unit == "days" else 1):
        return None
    if unit == "months":
        return _add_months(as_of, count)
    if unit == "weeks":
        return as_of + timedelta(weeks=count)
    return as_of + timedelta(days=count)


def _asap(text: str) -> bool:
    return bool(_ASAP_RE.search(text)) and not _NOT_ASAP_RE.search(text)


RELATIVE_BASES = frozenset({"asap", "notice"})


def availability_from_notes(
    availability: Any,
    *,
    as_of: Optional[date],
    latest_note_day: Optional[date] = None,
) -> Optional[tuple[date, str]]:
    """(data dostępności, podstawa) z faktu notatek albo ``None``.

    ``as_of`` — dzień najnowszej notatki o dostępności; ``latest_note_day`` —
    dzień najnowszej notatki wejścia (tylko odniesienie dla pełnej daty
    i miesiąca bez roku, gdy notatki o dostępności nie ma).

    Kolejność: pełna data w „od kiedy” → miesiąc („11.2026”, „od listopada”)
    → „od zaraz” w „od kiedy” = dzień notatki → okres wypowiedzenia od dnia
    notatki → „od zaraz” w pozostałych polach.
    Bez dnia notatki o dostępności (``as_of``) liczą się wyłącznie daty
    podane wprost. Podstawy: ``date``, ``month``, ``notice``, ``asap``.
    """
    if not isinstance(availability, dict):
        return None
    from_text = str(availability.get("available_from") or "")
    notice_text = str(availability.get("notice_period") or "")
    raw_text = str(availability.get("raw") or "")
    reference = as_of or latest_note_day
    day = _explicit_date(from_text)
    if day is not None:
        valid = _valid(day, reference)
        return (valid, "date") if valid else None
    month = _month_start(from_text, reference)
    if month is not None:
        valid = _valid(month, reference)
        return (valid, "month") if valid else None
    if as_of is None:
        return None
    if _asap(from_text):
        return as_of, "asap"
    notice = parse_notice(from_text) or parse_notice(notice_text)
    if notice is None and not _asap(notice_text):
        notice = parse_notice(raw_text)
    if notice is not None:
        after = _after_notice(as_of, notice)
        if after is not None:
            return after, "notice"
    if _asap(notice_text) or _asap(raw_text):
        return as_of, "asap"
    return None


def _owned_availability(candidate: Any, prior: dict) -> Optional[dict]:
    """Znacznik daty, którą wpisały notatki — ważny, póki profil ma tę datę."""
    marker = prior.get(AVAILABILITY_MARKER)
    current = getattr(candidate, "availability_date", None)
    if (
        isinstance(marker, dict)
        and current is not None
        and marker.get("date") == current.isoformat()
    ):
        return marker
    return None


def availability_origin(candidate: Any) -> Optional[dict[str, Any]]:
    """„Stan na” daty dostępności, którą wpisały notatki — albo ``None``.

    ``{"as_of": date | None, "basis": str | None}``, dopóki profil ma datę
    ze znacznika ``_availability_from_notes``; poprawka człowieka (inna data)
    go wyłącza. Czysta funkcja nad załadowanym ``cv_extracted_data`` — lista
    kandydatów liczy ją w pamięci, bez zapytania per wiersz.
    """
    extracted = getattr(candidate, "cv_extracted_data", None)
    insights = extracted.get("_notes_insights") if isinstance(extracted, dict) else None
    if not isinstance(insights, dict):
        return None
    marker = _owned_availability(candidate, insights)
    if marker is None:
        return None
    as_of_raw = marker.get("as_of")
    try:
        as_of = date.fromisoformat(as_of_raw) if isinstance(as_of_raw, str) else None
    except ValueError:
        as_of = None
    basis = marker.get("basis")
    return {"as_of": as_of, "basis": basis if isinstance(basis, str) else None}


def release_availability_from_notes(candidate: Any, insights: Any) -> bool:
    """Notatki już nie dają daty — zdejmij datę, którą same wpisały.

    Tylko gdy profil nadal ma datę ze znacznika (poprawki człowieka nie
    ruszamy). Mutuje obiekt (bez commitu, bez ``flag_modified`` — znacznik
    usuwa wołający razem z resztą faktów). Zwraca, czy data zniknęła.
    """
    if (
        not isinstance(insights, dict)
        or _owned_availability(candidate, insights) is None
    ):
        return False
    candidate.availability_date = None
    return True


def plan_profile_fill(
    candidate: Any,
    facts: dict,
    *,
    prior: dict,
    as_of: Optional[date],
    latest_note_day: Optional[date] = None,
    include_status: bool = True,
    release_stale_availability: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(zmiany pól, znaczniki do ``_notes_insights``). Czysta — nic nie zapisuje.

    ``as_of`` i ``latest_note_day`` — ``notes_days(rows)`` (dzień najnowszej
    notatki o dostępności i dzień najnowszej notatki wejścia).

    ``release_stale_availability`` (nocna ekstrakcja po zmianie notatek):
    datę, którą wpisały notatki, a której nowe fakty już nie dają, zdejmujemy
    (``availability_date: None``, bez znacznika). Domknięcie historii tylko
    wypełnia puste pola, więc jej nie zdejmuje.

    ``candidate`` to obiekt z atrybutami profilu (ORM albo wiersz odczytu).
    Znaczniki zwracane są zawsze, gdy dalej obowiązują (także bez zmiany).
    """
    changes: dict[str, Any] = {}
    markers: dict[str, Any] = {}

    years = facts.get("years_confirmed")
    if (
        getattr(candidate, "years_it_experience", None) is None
        and isinstance(years, (int, float))
        and not isinstance(years, bool)
        and 0 < years <= 60
    ):
        changes["years_it_experience"] = int(years)

    availability = facts.get("availability")
    availability = availability if isinstance(availability, dict) else {}
    if getattr(candidate, "notice_period", None) is None:
        notice = parse_notice(availability.get("notice_period")) or parse_notice(
            availability.get("raw")
        )
        if notice:
            changes["notice_period"] = notice

    owned = _owned_availability(candidate, prior)
    current_date = getattr(candidate, "availability_date", None)
    if current_date is None or owned is not None:
        found = availability_from_notes(
            availability, as_of=as_of, latest_note_day=latest_note_day
        )
        if found is not None:
            day, basis = found
            stated = as_of if basis in RELATIVE_BASES else (as_of or latest_note_day)
            markers[AVAILABILITY_MARKER] = {
                "date": day.isoformat(),
                "as_of": stated.isoformat() if stated else None,
                "basis": basis,
            }
            if day != current_date:
                changes["availability_date"] = day
        elif owned is not None and release_stale_availability:
            changes["availability_date"] = None
        elif owned is not None:
            markers[AVAILABILITY_MARKER] = owned
    elif owned is not None:
        markers[AVAILABILITY_MARKER] = owned

    if include_status:
        status = getattr(
            getattr(candidate, "availability_status", None),
            "value",
            getattr(candidate, "availability_status", None),
        )
        raw_txt = " ".join(
            str(availability.get(key) or "")
            for key in ("raw", "notice_period", "available_from")
        )
        if status == "unknown" and _asap(raw_txt):
            changes["availability_status"] = "actively_looking"

    derived = work_mode_from_insights(facts)
    if derived is not None:
        current = profile_work_mode(candidate)
        if not current["modes"] and derived["modes"]:
            changes["remote_modes"] = derived["modes"]
            markers[REMOTE_MODES_MARKER] = True
        if (
            getattr(candidate, "max_onsite_days_per_week", None) is None
            and derived["max_onsite_days"] is not None
        ):
            changes["max_onsite_days_per_week"] = derived["max_onsite_days"]
            markers[ONSITE_DAYS_MARKER] = True
    return changes, markers


def apply_profile_fill(candidate: Any, changes: dict[str, Any]) -> None:
    """Zapisz zmiany z ``plan_profile_fill`` na obiekcie ORM (bez commitu)."""
    from app.models.candidate import AvailabilityStatus

    if "years_it_experience" in changes:
        candidate.years_it_experience = changes["years_it_experience"]
    if "notice_period" in changes:
        candidate.notice_period, candidate.notice_period_unit = changes["notice_period"]
    if "availability_date" in changes:
        candidate.availability_date = changes["availability_date"]
    if "availability_status" in changes:
        candidate.availability_status = AvailabilityStatus(
            changes["availability_status"]
        )
    if "remote_modes" in changes:
        _set_preference(candidate, "remote_modes", changes["remote_modes"])
    if "max_onsite_days_per_week" in changes:
        set_office_days_limit(candidate, changes["max_onsite_days_per_week"])


@dataclass(frozen=True)
class NotesDays:
    """Dni notatek wejścia, od których liczymy dostępność."""

    #: Dzień najnowszej notatki, której treść mówi o dostępności.
    availability: Optional[date]
    #: Dzień najnowszej notatki wejścia w ogóle.
    latest: Optional[date]


def notes_days(rows: Any) -> NotesDays:
    """Dni z wierszy ``load_note_rows`` / ``load_note_rows_bulk``.

    JEDNA funkcja dla nocnej ekstrakcji i domknięcia historii — obie drogi
    liczą ją na tym samym zbiorze notatek (tym, który czyta odczyt AI).
    Kolumny: 4. — treść, 5. — dzień notatki.
    """
    latest: Optional[date] = None
    availability: Optional[date] = None
    for row in rows or ():
        if len(row) <= 4 or row[4] is None:
            continue
        day = row[4]
        latest = day if latest is None else max(latest, day)
        if _AVAILABILITY_TEXT_RE.search(str(row[3] or "")):
            availability = day if availability is None else max(availability, day)
    return NotesDays(availability=availability, latest=latest)


LANGUAGE_SOURCE_REF = "notes_insights"


def observed_languages(facts: Any) -> list[dict]:
    """``languages_observed`` w kształcie czytanym przez writer języków."""
    value = facts.get("languages_observed") if isinstance(facts, dict) else None
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out.append({"name": item["name"], "level": item.get("level")})
        elif isinstance(item, str):
            out.append({"name": item, "level": None})
    return out


def languages_to_add(facts: Any, existing_codes: set[str]) -> list[str]:
    """Kody języków z notatek, których profil nie zna (także jako usunięte)."""
    from app.services.candidate_language_writer import normalize_language_payload

    incoming, _ = normalize_language_payload(observed_languages(facts))
    return [i.language_code for i in incoming if i.language_code not in existing_codes]


async def fill_languages_from_notes(db: Any, candidate_id: int, facts: Any) -> int:
    """Dopisz do profilu języki z notatek, których profil nie zna. Zwraca liczbę.

    Źródło ``notes`` tylko DOPISUJE (``candidate_language_writer``): język
    z CV, z Traffita albo wpisany przez człowieka zostaje taki, jaki był —
    także jego poziom — a usunięty przez człowieka nie wraca.
    """
    languages = observed_languages(facts)
    if not languages:
        return 0
    from app.services.candidate_language_writer import (
        sync_candidate_languages_from_source,
    )

    result = await sync_candidate_languages_from_source(
        db,
        candidate_id=candidate_id,
        raw_languages=languages,
        provenance="notes",
        source_ref=LANGUAGE_SOURCE_REF,
        replace_source_snapshot=False,
    )
    return result.inserted
