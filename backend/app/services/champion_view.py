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
    "experience",
    "insights",
    "team_insights",
    "candidate_insights",
    "requirement_source",
    "LEGACY_INSIGHT_FIELDS",
    "VERIFICATION_INSIGHT_IDS",
    "narrative_parts",
    "embedding_parts",
    "hourly_rate",
    "seniority_min_years",
    "disqualifiers",
    "api_response",
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
    "deadline",
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


def experience(source: Any) -> dict:
    """Sekcja 4 — doświadczenie poza stackiem (dziedzina, certyfikaty, regulacje).

    Stary kształt jej nie ma; pusty słownik znaczy „DL nic nie podał".
    """
    out = _sub(as_dict(source), "experience")
    for key in ("domains", "certifications", "regulations"):
        value = out.get(key)
        out[key] = [
            item
            for item in (value if isinstance(value, list) else [])
            if isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and item["name"].strip()
        ]
    return out


# Stare pola sekcji „O kliencie", które od 09.2026 edytuje się jako notatki
# sekcji 8. Zostają w bazie i w `client()` bajt w bajt, bo czyta je tekst
# embeddingu oferty v1 — przepisanie ich zmieniłoby wektory 949 ofert.
LEGACY_INSIGHT_FIELDS = {
    "legacy:client.consultant_insight": (
        "consultant_insight",
        {"source": "consultant", "topic": "team"},
    ),
    "legacy:client.historical_questions": (
        "historical_questions",
        {"source": "client", "topic": "process"},
    ),
}
VERIFICATION_INSIGHT_IDS = ("verification:client", "verification:consultant")
# Lustro `schemas.champion.INSIGHT_TEXT_MAX_CHARS` (moduł bez Pydantica —
# patrz docstring). Stare pola i teksty weryfikacji nie mają limitu, a widok
# wraca do API walidacji importu: dłuższy tekst dawał tam 422.
_VIEW_TEXT_MAX_CHARS = 2000


def _view_text(value: Any) -> str:
    return str(value).strip()[:_VIEW_TEXT_MAX_CHARS]


def insights(source: Any) -> list[dict]:
    """Sekcja 8 — wiedza z rozmów: zapisane notatki + wpisy składane przy odczycie.

    Kolejność: weryfikacja (najmocniejsze źródło — DL rozmawiał z klientem
    i konsultantem), potem stare pola, potem notatki w kolejności zapisu.
    Wpisy `verification:*` są tylko do odczytu (zmienia je ponowna
    weryfikacja), `legacy:*` edytor zmienia przez stare pole w sekcji `client`.
    """
    raw = as_dict(source)
    out: list[dict] = []
    verification = _sub(raw, "verification")
    client_ver = _sub(verification, "client")
    consultant_ver = _sub(verification, "consultant")
    corrections = client_ver.get("key_corrections")
    if client_ver.get("status") == "verified" and not _blank(corrections):
        out.append(
            {
                "id": "verification:client",
                "source": "client",
                "topic": "needs",
                "audience": "team",
                "text": _view_text(corrections),
                "origin": "verification",
                "author_id": client_ver.get("verified_by_id"),
                "author_name": client_ver.get("verified_by_name"),
                "created_at": client_ver.get("verified_at"),
                "updated_at": client_ver.get("verified_at"),
                "editable": False,
                "done": False,
            }
        )
    consultant_text = consultant_ver.get("insights")
    if consultant_ver.get("status") == "verified" and not _blank(consultant_text):
        who = consultant_ver.get("consultant_name")
        out.append(
            {
                "id": "verification:consultant",
                "source": "consultant",
                "topic": "team",
                "audience": "team",
                "text": _view_text(consultant_text),
                "origin": "verification",
                "author_id": consultant_ver.get("verified_by_id"),
                "author_name": consultant_ver.get("verified_by_name"),
                "created_at": consultant_ver.get("verified_at"),
                "updated_at": consultant_ver.get("verified_at"),
                "editable": False,
                "done": False,
                **({"consultant_name": who} if who else {}),
            }
        )
    cli = client(source)
    for note_id, (field, meta) in LEGACY_INSIGHT_FIELDS.items():
        text = cli.get(field)
        if isinstance(text, str) and text.strip():
            out.append(
                {
                    "id": note_id,
                    **meta,
                    "audience": "team",
                    "text": _view_text(text),
                    "origin": "legacy",
                    "author_id": None,
                    "author_name": None,
                    "created_at": None,
                    "updated_at": None,
                    "editable": True,
                    "done": False,
                }
            )
    stored = raw.get("insights")
    for note in stored if isinstance(stored, list) else []:
        if not isinstance(note, Mapping) or _blank(note.get("text")):
            continue
        if str(note.get("id") or "").startswith(("legacy:", "verification:")):
            continue
        out.append({**dict(note), "editable": True})
    return out


def team_insights(source: Any) -> list[dict]:
    return [n for n in insights(source) if n.get("audience") != "candidate"]


def candidate_insights(source: Any) -> list[dict]:
    """Tylko to, co DL oznaczył „Można powiedzieć kandydatowi"."""
    return [n for n in insights(source) if n.get("audience") == "candidate"]


