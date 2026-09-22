"""Zakres OAuth klienta zależny od trasy (audyt 22.09.2026, AUTH-01).

Token klienta OAuth (``type="client"``) jest w ``deps._resolve_client_principal``
rozwiązywany do usera serwisowego. Do tej zmiany zakres sprawdzał wyłącznie
tryb: mutacja wymagała DOWOLNEGO ``*:write``, odczyt — dowolnego scope'u.
Klient z samym ``dictionary:read`` czytał więc kandydatów, a ``candidate:write``
zmieniał rekrutacje — granicę wyznaczała tylko rola usera serwisowego.

Tu mieszka JEDNO miejsce, które mówi, które trasy w ogóle są wystawione
klientom OAuth i jakiego zasobu dotyczą:

* klucz mapy = pełny szablon trasy (z prefiksami ``include_router``),
* wartość = zasoby, z których KAŻDY wystarcza (``proposals/bulk`` przyjmuje
  ``candidate:write`` albo ``job:write`` — scrapery mają oba),
* tryb odczyt/zapis wyznacza ``is_read_only_http_request`` — ta sama
  klasyfikacja co sekcje i podgląd, więc ``check-duplicates`` (POST tylko do
  odczytu) przechodzi z ``candidate:read``,
* ``X:write`` spełnia ``X:read``.

Trasa spoza mapy = ``route_not_exposed_to_clients``. Egzekwowanie włącza
``OAUTH_ROUTE_SCOPES_ENFORCE``; do tego czasu decyzja jest tylko logowana
(tryb cienia), bo kodu scraperów nie ma w repo i mapę uzupełniamy z logów.

Uwaga na FastAPI >= 0.139: ``request.scope["route"].path`` NIE zawiera
prefiksu z ``include_router`` (siedzi w ``include_context``), więc pełny szablon
składamy z drzewa tras aplikacji — tak samo jak ``tests/_route_introspection``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional

from fastapi.routing import APIRoute

from app.services.request_semantics import is_read_only_http_request

ROUTE_NOT_EXPOSED = "route_not_exposed_to_clients"
INSUFFICIENT_SCOPE = "insufficient_scope"

#: Szablon trasy → zasoby, z których każdy wystarcza. Dopisując trasę, sprawdź,
#: że szablon istnieje (pilnuje tego test kontraktowy).
OAUTH_ROUTE_RESOURCES: dict[str, tuple[str, ...]] = {
    # Runy integracji (scrapery pracuj.pl / JJIT, migracja 0314).
    "/api/integrations/runs": ("candidate",),
    "/api/integrations/runs/{run_id}": ("candidate",),
    "/api/integrations/runs/{run_id}/events": ("candidate",),
    # Wrzucanie kandydatów z CV i sprawdzanie duplikatów przed wrzuceniem.
    "/api/candidates/from-cv": ("candidate",),
    "/api/candidates/check-duplicates": ("candidate",),
    # Dodanie kandydatów do rekrutacji i odczyt etapów do wyboru.
    "/api/jobs/{job_id}/proposals/bulk": ("candidate", "job"),
    "/api/jobs/{job_id}/assignable-stages": ("job",),
}


@dataclass(frozen=True)
class RouteScopeDecision:
    """Wynik sprawdzenia zakresu dla jednego żądania klienta."""

    allowed: bool
    template: Optional[str]
    mode: str  # "read" | "write"
    required: tuple[str, ...]  # scope'y, z których każdy by wystarczył
    reason: Optional[str] = None  # ROUTE_NOT_EXPOSED | INSUFFICIENT_SCOPE


def _walk(node: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    if isinstance(node, APIRoute):
        yield prefix + node.path, node
        return
    ctx = getattr(node, "include_context", None)
    if ctx is not None:
        inner = prefix + (getattr(ctx, "prefix", "") or "")
        original = getattr(node, "original_router", None)
        for route in getattr(original, "routes", []) or []:
            yield from _walk(route, inner)
        return
    for route in getattr(node, "routes", []) or []:
        yield from _walk(route, prefix)


def _template_index(app: Any) -> dict[int, str]:
    """Mapa ``id(trasa) → pełny szablon``, liczona raz na aplikację."""

    state = getattr(app, "state", None)
    cached = getattr(state, "_oauth_route_templates", None) if state else None
    if cached is not None:
        return cached
    index: dict[int, str] = {}
    for route in getattr(app, "routes", []) or []:
        for full_path, api_route in _walk(route, ""):
            index[id(api_route)] = full_path
    if state is not None:
        state._oauth_route_templates = index
    return index


def route_template(request: Any) -> Optional[str]:
    """Pełny szablon trasy dopasowanej do żądania albo ``None``."""

    scope = getattr(request, "scope", None) or {}
    route = scope.get("route") if isinstance(scope, dict) else None
    if route is None:
        return None
    app = scope.get("app") if isinstance(scope, dict) else None
    if app is not None:
        template = _template_index(app).get(id(route))
        if template is None:
            # Trasa dodana po pierwszym zbudowaniu indeksu — przebuduj raz.
            state = getattr(app, "state", None)
            if state is not None and hasattr(state, "_oauth_route_templates"):
                del state._oauth_route_templates
            template = _template_index(app).get(id(route))
        if template is not None:
            return template
    return getattr(route, "path", None)


def _satisfies(granted: Iterable[str], resource: str, mode: str) -> bool:
    granted_set = set(granted)
    if f"{resource}:write" in granted_set:
        return True
    return mode == "read" and f"{resource}:read" in granted_set


def decide(
    *, method: str, path: str, template: Optional[str], scopes: Iterable[str]
) -> RouteScopeDecision:
    """Czy zakres klienta obejmuje tę trasę? Czysta funkcja, bez I/O."""

    mode = "read" if is_read_only_http_request(method, path) else "write"
    resources = OAUTH_ROUTE_RESOURCES.get(template or "")
    if not resources:
        return RouteScopeDecision(
            allowed=False,
            template=template,
            mode=mode,
            required=(),
            reason=ROUTE_NOT_EXPOSED,
        )
    required = tuple(f"{resource}:{mode}" for resource in resources)
    granted = tuple(scopes)
    if any(_satisfies(granted, resource, mode) for resource in resources):
        return RouteScopeDecision(
            allowed=True, template=template, mode=mode, required=required
        )
    return RouteScopeDecision(
        allowed=False,
        template=template,
        mode=mode,
        required=required,
        reason=INSUFFICIENT_SCOPE,
    )
