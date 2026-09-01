"""Odczyt profilu Championa niezależny od tego, w którym kształcie jest zapisany.

`jobs.champion_profile` to JSONB, więc na produkcji współistnieją DWA kształty:

* **stary** (import 08.2026, 1095 plików, parser v3) — `project_context`,
  `sourcing`, `client_standards` oraz płaskie `rate_value`, `seniority_min_years`,
  `sectors`, `disqualifiers` na wierzchu dokumentu;
* **nowy** (agenda 09.2026) — siedem sekcji: `basics`, `search`, `stack`,
  `project`, `screening_questions`, `client`, `documents`.

Ten moduł jest JEDYNYM miejscem, które o tym rozdwojeniu wie. Konsumenci
(scoring, embedding, generator CV, Talent Radar) pytają o sekcję po nazwie i
dostają ją niezależnie od tego, co leży w bazie.

Celowo **bez Pydantica**: `_extract_skills_from_champion` i budowanie tekstu
kanonicznego wołane są w pętli scoringu, a `model_validate` na każdym wywołaniu
zamieniłoby odczyt kilku kluczy w rekonstrukcję całego dokumentu. Tu wystarczą
operacje na słownikach.

Kierunek jest jednostronny: czytamy oba kształty, **zapisujemy wyłącznie nowy**
(`ChampionProfile.model_dump`). Dzięki temu migracja dzieje się leniwie, przy
pierwszym zapisie danej oferty, a nie jednorazowym przepisaniem 949 wierszy
JSONB — odwracalnym tylko z kopii, której off-site nie mamy.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = [
    "as_dict",
    "basics",
    "search",
    "stack",
    "project",
    "client",
    "screening_questions",
    "documents",
    "narrative_parts",
    "embedding_parts",
    "hourly_rate",
    "seniority_min_years",
    "disqualifiers",
]

# Pola, które w starym kształcie leżały na wierzchu dokumentu, a w nowym
# należą do sekcji 1. To one ginęły przy każdym zapisie z UI.
_FLAT_TO_BASICS = (
    "role_name",
    "seniority_min_years",
    "rate_value",
    "rate_raw",
    "work_mode",
    "start_date",
    "contract_length",
)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return not value
    return False


def _sub(raw: Mapping[str, Any], key: str) -> dict:
    value = raw.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def as_dict(source: Any) -> dict:
    """Profil jako słownik — przyjmuje `Job`, słownik albo cokolwiek innego.

    Nie-słownik (w tym `None`) daje pusty słownik, nie wyjątek: brak Championa
    jest normalnym stanem ~95% ofert i każdy konsument musi to znieść.
    """
    if isinstance(source, Mapping):
        return dict(source)
    profile = getattr(source, "champion_profile", None)
    return dict(profile) if isinstance(profile, Mapping) else {}


def basics(source: Any) -> dict:
    """Sekcja 1 — podstawowe informacje, z podniesieniem płaskich pól starego kształtu."""
    raw = as_dict(source)
    out = _sub(raw, "basics")
    for key in _FLAT_TO_BASICS:
        if _blank(out.get(key)) and not _blank(raw.get(key)):
            out[key] = raw[key]
    return out


def search(source: Any) -> dict:
    """Sekcja 2 — co wpisać. Stary `sourcing` czytany pod nowymi nazwami."""
    raw = as_dict(source)
    out = _sub(raw, "search")
    legacy = _sub(raw, "sourcing")
    for key in ("keywords", "target_companies", "notes", "sources"):
        if _blank(out.get(key)) and not _blank(legacy.get(key)):
            out[key] = legacy[key]
    if _blank(out.get("disqualifiers")) and not _blank(raw.get("disqualifiers")):
        out["disqualifiers"] = raw["disqualifiers"]
    return out


def stack(source: Any) -> dict:
    """Sekcja 3 — stack technologiczny.

    Stary kształt nie ma odpowiednika: parser zapisywał `must_skills`/`nice_skills`
    wprost do KOLUMN oferty, z pominięciem JSONB. Dlatego pusty wynik tutaj nie
    znaczy „brak wymagań" — znaczy „wymagania są w `Job.must_skills`".
    """
    return _sub(as_dict(source), "stack")


def project(source: Any) -> dict:
    """Sekcja 4 — o projekcie. Stary `project_context` bez `selling_points`."""
    raw = as_dict(source)
    out = _sub(raw, "project")
    legacy = _sub(raw, "project_context")
    for key in ("about", "responsibilities"):
        if _blank(out.get(key)) and not _blank(legacy.get(key)):
            out[key] = legacy[key]
    return out


def client(source: Any) -> dict:
    """Sekcja 6 — o kliencie.

    Scala cztery byty starego kształtu: `project_context.selling_points`,
    `internal_consultant_insight`, `historical_client_questions` oraz
    `client_standards.*` i `sectors`.
    """
    raw = as_dict(source)
    out = _sub(raw, "client")
    legacy_ctx = _sub(raw, "project_context")
    legacy_std = _sub(raw, "client_standards")

    def _fill(key: str, value: Any) -> None:
        if _blank(out.get(key)) and not _blank(value):
            out[key] = value

    _fill("selling_points", legacy_ctx.get("selling_points"))
    _fill("consultant_insight", raw.get("internal_consultant_insight"))
    _fill("historical_questions", raw.get("historical_client_questions"))
    _fill("sectors", raw.get("sectors"))
    for key in ("priority_rules", "offlimit", "contract_type", "cv_language"):
        _fill(key, legacy_std.get(key))
    return out


def screening_questions(source: Any) -> list:
    value = as_dict(source).get("screening_questions")
    return list(value) if isinstance(value, list) else []


def documents(source: Any) -> list:
    value = as_dict(source).get("documents")
    return list(value) if isinstance(value, list) else []


def narrative_parts(source: Any) -> list[str]:
    """Cały tekst Championa, w kolejności malejącej wartości sygnału.

    Jedno źródło prawdy dla ekstrakcji skilli (`scoring_service`) i tekstu
    kanonicznego (`canonical_text`). Wcześniej obie ścieżki miały własną,
    ręcznie utrzymywaną listę pól — i już się rozjechały: tekst kanoniczny brał
    wyłącznie `project_context`, więc słowa kluczowe z sourcingu i pytania
    screeningowe nigdy nie trafiały do wektora oferty, mimo że scoring wyciągał
    z nich skille.

    Stack jest PIERWSZY i to jest sedno przebudowy: gdy sekcja 3 jest wypełniona,
    najmocniejszy sygnał jest podany wprost, a nie zgadywany regexem z prozy.
    """
    parts: list[str] = []

    stack_section = stack(source)
    for key in ("must", "nice"):
        for item in stack_section.get(key) or []:
            if isinstance(item, Mapping):
                name = item.get("name")
            else:
                name = item
            if isinstance(name, str) and name.strip():
                parts.append(name)
    if isinstance(stack_section.get("notes"), str):
        parts.append(stack_section["notes"])

    proj = project(source)
    for key in ("about", "responsibilities"):
        value = proj.get(key)
        if isinstance(value, str):
            parts.append(value)

    for question in screening_questions(source):
        if isinstance(question, Mapping):
            for key in ("question", "ideal_answer", "deal_breaker"):
                value = question.get(key)
                if isinstance(value, str):
                    parts.append(value)

    srch = search(source)
    for key in ("keywords", "target_companies", "notes"):
        value = srch.get(key)
        if isinstance(value, str):
            parts.append(value)
    for item in srch.get("disqualifiers") or []:
        if isinstance(item, str):
            parts.append(item)

    cli = client(source)
    for key in (
        "about",
        "selling_points",
        "consultant_insight",
        "historical_questions",
        "priority_rules",
    ):
        value = cli.get(key)
        if isinstance(value, str):
            parts.append(value)

    return [p for p in parts if p and p.strip()]


def hourly_rate(source: Any) -> float | None:
    """Stawka kandydata PLN/h albo None. Czyta oba kształty."""
    value = basics(source).get("rate_value")
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def seniority_min_years(source: Any) -> int | None:
    value = basics(source).get("seniority_min_years")
    if value is None:
        return None
    try:
        years = int(value)
    except (TypeError, ValueError):
        return None
    return years if years > 0 else None


def disqualifiers(source: Any) -> list[str]:
    value = search(source).get("disqualifiers")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def embedding_parts(source: Any) -> list[str]:
    """Tekst Championa do WEKTORA oferty — celowo węższy niż `narrative_parts`.

    Zakres jest DOKŁADNIE taki jak przed przebudową szablonu (`about`,
    `responsibilities`, `selling_points`), powiększony wyłącznie o nazwy ze
    stacku, którego stare profile w ogóle nie mają. Dzięki temu 949 ofert
    z importu 08.2026 dostaje **bit w bit ten sam tekst kanoniczny** co dotąd:
    ich wektory się nie zmieniają, indeks nie wymaga przeliczenia, a przebudowa
    szablonu nie miesza się w pomiarze z zmianą retrievalu.

    Rozszerzenie tego zakresu (np. o pytania screeningowe albo słowa kluczowe)
    jest osobną zmianą jakości wyszukiwania i wymaga własnego A/B na zamrożonym
    zestawie — nie wolno jej przemycić razem z przebudową formularza. Poprzedni
    raz, gdy dwa sygnały poszły pod jedną flagą, hipoteza o tym, który z nich
    działa, okazała się dokładnie odwrotna do wyniku.
    """
    parts: list[str] = []

    stack_section = stack(source)
    for key in ("must", "nice"):
        for item in stack_section.get(key) or []:
            name = item.get("name") if isinstance(item, Mapping) else item
            if isinstance(name, str) and name.strip():
                parts.append(name)

    proj = project(source)
    for key in ("about", "responsibilities"):
        value = proj.get(key)
        if isinstance(value, str):
            parts.append(value)
    selling = client(source).get("selling_points")
    if isinstance(selling, str):
        parts.append(selling)

    return [p for p in parts if p and p.strip()]
