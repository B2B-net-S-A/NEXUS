"""Rejestr narzędzi Jarvisa.

Każde narzędzie to OPIS wywołania istniejącego API — nigdy własna logika
domenowa ani własny SQL. Wykonanie idzie przez ``transport.JarvisTransport``
tokenem pytającego, więc bramki sekcji, członkostwa, portfela DL i redakcja
kwot działają dokładnie tak, jak na ekranie tej osoby.

Trzy poziomy (``tier``):

- ``read``  — odczyt; wykonywany od razu, w trakcie tury.
- ``write`` — zapis odwracalny; model tylko PROPONUJE. Serwer zapisuje
  ``jarvis_actions(status=proposed)``, a wykonanie następuje dopiero po
  kliknięciu „Zrób to” przez człowieka.
- ``link``  — operacje, których Jarvis nigdy nie wykonuje (usuwanie,
  wypowiedzenia, podpisy, stawki, maile). Narzędzie zwraca link do ekranu,
  na którym człowiek klika sam.

Dodając narzędzie: opis dla modelu po polsku (co zwraca, kiedy wołać),
``label`` widoczny w UI („Sprawdzam…”), ``section`` do filtrowania listy
podawanej modelowi i ``shape`` przycinający wynik (koszt tokenów). Kontrakt
pilnuje ``tests/test_jarvis_tool_registry_contract.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.data.screen_guides import SCREEN_KEYS
from app.services.section_permissions import ProductSection

Tier = Literal["read", "write", "link"]

# Wynik narzędzia podawany modelowi nie przekracza tylu znaków — dłuższy jest
# przycinany z jawnym dopiskiem, żeby model wiedział, że widzi fragment.
MAX_RESULT_CHARS = 6000
MAX_LIST_ITEMS = 20
MAX_STRING_CHARS = 1500


@dataclass(frozen=True)
class RequestSpec:
    method: str
    path: str
    params: Optional[dict[str, Any]] = None
    json: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class JarvisTool:
    name: str
    label: str
    description: str
    input_schema: dict[str, Any]
    tier: Tier
    # Szablon ścieżki — do testu kontraktowego (trasa musi istnieć) i do
    # listy zakazanej. ``None`` tylko dla narzędzi ``link``.
    method: Optional[str]
    path: Optional[str]
    section: Optional[ProductSection]
    build: Callable[[dict[str, Any]], RequestSpec] = field(repr=False)
    shape: Callable[[Any, dict[str, Any]], Any] = field(repr=False)
    # Typ rekordu, którego ID niosą argumenty/wynik (RODO: powiązanie rozmowy).
    entity_type: Optional[str] = None
    # Klucze react-query do odświeżenia po wykonaniu akcji (front).
    invalidates: tuple[tuple[str, ...], ...] = ()
    # Zdanie na karcie akcji (tylko ``write``) — budowane z args po stronie
    # serwera, nie przez model.
    preview: Optional[Callable[[dict[str, Any]], str]] = field(default=None, repr=False)
    # Pełna treść pokazywana POD zdaniem karty jako zwykły tekst (audyt 22.09
    # r2, SEC-07): zdanie przycina treść do 160 znaków, a „Zrób to" zapisuje
    # całość — człowiek musi widzieć dokładnie to, co zatwierdza.
    detail: Optional[Callable[[dict[str, Any]], str]] = field(default=None, repr=False)
    # Komunikat po udanym wykonaniu akcji (tylko ``write``).
    done: str = "Gotowe."

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ── pomocniki kształtu wyniku ──────────────────────────────────────────────


def trim(value: Any, *, depth: int = 0) -> Any:
    """Przycina zagnieżdżone listy i długie teksty — bez zmiany kształtu."""
    if isinstance(value, dict):
        return {k: trim(v, depth=depth + 1) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        items = [trim(v, depth=depth + 1) for v in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append(f"… i {len(value) - MAX_LIST_ITEMS} więcej")
        return items
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        return value[:MAX_STRING_CHARS] + "…"
    return value


def pick(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return item
    return {k: item[k] for k in keys if k in item and item[k] not in (None, "", [], {})}


def pick_list(keys: tuple[str, ...], *, items_key: str = "items"):
    def _shape(data: Any, _args: dict[str, Any]) -> Any:
        if isinstance(data, list):
            rows = data
            meta: dict[str, Any] = {}
        elif isinstance(data, dict):
            rows = data.get(items_key) or []
            meta = {
                k: data[k]
                for k in ("total", "page", "page_size", "total_active", "unread_count")
                if k in data
            }
        else:
            return data
        return trim({**meta, items_key: [pick(r, keys) for r in rows]})

    return _shape


def as_is(data: Any, _args: dict[str, Any]) -> Any:
    return trim(data)


def render_result(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …[wynik przycięty — zawęź zapytanie]"
    return text


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v not in (None, "", [])}


def _limit(args: dict[str, Any], key: str = "limit", default: int = 10) -> int:
    try:
        return max(1, min(int(args.get(key) or default), MAX_LIST_ITEMS))
    except (TypeError, ValueError):
        return default


def _int(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Brak wymaganego pola {key}")
    return int(value)


def _schema(
    properties: dict[str, Any], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


INT = {"type": "integer"}
STR = {"type": "string"}
BOOL = {"type": "boolean"}
LIMIT = {"type": "integer", "minimum": 1, "maximum": MAX_LIST_ITEMS}
PERIOD = {
    "type": "string",
    "enum": ["week", "month", "quarter", "year"],
    "description": "Okres raportu; domyślnie miesiąc.",
}
OFFSET = {
    "type": "integer",
    "maximum": 0,
    "description": "0 = bieżący okres, -1 = poprzedni zamknięty itd.",
}


# ── kształty specyficzne ───────────────────────────────────────────────────

_CANDIDATE_ROW = (
    "id",
    "name",
    "lastname",
    "status",
    "availability_status",
    "competence_category",
    "current_position",
    "location_city",
    "skills",
    "expected_rate_hourly",
    "experience_years",
    "active_recruitments",
    "last_activity_at",
    "score",
)


def _shape_search(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    return trim(
        {
            "total": data.get("total"),
            "items": [pick(r, _CANDIDATE_ROW) for r in data.get("items") or []],
        }
    )


def _shape_kanban(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    columns = []
    for col in data.get("columns") or []:
        columns.append(
            {
                "stage": col.get("name") or col.get("stage"),
                "stage_code": col.get("stage"),
                "stage_def_id": col.get("stage_def_id"),
                "count": col.get("count"),
                "cards": [
                    pick(
                        card,
                        (
                            "candidate_id",
                            "name",
                            "lastname",
                            "days_in_stage",
                            "moved_at",
                            "process_state_version",
                            "screening_done",
                            "scorecard_done",
                        ),
                    )
                    for card in (col.get("items") or [])
                ],
            }
        )
    return trim({"job_id": data.get("job_id"), "columns": columns})


def _shape_next_steps(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    jobs = []
    for job in data.get("jobs") or []:
        jobs.append(
            {
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "client_name": job.get("client_name"),
                "board": _shape_kanban(job.get("view") or {}, {}),
            }
        )
    return trim({**{k: v for k, v in data.items() if k != "jobs"}, "jobs": jobs})


_MY_PEOPLE_KEYS = (
    "candidate_id",
    "full_name",
    "category_id",
    "furthest_stage",
    "last_sent_client_name",
    "last_sent_job_title",
    "days_since_last_send",
    "sent_count",
    "active_processes",
    "expected_rate_hourly",
    "availability_status",
    "new_matches",
)


def _shape_my_people(data: Any, _args: dict[str, Any]) -> Any:
    """Tylko osoby do przepięcia — bez „Pracują" i „Uśpieni".

    Kolejność z serwera (najdalszy etap, potem najświeższa wysyłka) zostaje;
    liczniki mówią modelowi, ilu osób nie widzi.
    """
    if not isinstance(data, dict):
        return trim(data)
    rows = [
        pick(r, _MY_PEOPLE_KEYS)
        for r in data.get("rows") or []
        if isinstance(r, dict) and not r.get("working") and not r.get("snoozed")
    ]
    return trim(
        {
            "active_count": data.get("active_count"),
            "working_count": data.get("working_count"),
            "snoozed_count": data.get("snoozed_count"),
            "people": rows,
        }
    )


def _shape_my_people_for_job(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    rows = []
    for r in data.get("rows") or []:
        if not isinstance(r, dict):
            continue
        row = pick(
            r,
            (
                "candidate_id",
                "full_name",
                "score",
                "sent_to_client_at",
                "active_processes",
                "expected_rate_hourly",
            ),
        )
        # `None` to „nie policzono", nie „zero" — model musi to widzieć wprost.
        if r.get("score") is None:
            row["score"] = "niepoliczony"
        elig = r.get("eligibility")
        if isinstance(elig, dict):
            row["ostrzezenie"] = elig.get("reason")
            if elig.get("assignment_allowed") is False:
                row["nie_mozna_dodac"] = True
        rows.append(row)
    return trim(
        {
            "job_id": data.get("job_id"),
            "job_title": data.get("job_title"),
            "already_in_job": data.get("in_job_count"),
            "degraded": data.get("degraded"),
            "people": rows,
        }
    )


def _shape_client_profile(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    keep = {
        k: data[k]
        for k in (
            "client",
            "summary",
            "active_mrr",
            "open_jobs",
            "active_consultants",
            "planned_consultants",
        )
        if k in data
    }
    return trim(keep or data)


# ── narzędzia odczytu ──────────────────────────────────────────────────────


def _get(path: str, params: Optional[dict[str, Any]] = None) -> RequestSpec:
    return RequestSpec("GET", path, params=_clean(params or {}))


_BOARD_TASK_ROW = (
    "kind",
    "candidate_id",
    "candidate_name",
    "job_id",
    "job_title",
    "client_name",
    "since",
)
_BOARD_TASK_LISTS = {
    "cpro_to_send": "do wysłania do Cpro",
    "cpro_sent": "wysłane do Cpro",
    "dl_review": "czeka na przegląd Delivery Leada (kolumna QC CV)",
}


def _shape_board_tasks(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    out: dict[str, Any] = {}
    for key, label in _BOARD_TASK_LISTS.items():
        rows = [r for r in data.get(key) or [] if isinstance(r, dict)]
        out[key] = {
            "znaczenie": label,
            "count": len(rows),
            "items": [pick(r, _BOARD_TASK_ROW) for r in rows[:10]],
        }
    return trim(out)


_CYCLE_PAIR = ("candidate_id", "candidate_name", "job_id", "job_title", "client_name")
_CYCLE_TODO_LABELS = {
    "call_now": "zadzwoń do kandydata po rozmowie u klienta",
    "debrief_overdue": "zaległy debrief po rozmowie",
    "slots_pick": "wybierz termin z propozycji klienta",
    "slots_confirm": "potwierdź termin u klienta",
    "prep_missing": "brak przygotowania (prep) przed rozmową",
    "slots_missing": "brak terminów od klienta",
    "prep2_missing": "brak drugiego przygotowania",
}


def _shape_interview_cycle(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    from app.core.scheduling import business_today

    horizon = (business_today() + timedelta(days=1)).isoformat()
    todos = [
        {
            **pick(t, (*_CYCLE_PAIR, "kind", "due", "event_id", "slot_request_id")),
            "co_zrobic": _CYCLE_TODO_LABELS.get(str(t.get("kind")), t.get("kind")),
        }
        for t in data.get("todos") or []
        if isinstance(t, dict)
    ]
    agenda = [
        pick(a, (*_CYCLE_PAIR, "kind", "start", "end", "event_id", "done"))
        for a in data.get("agenda") or []
        if isinstance(a, dict) and str(a.get("start") or "")[:10] <= horizon
    ]
    return trim(
        {
            "todos": todos,
            "agenda_dzis_i_jutro": agenda,
            "okno_telefonu_min": data.get("call_window_minutes"),
            "truncated": data.get("truncated"),
        }
    )


def _shape_prep_kit(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    out = pick(
        data,
        (
            "client_overview",
            "candidate_strengths",
            "candidate_gaps",
            "selling_points",
            "recommended_strategy",
            "degraded",
            "degraded_reason",
        ),
    )
    out["likely_questions"] = list(data.get("likely_questions") or [])[:10]
    return trim(out)


def _shape_proposals(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    rows = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        person = (
            item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        )
        eligibility = (
            item.get("eligibility") if isinstance(item.get("eligibility"), dict) else {}
        )
        reassign = (
            item.get("reassign_from")
            if isinstance(item.get("reassign_from"), dict)
            else {}
        )
        rows.append(
            {
                "candidate_id": person.get("id"),
                "name": " ".join(
                    str(person.get(k) or "").strip() for k in ("name", "lastname")
                ).strip(),
                "title": person.get("title"),
                "city": person.get("city"),
                "score": item.get("score"),
                "sources": item.get("sources"),
                "is_new": item.get("is_new"),
                "ostrzezenie": eligibility.get("reason"),
                "przepiecie_z": reassign.get("title"),
            }
        )
    return trim(
        {
            "total": data.get("total"),
            "ukrytych_przez_bramke": data.get("hidden_on_page"),
            "items": rows,
        }
    )


def _shape_metric_catalog(data: Any, _args: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return trim(data)
    sources = []
    for src in data.get("sources") or []:
        if not isinstance(src, dict):
            continue
        sources.append(
            {
                **pick(
                    src,
                    (
                        "key",
                        "label",
                        "available",
                        "reason",
                        "group_by",
                        "filters",
                        "supports_author",
                    ),
                ),
                "measures": [
                    pick(m, ("key", "label", "snapshot"))
                    for m in src.get("measures") or []
                    if isinstance(m, dict)
                ],
            }
        )
    return trim(
        {
            "sources": sources,
            "stages": data.get("stages"),
            "periods": data.get("periods"),
        }
    )


READ_TOOLS: tuple[JarvisTool, ...] = (
    JarvisTool(
        name="search_candidates",
        label="Szukam kandydatów",
        description=(
            "Wyszukiwarka kandydatów w bazie NEXUS (ta sama co ekran Wyszukiwanie). "
            "Podaj frazę (np. 'Java Spring') i/lub filtry. Zwraca listę z ID, "
            "stanowiskiem, miastem, skillami i dostępnością."
        ),
        input_schema=_schema(
            {
                "query": {**STR, "description": "Fraza, np. 'senior java kafka'."},
                "skills_must": {"type": "array", "items": STR, "maxItems": 10},
                "cities": {"type": "array", "items": STR, "maxItems": 5},
                "rate_hourly_max": {"type": "number"},
                "exclude_in_job_id": {
                    **INT,
                    "description": "Pomiń kandydatów, którzy już są w tej rekrutacji.",
                },
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="POST",
        path="/api/search/candidates",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: RequestSpec(
            "POST",
            "/api/search/candidates",
            json=_clean(
                {
                    "q": a.get("query"),
                    "skills_must": a.get("skills_must") or [],
                    "location_cities": a.get("cities") or [],
                    "rate_hourly_max": a.get("rate_hourly_max"),
                    "exclude_in_job_id": a.get("exclude_in_job_id"),
                    "search_mode": "hybrid" if a.get("query") else "boolean",
                    "page": 1,
                    "page_size": _limit(a),
                }
            ),
        ),
        shape=_shape_search,
    ),
    JarvisTool(
        name="get_candidate",
        label="Czytam profil kandydata",
        description="Skrócony profil kandydata po ID: dane, skille, dostępność, aktywne rekrutacje.",
        input_schema=_schema({"candidate_id": INT}, ("candidate_id",)),
        tier="read",
        method="GET",
        path="/api/candidates/{candidate_id}/quick-view",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: _get(f"/api/candidates/{_int(a, 'candidate_id')}/quick-view"),
        shape=as_is,
    ),
    JarvisTool(
        name="get_candidate_timeline",
        label="Czytam historię kandydata",
        description="Oś czasu kandydata: notatki, ruchy w rekrutacjach, rozmowy, zdarzenia.",
        input_schema=_schema({"candidate_id": INT, "limit": LIMIT}, ("candidate_id",)),
        tier="read",
        method="GET",
        path="/api/candidates/{candidate_id}/timeline",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: _get(
            f"/api/candidates/{_int(a, 'candidate_id')}/timeline",
            {"limit": _limit(a, default=15)},
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="get_candidate_activity_summary",
        label="Czytam podsumowanie aktywności",
        description=(
            "Zapisane podsumowanie AI historii kandydata (wysyłki, feedbacki, stawki). "
            "Nie generuje nowego — 404 znaczy, że jeszcze go nie ma."
        ),
        input_schema=_schema({"candidate_id": INT}, ("candidate_id",)),
        tier="read",
        method="GET",
        path="/api/candidates/{candidate_id}/activity-summary",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: _get(
            f"/api/candidates/{_int(a, 'candidate_id')}/activity-summary"
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="global_search",
        label="Szukam w całym NEXUSIE",
        description=(
            "Szybkie wyszukiwanie po nazwie w kandydatach, rekrutacjach, klientach i "
            "kontaktach (po 5 wyników). Użyj, gdy znasz nazwę, a nie znasz ID."
        ),
        input_schema=_schema({"query": {**STR, "minLength": 2}}, ("query",)),
        tier="read",
        method="GET",
        path="/api/search/global",
        section=None,
        build=lambda a: _get("/api/search/global", {"q": a.get("query")}),
        shape=as_is,
    ),
    JarvisTool(
        name="list_jobs",
        label="Przeglądam rekrutacje",
        description="Lista rekrutacji (filtry: fraza, tylko otwarte, klient).",
        input_schema=_schema(
            {
                "query": STR,
                "open_only": {**BOOL, "description": "Domyślnie true."},
                "client_id": INT,
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="GET",
        path="/api/jobs",
        section=ProductSection.pipeline,
        build=lambda a: _get(
            "/api/jobs",
            {
                "q": a.get("query"),
                "open_only": a.get("open_only", True),
                "client_id": a.get("client_id"),
                "page_size": _limit(a),
            },
        ),
        shape=pick_list(
            (
                "id",
                "title",
                "working_title",
                "client_reference",
                "status",
                "client_name",
                "client_id",
                "deadline",
                "candidates_count",
                "recruiter_name",
                "location",
                "rate_budget_hourly",
            )
        ),
    ),
    JarvisTool(
        name="get_job",
        label="Czytam rekrutację",
        description="Szczegóły rekrutacji po ID: klient, wymagania, budżet, zespół, termin.",
        input_schema=_schema({"job_id": INT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/jobs/{job_id}",
        section=ProductSection.pipeline,
        build=lambda a: _get(f"/api/jobs/{_int(a, 'job_id')}"),
        shape=as_is,
    ),
    JarvisTool(
        name="get_job_board",
        label="Czytam tablicę rekrutacji",
        description=(
            "Tablica (kanban) rekrutacji: etapy, kandydaci na każdym etapie, dni na "
            "etapie, stage_def_id i process_state_version (potrzebne do przesunięcia)."
        ),
        input_schema=_schema({"job_id": INT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/pipeline/kanban/{job_id}",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get(f"/api/pipeline/kanban/{_int(a, 'job_id')}"),
        shape=_shape_kanban,
    ),
    JarvisTool(
        name="get_job_readiness",
        label="Sprawdzam gotowość rekrutacji",
        description="Czego brakuje rekrutacji do przekazania do searchu (lista blokad).",
        input_schema=_schema({"job_id": INT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/jobs/{job_id}/readiness",
        section=ProductSection.pipeline,
        build=lambda a: _get(f"/api/jobs/{_int(a, 'job_id')}/readiness"),
        shape=as_is,
    ),
    JarvisTool(
        name="my_next_steps",
        label="Sprawdzam Twoje następne kroki",
        description="Rekrutacje użytkownika z kandydatami czekającymi na jego ruch.",
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/pipeline/my-next-steps",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get("/api/pipeline/my-next-steps"),
        shape=_shape_next_steps,
    ),
    JarvisTool(
        name="my_people",
        label="Przeglądam Twoich ludzi",
        description=(
            "Lista „Moi ludzie” użytkownika: kandydaci, których zweryfikował jako "
            "pierwszy i których CV poszło do klienta — ludzie do ponownego "
            "polecenia. Zwraca tylko osoby do przepięcia (bez pracujących "
            "i uśpionych); `days_since_last_send` = dni od ostatniej wysyłki, "
            "`new_matches` = nowe rekrutacje, do których pasują."
        ),
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/my-people",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: _get("/api/my-people"),
        shape=_shape_my_people,
    ),
    JarvisTool(
        name="my_people_for_job",
        label="Sprawdzam, kto z Twoich ludzi pasuje",
        description=(
            "Kto z listy „Moi ludzie” pasuje do wskazanej rekrutacji: kanoniczny "
            'wynik dopasowania 0-100 ("niepoliczony" to brak danych, NIE zero), '
            "ostrzeżenia i czy osoba była już wysłana do tego klienta. Osoby już "
            "w tej rekrutacji są pominięte. Użyj przed zaproponowaniem "
            "`add_candidates_to_job`; `degraded: true` znaczy, że wyniki są "
            "chwilowo niedostępne — powiedz to, nie twierdź, że nikt nie pasuje."
        ),
        input_schema=_schema({"job_id": INT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/my-people/for-job/{job_id}",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get(f"/api/my-people/for-job/{_int(a, 'job_id')}"),
        shape=_shape_my_people_for_job,
    ),
    JarvisTool(
        name="list_notifications",
        label="Czytam powiadomienia",
        description="Powiadomienia użytkownika (nieprzeczytane najpierw).",
        input_schema=_schema({"limit": LIMIT}),
        tier="read",
        method="GET",
        path="/api/notifications",
        section=None,
        build=lambda a: _get("/api/notifications", {"limit": _limit(a)}),
        shape=pick_list(
            (
                "id",
                "title",
                "message",
                "notification_type",
                "is_read",
                "link",
                "created_at",
            )
        ),
    ),
    JarvisTool(
        name="list_client_alerts",
        label="Sprawdzam sprawy klientów",
        description=(
            "Otwarte sprawy Delivery Leada (panel „Moi klienci”): kończące się "
            "zamówienia i umowy, niska pula MD, szkice do uzupełnienia."
        ),
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/dl-alerts/cards",
        section=ProductSection.delivery,
        build=lambda a: _get("/api/dl-alerts/cards"),
        shape=pick_list(
            (
                "id",
                "alert_type",
                "title",
                "message",
                "priority",
                "client_name",
                "link",
                "created_at",
            ),
            items_key="cards",
        ),
    ),
    JarvisTool(
        name="list_clients",
        label="Przeglądam klientów",
        description="Katalog klientów (aktywni / relacja / nieaktywni), z wyszukiwaniem po nazwie.",
        input_schema=_schema(
            {
                "query": STR,
                "category": {
                    "type": "string",
                    "enum": ["active", "relationship", "inactive"],
                },
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="GET",
        path="/api/clients/directory",
        section=ProductSection.delivery,
        build=lambda a: _get(
            "/api/clients/directory",
            {
                "q": a.get("query"),
                "category": a.get("category") or "active",
                "page_size": _limit(a),
            },
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="get_client_profile",
        label="Czytam profil klienta",
        description=(
            "Profil klienta: obecni i planowani konsultanci, otwarte rekrutacje, MRR "
            "(kwoty tylko przy uprawnieniu)."
        ),
        input_schema=_schema({"client_id": INT}, ("client_id",)),
        tier="read",
        method="GET",
        path="/api/clients/{client_id}/profile",
        section=ProductSection.delivery,
        build=lambda a: _get(f"/api/clients/{_int(a, 'client_id')}/profile"),
        shape=_shape_client_profile,
    ),
    JarvisTool(
        name="get_client_playbook",
        label="Czytam kartę klienta",
        description="Karta klienta: SLA, limity CV, zasady procesu, co mówić kandydatom, dokumenty.",
        input_schema=_schema({"client_id": INT}, ("client_id",)),
        tier="read",
        method="GET",
        path="/api/clients/{client_id}/playbook",
        section=None,
        build=lambda a: _get(f"/api/clients/{_int(a, 'client_id')}/playbook"),
        shape=as_is,
    ),
    JarvisTool(
        name="list_contracts",
        label="Przeglądam kontrakty",
        description=(
            "Rejestr kontraktów konsultantów. Filtry: fraza (nazwisko), klient, kandydat, "
            "status, kończące się w ciągu N dni."
        ),
        input_schema=_schema(
            {
                "query": STR,
                "client_id": INT,
                "candidate_id": INT,
                "status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "draft",
                            "ready_for_signature",
                            "active",
                            "ending",
                            "ended",
                            "void",
                        ],
                    },
                },
                "expiring_in_days": {"type": "integer", "minimum": 1, "maximum": 365},
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="GET",
        path="/api/contracts",
        section=ProductSection.delivery,
        entity_type="candidate",
        build=lambda a: _get(
            "/api/contracts",
            {
                "q": a.get("query"),
                "client_id": a.get("client_id"),
                "candidate_id": a.get("candidate_id"),
                "status": a.get("status") or None,
                "expiring_in_days": a.get("expiring_in_days"),
                "page_size": _limit(a),
            },
        ),
        shape=pick_list(
            (
                "id",
                "candidate_id",
                "candidate_name",
                "client_id",
                "client_name",
                "status",
                "contract_type",
                "start_date",
                "end_date",
                "client_order_end_date",
                "rate_candidate",
                "rate_client",
                "rate_unit",
                "margin",
            )
        ),
    ),
    JarvisTool(
        name="get_contract",
        label="Czytam kontrakt",
        description=(
            "Szczegóły jednego kontraktu po ID: osoba, klient, status, daty umowy i "
            "bieżącego zamówienia, stawki i marża (kwoty tylko, gdy użytkownik ma do "
            "nich prawo), zakończenie współpracy, powiązane kontrakty."
        ),
        input_schema=_schema({"contract_id": INT}, ("contract_id",)),
        tier="read",
        method="GET",
        path="/api/contracts/{contract_id}",
        section=ProductSection.delivery,
        entity_type="candidate",
        build=lambda a: _get(f"/api/contracts/{_int(a, 'contract_id')}"),
        shape=lambda data, _a: trim(
            pick(
                data,
                (
                    "id",
                    "candidate_id",
                    "candidate_name",
                    "client_id",
                    "client_name",
                    "job_title",
                    "status",
                    "contract_type",
                    "start_date",
                    "end_date",
                    "client_order_start_date",
                    "client_order_end_date",
                    "latest_order_end_date",
                    "rate_candidate",
                    "rate_client",
                    "rate_unit",
                    "currency",
                    "monthly_rate_candidate",
                    "monthly_rate_client",
                    "monthly_margin",
                    "termination_reason",
                    "terminated_at",
                    "project_name",
                    "work_mode",
                    "engagement_model",
                    "order_consumption",
                    "order_consumption_unit",
                    "related_contracts",
                ),
            )
        ),
    ),
    JarvisTool(
        name="list_client_orders",
        label="Czytam zamówienia klienta",
        description="Zamówienia okresowe klienta — jedna karta na kontraktora z historią zamówień.",
        input_schema=_schema({"client_id": INT}, ("client_id",)),
        tier="read",
        method="GET",
        path="/api/clients/{client_id}/orders",
        section=ProductSection.delivery,
        build=lambda a: _get(f"/api/clients/{_int(a, 'client_id')}/orders"),
        shape=as_is,
    ),
    JarvisTool(
        name="list_client_order_groups",
        label="Czytam zamówienia MD i kosztowe",
        description="Zamówienia wielo-konsultantowe klienta (MD / kosztowe) z liniami i budżetem.",
        input_schema=_schema({"client_id": INT}, ("client_id",)),
        tier="read",
        method="GET",
        path="/api/clients/{client_id}/order-groups",
        section=ProductSection.delivery,
        build=lambda a: _get(f"/api/clients/{_int(a, 'client_id')}/order-groups"),
        shape=as_is,
    ),
    JarvisTool(
        name="list_calendar_events",
        label="Sprawdzam kalendarz",
        description=(
            "Wydarzenia z kalendarza (rozmowy, screeningi, spotkania). Daty ISO "
            "(RRRR-MM-DD). Bez dat = najbliższe nadchodzące."
        ),
        input_schema=_schema(
            {
                "from_date": {**STR, "format": "date"},
                "to_date": {**STR, "format": "date"},
                "mine_only": {**BOOL, "description": "Domyślnie true."},
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="GET",
        path="/api/calendar/events",
        section=ProductSection.pipeline,
        build=lambda a: _get(
            "/api/calendar/events",
            {
                "from_date": a.get("from_date"),
                "to_date": a.get("to_date"),
                "upcoming": not (a.get("from_date") or a.get("to_date")),
                "mine_only": a.get("mine_only", True),
                "limit": _limit(a),
            },
        ),
        shape=pick_list(
            (
                "id",
                "title",
                "event_type",
                "status",
                "start_time",
                "end_time",
                "all_day",
                "candidate_id",
                "candidate_name",
                "job_id",
                "job_title",
                "location",
            )
        ),
    ),
    JarvisTool(
        name="get_my_kpis",
        label="Sprawdzam Twoje KPI",
        description="Panel KPI użytkownika: cele i wykonanie (weryfikacje, CV, rozmowy, placementy).",
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/kpis/me/panel",
        section=ProductSection.insights,
        build=lambda a: _get("/api/kpis/me/panel"),
        shape=as_is,
    ),
    JarvisTool(
        name="insights_funnel",
        label="Liczę lejek rekrutacyjny",
        description="Lejek rekrutacyjny firmy w okresie (liczby na etapach, konwersje).",
        input_schema=_schema({"period": PERIOD, "offset": OFFSET}),
        tier="read",
        method="GET",
        path="/api/insights/recruitment/funnel",
        section=ProductSection.insights,
        build=lambda a: _get(
            "/api/insights/recruitment/funnel",
            {"period": a.get("period") or "month", "offset": a.get("offset", 0)},
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="insights_team_table",
        label="Liczę wyniki zespołu",
        description="Wyniki zespołu w okresie przy nazwiskach (weryfikacje, CV, rozmowy, placementy).",
        input_schema=_schema({"period": PERIOD, "offset": OFFSET}),
        tier="read",
        method="GET",
        path="/api/insights/team-table",
        section=ProductSection.insights,
        build=lambda a: _get(
            "/api/insights/team-table",
            {"period": a.get("period") or "month", "offset": a.get("offset", 0)},
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="insights_board",
        label="Liczę kokpit Rady",
        description="Kokpit Rady: przychód, marża, MRR, zejścia w okresie (kwoty przy uprawnieniu).",
        input_schema=_schema({"period": PERIOD, "offset": OFFSET}),
        tier="read",
        method="GET",
        path="/api/insights/board",
        section=ProductSection.insights,
        build=lambda a: _get(
            "/api/insights/board",
            {"period": a.get("period") or "month", "offset": a.get("offset", 0)},
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="finance_order_changes",
        label="Sprawdzam zmiany w zamówieniach",
        description=(
            "Miesięczny audyt Finansów: wejścia, zejścia, kończące się zamówienia, "
            "zmiany i braki następców."
        ),
        input_schema=_schema(
            {
                "year": {"type": "integer", "minimum": 2020, "maximum": 2100},
                "month": {"type": "integer", "minimum": 1, "maximum": 12},
                "query": STR,
                "client_id": INT,
            },
            ("year", "month"),
        ),
        tier="read",
        method="GET",
        path="/api/finance/order-changes",
        section=ProductSection.finance,
        build=lambda a: _get(
            "/api/finance/order-changes",
            {
                "year": a.get("year"),
                "month": a.get("month"),
                "q": a.get("query"),
                "client_id": a.get("client_id"),
            },
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="order_mail_status",
        label="Sprawdzam skrzynkę zamówień",
        description="Stan pobierania zamówień z maila: ostatni bieg, ile nowych, ile do weryfikacji.",
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/order-mail/sync/status",
        section=ProductSection.delivery,
        build=lambda a: _get("/api/order-mail/sync/status"),
        shape=as_is,
    ),
    JarvisTool(
        name="talent_radar_search",
        label="Przeszukuję bazę pod request klienta",
        description=(
            "Talent Radar: ranking kandydatów z bazy pod wklejony request klienta, bez "
            "zakładania rekrutacji. Wymaga ID klienta (blacklisty, NDA)."
        ),
        input_schema=_schema(
            {
                "client_id": INT,
                "text": {**STR, "description": "Treść requestu klienta."},
                "limit": LIMIT,
            },
            ("client_id", "text"),
        ),
        tier="read",
        method="POST",
        path="/api/talent-radar/search",
        section=ProductSection.sourcing,
        entity_type="candidate",
        build=lambda a: RequestSpec(
            "POST",
            "/api/talent-radar/search",
            json={
                "client_id": _int(a, "client_id"),
                "text": str(a.get("text") or "")[:8000],
                "top_k": _limit(a),
            },
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="list_talent_pools",
        label="Przeglądam pule talentów",
        description="Pule talentów widoczne dla użytkownika (ID potrzebne do dodania kandydata).",
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/talent-pools",
        section=ProductSection.sourcing,
        build=lambda a: _get("/api/talent-pools"),
        shape=pick_list(("id", "name", "description", "candidates_count", "is_shared")),
    ),
    JarvisTool(
        name="my_board_tasks",
        label="Sprawdzam kolejkę „Czeka na Ciebie”",
        description=(
            "Kolejka „Czeka na Ciebie” z pulpitu: osoby do wysłania do Cpro (Nordea), "
            "wysłane do Cpro i czekające na przegląd Delivery Leada w kolumnie "
            "QC CV — policzone dla tej osoby. Wołaj przy „co mam dziś zrobić”."
        ),
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/board-tasks",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get("/api/board-tasks"),
        shape=_shape_board_tasks,
    ),
    JarvisTool(
        name="my_interview_cycle",
        label="Sprawdzam rozmowy u klienta",
        description=(
            "Cykl rozmów u klienta: zadania (zadzwoń do kandydata po rozmowie, zaległy "
            "debrief, termin do wyboru, brak przygotowania) i agenda na dziś i jutro. "
            "scope: mine (moje, domyślnie), jobs (moje rekrutacje), all (cała firma — "
            "tylko admin i Head of Recruitment)."
        ),
        input_schema=_schema(
            {"scope": {"type": "string", "enum": ["mine", "jobs", "all"]}}
        ),
        tier="read",
        method="GET",
        path="/api/interview-cycle",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get(
            "/api/interview-cycle", {"scope": a.get("scope") or "mine"}
        ),
        shape=_shape_interview_cycle,
    ),
    JarvisTool(
        name="prep_for_interview",
        label="Przygotowuję materiały na rozmowę",
        description=(
            "Przygotowanie kandydata do rozmowy u klienta: prawdopodobne pytania (także "
            "te, które ten klient zadawał wcześniej), mocne strony, luki, argumenty "
            "i strategia. Bez kosztu AI."
        ),
        input_schema=_schema(
            {"candidate_id": INT, "job_id": INT}, ("candidate_id", "job_id")
        ),
        tier="read",
        method="POST",
        path="/api/prep-kit/generate",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: RequestSpec(
            "POST",
            "/api/prep-kit/generate",
            json={"candidate_id": _int(a, "candidate_id"), "job_id": _int(a, "job_id")},
        ),
        shape=_shape_prep_kit,
    ),
    JarvisTool(
        name="client_questions",
        label="Sprawdzam pytania klienta",
        description=(
            "Pytania, które klient tej rekrutacji zadawał na wcześniejszych rozmowach "
            "(z debriefów rekruterów), najnowsze najpierw."
        ),
        input_schema=_schema({"job_id": INT, "limit": LIMIT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/interview-cycle/client-questions",
        section=ProductSection.pipeline,
        build=lambda a: _get(
            "/api/interview-cycle/client-questions",
            {"job_id": _int(a, "job_id"), "limit": _limit(a)},
        ),
        shape=pick_list(("text", "created_at")),
    ),
    JarvisTool(
        name="get_debrief",
        label="Czytam debrief rozmowy",
        description=(
            "Zapisany debrief rozmowy u klienta (po ID wydarzenia z kalendarza albo "
            "z my_interview_cycle): jak poszło, akceptacja oferty, pytania klienta."
        ),
        input_schema=_schema({"event_id": INT}, ("event_id",)),
        tier="read",
        method="GET",
        path="/api/interview-cycle/events/{event_id}/debrief",
        section=ProductSection.pipeline,
        build=lambda a: _get(
            f"/api/interview-cycle/events/{_int(a, 'event_id')}/debrief"
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="list_job_proposals",
        label="Przeglądam propozycje do rekrutacji",
        description=(
            "Ekran „Do przejrzenia” rekrutacji: osoby zaproponowane przez automaty "
            "(przegląd bazy, nowe CV, przepięcia z podobnych rekrutacji) — wynik, "
            "źródło, ostrzeżenie. Osoby ukryte przez bramkę są tylko liczone."
        ),
        input_schema=_schema({"job_id": INT, "limit": LIMIT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/jobs/{job_id}/proposal-inbox",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get(
            f"/api/jobs/{_int(a, 'job_id')}/proposal-inbox",
            {"status": "proposed", "limit": _limit(a, default=20)},
        ),
        shape=_shape_proposals,
    ),
    JarvisTool(
        name="get_hm_feedback",
        label="Sprawdzam werdykty klienta",
        description=(
            "Werdykty hiring managera w rekrutacji (po jednym na kandydata): dalej / "
            "odrzucony / wstrzymany, powód, notatka, autor. `can_record` mówi, czy ta "
            "osoba może zapisać werdykt."
        ),
        input_schema=_schema({"job_id": INT}, ("job_id",)),
        tier="read",
        method="GET",
        path="/api/jobs/{job_id}/hiring-manager-feedback",
        section=ProductSection.pipeline,
        entity_type="candidate",
        build=lambda a: _get(f"/api/jobs/{_int(a, 'job_id')}/hiring-manager-feedback"),
        shape=lambda data, _a: trim(
            {
                "can_record": data.get("can_record")
                if isinstance(data, dict)
                else None,
                "items": [
                    pick(
                        r,
                        (
                            "candidate_id",
                            "decision",
                            "rejection_reason_name",
                            "note",
                            "overall_fit",
                            "author_name",
                            "event_title",
                        ),
                    )
                    for r in (
                        (data or {}).get("items") or []
                        if isinstance(data, dict)
                        else []
                    )
                ],
            }
        ),
    ),
    JarvisTool(
        name="order_mail_queue",
        label="Sprawdzam skrzynkę zamówień",
        description=(
            "Zamówienia z maila czekające na decyzję człowieka („Do weryfikacji”) z "
            "powodami wstrzymania; outcome=needs_review domyślnie. Opcjonalnie tylko "
            "jeden klient."
        ),
        input_schema=_schema(
            {
                "client_id": INT,
                "outcome": {
                    "type": "string",
                    "enum": [
                        "needs_review",
                        "unrecognized_client",
                        "failed",
                        "applied",
                        "auto_applied",
                    ],
                },
                "limit": LIMIT,
            }
        ),
        tier="read",
        method="GET",
        path="/api/order-mail/queue",
        section=ProductSection.delivery,
        build=lambda a: _get(
            "/api/order-mail/queue",
            {
                "outcome": a.get("outcome") or "needs_review",
                "client_id": a.get("client_id"),
                "limit": _limit(a, default=20),
            },
        ),
        shape=pick_list(
            (
                "id",
                "received_at",
                "subject",
                "attachment_name",
                "client_name",
                "outcome",
                "gate_reasons",
                "can_apply",
            )
        ),
    ),
    JarvisTool(
        name="metric_catalog",
        label="Sprawdzam, co da się policzyć",
        description=(
            "Katalog miar do evaluate_metric: źródła (ruchy w pipeline, kandydaci, "
            "rekrutacje, kontrakty, zamówienia, finanse), ich miary, podziały, etapy "
            "i okresy — oraz które są dostępne dla tej osoby."
        ),
        input_schema=_schema({}),
        tier="read",
        method="GET",
        path="/api/dashboard-metrics/catalog",
        section=None,
        build=lambda a: _get("/api/dashboard-metrics/catalog"),
        shape=_shape_metric_catalog,
    ),
    JarvisTool(
        name="evaluate_metric",
        label="Liczę",
        description=(
            "Liczy jedną miarę (np. ile CV wysłałem w zeszłym miesiącu, ilu nowych "
            "kandydatów w tym kwartale, przychód klienta). Najpierw metric_catalog — "
            "użyj kluczy z niego. author: me (moje), team, all (cała firma, jeśli wolno)."
        ),
        input_schema=_schema(
            {
                "source": {
                    "type": "string",
                    "enum": [
                        "pipeline_moves",
                        "candidates",
                        "jobs",
                        "contracts",
                        "orders",
                        "finance",
                    ],
                },
                "measure": STR,
                "stage": STR,
                "group_by": STR,
                "period": STR,
                "compare_previous": BOOL,
                "author": {"type": "string", "enum": ["me", "team", "all"]},
                "client_ids": {"type": "array", "items": INT, "maxItems": 20},
                "job_ids": {"type": "array", "items": INT, "maxItems": 20},
            },
            ("source", "measure", "period"),
        ),
        tier="read",
        method="POST",
        path="/api/dashboard-metrics/evaluate",
        section=None,
        build=lambda a: RequestSpec(
            "POST",
            "/api/dashboard-metrics/evaluate",
            json=_clean(
                {
                    "source": a.get("source"),
                    "measure": a.get("measure"),
                    "stage": a.get("stage"),
                    "group_by": a.get("group_by") or "none",
                    "period": a.get("period"),
                    "compare_previous": bool(a.get("compare_previous")),
                    "filters": _clean(
                        {
                            "author": a.get("author"),
                            "client_ids": a.get("client_ids"),
                            "job_ids": a.get("job_ids"),
                        }
                    )
                    or None,
                }
            ),
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="explain_match",
        label="Sprawdzam dopasowanie",
        description=(
            "Dlaczego kandydat pasuje (albo nie) do rekrutacji: wynik, podsumowanie, "
            "mocne strony i luki. Przy pierwszym pytaniu o parę to PŁATNE wywołanie AI — "
            "wołaj tylko na wyraźną prośbę użytkownika."
        ),
        input_schema=_schema(
            {"candidate_id": INT, "job_id": INT}, ("candidate_id", "job_id")
        ),
        tier="read",
        method="GET",
        path="/api/candidates/{candidate_id}/scoring/{job_id}",
        section=ProductSection.sourcing,
        entity_type="candidate",
        # BEZ `refresh`: ponowne liczenie zawsze płaci, a Jarvis nie ma powodu go wymuszać.
        build=lambda a: _get(
            f"/api/candidates/{_int(a, 'candidate_id')}/scoring/{_int(a, 'job_id')}"
        ),
        shape=lambda data, _a: trim(
            pick(
                data,
                (
                    "candidate_id",
                    "job_id",
                    "job_title",
                    "score",
                    "summary",
                    "pros",
                    "watchouts",
                    "generated_at",
                ),
            )
        ),
    ),
    JarvisTool(
        name="get_screen_guide",
        label="Czytam przewodnik ekranu",
        description=(
            "Przewodnik ekranu NEXUSA: co się tu robi, najczęstsze zadania krok po "
            "kroku z nazwami przycisków, pułapki i lista elementów, które da się "
            "pokazać (show_on_screen). Klucz bieżącego ekranu jest w kontekście; "
            "przy pytaniu o inny ekran wybierz jego klucz z listy."
        ),
        input_schema=_schema(
            {"key": {"type": "string", "enum": list(SCREEN_KEYS)}}, ("key",)
        ),
        tier="read",
        method="GET",
        path="/api/help/screens/{key}",
        section=None,
        build=lambda a: _get(
            f"/api/help/screens/{quote(str(a.get('key') or ''), safe='.')}"
        ),
        shape=as_is,
    ),
    JarvisTool(
        name="search_help",
        label="Szukam w Pomocy",
        description=(
            "Szuka w procedurach modułu Pomoc — użyj przy pytaniach „jak zrobić X w "
            "NEXUSIE”. Pytaj pełnym zdaniem albo kilkoma słowami; wyniki są "
            "posortowane od najtrafniejszego i mają fragment treści. Pełną treść "
            "czytasz narzędziem get_help_article."
        ),
        input_schema=_schema({"query": STR}),
        tier="read",
        method="GET",
        path="/api/procedures",
        section=None,
        build=lambda a: _get(
            "/api/procedures", {"q": a.get("query"), "ranked": "true"}
        ),
        shape=pick_list(("id", "slug", "title", "excerpt")),
    ),
    JarvisTool(
        name="get_help_article",
        label="Czytam procedurę",
        description=(
            "Treść procedury z modułu Pomoc (po ID albo slugu). Procedury bywają długie — "
            "ZAWSZE podaj `query` (np. 'PDF', 'przedłużenie'): dostaniesz sekcje, które go "
            "zawierają, plus spis wszystkich nagłówków."
        ),
        input_schema=_schema(
            {
                "id_or_slug": STR,
                "query": {
                    **STR,
                    "description": "Fraza, której szukasz w procedurze.",
                },
            },
            ("id_or_slug",),
        ),
        tier="read",
        method="GET",
        path="/api/procedures/{id_or_slug}",
        section=None,
        build=lambda a: _get(
            f"/api/procedures/{quote(str(a.get('id_or_slug') or ''), safe='')}"
        ),
        shape=lambda data, a: shape_procedure(data, a.get("query")),
    ),
)


def _fold(text: str) -> str:
    """Małe litery bez polskich znaków — wyszukiwanie „pdf” trafia „PDF-a”."""
    import unicodedata

    text = text.lower().replace("ł", "l")
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _sections(content: str) -> list[tuple[str, str]]:
    """Podział Markdownu na (nagłówek, treść) po nagłówkach ## i ###."""
    sections: list[tuple[str, str]] = []
    heading, lines = "(wstęp)", []
    for line in content.splitlines():
        if re.match(r"^#{2,3} ", line):
            if lines:
                sections.append((heading, "\n".join(lines).strip()))
            heading, lines = line.lstrip("#").strip(), []
        else:
            lines.append(line)
    if lines:
        sections.append((heading, "\n".join(lines).strip()))
    return sections


