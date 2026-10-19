"""Własna stawka (decyzja Artura 19.10.2026): Płace nie ustawiają ani nie usuwają
stawki sobie — robi to druga osoba z Płac albo administrator.

Czysta reguła bez bazy (``payroll_rates.ensure_not_own_rate``); ścieżkę HTTP
sprawdza ``test_hr_payroll_api.py``.
"""

from __future__ import annotations

import pytest

from app.services.hr.payroll_errors import PayrollForbidden
from app.services.hr.payroll_rates import (
    OWN_RATE_DELETE_DETAIL,
    OWN_RATE_SET_DETAIL,
    ensure_not_own_rate,
)


def test_own_rate_is_refused_for_payroll_without_admin() -> None:
    with pytest.raises(PayrollForbidden) as refused:
        ensure_not_own_rate(7, actor_id=7, actor_is_admin=False)
    assert refused.value.status_code == 403
    assert refused.value.message == OWN_RATE_SET_DETAIL
    assert "druga osoba z Płac albo administrator" in OWN_RATE_SET_DETAIL


def test_own_rate_delete_has_its_own_sentence() -> None:
    with pytest.raises(PayrollForbidden) as refused:
        ensure_not_own_rate(7, actor_id=7, actor_is_admin=False, deleting=True)
    assert refused.value.message == OWN_RATE_DELETE_DETAIL
    assert OWN_RATE_DELETE_DETAIL.startswith("Własnej stawki nie usuwasz")


def test_admin_may_set_own_rate_and_others_are_untouched() -> None:
    ensure_not_own_rate(7, actor_id=7, actor_is_admin=True)
    ensure_not_own_rate(7, actor_id=7, actor_is_admin=True, deleting=True)
    ensure_not_own_rate(7, actor_id=8, actor_is_admin=False)
    ensure_not_own_rate(7, actor_id=8, actor_is_admin=False, deleting=True)
