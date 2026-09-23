"""Plakietki „Doświadczenie poza stackiem” — czy CV ma ślad dziedziny/certyfikatu.

Deterministycznie, bez modelu. Dla każdej pozycji sekcji 4 profilu Championa
zwraca ``met`` (jest ślad, z opisem skąd) albo ``unknown`` (brak danych) —
NIGDY „nie ma”: branża w CV bywa pusta, a certyfikat pominięty, więc brak
śladu to brak wiedzy, nie dowód braku (ta sama filozofia co
`requirement_contract.evaluate_requirements`).

Plakietka nie zmienia `fit_score` ani rankingu (decyzja 23.09.2026). Minimalna
liczba lat w dziedzinie nie jest liczona — CV nie niesie dat per dziedzina.

Źródła w kolejności siły: sektory odczytane z CV → projekty → certyfikaty
(także z Traffita) → surowy tekst CV. Dopasowanie po złożeniu (małe litery,
bez polskich znaków), jako POCZĄTEK słowa: „platnos” łapie „płatnościach”.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services import champion_view
from app.services.champion_document import folded

_DATA = Path(__file__).resolve().parent.parent / "data" / "experience_domains.json"
_GENERIC = frozenset(
    {"certyfikat", "certified", "certification", "cert", "level", "poziom", "i", "and"}
)
_TOKEN = re.compile(r"[a-z0-9+#]+")
RAW_TEXT_CAP = 60_000


@lru_cache(maxsize=1)
def _domain_aliases() -> dict[str, tuple[str, ...]]:
    data = json.loads(_DATA.read_text(encoding="utf-8"))
    return {
        folded(label): tuple(folded(a) for a in aliases)
        for label, aliases in (data.get("domains") or {}).items()
    }


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", folded(text)).strip() if isinstance(text, str) else ""


def _has_prefix(haystack: str, needle: str) -> bool:
    return (
        bool(needle)
        and re.search(r"(?<![a-z0-9])" + re.escape(needle), haystack) is not None
    )


def domain_forms(name: str) -> tuple[str, ...]:
    """Formy, których szukamy dla dziedziny: własna nazwa + synonimy ze słownika."""
    key = _norm(name)
    forms = {key}
    for label, aliases in _domain_aliases().items():
        if (
            key.startswith(label)
            or label.startswith(key)
            or any(_has_prefix(key, alias) for alias in aliases)
        ):
            forms.add(label)
            forms.update(aliases)
    return tuple(sorted(f for f in forms if f))


def _tokens(name: str) -> list[str]:
    return [t for t in _TOKEN.findall(_norm(name)) if t not in _GENERIC and len(t) >= 2]


def _cert_found(haystack: str, name: str) -> bool:
    tokens = _tokens(name)
    return bool(tokens) and all(_has_prefix(haystack, t) for t in tokens)


def _cv_sources(candidate: Any) -> list[tuple[str, str]]:
    """(opis źródła, złożony tekst) w kolejności siły dowodu."""
    data = getattr(candidate, "cv_extracted_data", None) or {}
    data = data if isinstance(data, Mapping) else {}
    out: list[tuple[str, str]] = []
    highlights = (
        data.get("cv_highlights")
        if isinstance(data.get("cv_highlights"), Mapping)
        else {}
    )
    sectors = [*(data.get("sectors") or []), *(highlights.get("sectors") or [])]
    if sectors:
        out.append(("sektor w CV", _norm(" ; ".join(str(s) for s in sectors))))
    for project in data.get("projects") or []:
        if isinstance(project, Mapping):
            label = str(project.get("name") or "").strip()[:60]
            text = " ".join(
                str(project.get(k) or "")
                for k in ("name", "company", "description", "role")
            )
            out.append((f"projekt: {label}" if label else "projekt w CV", _norm(text)))
    certs = [
        *(
            c.get("name")
            for c in data.get("certifications") or []
            if isinstance(c, Mapping) and c.get("name")
        ),
        *(
            [data["traffit_certificates"]]
            if isinstance(data.get("traffit_certificates"), str)
            else data.get("traffit_certificates") or []
        ),
    ]
    if certs:
        out.append(("certyfikat w CV", _norm(" ; ".join(str(c) for c in certs))))
    raw = getattr(candidate, "raw_cv_text", None)
    if isinstance(raw, str) and raw.strip():
        out.append(("tekst CV", _norm(raw[:RAW_TEXT_CAP])))
    return out


def _find(sources: Iterable[tuple[str, str]], matches) -> str | None:
    for label, text in sources:
        if text and matches(text):
            return label
    return None


def evaluate(profile: Any, candidate: Any) -> list[dict[str, Any]]:
    """Pozycje sekcji 4 z werdyktem `met`/`unknown` dla jednego kandydata."""
    experience = champion_view.experience(profile)
    items = [
        (kind, item)
        for kind in ("domains", "certifications", "regulations")
        for item in experience.get(kind) or []
    ]
    if not items:
        return []
    sources = _cv_sources(candidate)
    out: list[dict[str, Any]] = []
    for kind, item in items:
        name = str(item.get("name") or "").strip()
        if kind == "domains":
            forms = domain_forms(name)
            found = _find(
                sources, lambda text: any(_has_prefix(text, f) for f in forms)
            )
        else:
            found = _find(sources, lambda text: _cert_found(text, name))
        out.append(
            {
                "kind": kind,
                "name": name,
                "level": item.get("level") or "must",
                "min_years": item.get("min_years") if kind == "domains" else None,
                "status": "met" if found else "unknown",
                "source": found,
            }
        )
    return out