# Budżet treści sekcji w odpowiedzi — resztę limitu zjada spis nagłówków.
_PROCEDURE_BUDGET = 4500


def shape_procedure(data: Any, query: Any = None) -> Any:
    """Długa procedura NIE jest ucinana na ślepo: z `query` zwraca pasujące
    sekcje (najwięcej trafień pierwsze), zawsze ze spisem nagłówków — model
    wie, czego jeszcze może zapytać. Do 21.09 narzędzie oddawało pierwsze 5000
    znaków 40-kilobajtowej instrukcji zamówień, więc na „jak dodać zamówienie
    z PDF-a” Jarvis odpowiadał, że widzi tylko zajawkę (test na produkcji)."""
    if not isinstance(data, dict):
        return trim(data)
    content = str(data.get("content") or "")
    sections = _sections(content)
    head = {
        k: data.get(k) for k in ("id", "slug", "title", "updated_at") if data.get(k)
    }
    if len(content) <= _PROCEDURE_BUDGET:
        return {**head, "content": content}
    terms = [t for t in re.split(r"\W+", _fold(str(query or ""))) if len(t) >= 3]
    ranked: list[tuple[int, int, str, str]] = []
    for index, (title, body) in enumerate(sections):
        haystack = _fold(title + "\n" + body)
        score = sum(haystack.count(term) for term in terms) + sum(
            3 for term in terms if term in _fold(title)
        )
        if score or not terms:
            ranked.append((score, -index, title, body))
    ranked.sort(reverse=True)
    picked: list[dict[str, str]] = []
    used = 0
    for _score, _neg, title, body in ranked:
        if used >= _PROCEDURE_BUDGET:
            break
        chunk = body[: _PROCEDURE_BUDGET - used]
        picked.append({"heading": title, "content": chunk})
        used += len(chunk)
    return {
        **head,
        "matched_sections": picked,
        "all_headings": [title for title, _ in sections][:60],
        "note": (
            "Procedura jest długa — pokazuję sekcje pasujące do zapytania. "
            "Zapytaj ponownie z inną frazą, żeby zobaczyć inne sekcje."
            if terms
            else "Procedura jest długa — podaj `query`, żeby dostać właściwe sekcje."
        ),
    }


