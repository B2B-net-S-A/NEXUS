"""Kreator metryk pulpitu: kwoty idą za uprawnieniem „Stawki i kwoty: podgląd”.

Do 02.10.2026 źródło „finance” wpuszczało rolę Delivery Leada (i capability
``VIEW_FINANCE``). Po przejściu na uprawnienia katalog kafelków pyta o
``amounts_view``, więc serwer musi pytać o to samo: Delivery Lead z wyłączonym
podglądem kwot nie liczy pieniędzy portfela, a osoba z nadanym podglądem je
liczy — u wszystkich klientów, jeśli nie rządzi nią portfel DL.

Testy bez bazy.
"""

from __future__ import annotations

import pytest

from app.models.user import User, UserRole
from app.services import permission_catalog
from app.services.custom_metrics import engine
from app.services.section_permissions import ProductSection


def _holder(role: UserRole, *permissions: str) -> User:
    user = User(
        id=71,
        email="metrics-perm@example.com",
        name="Metryki",
        role=role,
        roles=[role.value],
        is_active=True,
    )
    held = permission_catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = {
        **{section.value: "none" for section in ProductSection},
        **permission_catalog.derive_sections(held),
    }
    return user


def test_delivery_lead_without_amounts_view_cannot_count_money():
    lead = _holder(UserRole.delivery_lead, "delivery_view", "clients_edit")

    reason = engine.source_denial(lead, "finance")

    assert reason and "Stawki i kwoty: podgląd" in reason


def test_recruiter_granted_amounts_view_counts_money():
    recruiter = _holder(UserRole.recruiter, "amounts_view")

    assert engine.source_denial(recruiter, "finance") is None


def test_recruiter_without_amounts_view_is_told_which_permission_is_missing():
    recruiter = _holder(UserRole.recruiter)

    reason = engine.source_denial(recruiter, "finance")

    assert reason and "Stawki i kwoty: podgląd" in reason


@pytest.mark.asyncio
async def test_granted_holder_without_dl_role_counts_every_client(monkeypatch):
    async def _no_portfolio(user, db):
        return None

    monkeypatch.setattr(engine, "resolve_delivery_lead_finance_client_ids", _no_portfolio)
    recruiter = _holder(UserRole.recruiter, "amounts_view")

    assert await engine._finance_client_boundary(recruiter, None) is None


@pytest.mark.asyncio
async def test_delivery_lead_counts_only_the_portfolio(monkeypatch):
    async def _portfolio(user, db):
        return frozenset({3, 7})

    monkeypatch.setattr(engine, "resolve_delivery_lead_finance_client_ids", _portfolio)
    lead = _holder(UserRole.delivery_lead, "amounts_view")

    assert await engine._finance_client_boundary(lead, None) == frozenset({3, 7})


@pytest.mark.asyncio
async def test_delivery_lead_without_clients_is_refused_not_zeroed(monkeypatch):
    async def _empty(user, db):
        return frozenset()

    monkeypatch.setattr(engine, "resolve_delivery_lead_finance_client_ids", _empty)
    lead = _holder(UserRole.delivery_lead, "amounts_view")

    with pytest.raises(engine.MetricAccessDenied):
        await engine._finance_client_boundary(lead, None)
