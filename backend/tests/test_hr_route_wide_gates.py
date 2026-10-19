"""Trasy „Ludzi w NEXUSIE” na samych szerokich bramkach — zamrożona lista.

Kontrakt tras (``test_route_authz_contract.py``) liczy każdą fabrykę
``require_hr_*`` jako bramkę. Część z nich niczego nie rozstrzyga o cudzych
danych — przepuszcza każdego z kartoteką albo z dowolnym uprawnieniem z grupy
„Ludzie”, a zakres (czyje dane) sprawdza dopiero handler (``payroll_access``,
``time_access.can_read``, ``documents.can_see``…). Dziś każdy z tych handlerów
zakres sprawdza (audyt A4, 19.10.2026), ale nowa trasa z taką bramką i bez
sprawdzenia w ciele przeszłaby CI.

Ten test robi z tego wpis w rejestrze: trasa, której JEDYNYMI bramkami są
szerokie bramki HR, musi być na liście ``_WIDE_HR_BASELINE``. Dopisując ją,
wskaż funkcję, która w handlerze rozstrzyga zakres.
"""

from __future__ import annotations

from typing import Any

from tests.test_route_authz_contract import _GATE_QUALNAME_MARKERS, _walk_dependants

#: Bramki, które przepuszczają szeroko i zostawiają zakres handlerowi.
_WIDE_HR_GATES = (
    "require_hr_config_reader",
    "require_hr_documents_reader",
    "require_hr_lifecycle_member",
    "require_hr_equipment_self",
    "require_hr_settlements_billing_reader",
    "require_hr_payroll_member",
    "require_hr_absence_reader",
    "require_hr_substitution_reader",
    "require_hr_time_reader",
)

#: Stan na 19.10.2026 — zakres rozstrzyga handler (w nawiasie).
_WIDE_HR_BASELINE: set[tuple[str, str]] = {
    # własny stan i liczniki (current_user)
    ("GET", "/api/hr/config"),
    ("GET", "/api/hr/me"),
    ("GET", "/api/hr/counts"),
    ("GET", "/api/equipment/me"),
    ("GET", "/api/hr/payroll/me"),
    ("GET", "/api/hr/payroll/me/settlement"),
    ("GET", "/api/hr/lifecycle/my-tasks"),
    # zastępstwa i nieobecności (krąg D6 w absence.py / leave_substitute)
    ("GET", "/api/hr/dashboard/substitution"),
    ("GET", "/api/hr/leave/absent-today"),
    ("GET", "/api/hr/leave/absence"),
    # czas (time_access.can_read)
    ("GET", "/api/hr/time/timesheets/{timesheet_id}/pdf"),
    ("GET", "/api/hr/time/people/{user_id}/export.csv"),
    # płace i premie (payroll_access / PayrollViewer)
    ("GET", "/api/hr/payroll/months/{year}/{month}"),
    ("GET", "/api/hr/payroll/people/{user_id}"),
    ("GET", "/api/hr/payroll/bonuses"),
    ("POST", "/api/hr/payroll/bonuses"),
    ("PATCH", "/api/hr/payroll/bonuses/{bonus_id}"),
    ("POST", "/api/hr/payroll/bonuses/{bonus_id}/approve"),
    ("POST", "/api/hr/payroll/bonuses/{bonus_id}/cancel"),
    # dane do rozliczeń (billing_details.require_subject)
    ("GET", "/api/hr/settlements/billing/{user_id}"),
    # e-teczka (documents.can_see)
    ("GET", "/api/hr/documents/people/{user_id}"),
    ("GET", "/api/hr/documents/people/{user_id}/protocols/{protocol_id}/file"),
    ("GET", "/api/hr/documents/{document_id}/file"),
    # wejście i odejście (lifecycle_access)
    ("GET", "/api/hr/lifecycle/cases"),
    ("GET", "/api/hr/lifecycle/cases/{case_id}"),
    ("PATCH", "/api/hr/lifecycle/tasks/{task_id}"),
    ("GET", "/api/hr/lifecycle/people/{user_id}/summary"),
}


def _gate_qualnames(route: Any) -> list[str]:
    names = []
    for node in _walk_dependants(getattr(route, "dependant", None)):
        call = getattr(node, "call", None)
        if call is None:
            continue
        name = getattr(call, "__qualname__", "") or getattr(call, "__name__", "")
        if any(m in name for m in _GATE_QUALNAME_MARKERS):
            names.append(name)
    return names


def _wide_routes() -> set[tuple[str, str]]:
    from app.main import app

    from tests._route_introspection import iter_api_routes

    found: set[tuple[str, str]] = set()
    for path, route in iter_api_routes(app):
        if not path.startswith("/api/") or not getattr(route, "methods", None):
            continue
        gates = _gate_qualnames(route)
        if not gates or not all(any(w in g for w in _WIDE_HR_GATES) for g in gates):
            continue
        for method in route.methods:
            if method not in {"HEAD", "OPTIONS"}:
                found.add((method, path))
    return found


def test_no_new_hr_routes_on_wide_gates_only() -> None:
    new = sorted(_wide_routes() - _WIDE_HR_BASELINE)
    assert not new, (
        "Nowe trasy „Ludzi” stoją tylko na szerokiej bramce (zakres = handler). "
        "Daj im bramkę, która rozstrzyga zakres, albo dopisz do "
        "_WIDE_HR_BASELINE z nazwą funkcji sprawdzającej zakres:\n"
        + "\n".join(f"  {m} {p}" for m, p in new)
    )


def test_wide_baseline_has_no_stale_entries() -> None:
    stale = sorted(_WIDE_HR_BASELINE - _wide_routes())
    assert not stale, (
        "Te trasy mają już bramkę z zakresem albo zniknęły — usuń je z "
        "_WIDE_HR_BASELINE:\n" + "\n".join(f"  {m} {p}" for m, p in stale)
    )