# ── narzędzia zapisu (tylko propozycja; wykonuje kliknięcie człowieka) ──────


def _who(a: dict[str, Any], key: str = "candidate_id", label: str = "Kandydat") -> str:
    name = (
        a.get("_display", {}).get(key) if isinstance(a.get("_display"), dict) else None
    )
    return f"**{name}**" if name else f"**{label} #{a.get(key)}**"


def _short(text: Any, n: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _aware_time(a: dict[str, Any], key: str) -> Optional[str]:
    """Czas ISO 8601 ZE STREFĄ albo ``ValueError`` (→ propozycja odrzucona).

    Runda 8 (R8-N1-3): czas bez strefy zapisywał się jako UTC (kontener
    chodzi w UTC), a karta pokazywała go dosłownie — wydarzenie lądowało
    1–2 h później, niż mówiła karta. Teraz model musi podać strefę, a karta
    pokazuje godzinę w Europe/Warsaw.
    """
    raw = a.get(key)
    if raw in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"Pole {key} nie jest czasem ISO 8601 (np. 2026-09-22T10:00:00+02:00)"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"Pole {key} musi mieć strefę czasową (np. 2026-09-22T10:00:00+02:00)"
        )
    return parsed.isoformat()


def _local_time(a: dict[str, Any], key: str) -> str:
    raw = str(a.get(key) or "")
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        return raw
    return parsed.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%d.%m.%Y %H:%M")


