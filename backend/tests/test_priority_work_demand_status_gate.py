"""Bramka statusów demandu: kto może przenieść zapotrzebowanie na `fulfilled`.

Kontrakt jest tu pokryty wyłącznie asercją na źródle
(`assert "assert_demand_status_transition(" in update_source`
w test_priority_work_api.py), a ta przechodzi niezależnie od zawartości tabeli
przejść. Panel Delivery Leada oferował „Oznacz jako zrealizowane" — cel, którego
`_DEMAND_STATUS_TRANSITIONS_DL` nie zna — więc rozjazd UI↔backend był cichy:
frontend mockuje klienta, backend testuje wyłącznie aktora HoR.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import priority_work
from app.models.recruitment_priority import PriorityDemandStatus
from app.models.user import UserRole
from app.services.priority_work_service import assert_demand_status_transition


class _Actor:
    def __init__(self, *roles: UserRole):
        self.id = 77
        self._roles = set(roles)

    def has_any_role(self, *roles: UserRole) -> bool:
        return bool(self._roles & set(roles))

    def has_role(self, role: UserRole) -> bool:
        return role in self._roles


def _demand_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=8,
        job_id=5,
        status=PriorityDemandStatus.open,
        row_version=1,
    )


async def test_delivery_lead_cannot_fulfil_own_demand() -> None:
    """Dokładnie to, co robił przycisk w PriorityRequestsPanel: DL → fulfilled."""

    row = _demand_row()
    actor = _Actor(UserRole.delivery_lead)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[row, actor.id]))
    payload = priority_work.DemandUpdateRequest(expected_version=1, status="fulfilled")

    with pytest.raises(HTTPException) as error:
        await priority_work.update_priority_demand(8, payload, actor, db)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "PRIORITY_DEMAND_TRANSITION_INVALID"
    # Status na wierszu nie może się ruszyć — 422 z niezapisaną zmianą, nie
    # „zapisano i dopiero potem odmówiono".
    assert row.status is PriorityDemandStatus.open
    assert row.row_version == 1


@pytest.mark.parametrize(
    "current",
    [PriorityDemandStatus.open, PriorityDemandStatus.covered],
)
def test_transition_table_splits_pause_from_fulfil_for_delivery_lead(
    current: PriorityDemandStatus,
) -> None:
    """Sąsiednie przyciski panelu: „Wstrzymaj" legalne, „Zrealizowane" nie.

    Oba stany (`open`, `covered`) to dokładnie te, dla których panel renderuje
    pasek akcji — gdyby ktoś dopisał `fulfilled` do wpisów DL, ten test ma
    wymusić świadomą decyzję zamiast cichego poszerzenia uprawnień.
    """

    assert_demand_status_transition(
        current, PriorityDemandStatus.paused, actor_is_hor=False
    )
    with pytest.raises(HTTPException) as error:
        assert_demand_status_transition(
            current, PriorityDemandStatus.fulfilled, actor_is_hor=False
        )
    assert error.value.status_code == 422

    # Ten sam ruch wykonany przez HoR jest legalny — to jest werdykt HoR-a.
    assert_demand_status_transition(
        current, PriorityDemandStatus.fulfilled, actor_is_hor=True
    )
