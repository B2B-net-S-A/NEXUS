"""Macierz bramek tras: werdykt (trasa × persona) przez okablowanie FastAPI.

Każda trasa aplikacji jest wołana raz na personę. Handler się NIE wykonuje
(podmieniony ``run_endpoint_function``), baza jest atrapą, a użytkownika
podstawia ``dependency_overrides`` — więc wynik mówi wyłącznie, co zrobiły
zależności trasy: bramka sekcji, bramka roli, bramka uprawnienia.

Żądania idą do routera aplikacji z samą obsługą wyjątków, bez middleware'ów
(2,6× szybciej; żaden z nich nie decyduje o dostępie). Że to nadal prawda,
pilnuje ``test_middleware_does_not_change_the_verdict``.

Litery werdyktu (celowo grube — zmiana TREŚCI odmowy nie jest zmianą dostępu):

* ``D`` — odmowa (403),
* ``U`` — brak sesji (401; trasy na klucz serwisowy albo własne tokeny),
* ``B`` — bramki przeszły, a kolejna zależność sięgnęła do bazy (zakres klienta),
* ``E`` — błąd serwera (500; nie powinno go być — patrz test),
* ``P`` — bramki przeszły (każdy inny status, także 422 z walidacji ciała).

Persony odwzorowują politykę PRODUKCJI (macierz ról z kodu + odstępstwa
zapisane w panelu), bo siatka ma pokazywać zmiany widoczne dla ludzi.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.middleware.asyncexitstack import AsyncExitStackMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware

from app.api import deps
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    ProductAction,
    serialize_action_access,
)
from app.services.effective_access import effective_access_from_rows
from app.services.section_permissions import (
    DEFAULT_ROLE_SECTION_ACCESS,
    ProductSection,
    SectionAccess,
    serialize_section_access,
)
from tests._route_introspection import iter_api_routes

GOLDEN_DIR = Path(__file__).parent / "data" / "authz_golden"

_DB_REACHED = 418
_HANDLER_REACHED = 299
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PATH_PARAM = re.compile(r"\{([^}:]+)(:[^}]+)?\}")


@dataclass(frozen=True)
class Persona:
    """Konto wzorcowe: rola główna, role dodatkowe i uprawnienia nadane osobie."""

    key: str
    role: UserRole
    extra_roles: tuple[UserRole, ...] = ()
    grants: tuple[str, ...] = ()


PERSONAS: tuple[Persona, ...] = (
    Persona("admin", UserRole.admin),
    Persona("finance", UserRole.finance),
    Persona("head_of_recruitment", UserRole.head_of_recruitment),
    Persona("delivery_lead", UserRole.delivery_lead),
    Persona("talent_community_manager", UserRole.talent_community_manager),
    Persona("tac", UserRole.tac),
    Persona("recruiter", UserRole.recruiter),
    Persona("sourcer", UserRole.sourcer),
    Persona("user", UserRole.user),
    Persona("trainee", UserRole.trainee),
    # Konta wielorolowe, które istnieją na produkcji (02.10.2026).
    Persona(
        "delivery_lead+talent_community_manager",
        UserRole.delivery_lead,
        (UserRole.talent_community_manager,),
    ),
    Persona(
        "head_of_recruitment+delivery_lead",
        UserRole.head_of_recruitment,
        (UserRole.delivery_lead,),
    ),
    Persona("delivery_lead+tac", UserRole.delivery_lead, (UserRole.tac,)),
    Persona("head_of_recruitment+tac", UserRole.head_of_recruitment, (UserRole.tac,)),
    Persona(
        "talent_community_manager+sourcer",
        UserRole.talent_community_manager,
        (UserRole.sourcer,),
    ),
    # Uprawnienie nadane jednej osobie ponad rolę (okno „Edytuj użytkownika”).
    Persona(
        "talent_community_manager+contracts_orders_edit",
        UserRole.talent_community_manager,
        grants=("contracts_orders_edit",),
    ),
    Persona("recruiter+clients_edit", UserRole.recruiter, grants=("clients_edit",)),
    Persona("recruiter+delivery_view", UserRole.recruiter, grants=("delivery_view",)),
)

#: Odstępstwa produkcji od macierzy z kodu (odczyt 02.10.2026): TCM ma
#: w panelu Delivery „Odczyt i zapis” od 03.09.2026.
PRODUCTION_SECTION_DEVIATIONS: dict[tuple[UserRole, ProductSection], SectionAccess] = {
    (UserRole.talent_community_manager, ProductSection.delivery): SectionAccess.write,
}


def _section_rows() -> list[SimpleNamespace]:
    rows = []
    for role, policy in DEFAULT_ROLE_SECTION_ACCESS.items():
        for section, access in policy.items():
            access = PRODUCTION_SECTION_DEVIATIONS.get((role, section), access)
            rows.append(
                SimpleNamespace(
                    role=role.value, section=section.value, access=access.name
                )
            )
    return rows


def _action_rows() -> list[SimpleNamespace]:
    """Wiersze akcji jak na produkcji po migracji 0409.

    Generator i podpis B2B — wartości z kodu; pozostałe uprawnienia — funkcja
    zasiewu policzona z sekcji powyżej (ta sama, którą wykonuje migracja).
    """

    section_levels: dict[str, dict[str, str]] = {}
    for row in _section_rows():
        section_levels.setdefault(row.role, {})[row.section] = row.access
    rows = []
    for role, policy in DEFAULT_ROLE_ACTION_ACCESS.items():
        for action in (
            ProductAction.b2b_contract_generator,
            ProductAction.b2b_signature_confirmation,
        ):
            rows.append(
                SimpleNamespace(
                    role=role.value, action=action.value, access=policy[action].name
                )
            )
        seeded = catalog.seed_rows_for_role(role.value, section_levels[role.value])
        rows.extend(
            SimpleNamespace(role=role.value, action=key, access=access)
            for key, access in seeded.items()
        )
    return rows


def build_user(persona: Persona, *, user_id: int) -> User:
    """Konto persony z dołączoną polityką — tak, jak robi to uwierzytelnienie."""

    roles = [persona.role.value, *(role.value for role in persona.extra_roles)]
    user = User(
        id=user_id,
        email=f"{persona.key.replace('+', '-')}@authz-matrix.test",
        name=persona.key,
        role=persona.role,
        roles=roles,
        is_active=True,
        email_verified=True,
        profile_completed=True,
        can_delete_clients=False,
        allowed_sections=[],
    )
    access = effective_access_from_rows(
        user,
        section_role_rows=_section_rows(),
        section_override_rows=[],
        action_role_rows=_action_rows(),
        action_override_rows=[
            SimpleNamespace(user_id=user_id, action=key, access="manage")
            for key in persona.grants
        ],
    )
    user.effective_section_access = serialize_section_access(access.sections)
    user.effective_action_access = serialize_action_access(access.actions)
    return user


class _DatabaseStub:
    """Sesja, której każde użycie kończy żądanie werdyktem ``B``."""

    def __getattr__(self, name: str):
        raise HTTPException(status_code=_DB_REACHED, detail="db")


def _verdict(status_code: int) -> str:
    if status_code == 403:
        return "D"
    if status_code == 401:
        return "U"
    if status_code == _DB_REACHED:
        return "B"
    if status_code >= 500:
        return "E"
    return "P"


def _concrete_path(template: str) -> str:
    def fill(match: re.Match[str]) -> str:
        return "x" if match.group(2) == ":path" else "99999999"

    return _PATH_PARAM.sub(fill, template)


def module_key(route) -> str:
    """Nazwa pliku wzorca: moduł handlera bez prefiksu pakietu API."""

    module = getattr(route.endpoint, "__module__", "") or "unknown"
    return module.removeprefix("app.api.").removeprefix("app.")


def route_requests(app) -> Iterator[tuple[str, str, str, str]]:
    """``(moduł, klucz trasy, metoda, konkretna ścieżka)`` dla każdej trasy."""

    seen: set[str] = set()
    for path, route in iter_api_routes(app):
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            key = f"{method} {path}"
            if key in seen:
                continue
            seen.add(key)
            yield module_key(route), key, method, _concrete_path(path)


@contextmanager
def guards_only(app, monkeypatch) -> Iterator[dict[str, User]]:
    """Aplikacja, w której działają wyłącznie zależności tras.

    Zwraca słownik z kluczem ``"user"`` — tam wołający wstawia bieżącą personę.
    """

    from app.core.rate_limit import limiter

    holder: dict[str, User] = {}

    async def _current_user(request: Request) -> User:
        # ``get_current_user`` woła uwierzytelnienie wprost (nie przez Depends),
        # więc podmieniamy je razem z tym, co robi po nim.
        user = deps.ensure_onboarding_complete(holder["user"])
        deps.ensure_not_trainee(user)
        return user

    async def _authenticated_user(request: Request) -> User:
        return holder["user"]

    async def _database() -> _DatabaseStub:
        return _DatabaseStub()

    async def _handler_not_executed(*, dependant, values, is_coroutine):
        return Response(status_code=_HANDLER_REACHED)

    import fastapi.routing

    monkeypatch.setattr(fastapi.routing, "run_endpoint_function", _handler_not_executed)
    monkeypatch.setattr(limiter, "enabled", False)
    # Wyłącznik rolloutu stoi PRZED bramkami capability — przy „off” każda
    # trasa analityki kończyłaby się 503 i nie mówiła nic o dostępie.
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "live")
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[deps.get_current_user] = _current_user
    app.dependency_overrides[deps.get_authenticated_user] = _authenticated_user
    app.dependency_overrides[get_db] = _database
    try:
        yield holder
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def routes_only(app):
    """Router aplikacji z obsługą wyjątków, bez middleware'ów użytkownika."""

    handlers = {
        key: handler
        for key, handler in app.exception_handlers.items()
        if key not in (500, Exception)
    }
    inner = ExceptionMiddleware(AsyncExitStackMiddleware(app.router), handlers=handlers)

    async def asgi(scope, receive, send) -> None:
        scope["app"] = app
        await inner(scope, receive, send)

    return asgi


