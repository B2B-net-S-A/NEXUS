"""Filtr „Kończy u nas w ciągu 60 dni” tylko z dostępem do Delivery (09.11.2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.candidates import _reject_ending_soon_without_delivery


def _user(delivery: str) -> SimpleNamespace:
    return SimpleNamespace(effective_section_access={"delivery": delivery})


def test_recruiter_without_delivery_gets_403():
    with pytest.raises(HTTPException) as exc:
        _reject_ending_soon_without_delivery(["ending_soon"], _user("none"))

    assert exc.value.status_code == 403


@pytest.mark.parametrize("access", ["read", "write"])
def test_delivery_access_passes(access: str):
    _reject_ending_soon_without_delivery(["ending_soon"], _user(access))


@pytest.mark.parametrize("employment", [None, [], ["at_client"], ["available"]])
def test_other_employment_filters_stay_open(employment):
    _reject_ending_soon_without_delivery(employment, _user("none"))
