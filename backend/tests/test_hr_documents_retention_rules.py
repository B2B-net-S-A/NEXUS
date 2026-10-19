"""E-teczka — okres przechowywania co najmniej 10 lat (decyzja Artura 19.10.2026).

Czysta reguła ``documents_rules.parse_retention`` bez bazy: 9 lat to odmowa
z zakresem 10–50 w komunikacie, 10 i 50 lat przechodzą.
"""

from __future__ import annotations

import pytest

from app.services.hr.documents_rules import (
    RETENTION_MAX_YEARS,
    RETENTION_MIN_YEARS,
    RetentionSettingsError,
    parse_retention,
)


def test_minimum_is_ten_years() -> None:
    assert RETENTION_MIN_YEARS == 10
    assert RETENTION_MAX_YEARS == 50


@pytest.mark.parametrize("years", [0, 1, 9, "9", 51])
def test_period_outside_ten_to_fifty_years_is_refused(years) -> None:
    with pytest.raises(RetentionSettingsError) as refused:
        parse_retention({"contract": years})
    assert "od 10 do 50 lat" in str(refused.value)


@pytest.mark.parametrize("years", [10, "10", 25, 50])
def test_ten_to_fifty_years_is_saved(years) -> None:
    assert parse_retention({"contract": years})["contract"] == int(years)