async def collect_matrix(
    app,
    monkeypatch,
    personas: tuple[Persona, ...] = PERSONAS,
    *,
    with_middleware: bool = False,
    every: int = 1,
) -> dict[str, dict[str, str]]:
    """``{moduł: {"METODA /ścieżka": "litery w kolejności person"}}``.

    ``every`` bierze co n-tą trasę — do taniego porównania obu stosów.
    """

    requests = list(route_requests(app))[::every]
    letters: dict[str, list[str]] = {key: [] for _, key, _, _ in requests}
    transport = httpx.ASGITransport(
        app=app if with_middleware else routes_only(app), raise_app_exceptions=False
    )
    with guards_only(app, monkeypatch) as holder:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://authz-matrix"
        ) as client:
            for index, persona in enumerate(personas):
                holder["user"] = build_user(persona, user_id=900_000 + index)
                for _, key, method, path in requests:
                    response = await client.request(
                        method, path, json={} if method in _MUTATING else None
                    )
                    letters[key].append(_verdict(response.status_code))
    matrix: dict[str, dict[str, str]] = {}
    for module, key, _, _ in requests:
        matrix.setdefault(module, {})[key] = "".join(letters[key])
    return matrix


def load_golden() -> dict[str, dict[str, str]]:
    golden: dict[str, dict[str, str]] = {}
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        golden[path.stem] = json.loads(path.read_text(encoding="utf-8"))["routes"]
    return golden