def _event_start(a: dict[str, Any]) -> str:
    start = _local_time(a, "start_time")
    if a.get("end_time"):
        return f"{start} – {_local_time(a, 'end_time')}"
    return start


def _lines(*parts: Optional[str]) -> str:
    return "\n\n".join(p for p in parts if p)


def _labelled(label: str, value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return f"{label}: {text}" if text else None


def _names(a: dict[str, Any], key: str, label: str) -> str:
    """Lista osób na karcie — nazwy z odczytu API, brak nazwy = numer."""
    display = a.get("_display") if isinstance(a.get("_display"), dict) else {}
    named = display.get(key) if isinstance(display, dict) else None
    ids = [str(i) for i in (a.get(key) or [])]
    if isinstance(named, list) and len(named) == len(ids):
        return ", ".join(f"**{n}**" for n in named)
    return ", ".join(f"**{label} #{i}**" for i in ids)


WRITE_TOOLS: tuple[JarvisTool, ...] = (
    JarvisTool(
        name="create_note",
        done="Notatka dodana.",
        label="Przygotowuję notatkę",
        description=(
            "PROPONUJE dodanie notatki do profilu kandydata (opcjonalnie w kontekście "
            "rekrutacji). Nic nie zapisuje — użytkownik zatwierdza kartę."
        ),
        input_schema=_schema(
            {
                "candidate_id": INT,
                "job_id": INT,
                "content": {**STR, "minLength": 1, "maxLength": 4000},
            },
            ("candidate_id", "content"),
        ),
        tier="write",
        method="POST",
        path="/api/notes",
        section=ProductSection.sourcing,
        entity_type="candidate",
        invalidates=(("candidate",), ("candidate-timeline",), ("candidate-notes",)),
        build=lambda a: RequestSpec(
            "POST",
            "/api/notes",
            json=_clean(
                {
                    "candidate_id": _int(a, "candidate_id"),
                    "job_id": a.get("job_id"),
                    "content": str(a.get("content") or "")[:4000],
                }
            ),
        ),
        shape=pick_list(("id", "candidate_id", "job_id", "created_at")),
        preview=lambda a: (
            f"Dodam notatkę do {_who(a)}"
            + (
                f" (rekrutacja {_who(a, 'job_id', 'Rekrutacja')})"
                if a.get("job_id")
                else ""
            )
            + f": „{_short(a.get('content'))}”"
        ),
        detail=lambda a: str(a.get("content") or "")[:4000],
    ),
    JarvisTool(
        name="move_candidate_stage",
        done="Kandydat przesunięty na tablicy.",
        label="Przygotowuję przesunięcie na tablicy",
        description=(
            "PROPONUJE przesunięcie kandydata na inny etap rekrutacji. Najpierw odczytaj "
            "tablicę (get_job_board), weź stage_def_id docelowego etapu i "
            "process_state_version z karty kandydata. Nic nie zapisuje bez zgody."
        ),
        input_schema=_schema(
            {
                "candidate_id": INT,
                "job_id": INT,
                "stage_def_id": INT,
                "stage_name": {
                    **STR,
                    "description": "Nazwa etapu docelowego (do karty).",
                },
                "expected_state_version": INT,
                "notes": {**STR, "maxLength": 1000},
            },
            ("candidate_id", "job_id", "stage_def_id", "stage_name"),
        ),
        tier="write",
        method="POST",
        path="/api/pipeline/move",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(
            ("kanban",),
            ("candidate",),
            ("candidate-timeline",),
            ("my-next-steps",),
        ),
        build=lambda a: RequestSpec(
            "POST",
            "/api/pipeline/move",
            json=_clean(
                {
                    "candidate_id": _int(a, "candidate_id"),
                    "job_id": _int(a, "job_id"),
                    "stage_def_id": _int(a, "stage_def_id"),
                    "notes": a.get("notes"),
                    "expected_state_version": a.get("expected_state_version"),
                    "acknowledge_eligibility": bool(a.get("acknowledge_eligibility"))
                    or None,
                }
            ),
        ),
        shape=pick_list(
            ("id", "candidate_id", "job_id", "stage", "stage_def_id", "moved_at")
        ),
        preview=lambda a: (
            f"Przesunę {_who(a)} w {_who(a, 'job_id', 'Rekrutacja')} na etap "
            f"**{a.get('stage_name')}**"
            + (" — mimo ostrzeżenia" if a.get("acknowledge_eligibility") else "")
        ),
        detail=lambda a: _labelled("Notatka przy przesunięciu", a.get("notes")) or "",
    ),
    JarvisTool(
        name="add_candidates_to_job",
        done="Dodano do rekrutacji.",
        label="Przygotowuję dodanie do rekrutacji",
        description=(
            "PROPONUJE dodanie jednego lub kilku kandydatów do rekrutacji (na pierwszy "
            "etap szablonu). Nic nie zapisuje bez zgody użytkownika."
        ),
        input_schema=_schema(
            {
                "job_id": INT,
                "candidate_ids": {
                    "type": "array",
                    "items": INT,
                    "minItems": 1,
                    "maxItems": 20,
                },
                "note": {**STR, "maxLength": 1000},
            },
            ("job_id", "candidate_ids"),
        ),
        tier="write",
        method="POST",
        path="/api/jobs/{job_id}/proposals/bulk",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("kanban",), ("jobs",)),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/jobs/{_int(a, 'job_id')}/proposals/bulk",
            json=_clean(
                {
                    "candidate_ids": [int(c) for c in (a.get("candidate_ids") or [])][
                        :20
                    ],
                    "note": a.get("note"),
                    "source": "jarvis",
                }
            ),
        ),
        shape=as_is,
        preview=lambda a: (
            f"Dodam {len(a.get('candidate_ids') or [])} "
            f"{'kandydata' if len(a.get('candidate_ids') or []) == 1 else 'kandydatów'} do "
            f"{_who(a, 'job_id', 'Rekrutacja')}: "
            f"{_names(a, 'candidate_ids', 'Kandydat')}"
        ),
        detail=lambda a: (
            _labelled(
                "Notatka (trafi do profilu każdej z tych osób)", a.get("note")
            )
            or ""
        ),
    ),
    JarvisTool(
        name="create_calendar_event",
        done="Wydarzenie dodane do kalendarza.",
        label="Przygotowuję wpis w kalendarzu",
        description=(
            "PROPONUJE wydarzenie w kalendarzu NEXUS użytkownika (bez zapraszania innych "
            "osób). Czas w ISO 8601 ze strefą (np. 2026-09-22T10:00:00+02:00)."
        ),
        input_schema=_schema(
            {
                "title": {**STR, "minLength": 1, "maxLength": 200},
                "start_time": STR,
                "end_time": STR,
                "event_type": {
                    "type": "string",
                    "enum": [
                        "interview",
                        "screening",
                        "prep_call",
                        "meeting",
                        "deadline",
                    ],
                },
                "candidate_id": INT,
                "job_id": INT,
                "description": {**STR, "maxLength": 2000},
            },
            ("title", "start_time"),
        ),
        tier="write",
        method="POST",
        path="/api/calendar/events",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("calendar-events",), ("candidate-timeline",)),
        build=lambda a: RequestSpec(
            "POST",
            "/api/calendar/events",
            json=_clean(
                {
                    "title": str(a.get("title") or "")[:200],
                    "start_time": _aware_time(a, "start_time"),
                    "end_time": _aware_time(a, "end_time"),
                    "event_type": a.get("event_type") or "meeting",
                    "candidate_id": a.get("candidate_id"),
                    "job_id": a.get("job_id"),
                    "description": a.get("description"),
                }
            ),
        ),
        shape=pick_list(("id", "title", "start_time", "end_time")),
        preview=lambda a: (
            f"Dodam do kalendarza **{_short(a.get('title'), 200)}** — "
            f"{_event_start(a)} (czas polski)"
        ),
        detail=lambda a: _lines(
            _labelled(
                "Rodzaj",
                _EVENT_TYPE_PL.get(
                    str(a.get("event_type") or "meeting"), a.get("event_type")
                ),
            ),
            f"Kandydat: {_who(a)}" if a.get("candidate_id") else None,
            f"Rekrutacja: {_who(a, 'job_id', 'Rekrutacja')}"
            if a.get("job_id")
            else None,
            _labelled("Opis", a.get("description")),
        ),
    ),
    JarvisTool(
        name="add_to_talent_pool",
        done="Kandydat dodany do puli.",
        label="Przygotowuję dodanie do puli",
        description="PROPONUJE dodanie kandydata do puli talentów (ID puli z list_talent_pools).",
        input_schema=_schema(
            {"pool_id": INT, "candidate_id": INT},
            ("pool_id", "candidate_id"),
        ),
        tier="write",
        method="POST",
        path="/api/talent-pools/{pool_id}/add",
        section=ProductSection.sourcing,
        entity_type="candidate",
        invalidates=(("talent-pools",),),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/talent-pools/{_int(a, 'pool_id')}/add",
            json={"candidate_id": _int(a, "candidate_id")},
        ),
        shape=as_is,
        preview=lambda a: f"Dodam {_who(a)} do puli {_who(a, 'pool_id', 'Pula')}",
    ),
    JarvisTool(
        name="mark_notifications_read",
        done="Powiadomienia oznaczone jako przeczytane.",
        label="Przygotowuję oznaczenie powiadomień",
        description="PROPONUJE oznaczenie wszystkich powiadomień użytkownika jako przeczytane.",
        input_schema=_schema({}),
        tier="write",
        method="PATCH",
        path="/api/notifications/read-all",
        section=None,
        invalidates=(("notifications",),),
        build=lambda a: RequestSpec("PATCH", "/api/notifications/read-all"),
        shape=as_is,
        preview=lambda a: "Oznaczę wszystkie Twoje powiadomienia jako przeczytane",
    ),
    JarvisTool(
        name="mark_client_alert_handled",
        done="Sprawa oznaczona jako załatwiona.",
        label="Przygotowuję odhaczenie sprawy",
        description="PROPONUJE oznaczenie sprawy klienta (list_client_alerts) jako załatwionej.",
        input_schema=_schema({"alert_id": INT}, ("alert_id",)),
        tier="write",
        method="POST",
        path="/api/dl-alerts/{alert_id}/handled",
        section=ProductSection.delivery,
        invalidates=(("dl-alerts",),),
        build=lambda a: RequestSpec(
            "POST", f"/api/dl-alerts/{_int(a, 'alert_id')}/handled"
        ),
        shape=as_is,
        preview=lambda a: (
            f"Oznaczę sprawę {_who(a, 'alert_id', 'Sprawa')} jako załatwioną"
        ),
    ),
    JarvisTool(
        name="start_order_mail_sync",
        done="Pobieranie zamówień uruchomione — wynik zobaczysz w kolejce zamówień.",
        label="Przygotowuję pobranie zamówień",
        description="PROPONUJE uruchomienie pobierania zamówień ze skrzynki zamowienia@ (bieg w tle).",
        input_schema=_schema({}),
        tier="write",
        method="POST",
        path="/api/order-mail/sync",
        section=ProductSection.delivery,
        invalidates=(("order-mail",),),
        build=lambda a: RequestSpec("POST", "/api/order-mail/sync"),
        shape=as_is,
        preview=lambda a: "Uruchomię pobieranie zamówień ze skrzynki zamówień",
    ),
    JarvisTool(
        name="refresh_activity_summary",
        done="Podsumowanie aktywności odświeżone.",
        label="Przygotowuję odświeżenie podsumowania",
        description=(
            "PROPONUJE wygenerowanie/odświeżenie podsumowania aktywności kandydata (płatne "
            "wywołanie AI; bez zmian w historii nic nie kosztuje)."
        ),
        input_schema=_schema({"candidate_id": INT}, ("candidate_id",)),
        tier="write",
        method="POST",
        path="/api/candidates/{candidate_id}/activity-summary/refresh",
        section=ProductSection.sourcing,
        entity_type="candidate",
        invalidates=(("candidate-activity-summary",),),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/candidates/{_int(a, 'candidate_id')}/activity-summary/refresh",
        ),
        shape=as_is,
        preview=lambda a: f"Odświeżę podsumowanie aktywności {_who(a)}",
    ),
    JarvisTool(
        name="save_interview_debrief",
        done="Debrief zapisany.",
        label="Przygotowuję debrief rozmowy",
        description=(
            "PROPONUJE zapis debriefu po rozmowie u klienta (ID wydarzenia z "
            "my_interview_cycle albo kalendarza): jak poszło (good/medium/bad), czy "
            "kandydat przyjmie ofertę (yes/likely/no/unknown), komentarz, pytania "
            "zadane przez klienta. Pytania trafią do banku pytań tego klienta. "
            "no_client_questions=true TYLKO, gdy użytkownik wprost powie, że klient "
            "nie zadawał pytań. Nie wymyślaj pytań."
        ),
        input_schema=_schema(
            {
                "event_id": INT,
                "candidate_id": {
                    **INT,
                    "description": (
                        "Kandydat, o którym mówi użytkownik — serwer sprawdzi, "
                        "czy to ta sama osoba co w wydarzeniu."
                    ),
                },
                "outcome": {"type": "string", "enum": ["good", "medium", "bad"]},
                "offer_acceptance": {
                    "type": "string",
                    "enum": ["yes", "likely", "no", "unknown"],
                },
                "candidate_comment": {**STR, "maxLength": 4000},
                "questions": {
                    "type": "array",
                    "items": {**STR, "maxLength": 500},
                    "maxItems": 20,
                },
                "acceptance_condition": {**STR, "maxLength": 2000},
                "no_client_questions": BOOL,
            },
            ("event_id", "outcome", "offer_acceptance"),
        ),
        tier="write",
        method="PUT",
        path="/api/interview-cycle/events/{event_id}/debrief",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("interview-cycle",), ("client-questions",), ("kanban",)),
        build=lambda a: RequestSpec(
            "PUT",
            f"/api/interview-cycle/events/{_int(a, 'event_id')}/debrief",
            json=_clean(
                {
                    "outcome": a.get("outcome"),
                    "offer_acceptance": a.get("offer_acceptance"),
                    "candidate_comment": a.get("candidate_comment"),
                    "questions": [
                        str(q)[:500]
                        for q in (a.get("questions") or [])
                        if str(q).strip()
                    ][:20],
                    "acceptance_condition": a.get("acceptance_condition"),
                    "no_client_questions": bool(a.get("no_client_questions")) or None,
                }
            ),
        ),
        shape=lambda data, _a: trim(
            pick(data, ("id", "outcome", "offer_acceptance", "questions_saved"))
            if isinstance(data, dict)
            else data
        ),
        preview=lambda a: (
            "Zapiszę debrief rozmowy u klienta"
            + (
                f" — {_who(a)}"
                if a.get("candidate_id")
                else f" (wydarzenie #{a.get('event_id')})"
            )
            + (f" ({_who(a, 'job_id', 'Rekrutacja')})" if a.get("job_id") else "")
            + f": {_OUTCOME_PL.get(str(a.get('outcome')), a.get('outcome'))}, "
            f"oferta: {_ACCEPTANCE_PL.get(str(a.get('offer_acceptance')), a.get('offer_acceptance'))}"
        ),
        detail=lambda a: _debrief_detail(a),
    ),
    JarvisTool(
        name="dismiss_job_proposal",
        done="Propozycja odrzucona — przywrócisz ją na ekranie „Do przejrzenia”.",
        label="Przygotowuję odrzucenie propozycji",
        description=(
            "PROPONUJE odrzucenie propozycji kandydata w rekrutacji (ekran „Do "
            "przejrzenia”). Da się ją przywrócić; nowe CV tej osoby zaproponuje ją ponownie."
        ),
        input_schema=_schema(
            {"job_id": INT, "candidate_id": INT}, ("job_id", "candidate_id")
        ),
        tier="write",
        method="POST",
        path="/api/jobs/{job_id}/proposal-inbox/{candidate_id}/dismiss",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("job-proposals",),),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/jobs/{_int(a, 'job_id')}/proposal-inbox/{_int(a, 'candidate_id')}/dismiss",
            json={},
        ),
        shape=as_is,
        preview=lambda a: (
            f"Odrzucę propozycję {_who(a)} w rekrutacji {_who(a, 'job_id', 'Rekrutacja')}"
        ),
    ),
    JarvisTool(
        name="record_hm_feedback",
        done="Werdykt klienta zapisany.",
        label="Przygotowuję werdykt klienta",
        description=(
            "PROPONUJE zapis werdyktu hiring managera o kandydacie w rekrutacji: "
            "advance (dalej), reject (odrzucony), on_hold (wstrzymany), z notatką "
            "i oceną 1–5. Powód odrzucenia ze słownika wybiera człowiek na ekranie."
        ),
        input_schema=_schema(
            {
                "job_id": INT,
                "candidate_id": INT,
                "decision": {
                    "type": "string",
                    "enum": ["advance", "reject", "on_hold"],
                },
                "note": {**STR, "maxLength": 8000},
                "overall_fit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            ("job_id", "candidate_id", "decision"),
        ),
        tier="write",
        method="POST",
        path="/api/jobs/{job_id}/hiring-manager-feedback",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("hiring-manager-feedback",), ("kanban",)),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/jobs/{_int(a, 'job_id')}/hiring-manager-feedback",
            json=_clean(
                {
                    "candidate_id": _int(a, "candidate_id"),
                    "decision": a.get("decision"),
                    "note": a.get("note"),
                    "overall_fit": a.get("overall_fit"),
                }
            ),
        ),
        shape=lambda data, _a: trim(
            pick(data, ("id", "candidate_id", "decision", "note"))
            if isinstance(data, dict)
            else data
        ),
        preview=lambda a: (
            f"Zapiszę werdykt klienta o {_who(a)} w rekrutacji "
            f"{_who(a, 'job_id', 'Rekrutacja')}: "
            f"{_DECISION_PL.get(str(a.get('decision')), a.get('decision'))}"
            + (f", ocena {a.get('overall_fit')}/5" if a.get("overall_fit") else "")
        ),
        detail=lambda a: str(a.get("note") or ""),
    ),
    JarvisTool(
        name="claim_candidate",
        done="Kandydat jest Twój przez 12 godzin.",
        label="Przygotowuję „Biorę”",
        description=(
            "PROPONUJE „Biorę” — 12-godzinną rezerwację kandydata z kolumny „Nowi” "
            "w rekrutacji dla tej osoby. Cudzą aktywną rezerwację przejmują tylko "
            "Delivery Lead, Head of Recruitment i admin (poprzednia osoba dostaje "
            "powiadomienie)."
        ),
        input_schema=_schema(
            {"job_id": INT, "candidate_id": INT}, ("job_id", "candidate_id")
        ),
        tier="write",
        method="POST",
        path="/api/pipeline/claim",
        section=ProductSection.pipeline,
        entity_type="candidate",
        invalidates=(("kanban",),),
        build=lambda a: RequestSpec(
            "POST",
            "/api/pipeline/claim",
            json={"candidate_id": _int(a, "candidate_id"), "job_id": _int(a, "job_id")},
        ),
        shape=as_is,
        preview=lambda a: (
            f"Wezmę {_who(a)} w rekrutacji {_who(a, 'job_id', 'Rekrutacja')} na 12 godzin"
        ),
        detail=lambda _a: (
            "Jeśli tę osobę prowadzi już ktoś inny, przejęcie zadziała tylko dla "
            "Delivery Leada, Head of Recruitment i admina — poprzednia osoba dostanie "
            "powiadomienie."
        ),
    ),
    JarvisTool(
        name="snooze_my_person",
        done="Osoba uśpiona w „Moich ludziach”.",
        label="Przygotowuję uśpienie",
        description=(
            "PROPONUJE uśpienie osoby na liście „Moi ludzie” z powodem: found_job "
            "(znalazła pracę), not_interested (nie jest zainteresowana), no_contact "
            "(brak kontaktu), other (z notatką). Wybudzić można na liście."
        ),
        input_schema=_schema(
            {
                "candidate_id": INT,
                "reason": {
                    "type": "string",
                    "enum": ["found_job", "not_interested", "no_contact", "other"],
                },
                "note": {**STR, "maxLength": 500},
            },
            ("candidate_id", "reason"),
        ),
        tier="write",
        method="POST",
        path="/api/my-people/{candidate_id}/snooze",
        section=ProductSection.sourcing,
        entity_type="candidate",
        invalidates=(("my-people",),),
        build=lambda a: RequestSpec(
            "POST",
            f"/api/my-people/{_int(a, 'candidate_id')}/snooze",
            json=_clean({"reason": a.get("reason"), "note": a.get("note")}),
        ),
        shape=lambda _data, _a: {"ok": True},
        preview=lambda a: (
            f"Uśpię {_who(a)} w „Moich ludziach” — "
            f"{_SNOOZE_PL.get(str(a.get('reason')), a.get('reason'))}"
        ),
        detail=lambda a: str(a.get("note") or ""),
    ),
    JarvisTool(
        name="pin_my_person",
        done="Osoba przypięta do „Moich ludzi”.",
        label="Przygotowuję przypięcie",
        description=(
            "PROPONUJE przypięcie osoby do listy „Moi ludzie” (także kogoś, kogo "
            "lista nie wyliczyła sama). Odpiąć można na liście."
        ),
        input_schema=_schema({"candidate_id": INT}, ("candidate_id",)),
        tier="write",
        method="POST",
        path="/api/my-people/{candidate_id}/pin",
        section=ProductSection.sourcing,
        entity_type="candidate",
        invalidates=(("my-people",),),
        build=lambda a: RequestSpec(
            "POST", f"/api/my-people/{_int(a, 'candidate_id')}/pin", json={}
        ),
        shape=lambda _data, _a: {"ok": True},
        preview=lambda a: f"Przypnę {_who(a)} do „Moich ludzi”",
    ),
    JarvisTool(
        name="remember_preference",
        done="Zapamiętane. Listę zobaczysz w ustawieniach Jarvisa.",
        label="Przygotowuję zapamiętanie",
        description=(
            "PROPONUJE zapamiętanie preferencji użytkownika o sposobie pracy z "
            "Jarvisem (np. „odpowiadaj krócej”, „moi klienci to X i Y”). NIGDY "
            "informacji o kandydatach ani danych osobowych innych osób."
        ),
        input_schema=_schema(
            {"text": {**STR, "minLength": 3, "maxLength": 200}}, ("text",)
        ),
        tier="write",
        method="PATCH",
        path="/api/users/me/preferences",
        section=None,
        invalidates=(("jarvis",),),
        # Pełną listę (stare + nowa) składa serwer w ``prepare_proposal``
        # (klucz ``_notes``, którego model nie może podać — ``sanitize_args``).
        build=lambda a: RequestSpec(
            "PATCH",
            "/api/users/me/preferences",
            json={
                "jarvis": {
                    "notes": list(a.get("_notes") or [])
                    or [str(a.get("text") or "").strip()]
                }
            },
        ),
        shape=lambda _data, _a: {"ok": True},
        preview=lambda a: f"Zapamiętam: „{_short(a.get('text'), 200)}”",
    ),
)


