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
        name="search_help",
        label="Szukam w Pomocy",
        description=(
            "Szuka w procedurach modułu Pomoc — użyj przy pytaniach „jak zrobić X w "
            "NEXUSIE”. Zwraca tytuły i slug; treść czytasz narzędziem get_help_article."
        ),
        input_schema=_schema({"query": STR}),
        tier="read",
        method="GET",
        path="/api/procedures",
        section=None,
        build=lambda a: _get("/api/procedures", {"q": a.get("query")}),
        shape=pick_list(("id", "slug", "title", "category", "summary", "updated_at")),
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


def _event_start(a: dict[str, Any]) -> str:
    raw = str(a.get("start_time") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime(
            "%d.%m.%Y %H:%M"
        )
    except ValueError:
        return raw


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
        preview=lambda a: f"Dodam notatkę do {_who(a)}: „{_short(a.get('content'))}”",
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
            f"{_who(a, 'job_id', 'Rekrutacja')}"
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
                    "start_time": a.get("start_time"),
                    "end_time": a.get("end_time"),
                    "event_type": a.get("event_type") or "meeting",
                    "candidate_id": a.get("candidate_id"),
                    "job_id": a.get("job_id"),
                    "description": a.get("description"),
                }
            ),
        ),
        shape=pick_list(("id", "title", "start_time", "end_time")),
        preview=lambda a: (
            f"Dodam do kalendarza **{_short(a.get('title'), 80)}** — {_event_start(a)}"
        ),
    ),
    JarvisTool(
        name="add_to_talent_pool",
        done="Kandydat dodany do puli.",
        label="Przygotowuję dodanie do puli",
        description="PROPONUJE dodanie kandydata do puli talentów (ID puli z list_talent_pools).",
        input_schema=_schema(
            {"pool_id": INT, "candidate_id": INT, "pool_name": STR},
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
        preview=lambda a: (
            f"Dodam {_who(a)} do puli **{a.get('pool_name') or '#' + str(a.get('pool_id'))}**"
        ),
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
        input_schema=_schema({"alert_id": INT, "title": STR}, ("alert_id",)),
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
            f"Oznaczę sprawę **{_short(a.get('title') or '#' + str(a.get('alert_id')), 80)}** "
            "jako załatwioną"
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
)


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
        href = template.replace("{id}", str(_int(args, "id")))
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
                "description": "ID rekordu (dla ekranów konkretnego rekordu).",
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


ALL_TOOLS: tuple[JarvisTool, ...] = (*READ_TOOLS, *WRITE_TOOLS, OPEN_SCREEN)
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
