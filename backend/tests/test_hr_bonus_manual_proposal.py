"""Premia ręczna od przełożonego = propozycja dla Płac (decyzja Artura 19.10.2026).

Czysta reguła bez bazy (``payroll_bonuses.approval_refusal`` / ``can_approve``):
propozycję ręczną zatwierdzają tylko Płace, nigdy jej autor; propozycje
automatów zatwierdza dalej przełożony osoby. Ścieżkę HTTP sprawdza
``test_hr_payroll_api.py``. Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.hr_payroll import HrBonus
from app.services.hr.payroll_access import PayrollViewer
from app.services.hr.payroll_bonuses import approval_refusal, can_approve

BOSS, OTHER_BOSS, FINANCE, WORKER = 10, 11, 12, 20


def _viewer(user_id: int, *, payroll: bool = False) -> PayrollViewer:
    reports = frozenset() if payroll else frozenset({WORKER})
    return PayrollViewer(
        user_id=user_id, payroll=payroll, admin=False, report_ids=reports
    )


def _bonus(
    *, source: str = "manual", status: str = "proposed", by: int | None = BOSS
) -> HrBonus:
    return HrBonus(
        recipient_user_id=WORKER,
        proposed_by=by,
        amount=Decimal("100"),
        currency="PLN",
        category="custom",
        period_year=2026,
        period_month=10,
        status=status,
        source=source,
    )


def test_author_of_manual_proposal_does_not_approve_it() -> None:
    refusal = approval_refusal(_viewer(BOSS), _bonus())
    assert refusal is not None and "Płace" in refusal
    assert can_approve(_viewer(BOSS), _bonus()) is False


def test_other_manager_does_not_approve_manual_proposal() -> None:
    refusal = approval_refusal(_viewer(OTHER_BOSS), _bonus())
    assert refusal == "Premię ręczną od przełożonego zatwierdzają Płace."


def test_payroll_approves_manual_proposal() -> None:
    assert approval_refusal(_viewer(FINANCE, payroll=True), _bonus()) is None
    assert can_approve(_viewer(FINANCE, payroll=True), _bonus()) is True


def test_manager_still_approves_automated_proposal() -> None:
    automated = _bonus(source="contract_placement", by=None)
    assert approval_refusal(_viewer(BOSS), automated) is None
    assert can_approve(_viewer(BOSS), automated) is True


def test_nothing_to_approve_outside_proposals() -> None:
    assigned = _bonus(status="assigned")
    assert can_approve(_viewer(FINANCE, payroll=True), assigned) is False