_OUTCOME_PL = {"good": "poszło dobrze", "medium": "średnio", "bad": "słabo"}
_ACCEPTANCE_PL = {
    "yes": "przyjmie",
    "likely": "raczej przyjmie",
    "no": "nie przyjmie",
    "unknown": "nie wiadomo",
}
_DECISION_PL = {
    "advance": "dalej w procesie",
    "reject": "odrzucony",
    "on_hold": "wstrzymany",
}
_EVENT_TYPE_PL = {
    "interview": "rozmowa",
    "screening": "screening",
    "prep_call": "prep",
    "meeting": "spotkanie",
    "deadline": "termin",
}
_SNOOZE_PL = {
    "found_job": "znalazła pracę",
    "not_interested": "nie jest zainteresowana",
    "no_contact": "brak kontaktu",
    "other": "inny powód",
}


def _debrief_detail(a: dict[str, Any]) -> str:
    parts: list[str] = []
    if a.get("candidate_comment"):
        parts.append(f"Komentarz: {a['candidate_comment']}")
    if a.get("acceptance_condition"):
        parts.append(f"Warunek akceptacji: {a['acceptance_condition']}")
    questions = [str(q).strip() for q in a.get("questions") or [] if str(q).strip()]
    if questions:
        parts.append(
            "Pytania klienta (trafią do banku pytań tego klienta):\n"
            + "\n".join(f"• {q}" for q in questions)
        )
    elif a.get("no_client_questions"):
        parts.append("Klient nie zadawał pytań.")
    return "\n\n".join(parts)