# Klucze, które opisują pracę NAD profilem, a nie wymagania roli. Zmiana
# żadnego z nich nie może unieważnić przejrzanego kontraktu wymagań ani
# odcisku rankingu (notatka z rozmowy nie zmienia tego, kogo szukamy).
_NON_REQUIREMENT_KEYS = frozenset(
    {
        "verification",
        "recommended_searches",
        "briefing",
        "intake",
        "insights",
        "client_history",
        "_parser",
        "_parsed_at",
        "_source",
    }
)


# Odcisk rankingu (`request_matching_context`) od zawsze pomijał tylko te dwa
# klucze; poszerzenie o resztę `_NON_REQUIREMENT_KEYS` zmieniłoby odcisk KAŻDEJ
# oferty i jednorazowo unieważniło wszystkie migawki rankingu.
RANKING_IGNORED_KEYS = frozenset(
    {"verification", "recommended_searches", "insights", "client_history"}
)


# Wymagania do wyszukiwania w bazie (sekcja 2, 25.09.2026) zasilają WYŁĄCZNIE
# „Szukaj ręcznie” — decyzja Artura: automaty (przegląd bazy, propozycje)
# liczą z must/nice. Ich edycja nie może więc ani skasować zatwierdzonego
# kontraktu wymagań, ani zmienić odcisku rankingu (409 na pełnym przeglądzie).
_SEARCH_ONLY_KEYS = ("requirements", "exclude")


def requirement_source(
    profile: Any, *, ignored: frozenset = _NON_REQUIREMENT_KEYS
) -> Any:
    """Profil bez maszynerii — do porównań „czy zmieniły się wymagania".

    Pusta sekcja `experience` jest usuwana: każdy zapis po 09.2026 dokłada ją
    z wartością domyślną, a jej pojawienie się nie jest zmianą wymagań. Tak
    samo pusta lista `insights` i pusty blok `client_history`, gdy wołający
    ich nie pomija. Z sekcji `search` zawsze wypadają wiersze wyszukiwania
    (`_SEARCH_ONLY_KEYS`) — dla obu porównań, więc profile sprzed tych pól
    i po nich dają ten sam odcisk.
    """
    if not isinstance(profile, Mapping):
        return profile
    out = {k: v for k, v in profile.items() if k not in ignored}
    search = out.get("search")
    if isinstance(search, Mapping) and any(k in search for k in _SEARCH_ONLY_KEYS):
        out["search"] = {k: v for k, v in search.items() if k not in _SEARCH_ONLY_KEYS}
    exp = out.get("experience")
    if (
        isinstance(exp, Mapping)
        and not any(
            exp.get(key) for key in ("domains", "certifications", "regulations")
        )
        and _blank(exp.get("notes"))
    ):
        out.pop("experience")
    return out


def search_requirements(source: Any) -> list[list[str]]:
    """Wiersze wymagań do wyszukiwania w bazie (sekcja 2) — puste pomijane."""
    section = source.get("search") if isinstance(source, Mapping) else None
    rows = section.get("requirements") if isinstance(section, Mapping) else None
    out: list[list[str]] = []
    for row in rows or []:
        if not isinstance(row, list):
            continue
        words = [w.strip() for w in row if isinstance(w, str) and w.strip()]
        if words:
            out.append(words)
    return out


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


def api_response(profile: Any) -> dict:
    """Profil W NOWYM KSZTAŁCIE do odesłania frontowi — jedyne wyjście na zewnątrz.

    Front zna wyłącznie siedem sekcji (`basics`, `search`, `stack`, `project`,
    `screening_questions`, `client`, `documents`). Zwrócenie mu surowego JSONB
    sprzed 09.2026 daje **pusty formularz na wypełnionym profilu**: edytor składa
    stan jako `{...EMPTY_CHAMPION_PROFILE, ...loaded}`, a stary kształt nie ma
    żadnego z nowych kluczy — przeżywa tylko `screening_questions`, bo jako
    jedyny nie zmienił nazwy.

    To nie jest usterka kosmetyczna: zapis z takiego pustego formularza nakłada
    puste sekcje na zmigrowany profil i **kasuje treść**, którą migracja właśnie
    poprawnie odczytała. Wykryte na produkcji (oferta 408936: `role_name`,
    `rate_value` 122.5, `seniority_min_years` 10 i opis projektu obecne w bazie,
    a wszystkie pola w UI puste).

    Ta funkcja jako JEDYNA w module używa Pydantica — reszta to celowo tanie
    operacje na słownikach, bo woła je pętla scoringu (patrz docstring modułu).
    Tu jest inaczej i słusznie: to granica API, wołana raz na żądanie, a
    rekonstrukcja przez model jest tym, co gwarantuje kompletny kształt zamiast
    „tego, co akurat było w bazie".

    Import `ChampionProfile` jest lokalny, żeby moduł czytany w pętli scoringu
    nie ciągnął za sobą schematów przy każdym starcie.
    """
    if not profile:
        return {}
    from app.schemas.champion import ChampionProfile

    out = ChampionProfile.model_validate(profile).model_dump(mode="json")
    # Sekcja 8 jako WIDOK: notatki zapisane + wpisy ze starych pól
    # i z weryfikacji. Zapis (`merge_insights`) rozpoznaje je po id.
    out["insights"] = [
        {
            **note,
            "created_at": _iso(note.get("created_at")),
            "updated_at": _iso(note.get("updated_at")),
        }
        for note in insights(out)
    ]
    return out


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
