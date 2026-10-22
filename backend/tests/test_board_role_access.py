"""Rola „Rada nadzorcza” (0490) widzi Insights z kwotami i nic więcej.

Obietnica z decyzji Artura (21.10.2026): Rada ogląda zbiorcze raporty
i statystyki — kokpit Firma z kwotami, rok do roku, ranking klientów,
zespół imiennie — a nie zakłada rekrutacji ani kontraktów. Test czyta wzorzec
bramek ``tests/data/authz_golden/`` (kolumna persony ``board``):

* poza Insights rola przechodzi dokładnie te trasy, które przechodzi
  „Pracownik” (własne konto, powiadomienia, pomoc) — nic biznesowego,
* każda trasa ponad „Pracownika” to odczyt (GET) albo nazwany niżej
  odczyt metodą POST — poza umowami przedwstępnymi, które Rada prowadzi jak
  rekruter (decyzja Artura 22.10.2026),
* kandydaci, rekrutacje, klienci, kontrakty, zamówienia, moduł Finanse,
  płace i Generator umów B2B są zamknięte.

Wzorzec odświeża ``AUTHZ_GOLDEN_WRITE=1 python -m pytest
tests/test_authz_guard_matrix.py``; ten test mówi, czy po odświeżeniu rola
nadal dotrzymuje obietnicy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.user import User, UserRole
from app.services import action_permissions
from app.services.hr.payroll_access import is_payroll
from app.tasks import kpi_email_reports as reports

GOLDEN = Path(__file__).parent / "data" / "authz_golden"
PASSES = frozenset("PB")

BOARD = "board"
EMPLOYEE = "employee"

# Metoda zapisu, ale bez zmiany danych: kreator metryk pulpitu liczy wartość
# na żądanie (kwoty tylko z „Stawki i kwoty: podgląd”, którego Rada nie ma).
READ_LIKE_POSTS = frozenset({"POST /api/dashboard-metrics/evaluate"})

# Umowy przedwstępne: odczyt, pliki i akcje jak rekruter (decyzja Artura
# 22.10.2026, audyt F54) — jedyny moduł z zapisem i danymi kandydatów.
PRE_CONTRACT_MODULE = "pre_contracts"

# Ekrany, dla których rola powstała — muszą się otworzyć.
REQUIRED_READS = (
    "GET /api/insights/board",
    "GET /api/insights/board/yoy",
    "GET /api/insights/clients/ranking",
    "GET /api/insights/delivery-leads/portfolio",
    "GET /api/insights/team/people",
    "GET /api/insights/team/attention",
    "GET /api/insights/recruitment/funnel",
    "GET /api/competitions/monthly-races",
)

# Moduły, w których rola nie przechodzi żadnej trasy.
CLOSED_MODULES = (
    "candidates",
    "jobs",
    "pipeline",
    "clients",
    "contracts",
    "client_orders",
    "client_order_groups",
    "finance",
    "client_sales_invoices",
    "hr_approval_finance",
    "b2b_contract_generator",
    "event_history",
)


def _matrix() -> dict[str, dict[str, str]]:
    routes: dict[str, dict[str, str]] = {}
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for route, letters in data["routes"].items():
            routes[route] = dict(zip(data["personas"], letters, strict=True))
    return routes


def _module_routes(module: str) -> dict[str, dict[str, str]]:
    data = json.loads((GOLDEN / f"{module}.json").read_text(encoding="utf-8"))
    return {
        route: dict(zip(data["personas"], letters, strict=True))
        for route, letters in data["routes"].items()
    }


def test_the_golden_has_the_board_column() -> None:
    matrix = _matrix()
    assert matrix
    assert all(BOARD in verdicts for verdicts in matrix.values())


def test_board_adds_only_reads_to_what_an_employee_can_do() -> None:
    beyond_employee = sorted(
        route
        for route, verdicts in _matrix().items()
        if verdicts[BOARD] in PASSES and verdicts[EMPLOYEE] not in PASSES
    )
    pre_contracts = set(_module_routes(PRE_CONTRACT_MODULE))
    writes = [
        route
        for route in beyond_employee
        if not route.startswith("GET ")
        and route not in READ_LIKE_POSTS
        and route not in pre_contracts
    ]
    assert writes == []
    assert beyond_employee, "Rada nie przechodzi niczego ponad Pracownika"


def test_board_works_on_pre_contracts_like_a_recruiter() -> None:
    routes = _module_routes(PRE_CONTRACT_MODULE)
    assert routes
    closed = sorted(
        route for route, verdicts in routes.items() if verdicts[BOARD] not in PASSES
    )
    assert closed == []


def test_listed_exceptions_still_exist() -> None:
    matrix = _matrix()
    for route in (*READ_LIKE_POSTS, *REQUIRED_READS):
        assert route in matrix, f"{route} zniknęła z wzorca — popraw listę"


@pytest.mark.parametrize("route", REQUIRED_READS)
def test_board_opens_the_reports_it_was_made_for(route: str) -> None:
    assert _matrix()[route][BOARD] in PASSES


@pytest.mark.parametrize("module", CLOSED_MODULES)
def test_board_never_reaches_operational_or_money_modules(module: str) -> None:
    opened = [
        route
        for route, verdicts in _module_routes(module).items()
        if verdicts[BOARD] in PASSES
    ]
    assert opened == []


def test_board_is_not_company_staff() -> None:
    # Bramki „każdy pracownik firmy” (Nieobecni dziś, zastępstwa) wpuszczają
    # wszystkich spoza listy ról, które pracownikami NIE są — Rada nadzorcza
    # musi na niej być (przegląd 21.10.2026: „Nieobecni dziś” pokazywały jej
    # nazwiska nieobecnych i zastępców). Bramka sięga do bazy po przełącznik
    # modułu przed sprawdzeniem roli, więc wzorzec bramek ma tam „B” —
    # pilnujemy samych list.
    from app.api import hr_dashboard, hr_leave
    from app.services.hr.people import NON_STAFF_ROLES

    assert UserRole.board in hr_leave._NOT_STAFF
    assert UserRole.board in hr_dashboard._NOT_STAFF
    assert UserRole.board in NON_STAFF_ROLES


def test_integration_events_hide_candidates_without_candidate_read() -> None:
    # Insights → Integracje: zdarzenia przebiegu niosą kandydata. Konto bez
    # odczytu kandydatów (Rada nadzorcza) widzi zdarzenie bez osoby — jak
    # w uzgodnieniu placementów (``insights_reconciliation``).
    from types import SimpleNamespace

    from app.api.integrations_runs import event_to_dict

    event = SimpleNamespace(
        id=1,
        action="created",
        external_id="x",
        candidate_id=7,
        traffit_id=9,
        candidate_name="Jan Kowalski",
        offer_title="Java",
        matched_jobs=[],
        error=None,
        occurred_at=None,
    )
    hidden = event_to_dict(event, show_candidates=False)
    assert hidden["candidate_name"] is None
    assert hidden["candidate_id"] is None
    assert hidden["traffit_id"] is None
    assert hidden["offer_title"] == "Java"
    assert (
        event_to_dict(event, show_candidates=True)["candidate_name"] == "Jan Kowalski"
    )


def _user(role: UserRole, *permissions: str) -> User:
    user = User(
        id=1,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
    )
    user.effective_action_access = {key: "manage" for key in permissions}
    user.effective_section_access = {"insights": "read"}
    return user


def test_board_accepts_no_grants() -> None:
    # Nadanie „Modułu Finanse” otworzyłoby Radzie faktury, zgody na wydatki
    # i zmiany w zamówieniach — rola przyjmuje tylko to, co ma z definicji.
    assert UserRole.board in action_permissions.UNGRANTABLE_ROLES
    assert not action_permissions.account_accepts_grants(_user(UserRole.board))


def test_board_never_gets_payroll() -> None:
    # Bramka „Płace” (``hr_payments``) sięga do bazy (przełącznik modułu)
    # przed sprawdzeniem uprawnienia, więc wzorzec ma tam „B” dla każdego —
    # o odmowie decyduje ta funkcja.
    assert not is_payroll(_user(UserRole.board))


def test_board_reads_money_but_head_of_recruitment_does_not() -> None:
    assert action_permissions.reads_board_money(_user(UserRole.board))
    assert action_permissions.reads_board_money(
        _user(UserRole.finance, "finance_module")
    )
    assert not action_permissions.reads_board_money(_user(UserRole.head_of_recruitment))


def test_monthly_board_mail_reaches_the_board() -> None:
    board = _user(UserRole.board)
    hor = _user(UserRole.head_of_recruitment)
    assert reports._board_readers([board, hor]) == [board]