# ── narzędzie linku (operacje krytyczne i ekrany) ──────────────────────────

SCREENS: dict[str, tuple[str, str]] = {
    # klucz → (szablon ścieżki, etykieta)
    "candidate": ("/candidates/{id}", "Profil kandydata"),
    "job": ("/jobs/{id}", "Rekrutacja"),
    "job_champion": ("/jobs/{id}?tab=champion", "Zlecenie i Champion"),
    "client": ("/clients/{id}", "Profil klienta"),
    "client_orders": ("/clients/{id}?tab=zamowienia", "Zamówienia klienta"),
    "contract": ("/contracts/{id}", "Kontrakt"),
    "contracts": ("/contracts", "Kontrakty"),
    "calendar_event": ("/calendar?event={id}", "Wydarzenie w kalendarzu"),
    "calendar": ("/calendar", "Kalendarz"),
    "cv_generator": ("/cv-generator", "Generator CV"),
    "b2b_generator": ("/contracts/b2b-generator", "Generator umów B2B"),
    "order_mail": (
        "/contracts?view=order-mail",
        "Skrzynka zamówień (zamówienia z maila)",
    ),
    "finance_order_changes": (
        "/finance?view=order-changes",
        "Finanse — zmiany w zamówieniach",
    ),
    "talent_radar": ("/talent-radar", "Talent Radar"),
    "insights": ("/insights", "Insights"),
    "settings": ("/settings", "Ustawienia"),
    "help": ("/help", "Pomoc"),
}

