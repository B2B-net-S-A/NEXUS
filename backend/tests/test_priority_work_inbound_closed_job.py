"""Zgłoszenie z publicznego linku na ofertę, która zdążyła się zamknąć.

Bramka „oferta zamknięta" stała PRZED gałęzią `external_inbound`, więc w trybie
shadow zamrażała `kpi_eligible=True` z `eligibility_assignment_id=NULL` na
twórcy linku: proces nigdy nie doliczał się do targetu rekrutera
(`record_accepted_verification` wychodzi wcześniej, gdy `kpi_eligible` jest już
ustawione), a własność szła do tożsamości, której gałąź inbound świadomie nie
kredytuje. W enforce zgłoszenie było po prostu odrzucane.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.recruitment_priority import PriorityMode, PriorityOriginKind
from app.services import priority_work_policy as policy


@pytest.mark.parametrize("mode", [PriorityMode.shadow, PriorityMode.enforce])
async def test_inbound_on_closed_job_defers_eligibility(monkeypatch, mode) -> None:
    monkeypatch.setattr(policy, "effective_priority_mode", AsyncMock(return_value=mode))

    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        # actor = twórca linku; to jego tożsamość nie może wyprodukować kredytu
        actor_user_id=33,
        origin_kind=PriorityOriginKind.external_inbound,
        continuation_exists=False,
        frozen_priority_compliant=True,
        job_is_open=False,
    )

    assert decision.allowed is True
    assert decision.reason is policy.PriorityWorkReason.external_inbound
    # None = „zdecyduje pierwsza zaakceptowana weryfikacja", nie True/False.
    assert decision.kpi_eligible is None
    assert decision.priority_compliant is True
    assert decision.assignment_owner_user_id is None
    assert decision.violation is False


@pytest.mark.parametrize("mode", [PriorityMode.shadow, PriorityMode.enforce])
async def test_inbound_on_open_job_is_unchanged(monkeypatch, mode) -> None:
    """Wyjątek dotyczy tylko zamkniętej oferty — otwarta zachowuje się jak dotąd."""

    monkeypatch.setattr(policy, "effective_priority_mode", AsyncMock(return_value=mode))

    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        origin_kind=PriorityOriginKind.external_inbound,
        continuation_exists=False,
        frozen_priority_compliant=True,
        job_is_open=True,
    )

    assert decision.reason is policy.PriorityWorkReason.external_inbound
    assert decision.kpi_eligible is None


async def test_closed_job_still_blocks_ordinary_recruiter_work(monkeypatch) -> None:
    """Wyjątek nie może rozszczelnić bramki dla zwykłej pracy z bazy."""

    monkeypatch.setattr(
        policy,
        "effective_priority_mode",
        AsyncMock(return_value=PriorityMode.enforce),
    )

    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        job_is_open=False,
    )

    assert decision.allowed is False
    assert decision.reason is policy.PriorityWorkReason.job_not_open


async def test_closed_job_shadow_still_records_a_violation(monkeypatch) -> None:
    monkeypatch.setattr(
        policy,
        "effective_priority_mode",
        AsyncMock(return_value=PriorityMode.shadow),
    )

    decision = await policy.decide_priority_work_access(
        AsyncMock(),
        candidate_id=11,
        job_id=22,
        actor_user_id=33,
        continuation_exists=False,
        job_is_open=False,
    )

    assert decision.reason is policy.PriorityWorkReason.shadow_job_not_open
    assert decision.violation is True
