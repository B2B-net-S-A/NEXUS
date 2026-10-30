"""Materiał ogłoszenia — co z rekrutacji wolno wziąć.

Jedno wejście dla modelu, złożenia zapasowego, lewej kolumny okna („Z tej
rekrutacji”) i odcisku ``material_hash``. Treść opisową bierze z
``job_public_profile.draft_material`` — tej samej funkcji, która karmi szkic
strony kariery — więc reguła „bez klienta, stawki, sekcji klienta i notatek
»Tylko zespół«” ma jedno miejsce.

Z ``basics`` Championa czytane jest WYŁĄCZNIE pole ``language``: sekcja niesie
też stawkę (``rate_value``, ``rate_raw``), więc nigdy nie idzie dalej w całości.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.services import champion_view, critical_skills
from app.services import job_public_profile as jpp
from app.services.champion_requirement_rows import ALTERNATIVE_JOINER, full_labels

# `draft_material` wpisuje te słowa w miejsce pustych pól (prompt strony kariery).
_EMPTY_MARKERS = {"brak", "nie podano"}

SENIORITY_LABELS = {
    "junior": "Junior",
    "mid": "Mid",
    "senior": "Senior",
    "lead": "Lead",
    "architect": "Architekt",
}


@dataclass(frozen=True)
class AdMaterial:
    title: str
    seniority: Optional[str]
    about: str
    responsibilities: str
    description: str
    requirements_text: str
    critical: tuple[str, ...]
    must: tuple[str, ...]
    nice: tuple[str, ...]
    domains: str
    certifications: str
    pitch: str
    city: Optional[str]
    remote_policy: Optional[str]
    onsite_days_per_week: Optional[int]
    onsite_days_per_month: Optional[int]
    contract: str
    start: Optional[str]
    duration: Optional[str]
    language: Optional[str]
    working_time: Optional[str]
    # Lokalizacja przed `public_city` — tylko do odcisku materiału: samo
    # wycięcie adresu (28.10.2026) nie jest zmianą rekrutacji i nie może
    # zapalić „Rekrutacja zmieniła się… Przygotuj ponownie”.
    location: Optional[str] = None
    # Zamienniki z wierszy wymagań, tylko dla modelu: „Agile: Prince2”. Poza
    # odciskiem (decyzja Artura 30.10.2026): zapisane ogłoszenia zostają bez
    # zmian i bez „Przygotuj ponownie”, które nadpisałoby ręczne poprawki.
    alternatives: tuple[str, ...] = ()


def _text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in _EMPTY_MARKERS else text


_CLIENT_LINE = re.compile(r"^\s*klient\s*:", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^\s*#+\s*")


def _legacy_description(value: Any) -> str:
    """Opis rekrutacji bez śladów starego „Szkicu ogłoszenia”.

    Do 12.10.2026 szablon ``ai_writer`` zapisywał w ``jobs.description``
    nagłówki ``## …`` i linię ``Klient: <nazwa>``. Gdy Champion jest pusty,
    opis wchodzi do materiału — linia z klientem nie może pójść z nim.
    """
    lines = [
        _MARKDOWN_HEADING.sub("", line)
        for line in _text(value).splitlines()
        if not _CLIENT_LINE.match(line)
    ]
    return "\n".join(lines).strip()


def _critical(job: Any, must: list[str]) -> tuple[str, ...]:
    """Krytyczne tylko z decyzji Delivery Leada — podpowiedzi z historii nie
    trafiają do ogłoszenia jako poziom „Advanced”."""
    stored = critical_skills.stored_critical(job)
    if not stored:
        return ()
    return tuple(critical_skills.match_must_labels(stored, must))


def _alternatives(raw: Any, labels: list[str]) -> tuple[str, ...]:
    """Słowa wiersza, których nie ma w etykiecie (`row_label` zna tylko słownik).

    Bez składni wyszukiwania: końcowa gwiazdka odpada, a słowa z gwiazdką
    w środku („hurtown* danych”) kandydat by nie przeczytał.
    """
    if not isinstance(raw, dict) or not raw:
        return ()
    full = full_labels(champion_view.stack(raw))
    out: list[str] = []
    for label in labels:
        if label not in full:
            continue
        extra = full[label].removeprefix(label + ALTERNATIVE_JOINER)
        words = [word.removesuffix("*") for word in extra.split(ALTERNATIVE_JOINER)]
        words = [word for word in words if "*" not in word]
        if words:
            out.append(f"{label}: {', '.join(words)}")
    return tuple(out)


def build_material(job: Any, title: str) -> AdMaterial:
    """``title`` = tytuł efektywny bez nazwy klienta (``jpp.public_titles``)."""
    draft = jpp.draft_material(job, title)
    params = jpp.public_params(job)
    raw = getattr(job, "champion_profile", None) or {}
    basics = champion_view.basics(raw) if isinstance(raw, dict) and raw else {}
    must = jpp.stack_names(job, "must")
    nice = jpp.stack_names(job, "nice")
    critical = _critical(job, must)
    work_mode = getattr(job, "work_mode", None)
    language = " ".join(str(basics.get("language") or "").split())[:80]
    return AdMaterial(
        title=draft["title"],
        seniority=params.get("seniority"),
        about=_text(draft["about"]),
        responsibilities=_text(draft["responsibilities"]),
        description=_legacy_description(draft["description"]),
        requirements_text=_legacy_description(draft["requirements"]),
        critical=critical,
        must=tuple(must),
        nice=tuple(n for n in nice if n.casefold() not in {m.casefold() for m in must}),
        domains=_text(draft["domains"]),
        certifications=_text(draft["certifications"]),
        pitch=_text(draft["pitch"]),
        city=params.get("city"),
        location=jpp.location(job),
        remote_policy=params.get("remote_policy"),
        onsite_days_per_week=params.get("onsite_days_per_week"),
        onsite_days_per_month=params.get("onsite_days_per_month"),
        contract=str(params.get("contract") or "B2B"),
        start=params.get("start"),
        duration=params.get("duration"),
        language=language or None,
        working_time=getattr(work_mode, "value", work_mode) or None,
        alternatives=_alternatives(raw, [*must, *nice]),
    )


# Jawna lista pól odcisku z numerem wersji: nowe pole `AdMaterial` nie może
# samo oznaczyć wszystkich zapisanych ogłoszeń jako „rekrutacja się zmieniła”.
# Dopisanie pola tutaj = świadoma zmiana wersji.
_HASH_VERSION = "v1"
_HASH_FIELDS = (
    "title",
    "seniority",
    "about",
    "responsibilities",
    "description",
    "requirements_text",
    "critical",
    "must",
    "nice",
    "domains",
    "certifications",
    "pitch",
    "city",
    "remote_policy",
    "onsite_days_per_week",
    "onsite_days_per_month",
    "contract",
    "start",
    "duration",
    "language",
    "working_time",
)


def material_hash(material: AdMaterial) -> str:
    data = asdict(material)
    if material.location:
        data["city"] = material.location
    payload = json.dumps(
        [_HASH_VERSION, {key: data[key] for key in _HASH_FIELDS}],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def workplace_label(material: AdMaterial) -> Optional[str]:
    """Tryb pracy po polsku — dla lewej kolumny okna."""
    mode = material.remote_policy
    if mode == "remote":
        return "zdalnie"
    if mode == "onsite":
        return "stacjonarnie"
    if mode != "hybrid":
        return None
    if material.onsite_days_per_week:
        return (
            f"hybrydowo, {_days_pl(material.onsite_days_per_week)} w tygodniu w biurze"
        )
    if material.onsite_days_per_month:
        return (
            f"hybrydowo, {_days_pl(material.onsite_days_per_month)} w miesiącu w biurze"
        )
    return "hybrydowo"


def _days_pl(count: int) -> str:
    return f"{count} dzień" if count == 1 else f"{count} dni"


def _requirements_summary(material: AdMaterial) -> Optional[str]:
    critical = len(material.critical)
    required = len(material.must) - critical
    parts = []
    if critical:
        parts.append(f"{critical} krytyczne")
    if required > 0:
        parts.append(f"{required} wymagane")
    if material.nice:
        parts.append(f"{len(material.nice)} mile widziane")
    return ", ".join(parts) or None


def facts(material: AdMaterial) -> list[dict[str, str]]:
    """Fakty „Z tej rekrutacji” — tylko te, które rekrutacja naprawdę ma."""
    rows = (
        ("seniority", "Poziom", SENIORITY_LABELS.get(material.seniority or "")),
        ("workplace", "Tryb", workplace_label(material)),
        ("city", "Miasto", material.city),
        ("contract", "Współpraca", material.contract),
        ("start", "Start", material.start),
        ("duration", "Długość", material.duration),
        ("language", "Język", material.language),
        ("requirements", "Wymagania", _requirements_summary(material)),
    )
    return [
        {"key": key, "label": label, "value": value}
        for key, label, value in rows
        if value
    ]


def readiness(material: AdMaterial) -> list[dict[str, Any]]:
    """Czego generator potrzebuje i co rekrutacja ma — lista „jest / brak”."""
    workplace = bool(material.remote_policy) and (
        material.remote_policy == "remote" or bool(material.city)
    )
    rows = (
        ("about", "Opis projektu", bool(material.about or material.description)),
        ("responsibilities", "Zakres obowiązków", bool(material.responsibilities)),
        ("must", "Wymagania", bool(material.must)),
        ("nice", "Mile widziane", bool(material.nice)),
        ("workplace", "Tryb pracy i miasto", workplace),
        ("seniority", "Poziom", bool(material.seniority)),
        ("language", "Język pracy", bool(material.language)),
        ("start", "Start projektu", bool(material.start)),
        ("duration", "Długość kontraktu", bool(material.duration)),
    )
    return [
        {"key": key, "label": label, "present": present} for key, label, present in rows
    ]
