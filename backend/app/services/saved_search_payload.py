"""Jeden format zapisanego wyszukiwania kandydatów (``version: 3``).

Do 09.2026 pod ``entity="candidates"`` żyły DWA niezgodne ładunki:

* lista — ``{version: 2, qs, api}`` (``frontend/src/lib/candidate-saved-search.ts``);
  ``api`` to parametry ``GET /api/candidates`` odtwarzane przez skaner alertów,
* wyszukiwarka — surowe ciało ``CandidateSearchRequest``
  (``frontend/src/lib/candidate-search-request.ts``).

Format v3 niesie JEDNO żądanie w kształcie wspólnym dla obu silników i jawnie
deklaruje ``semantics_version: 2`` (``candidate_search_predicates.Semantics``)::

    {
      "version": 3,
      "semantics_version": 2,
      "origin": "candidates_list" | "search_request",
      "request": { …wspólne filtry…, "list_only": {…}, "search_only": {…} },
      "qs": "…&sv=2",          # tylko origin=candidates_list — stan UI listy
      "legacy": { …oryginalny ładunek… },
      "migration": { …liczniki, bez danych osobowych… }
    }

Ten moduł jest CZYSTY (bez bazy) i ma lustro w TypeScripcie
(``frontend/src/lib/saved-search-unified.ts``). Parytet pilnuje wspólny plik
``frontend/src/lib/__fixtures__/saved-search-unified-cases.json`` czytany przez
pytest i vitest. Zmiana mapowania = ten plik + oba adaptery.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

UNIFIED_VERSION = 3
UNIFIED_SEMANTICS = 2

Origin = Literal["candidates_list", "search_request"]
Format = Literal["unified", "candidates_list", "search_request", "unknown"]

# Klucze, po których rozpoznajemy surowe żądanie wyszukiwarki — lustro
# `REQUEST_KEYS` z `frontend/src/lib/saved-search-format.ts`.
_SEARCH_REQUEST_KEYS = (
    "q",
    "q_all",
    "q_any",
    "q_any_groups",
    "q_none",
    "skills_must",
    "skills_any",
    "skills_none",
    "competence_category_ids",
    "location_cities",
    "location_countries",
    "languages",
    "rate_hourly_min",
    "rate_hourly_max",
    "status",
    "availability_status",
    "search_mode",
    "sort",
    "exclude_blacklisted",
)

# Parametry listy, których zapis nie niesie (stronicowanie i dodatki widoku).
_LIST_DROPPED = frozenset(
    {
        "page",
        "page_size",
        "id_after",
        "updated_after",
        "include_match_stats",
        "include_active_recruitments",
        "include_last_activity",
        "match_threshold",
        "profile_id",
        "semantics_version",
        "skill_combine",
    }
)
_SEARCH_DROPPED = frozenset({"page", "page_size", "semantics_version"})

# Pola WSPÓLNE w kształcie v3 (kolejność = kolejność w zapisie).
_SHARED_KEYS = (
    "q",
    "text_mode",
    "q_all",
    "q_any_groups",
    "q_none",
    "skills_required",
    "skills_required_any_groups",
    "skills_preferred",
    "skills_excluded",
    "status",
    "availability_status",
    "open_to",
    "competence_category_ids",
    "rate_hourly_min",
    "rate_hourly_max",
    "experience_years_min",
    "experience_years_max",
    "tags",
    "languages",
    "location_cities",
    "location_countries",
    "location_scope",
    "hide_unknown",
)

_OPEN_TO_FLAGS = (
    ("open_to_side_projects", "side_projects"),
    ("open_to_sales_support", "sales_support"),
    ("open_to_expert_consult", "expert_consult"),
)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _as_list(value: Any) -> list[Any]:
    if _empty(value):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _split_pipe(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]


def _languages_from_list(value: Any) -> list[dict[str, Any]]:
    """Parametr listy ``languages`` (``"en"`` / ``"en:B2"``) → kształt wspólny
    ``[{code, min_level?}]`` — ten sam co ``languages`` wyszukiwarki. Brak
    poziomu zostaje brakiem (oba silniki przyjmują wtedy próg domyślny B2)."""
    out: list[dict[str, Any]] = []
    for entry in _as_list(value):
        if isinstance(entry, dict):
            out.append(dict(entry))
            continue
        code, sep, level = str(entry).strip().partition(":")
        if not code.strip():
            continue
        item: dict[str, Any] = {"code": code.strip().upper()}
        level = level.strip()
        if sep and level:
            item["min_level"] = "native" if level.lower() == "native" else level.upper()
        out.append(item)
    return out


def _languages_to_list(value: Any) -> list[str]:
    """Kształt wspólny ``[{code, min_level?}]`` → parametr listy ``kod[:POZIOM]``."""
    out: list[str] = []
    for entry in _as_list(value):
        if isinstance(entry, dict):
            code = str(entry.get("code") or "").strip()
            if not code:
                continue
            level = entry.get("min_level")
            out.append(f"{code}:{level}" if level else code)
        elif str(entry).strip():
            out.append(str(entry).strip())
    return out


def _compact(request: dict[str, Any]) -> dict[str, Any]:
    """Bez pustych wartości; ``semantics_version`` zawsze na początku."""
    out: dict[str, Any] = {"semantics_version": UNIFIED_SEMANTICS}
    for key in _SHARED_KEYS:
        if not _empty(request.get(key)):
            out[key] = request[key]
    for key in ("list_only", "search_only"):
        extra = {k: v for k, v in (request.get(key) or {}).items() if not _empty(v)}
        if extra:
            out[key] = extra
    return out


def detect_format(filters: Any) -> Format:
    if not isinstance(filters, dict):
        return "unknown"
    if filters.get("version") == UNIFIED_VERSION and isinstance(
        filters.get("request"), dict
    ):
        return "unified"
    if isinstance(filters.get("qs"), str) or isinstance(filters.get("api"), dict):
        return "candidates_list"
    if any(key in filters for key in _SEARCH_REQUEST_KEYS):
        return "search_request"
    return "unknown"


def list_api_to_unified(api: dict[str, Any]) -> dict[str, Any]:
    """Parametry ``GET /api/candidates`` (``filters.api``) → żądanie wspólne.

    Pola legacy listy są TWARDE, więc lądują w „Musi mieć" / grupach /
    „Wyklucz" — dokładnie to, co znaczyły.
    """
    required = [str(s) for s in _as_list(api.get("skills_required"))]
    groups = [_split_pipe(g) for g in _as_list(api.get("skills_required_any_groups"))]
    legacy_skills = [str(s) for s in _as_list(api.get("skills")) if str(s).strip()]
    if legacy_skills:
        if str(api.get("skill_combine") or "and").strip().lower() == "or":
            flat: list[str] = []
            for entry in legacy_skills:
                flat.extend(_split_pipe(entry))
            groups.append(flat)
        else:
            required.extend(legacy_skills)
    groups.extend(_split_pipe(g) for g in _as_list(api.get("skills_any")))
    excluded: list[str] = []
    for entry in _as_list(api.get("skills_none")) + _as_list(
        api.get("skills_excluded")
    ):
        excluded.extend(_split_pipe(entry))

    q_groups: list[list[str]] = []
    if _as_list(api.get("q_any")):
        q_groups.append([str(v) for v in _as_list(api.get("q_any"))])
    q_groups.extend(_split_pipe(g) for g in _as_list(api.get("q_any_group")))

    cities = _as_list(api.get("location")) + _as_list(api.get("location_cities"))

    consumed = {
        "q",
        "text_mode",
        "q_all",
        "q_any",
        "q_any_group",
        "q_none",
        "skills",
        "skills_any",
        "skills_none",
        "skills_required",
        "skills_required_any_groups",
        "skills_preferred",
        "skills_excluded",
        "status",
        "availability",
        "open_to",
        "competence_category_id",
        "min_rate",
        "max_rate",
        "min_experience",
        "max_experience",
        "tags",
        "languages",
        "location",
        "location_cities",
        "country",
        "location_scope",
        "hide_unknown",
    }
    return _compact(
        {
            "q": api.get("q"),
            "text_mode": api.get("text_mode"),
            "q_all": _as_list(api.get("q_all")),
            "q_any_groups": [g for g in q_groups if g],
            "q_none": _as_list(api.get("q_none")),
            "skills_required": required,
            "skills_required_any_groups": [g for g in groups if g],
            "skills_preferred": _as_list(api.get("skills_preferred")),
            "skills_excluded": excluded,
            "status": _as_list(api.get("status")),
            "availability_status": _as_list(api.get("availability")),
            "open_to": _as_list(api.get("open_to")),
            "competence_category_ids": _as_list(api.get("competence_category_id")),
            "rate_hourly_min": api.get("min_rate"),
            "rate_hourly_max": api.get("max_rate"),
            "experience_years_min": api.get("min_experience"),
            "experience_years_max": api.get("max_experience"),
            "tags": _as_list(api.get("tags")),
            "languages": _languages_from_list(api.get("languages")),
            "location_cities": cities,
            "location_countries": _as_list(api.get("country")),
            "location_scope": api.get("location_scope"),
            "hide_unknown": api.get("hide_unknown"),
            "list_only": {
                k: v
                for k, v in api.items()
                if k not in consumed and k not in _LIST_DROPPED
            },
        }
    )


def search_request_to_unified(body: dict[str, Any]) -> dict[str, Any]:
    """Surowe ``CandidateSearchRequest`` → żądanie wspólne.

    Chipy ``skills_must`` / ``skills_any`` były w wyszukiwarce sygnałem
    RANKINGOWYM, więc lądują w „Mile widziane"; twarde było tylko
    ``skills_none``. Przełączniki ``open_to_*: true`` przechodzą do listy
    ``open_to``; ``false`` („NIE jest otwarty") zostaje polem wyszukiwarki.
    """
    preferred = (
        _as_list(body.get("skills_must"))
        + _as_list(body.get("skills_any"))
        + _as_list(body.get("skills_preferred"))
    )
    excluded: list[str] = []
    for entry in _as_list(body.get("skills_none")) + _as_list(
        body.get("skills_excluded")
    ):
        excluded.extend(_split_pipe(entry))
    groups = [
        [part for entry in _as_list(group) for part in _split_pipe(entry)]
        for group in _as_list(body.get("skills_required_any_groups"))
    ]
    q_groups: list[list[str]] = []
    if _as_list(body.get("q_any")):
        q_groups.append([str(v) for v in _as_list(body.get("q_any"))])
    for group in _as_list(body.get("q_any_groups")):
        parts = [part for entry in _as_list(group) for part in _split_pipe(entry)]
        if parts:
            q_groups.append(parts)

    open_to = [str(v) for v in _as_list(body.get("open_to"))]
    search_only: dict[str, Any] = {}
    for flag, name in _OPEN_TO_FLAGS:
        if body.get(flag) is True and name not in open_to:
            open_to.append(name)
        elif body.get(flag) is False:
            search_only[flag] = False

    consumed = {
        "q",
        "text_mode",
        "q_all",
        "q_any",
        "q_any_groups",
        "q_none",
        "skills_must",
        "skills_any",
        "skills_none",
        "skills_required",
        "skills_required_any_groups",
        "skills_preferred",
        "skills_excluded",
        "status",
        "availability_status",
        "open_to",
        "competence_category_ids",
        "rate_hourly_min",
        "rate_hourly_max",
        "experience_years_min",
        "experience_years_max",
        "tags",
        "languages",
        "location_cities",
        "location_countries",
        "location_scope",
        "hide_unknown",
    } | {flag for flag, _ in _OPEN_TO_FLAGS}
    for key, value in body.items():
        if key not in consumed and key not in _SEARCH_DROPPED:
            search_only[key] = value

    return _compact(
        {
            "q": body.get("q"),
            "text_mode": body.get("text_mode"),
            "q_all": _as_list(body.get("q_all")),
            "q_any_groups": q_groups,
            "q_none": _as_list(body.get("q_none")),
            "skills_required": _as_list(body.get("skills_required")),
            "skills_required_any_groups": [g for g in groups if g],
            "skills_preferred": preferred,
            "skills_excluded": excluded,
            "status": _as_list(body.get("status")),
            "availability_status": _as_list(body.get("availability_status")),
            "open_to": open_to,
            "competence_category_ids": _as_list(body.get("competence_category_ids")),
            "rate_hourly_min": body.get("rate_hourly_min"),
            "rate_hourly_max": body.get("rate_hourly_max"),
            "experience_years_min": body.get("experience_years_min"),
            "experience_years_max": body.get("experience_years_max"),
            "tags": _as_list(body.get("tags")),
            "languages": _as_list(body.get("languages")),
            "location_cities": _as_list(body.get("location_cities")),
            "location_countries": _as_list(body.get("location_countries")),
            "location_scope": body.get("location_scope"),
            "hide_unknown": body.get("hide_unknown"),
            "search_only": search_only,
        }
    )


def read_saved_search(
    filters: Any,
) -> tuple[Format, Optional[Origin], Optional[dict[str, Any]]]:
    """Dowolny z trzech formatów → ``(format, origin, żądanie wspólne)``.

    Żądanie jest ``None``, gdy zapisu nie da się odczytać bez przeglądarki:
    najstarszy format listy ``{qs}`` bez ``api`` (querystring rozumie wyłącznie
    ``decodeFilters`` po stronie frontu).
    """
    fmt = detect_format(filters)
    if fmt == "unified":
        origin = filters.get("origin")
        if origin not in ("candidates_list", "search_request"):
            origin = "candidates_list"
        return fmt, origin, _compact(filters["request"])
    if fmt == "candidates_list":
        api = filters.get("api")
        if not isinstance(api, dict):
            return fmt, "candidates_list", None
        return fmt, "candidates_list", list_api_to_unified(api)
    if fmt == "search_request":
        return fmt, "search_request", search_request_to_unified(filters)
    return fmt, None, None


def unified_to_list_params(request: dict[str, Any]) -> dict[str, Any]:
    """Żądanie wspólne → parametry ``GET /api/candidates`` (zawsze v2)."""
    req = _compact(request)
    out: dict[str, Any] = dict(req.get("list_only") or {})
    out["semantics_version"] = UNIFIED_SEMANTICS
    direct = {
        "q": "q",
        "text_mode": "text_mode",
        "q_all": "q_all",
        "q_none": "q_none",
        "skills_required": "skills_required",
        "skills_preferred": "skills_preferred",
        "skills_excluded": "skills_excluded",
        "status": "status",
        "availability_status": "availability",
        "open_to": "open_to",
        "competence_category_ids": "competence_category_id",
        "rate_hourly_min": "min_rate",
        "rate_hourly_max": "max_rate",
        "experience_years_min": "min_experience",
        "experience_years_max": "max_experience",
        "tags": "tags",
        "location_cities": "location_cities",
        "location_countries": "country",
        "location_scope": "location_scope",
        "hide_unknown": "hide_unknown",
    }
    for source, target in direct.items():
        if source in req:
            out[target] = req[source]
    if "skills_required_any_groups" in req:
        out["skills_required_any_groups"] = [
            "|".join(g) for g in req["skills_required_any_groups"]
        ]
    if "q_any_groups" in req:
        out["q_any_group"] = ["|".join(g) for g in req["q_any_groups"]]
    if "languages" in req:
        out["languages"] = _languages_to_list(req["languages"])
    return out


def with_literal_text(params: dict[str, Any]) -> dict[str, Any]:
    """Parametry listy z tekstem ``q`` czytanym DOSŁOWNIE.

    Od 22.09.2026 lista w v2 z ``text_mode`` auto/semantic odpala retrieval
    semantyczny (Voyage, pula ≤ ``SEARCH_HYBRID_POOL_SIZE`` z CAŁEJ bazy).
    Skaner alertów i porównanie w migracji zapisów odtwarzają zapis tak, jak
    lista działała dotąd — dosłownie: pula z całej bazy przecięta ze znakiem
    wodnym ``id_after`` gubiłaby nowych kandydatów, a każdy przebieg płaciłby
    za embeddingi.
    """
    if params.get("text_mode") in ("auto", "semantic"):
        return {**params, "text_mode": "literal"}
    return params


def unified_to_search_body(request: dict[str, Any]) -> dict[str, Any]:
    """Żądanie wspólne → ciało ``POST /api/search/candidates`` (zawsze v2)."""
    req = _compact(request)
    out: dict[str, Any] = dict(req.get("search_only") or {})
    out["semantics_version"] = UNIFIED_SEMANTICS
    for key in _SHARED_KEYS:
        if key in req:
            out[key] = req[key]
    return out


def list_engine_gaps(request: dict[str, Any]) -> list[str]:
    """Pola, których lista NIE umie wyrazić (np. źródła, „ma CV") — zapis z nimi
    nie może być odtwarzany przez listę jako alert, bo byłby szerszy."""
    ignored = {"sort", "search_mode"}
    gaps: list[str] = []
    for key, value in (request.get("search_only") or {}).items():
        if key in ignored:
            continue
        # Runda 8 (R8-N10-6): oba przełączniki ZAWĘŻAJĄ wynik. Pominięte
        # w odtworzeniu dawały alert szerszy niż zapis (osoby z czarnej listy
        # i osoby już w rekrutacji). Nie są luką tylko wtedy, gdy nic nie
        # zawężają: wyłączone albo czarną listę i tak wyklucza filtr statusu.
        if key == "exclude_blacklisted":
            statuses = request.get("status") or []
            if not value or (statuses and "blacklisted" not in statuses):
                continue
        if key == "exclude_in_job_id" and value is None:
            continue
        gaps.append(key)
    return sorted(gaps)


def build_unified_payload(
    filters: dict[str, Any],
    *,
    origin: Origin,
    request: dict[str, Any],
    migration: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Zapis v3. Oryginał zostaje w ``legacy`` (droga powrotu, bez utraty pól)."""
    payload: dict[str, Any] = {
        "version": UNIFIED_VERSION,
        "semantics_version": UNIFIED_SEMANTICS,
        "origin": origin,
        "request": _compact(request),
    }
    qs = filters.get("qs")
    if origin == "candidates_list" and isinstance(qs, str):
        payload["qs"] = with_semantics_marker(with_request_flags(qs, request))
    payload["legacy"] = (
        filters.get("legacy") if detect_format(filters) == "unified" else filters
    )
    if migration is not None:
        payload["migration"] = migration
    return payload


def with_request_flags(qs: str, request: dict[str, Any]) -> str:
    """Flagi żądania, które zmieniają wynik, także w querystringu UI listy.

    Audyt 22.09 r2 (CAND-06): migracja neutralizuje zapis z listy flagami
    ``hide_unknown`` i ``location_scope="location_only"``, a alert liczy się
    z ``request``. Bez nich w ``qs`` otwarty zapis pokazywał SZERSZY zbiór niż
    alert (lista: ``hu=1``, ``ls=location_only``). Dopisuje tylko brakujące.
    """
    parts = [p for p in qs.split("&") if p]
    keys = {p.split("=", 1)[0] for p in parts}
    if request.get("hide_unknown") is True and "hu" not in keys:
        parts.append("hu=1")
    if request.get("location_scope") == "location_only" and "ls" not in keys:
        parts.append("ls=location_only")
    return "&".join(parts)


def with_semantics_marker(qs: str) -> str:
    """Dopisuje ``sv=2`` do querystringu listy (raz) — po nim UI wysyła
    ``semantics_version=2`` i pokazuje TEN SAM zbiór, który liczy alert."""
    parts = [p for p in qs.split("&") if p and not p.startswith("sv=")]
    parts.append(f"sv={UNIFIED_SEMANTICS}")
    return "&".join(parts)


# ── Migracja: zachowanie dotychczasowych wyników ────────────────────────────

# Znacznik na ładunku LEGACY: właściciel wybrał „Zostaw po staremu" — zapis
# zostaje przy v1 i kolejne przebiegi migracji go nie ruszają.
KEEP_LEGACY_KEY = "keep_legacy_semantics"

# Kody reguł, które mogą zmienić wynik zapisu po przejściu na wspólną semantykę.
# Same kody (bez danych) — UI tłumaczy je na krótkie zdania po polsku
# (`frontend/src/lib/saved-search-reapproval.ts`).
RULE_LOCATION_WILDCARDS = "location_wildcards"
RULE_TAGS_WHOLE_MATCH = "tags_whole_match"
RULE_CATEGORY_SECONDARY = "category_secondary"
RULE_OPEN_TO_ANY = "open_to_any"
RULE_EXPERIENCE_TRAFFIT = "experience_traffit_fallback"
RULE_TEXT_PERSON = "text_person_literal"
RULE_OTHER = "other"


def neutralise_list_request(
    request: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Zapis z LISTY po migracji ma zwracać DOKŁADNIE to, co dotąd.

    Lista v1 wycinała osoby bez stawki / lokalizacji / stażu i czytała samą
    kolumnę ``location`` — oba zachowania da się wyrazić flagami żądania v2:
    ``hide_unknown`` i ``location_scope="location_only"``. Zwraca żądanie
    i listę zastosowanych flag. Zapisy z wyszukiwarki tego nie potrzebują
    (osoby bez danych widziały od zawsze).
    """
    out = dict(request)
    applied: list[str] = []
    uses_unknown = any(
        key in out
        for key in (
            "rate_hourly_min",
            "rate_hourly_max",
            "experience_years_min",
            "experience_years_max",
            "location_cities",
            "location_countries",
        )
    )
    if uses_unknown and out.get("hide_unknown") is None:
        out["hide_unknown"] = True
        applied.append("hide_unknown")
    if out.get("location_cities") and not out.get("location_scope"):
        out["location_scope"] = "location_only"
        applied.append("location_scope")
    return _compact(out), applied


def possible_difference_rules(origin: str, request: dict[str, Any]) -> list[str]:
    """Które reguły wspólnej semantyki DOTYCZĄ tego zapisu i nie dają się
    zneutralizować flagą. Gdy wynik się różni, to one są przyczyną; pusta lista
    przy różnicy = ``other``."""
    rules: list[str] = []
    if origin == "candidates_list":
        if any(
            "%" in str(c) or "_" in str(c) for c in request.get("location_cities") or []
        ):
            rules.append(RULE_LOCATION_WILDCARDS)
        return rules
    if request.get("tags"):
        rules.append(RULE_TAGS_WHOLE_MATCH)
    if request.get("competence_category_ids"):
        rules.append(RULE_CATEGORY_SECONDARY)
    if len(request.get("open_to") or []) > 1:
        rules.append(RULE_OPEN_TO_ANY)
    if "experience_years_min" in request or "experience_years_max" in request:
        rules.append(RULE_EXPERIENCE_TRAFFIT)
    return rules


def is_pinned_to_legacy(filters: Any) -> bool:
    return isinstance(filters, dict) and filters.get(KEEP_LEGACY_KEY) is True


def list_payload_is_unified(filters: Any) -> bool:
    """Zapis z LISTY w formacie ``{version: 2, qs, api}``, którego ``api`` już
    niesie ``semantics_version: 2`` — lista zapisuje tak od 21.09.2026 (UI
    domyślnie w v2). Taki zapis liczy się już wspólną semantyką, więc migracja
    NIE może dokładać flag neutralizujących dawne zachowanie listy
    (``hide_unknown``, ``location_scope``) — zmieniłyby wynik zapisu i wymusiły
    ponowną akceptację czegoś, co właściciel zapisał po nowemu.
    """
    if not isinstance(filters, dict):
        return False
    api = filters.get("api")
    if not isinstance(api, dict):
        return False
    try:
        return int(api.get("semantics_version") or 0) == 2
    except (TypeError, ValueError):
        return False


def restore_legacy_payload(filters: dict[str, Any]) -> Optional[dict[str, Any]]:
    """„Zostaw po staremu": oryginalny ładunek sprzed migracji + znacznik, że
    zostaje przy v1. ``None``, gdy zapis nie niesie oryginału."""
    legacy = filters.get("legacy")
    if not isinstance(legacy, dict):
        return None
    return {**legacy, KEEP_LEGACY_KEY: True}
