"""Zakresy kluczy API Compassa usunięte 22.11.2026 — nie wracają starym merge'em.

``contractors:read`` i ``people_roster:read`` otwierały wyłącznie trasy
``/api/integrations/compass/contractors`` i ``/roster``, które od #3696 dają 410.
Konto ``compass-integration`` jest wyłączone, ale w bazie ma pierwszy z nich
jako zwykły napis: lista kont dalej je pokazuje (``ServiceAccountOut.scopes``
to napisy), a nadać tego zakresu nikomu już się nie da.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.service_accounts import list_scopes
from app.models.service_account import SCOPE_LABELS, ServiceScope
from app.schemas.service_account import (
    ServiceAccountCreate,
    ServiceAccountOut,
    ServiceAccountUpdate,
)
from app.services.hr import program as hr_program

_RETIRED = ("contractors:read", "people_roster:read")


def test_scopes_are_gone_from_the_dictionary() -> None:
    assert set(_RETIRED).isdisjoint(scope.value for scope in ServiceScope)
    assert set(_RETIRED).isdisjoint(scope.value for scope in SCOPE_LABELS)
    assert set(_RETIRED).isdisjoint(hr_program.API_SCOPES)


async def test_picker_does_not_offer_them() -> None:
    offered = {scope.value for scope in await list_scopes(None)}
    assert offered, "słownik dla pickera jest pusty"
    assert set(_RETIRED).isdisjoint(offered)


@pytest.mark.parametrize("scope", _RETIRED)
def test_cannot_be_granted(scope: str) -> None:
    with pytest.raises(ValidationError):
        ServiceAccountCreate(slug="nowa-integracja", name="Nowa", scopes=[scope])
    with pytest.raises(ValidationError):
        ServiceAccountUpdate(scopes=[scope])


def test_disabled_account_with_retired_scope_still_lists() -> None:
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    account = ServiceAccountOut.model_validate(
        {
            "id": 2,
            "slug": "compass-integration",
            "name": "COMPASS",
            "description": None,
            "scopes": ["contractors:read"],
            "is_active": False,
            "created_by": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    assert account.scopes == ["contractors:read"]
