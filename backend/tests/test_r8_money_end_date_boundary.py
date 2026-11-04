"""Runda 8 (R8-N13-1): dzień zakończenia kontraktu = `end_date` → `terminated_at`.

`terminated_at` przeżywa aneks przedłużenia i przywrócenie
(`reopen_contract` go nie czyści), więc umowa zakończona, przedłużona
i zakończona ponownie niesie datę PIERWSZEGO zakończenia. Każde miejsce, które
liczy „dzień odejścia" (archiwum profilu klienta, LTV, zejścia rok do roku,
data końca współpracy na karcie zamówienia), bierze `end_date` przed
`terminated_at` — tak jak `contract_termination_sync`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.api.client_order_groups import _contract_cooperation_end
from app.api.clients import _archive_boundary
from app.models.contract import ContractStatus, ContractTerminationReason
from app.services.insights_board_yoy import _departures_by_month

TODAY = date(2026, 9, 26)


def _contract(**kw):
    base = {
        "status": ContractStatus.ended,
        "end_date": None,
        "terminated_at": None,
        "termination_reason": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_archive_boundary_prefers_end_date_over_stale_termination():
    reopened = _contract(end_date=date(2025, 9, 30), terminated_at=date(2025, 3, 31))
    assert _archive_boundary(reopened, TODAY) == date(2025, 9, 30)


def test_archive_boundary_falls_back_to_termination_then_today():
    assert _archive_boundary(_contract(terminated_at=date(2025, 3, 31)), TODAY) == date(
        2025, 3, 31
    )
    assert _archive_boundary(_contract(), TODAY) == TODAY


def test_departures_count_in_the_month_of_the_final_end():
    reopened = _contract(
        end_date=date(2025, 9, 30),
        terminated_at=date(2025, 3, 31),
        termination_reason=ContractTerminationReason.consultant_resigned,
    )
    departures, resignations, _ = _departures_by_month([reopened])
    assert dict(departures) == {(2025, 9): 1}
    assert dict(resignations) == {(2025, 9): 1}


def test_cooperation_end_ignores_termination_that_an_extension_undid():
    reopened_live = _contract(
        status=ContractStatus.active,
        end_date=None,
        terminated_at=date(2025, 3, 31),
    )
    assert _contract_cooperation_end(reopened_live) is None
    extended = _contract(
        status=ContractStatus.active,
        end_date=date(2026, 12, 31),
        terminated_at=date(2025, 3, 31),
    )
    assert _contract_cooperation_end(extended) is None


def test_cooperation_end_for_planned_and_final_terminations():
    planned = _contract(
        status=ContractStatus.ending,
        end_date=date(2026, 10, 15),
        terminated_at=date(2026, 10, 15),
    )
    assert _contract_cooperation_end(planned) == date(2026, 10, 15)
    ended_after_extension = _contract(
        end_date=date(2025, 9, 30), terminated_at=date(2025, 3, 31)
    )
    assert _contract_cooperation_end(ended_after_extension) == date(2025, 9, 30)
    natural_end_live = _contract(
        status=ContractStatus.active, end_date=date(2026, 12, 31)
    )
    assert _contract_cooperation_end(natural_end_live) is None
