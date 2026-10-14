"""„Zatrudniony” bez żadnej umowy u klienta po 12 miesiącach to historia
(decyzja Artura 14.10.2026).

Pomiar produkcji 14.10.2026: 85 osób stało na „Zatrudniony” bez żadnej umowy
w NEXUSIE u klienta tej rekrutacji (80 z rekrutacji Traffita, 65 zatrudnionych
ponad rok temu) i dalej miało znacznik „Pracuje u nas”. Umowy, która by to
zamknęła (`hire_closed_by_contract`), nie było. Nowe zatrudnienie bez umowy
(umowa dopiero powstaje) zostaje sygnałem przez pierwsze 12 miesięcy.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.services.employment_marker import (
    STALE_HIRE_DAYS,
    hire_closed_by_contract,
    hire_closed_by_contract_clause,
)

TODAY = date(2026, 10, 14)


def _hired(days_ago: int) -> datetime:
    return datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)


def _contract(client_id: int, status: str = "active", **kw) -> SimpleNamespace:
    values = {"end_date": None, "terminated_at": None, "voided_at": None}
    return SimpleNamespace(client_id=client_id, status=status, **{**values, **kw})


def test_old_hire_without_any_contract_at_the_client_is_history() -> None:
    assert hire_closed_by_contract(
        client_id=5, hired_at=_hired(STALE_HIRE_DAYS + 1), contracts=[], today=TODAY
    )


def test_recent_hire_without_a_contract_still_counts() -> None:
    assert not hire_closed_by_contract(
        client_id=5, hired_at=_hired(30), contracts=[], today=TODAY
    )
    # Granica: dokładnie 12 miesięcy temu — jeszcze się liczy.
    assert not hire_closed_by_contract(
        client_id=5, hired_at=_hired(STALE_HIRE_DAYS), contracts=[], today=TODAY
    )


def test_contract_only_at_another_client_does_not_keep_an_old_hire() -> None:
    assert hire_closed_by_contract(
        client_id=5,
        hired_at=_hired(400),
        contracts=[_contract(client_id=9)],
        today=TODAY,
    )


def test_any_contract_at_the_client_keeps_the_contract_rule() -> None:
    # Trwająca umowa u klienta: zatrudnienie trwa, wiek etapu bez znaczenia.
    assert not hire_closed_by_contract(
        client_id=5,
        hired_at=_hired(900),
        contracts=[_contract(client_id=5, status="active")],
        today=TODAY,
    )
    # Umowa zakończona PRZED zatrudnieniem (ponowne zatrudnienie): to reguła
    # umowy, nie wieku etapu — nie zamyka.
    assert not hire_closed_by_contract(
        client_id=5,
        hired_at=_hired(400),
        contracts=[
            _contract(client_id=5, status="ended", end_date=TODAY - timedelta(days=800))
        ],
        today=TODAY,
    )


def test_hire_without_a_date_is_not_judged_by_age() -> None:
    assert not hire_closed_by_contract(
        client_id=5, hired_at=None, contracts=[], today=TODAY
    )


def test_sql_mirror_carries_the_no_contract_age_condition() -> None:
    sql = str(
        hire_closed_by_contract_clause(today=TODAY).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "NOT (EXISTS" in sql
    assert "CAST(candidate_stages.moved_at AS DATE) <" in sql
    assert str(TODAY - timedelta(days=STALE_HIRE_DAYS)) in sql
