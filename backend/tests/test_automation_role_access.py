"""Rola „Automatyzacje” (0446) czyta, ale niczego nie zapisuje.

Obietnica z decyzji Artura (14.10.2026): osoba od automatyzacji widzi
rekrutacje, kandydatów, Insights oraz klientów, kontrakty i zamówienia bez
kwot — i nie zmienia niczego na ekranach. Test czyta wzorzec bramek
``tests/data/authz_golden/`` (kolumna persony ``automation``), więc nie
potrzebuje aplikacji ani bazy:

* zapis — rola nie przechodzi żadnej trasy z metodą zapisu, której nie
  przechodzi stary Viewer, poza nazwanymi niżej trasami, które niczego nie
  zmieniają (wyszukiwanie, podgląd), albo które zatrzymuje handler, i poza
  umowami przedwstępnymi, które rola prowadzi jak rekruter (decyzja Artura
  22.10.2026);
* odczyt — rola czyta to, co rekruter z podglądem Delivery, poza nazwanymi
  wyjątkami w obie strony;
* pieniądze — moduł Finanse, Generator umów B2B i stawki rynkowe są zamknięte.

Wzorzec odświeża ``AUTHZ_GOLDEN_WRITE=1 python -m pytest
tests/test_authz_guard_matrix.py``; ten test mówi, czy po odświeżeniu rola
nadal dotrzymuje obietnicy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.client_deletion import require_client_deletion_permission
from app.models.user import User, UserRole

GOLDEN = Path(__file__).parent / "data" / "authz_golden"
PASSES = frozenset("PB")
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

AUTOMATION = "automation"
VIEWER = "user"
READER_TWIN = "recruiter+delivery_view"

# Metoda zapisu, ale bez zmiany danych: wyszukiwanie, podgląd i render
# szablonu, wolne terminy w kalendarzu, ocena technologii, ściąga do rozmowy
# i podpowiedzi wymagań liczone na żądanie (``request_semantics`` uznaje dwie
# ostatnie za odczyt).
READ_LIKE_WRITES = frozenset(
    {
        "POST /api/candidates/check-duplicates",
        "POST /api/cv-generator/classify-technologies",
        "POST /api/email-templates/{template_id}/preview",
        "POST /api/job-intake/critical-suggestion",
        "POST /api/job-intake/requirement-rows",
        "POST /api/emails/preview",
        "POST /api/microsoft365/free-busy",
        "POST /api/prep-kit/generate",
        "POST /api/recommendations/cv-upload-preview",
        "POST /api/search/candidates",
        "POST /api/search/candidates/diagnostics",
        "POST /api/search/candidates/scores",
        "POST /api/search/semantic",
        "POST /api/user-email-templates/{template_id}/render",
    }
)

# Bramka trasy przepuszcza każdego z podglądem Delivery, a o usunięciu
# klienta decyduje imienne uprawnienie w handlerze — dla tej roli zawsze
# odmowa (test niżej).
HANDLER_DENIED_WRITES = frozenset(
    {
        "DELETE /api/clients/{client_id}",
        "POST /api/clients/{client_id}/deletion-check",
    }
)

# Odczyt ponad rekrutera z podglądem Delivery: przetargi bez wartości
# (capability analityki bez finansów; wartości tylko z ``VIEW_FINANCE``).
EXTRA_READS = frozenset({"GET /api/analytics/v1/commercial/tenders"})

# Moduły, w których rola nie przechodzi żadnej trasy: pieniądze i umowy.
CLOSED_MODULES = (
    "finance",
    "financial_adjustments",
    "contract_analytics",
    "rate_benchmarks",
    "b2b_contract_generator",
    "b2b_documents",
    "event_history",
)

# Opieka nad konsultantami i sprzęt konsultanta: rozmowy o ludziach,
# zadowolenie, sygnały odejścia, numery seryjne — nie dane do integracji
# (decyzja Artura 19.10.2026, audyt A4/A3).
CLOSED_CARE_MODULES = (
    "contract_care",
    "care_consultants",
    "care_skills",
    "care_structure",
    "care_announcements",
    "care_atlas",
    # Przebudowa opieki (22.10.2026): tablica, „Klienci”, sprawy w karcie.
    "care_board",
    "care_cases",
)
CLOSED_EQUIPMENT_ROUTES = ("GET /api/equipment/contracts/{contract_id}",)

# Umowy przedwstępne: odczyt, pliki i akcje jak rekruter (decyzja Artura
# 22.10.2026, audyt F54) — jedyny moduł, w którym rola zapisuje na ekranie.
PRE_CONTRACT_MODULE = "pre_contracts"

# Ekrany, dla których rola powstała — muszą się otworzyć.
REQUIRED_READS = (
    "GET /api/candidates",
    "GET /api/candidates/{candidate_id}",
    "GET /api/jobs",
    "GET /api/jobs/{job_id}",
    "GET /api/pipeline/overview",
    "GET /api/clients",
    "GET /api/clients/{client_id}",
    "GET /api/contracts",
    "GET /api/users/mentionable",
)


def _matrix() -> dict[str, dict[str, str]]:
    routes: dict[str, dict[str, str]] = {}
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        personas = data["personas"]
        for route, letters in data["routes"].items():
            routes[route] = dict(zip(personas, letters, strict=True))
    return routes


def _module_routes(module: str) -> dict[str, dict[str, str]]:
    data = json.loads((GOLDEN / f"{module}.json").read_text(encoding="utf-8"))
    return {
        route: dict(zip(data["personas"], letters, strict=True))
        for route, letters in data["routes"].items()
    }


def test_the_golden_has_the_automation_column() -> None:
    matrix = _matrix()
    assert matrix
    assert all(AUTOMATION in verdicts for verdicts in matrix.values())


def test_automation_writes_nothing_beyond_the_viewer() -> None:
    allowed = (
        READ_LIKE_WRITES
        | HANDLER_DENIED_WRITES
        | set(_module_routes(PRE_CONTRACT_MODULE))
    )
    unexpected = sorted(
        route
        for route, verdicts in _matrix().items()
        if route.split(" ", 1)[0] in MUTATING
        and verdicts[AUTOMATION] in PASSES
        and verdicts[VIEWER] not in PASSES
        and route not in allowed
    )
    assert unexpected == [], (
        "Rola „Automatyzacje” przechodzi bramkę zapisu — dopisz trasę do "
        "NOT_READ_ONLY (candidate_access.py) albo, jeśli niczego nie zmienia, "
        f"do READ_LIKE_WRITES: {unexpected}"
    )


def test_automation_works_on_pre_contracts_like_a_recruiter() -> None:
    routes = _module_routes(PRE_CONTRACT_MODULE)
    assert routes
    closed = sorted(
        route
        for route, verdicts in routes.items()
        if verdicts[AUTOMATION] not in PASSES
    )
    assert closed == []


def test_listed_exceptions_still_exist() -> None:
    matrix = _matrix()
    stale = sorted(
        route
        for route in READ_LIKE_WRITES | HANDLER_DENIED_WRITES | EXTRA_READS
        if route not in matrix
    )
    assert stale == []


def test_automation_reads_like_a_recruiter_with_delivery_view() -> None:
    extra = sorted(
        route
        for route, verdicts in _matrix().items()
        if route.startswith("GET ")
        and verdicts[AUTOMATION] in PASSES
        and verdicts[READER_TWIN] not in PASSES
        and route not in EXTRA_READS
    )
    assert extra == [], f"Rola czyta więcej niż rekruter z podglądem Delivery: {extra}"


@pytest.mark.parametrize("module", CLOSED_MODULES)
def test_automation_never_reaches_money(module: str) -> None:
    opened = sorted(
        route
        for route, verdicts in _module_routes(module).items()
        if verdicts[AUTOMATION] in PASSES
    )
    assert opened == []


@pytest.mark.parametrize("module", CLOSED_CARE_MODULES)
def test_automation_never_reaches_consultant_care(module: str) -> None:
    opened = sorted(
        route
        for route, verdicts in _module_routes(module).items()
        if verdicts[AUTOMATION] in PASSES
    )
    assert opened == []


@pytest.mark.parametrize("route", CLOSED_EQUIPMENT_ROUTES)
def test_automation_does_not_read_consultant_equipment(route: str) -> None:
    assert _matrix()[route][AUTOMATION] not in PASSES


@pytest.mark.parametrize("route", REQUIRED_READS)
def test_automation_opens_the_screens_it_was_made_for(route: str) -> None:
    assert _matrix()[route][AUTOMATION] in PASSES


class _NoClientDb:
    async def scalar(self, _statement):
        return None


@pytest.mark.asyncio
async def test_delete_clients_flag_does_not_open_deletion_for_automation() -> None:
    user = User(
        id=7,
        role=UserRole.automation,
        roles=[UserRole.automation.value],
        can_delete_clients=True,
    )
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as denied:
        await require_client_deletion_permission(
            request, client_id=1, current_user=user, db=_NoClientDb()
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_clients_flag_still_works_for_other_roles() -> None:
    user = User(
        id=8,
        role=UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value],
        can_delete_clients=True,
    )
    request = SimpleNamespace(state=SimpleNamespace())
    allowed = await require_client_deletion_permission(
        request, client_id=1, current_user=user, db=_NoClientDb()
    )
    assert allowed is user


class _JobDb:
    def __init__(self, job) -> None:
        self._job = job

    async def get(self, _model, _job_id):
        return self._job


@pytest.mark.asyncio
async def test_automation_reads_every_recruitment_without_membership() -> None:
    from app.api.recruitment_access import ensure_job_membership

    user = User(id=9, role=UserRole.automation, roles=[UserRole.automation.value])
    # Rekrutacja istnieje — bez członkostwa w zespole, jak u reszty firmy.
    await ensure_job_membership(_JobDb(object()), user, 123)
    with pytest.raises(HTTPException) as missing:
        await ensure_job_membership(_JobDb(None), user, 123)
    assert missing.value.status_code == 404