# Ekrany bez ID rekordu.
_SCREENS_WITHOUT_ID = frozenset(
    k for k, (tpl, _) in SCREENS.items() if "{id}" not in tpl
)


def build_screen_link(args: dict[str, Any]) -> dict[str, str]:
    screen = str(args.get("screen") or "")
    if screen not in SCREENS:
        raise ValueError(f"Nieznany ekran: {screen}")
    template, label = SCREENS[screen]
    if screen in _SCREENS_WITHOUT_ID:
        href = template
    else:
        record_id = args.get("id")
        if (
            isinstance(record_id, bool)
            or not isinstance(record_id, int)
            or record_id < 1
        ):
            raise ValueError(
                f"Ekran {screen} wymaga id rekordu — najpierw je ustal (np. global_search) "
                f"albo wybierz ekran bez id: {', '.join(sorted(_SCREENS_WITHOUT_ID))}."
            )
        href = template.replace("{id}", str(record_id))
    reason = _short(args.get("reason") or "", 200)
    return {"href": href, "label": label, "reason": reason}


OPEN_SCREEN = JarvisTool(
    name="open_screen",
    label="Przygotowuję link",
    description=(
        "Daje użytkownikowi przycisk do ekranu NEXUSA. Użyj ZAWSZE, gdy prośba dotyczy "
        "operacji, której nie wykonujesz: usunięcie, zakończenie współpracy, "
        "wypowiedzenie, podpis umowy, zmiana stawek, wysyłka maila, generowanie CV lub "
        "umowy, uprawnienia. Wyjaśnij w 'reason', co tam kliknąć."
    ),
    input_schema=_schema(
        {
            "screen": {"type": "string", "enum": sorted(SCREENS)},
            "id": {
                **INT,
                "description": (
                    "ID rekordu — WYMAGANE dla ekranów: "
                    + ", ".join(
                        sorted(k for k in SCREENS if k not in _SCREENS_WITHOUT_ID)
                    )
                    + "."
                ),
            },
            "reason": {**STR, "maxLength": 200},
        },
        ("screen", "reason"),
    ),
    tier="link",
    method=None,
    path=None,
    section=None,
    build=lambda a: RequestSpec("GET", ""),  # nieużywane — patrz build_screen_link
    shape=as_is,
)