def write_golden(matrix: dict[str, dict[str, str]]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for stale in GOLDEN_DIR.glob("*.json"):
        if stale.stem not in matrix:
            stale.unlink()
    for module, routes in matrix.items():
        payload = {
            "personas": [persona.key for persona in PERSONAS],
            "routes": dict(sorted(routes.items())),
        }
        (GOLDEN_DIR / f"{module}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )


def differences(
    golden: dict[str, dict[str, str]], actual: dict[str, dict[str, str]]
) -> list[str]:
    """Zmiany werdyktu na trasach, które wzorzec już zna (nowe trasy pomija)."""

    actual_by_key = {
        key: letters for routes in actual.values() for key, letters in routes.items()
    }
    lines: list[str] = []
    for module, routes in sorted(golden.items()):
        for key, expected in sorted(routes.items()):
            got = actual_by_key.get(key)
            if got is None or got == expected:
                continue
            changed = [
                f"{persona.key}: {before}→{after}"
                for persona, before, after in zip(PERSONAS, expected, got)
                if before != after
            ]
            if len(got) != len(expected):
                changed.append(f"liczba person {len(expected)}→{len(got)}")
            lines.append(f"{module}: {key}  [{', '.join(changed)}]")
    return lines


def unpinned(
    golden: dict[str, dict[str, str]], actual: dict[str, dict[str, str]]
) -> list[str]:
    known = {key for routes in golden.values() for key in routes}
    return sorted(
        key for routes in actual.values() for key in routes if key not in known
    )
