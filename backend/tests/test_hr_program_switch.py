"""Główny wyłącznik „Ludzi w NEXUSIE” (``HR_PROGRAM_ENABLED``, Artur 18.10.2026).

Wyłączony program nie zostawia śladu dla nikogo, także admina: trasy 404,
sondy „zamknięte”, bez kategorii „Czas i ludzie”, pętle nie startują.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.core.config import settings
from app.services.hr import availability_local
from app.services.hr import program as hr_program
from app.services.hr.program import require_hr_program
from app.tasks import hr_loops

#: Moduły tras programu — każda ich trasa musi stać za wyłącznikiem.
PROGRAM_API_MODULES = {
    "app.api.hr_import",
    "app.api.hr_admin",
    "app.api.hr_counts",
    "app.api.hr_dashboard",
    "app.api.hr_structure",
    "app.api.hr_team",
    "app.api.hr_people",
    "app.api.hr_m365",
    "app.api.hr_leave",
    "app.api.hr_time",
    "app.api.hr_payroll",
    "app.api.hr_settlements",
    "app.api.hr_ksef",
    "app.api.hr_payments",
    "app.api.hr_documents",
    "app.api.hr_agreements",
    "app.api.client_sales_invoices",
    "app.api.hr_approval_finance",
    "app.api.hr_lifecycle",
    "app.api.contract_care",
    "app.api.care_board",
    "app.api.care_cases",
    "app.api.care_skills",
    "app.api.care_atlas",
    "app.api.care_announcements",
    "app.api.public_consultant_mail",
    "app.api.admin_cases",
    "app.api.equipment",
    "app.api.client_onboarding",
    "app.api.equipment_intune",
    "app.api.equipment_public",
}
PROGRAM_PREFIXES = (
    "/api/hr/",
    "/api/care/",
    "/api/cases",
    "/api/equipment",
    "/api/client-onboarding",
    "/api/public/consultant-mail",
    "/api/public/equipment-protocols",
    "/api/finance/sales-invoices",
)


def _routes_with_include_dependencies(app):
    """``(pełna ścieżka, trasa, zależności z include_router)`` — od FastAPI
    0.139 zależności dołączenia siedzą w ``include_context``, nie w trasie
    (por. ``tests/_route_introspection.py``)."""

    def walk(node, prefix: str, inherited: tuple):
        if isinstance(node, APIRoute):
            yield prefix + node.path, node, inherited
            return
        ctx = getattr(node, "include_context", None)
        if ctx is not None:
            calls = tuple(d.dependency for d in (ctx.dependencies or ()))
            original = getattr(node, "original_router", None)
            for route in getattr(original, "routes", []):
                yield from walk(route, prefix + (ctx.prefix or ""), inherited + calls)
            return
        for route in getattr(node, "routes", []):
            yield from walk(route, prefix, inherited)

    for route in app.routes:
        yield from walk(route, "", ())


def test_every_program_route_stands_behind_the_switch() -> None:
    from app.main import app

    # Liczy się pierwsza rejestracja pary (metoda, ścieżka) — to ona obsługuje
    # żądanie. Starsze testy HR dopinają routery drugi raz (pod FastAPI 0.139+
    # nie widzą ich w płaskim `app.routes`); takie duplikaty są zasłonięte.
    serving: dict[tuple[frozenset[str], str], tuple] = {}
    for path, route, inherited in _routes_with_include_dependencies(app):
        serving.setdefault((frozenset(route.methods), path), (path, route, inherited))
    program = [
        (path, route, inherited)
        for path, route, inherited in serving.values()
        if route.endpoint.__module__ in PROGRAM_API_MODULES
        or path.startswith(PROGRAM_PREFIXES)
    ]
    assert len(program) > 200, len(program)
    ungated = sorted(
        f"{sorted(route.methods)} {path}"
        for path, route, inherited in program
        if require_hr_program not in inherited
        and not any(d.call is require_hr_program for d in route.dependant.dependencies)
    )
    assert ungated == [], ungated


@pytest.fixture
def program_off(monkeypatch):
    monkeypatch.setattr(settings, "HR_PROGRAM_ENABLED", False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/hr/people",
        "/api/hr/admin/days-off",
        "/api/hr/admin/availability-source",
        "/api/hr/settlements/months/2026/9",
        "/api/hr/agreements/settings",
        "/api/hr/documents/retention",
        "/api/hr/ksef/status",
        "/api/cases",
        "/api/care/owners",
        "/api/care/board",
        "/api/care/clients",
        "/api/finance/sales-invoices/status",
    ],
)
async def test_admin_gets_plain_404_when_program_is_off(
    program_off, app_client: AsyncClient, app_auth_headers: dict[str, str], path: str
) -> None:
    resp = await app_client.get(path, headers=app_auth_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_probes_answer_closed_when_program_is_off(
    program_off, app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    config = await app_client.get("/api/hr/config", headers=app_auth_headers)
    assert config.status_code == 200, config.text
    body = config.json()
    assert body["program"] is False
    assert body["open_modules"] and not any(body["open_modules"].values())
    assert not any(v for k, v in body["me"].items() if isinstance(v, bool))

    invoicing = await app_client.get(
        "/api/clients/sales-invoices/module", headers=app_auth_headers
    )
    assert invoicing.status_code == 200, invoicing.text
    assert invoicing.json() == {"enabled": False, "open": False}


@pytest.mark.asyncio
async def test_config_says_program_on_when_enabled(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.get("/api/hr/config", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["program"] is True
    # Przy włączonym programie admin dalej ma podgląd modułów (przygotowanie
    # importu) — poza „Zgodami”, które bez przełącznika są ukryte (21.10.2026).
    opened = resp.json()["open_modules"]
    assert all(value for key, value in opened.items() if key != "approvals")


@pytest.mark.asyncio
async def test_people_category_is_hidden_from_settings_when_program_is_off(
    program_off, app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    prefs = await app_client.get(
        "/api/notifications/preferences", headers=app_auth_headers
    )
    assert prefs.status_code == 200, prefs.text
    assert "people" not in {c["key"] for c in prefs.json()["categories"]}

    roles = await app_client.get(
        "/api/settings/notification-roles", headers=app_auth_headers
    )
    assert roles.status_code == 200, roles.text
    assert "people" not in {c["key"] for c in roles.json()["categories"]}


@pytest.mark.asyncio
async def test_people_category_is_listed_when_program_is_on(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    roles = await app_client.get(
        "/api/settings/notification-roles", headers=app_auth_headers
    )
    assert roles.status_code == 200, roles.text
    assert "people" in {c["key"] for c in roles.json()["categories"]}


def test_loops_do_not_start_when_program_is_off(program_off) -> None:
    assert hr_loops.loops_enabled("hr_workdays") is False
    assert hr_program.hides_category("people") is True
    assert hr_program.hides_category("recruitment") is False


@pytest.mark.asyncio
async def test_local_availability_stays_off_when_program_is_off(
    program_off, monkeypatch
) -> None:
    class _Db:
        async def scalar(self, _statement):
            return "local"

    availability_local.reset_source_cache()
    try:
        assert await availability_local.refresh_source(_Db(), force=True) is False
        monkeypatch.setattr(settings, "HR_PROGRAM_ENABLED", True)
        assert await availability_local.refresh_source(_Db(), force=True) is True
    finally:
        availability_local.reset_source_cache()