SHOW_ON_SCREEN = JarvisTool(
    name="show_on_screen",
    label="Pokazuję na ekranie",
    description=(
        "Podświetla element na ekranie, na którym jest użytkownik (np. przycisk, "
        "pasek filtrów, kolumnę). Identyfikator `anchor` bierz WYŁĄCZNIE z listy "
        "`anchors` w wyniku get_screen_guide dla bieżącego ekranu. W `reason` "
        "napisz jednym zdaniem, co tam zrobić."
    ),
    input_schema=_schema(
        {"anchor": {**STR, "maxLength": 60}, "reason": {**STR, "maxLength": 200}},
        ("anchor", "reason"),
    ),
    tier="link",
    method=None,
    path=None,
    section=None,
    build=lambda a: RequestSpec("GET", ""),  # nieużywane — patrz agent._handle_tool
    shape=as_is,
)


ALL_TOOLS: tuple[JarvisTool, ...] = (
    *READ_TOOLS,
    *WRITE_TOOLS,
    OPEN_SCREEN,
    SHOW_ON_SCREEN,
)
TOOLS_BY_NAME: dict[str, JarvisTool] = {tool.name: tool for tool in ALL_TOOLS}


def tools_for_user(section_access: dict[ProductSection, int]) -> list[JarvisTool]:
    """Narzędzia, których sekcje użytkownik w ogóle widzi.

    To tylko oszczędność tokenów i mniej odmów: API i tak egzekwuje każdą
    bramkę. Zapis wymaga sekcji na poziomie ``write`` (2).
    """
    visible: list[JarvisTool] = []
    for tool in ALL_TOOLS:
        if tool.section is None:
            visible.append(tool)
            continue
        required = 2 if tool.tier == "write" else 1
        if section_access.get(tool.section, 0) >= required:
            visible.append(tool)
    return visible


def default_calendar_window(today: date) -> tuple[str, str]:
    return today.isoformat(), (today + timedelta(days=7)).isoformat()
