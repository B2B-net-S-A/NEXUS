"""UAT B28: odwrócony przedział (min > max) w wyszukiwarce = 422, nie wynik.

Do 09.2026 „min 10 / max 2 lat" przechodziło walidację i zwracało wyłącznie
osoby bez uzupełnionego stażu — rekruter widział setki wyników pod
niemożliwym filtrem. Reguła ma jedno źródło (`raise_if_range_reversed`)
dzielone przez schemat legacy i V3.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.candidate_search import (
    EXPERIENCE_RANGE_REVERSED_MSG,
    RATE_RANGE_REVERSED_MSG,
    CandidateSearchRequest,
)
from app.schemas.candidate_search_v3 import HardFilters


def test_reversed_experience_range_is_rejected_with_polish_message() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CandidateSearchRequest(experience_years_min=10, experience_years_max=2)
    messages = [e["msg"] for e in excinfo.value.errors()]
    assert EXPERIENCE_RANGE_REVERSED_MSG in messages
    # Bez prefiksu „Value error, …" — użytkownik dostaje gotowe zdanie.
    assert all(not m.startswith("Value error") for m in messages)


def test_reversed_rate_range_is_rejected_with_polish_message() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CandidateSearchRequest(rate_hourly_min=200, rate_hourly_max=100)
    assert RATE_RANGE_REVERSED_MSG in [e["msg"] for e in excinfo.value.errors()]


@pytest.mark.parametrize(
    ("low", "high"),
    [(2, 6), (3, 3), (None, 2), (10, None), (None, None)],
)
def test_ordered_or_open_ranges_still_validate(low, high) -> None:
    request = CandidateSearchRequest(
        experience_years_min=low, experience_years_max=high
    )
    assert request.experience_years_min == low
    assert request.experience_years_max == high


def test_v3_hard_filters_mirror_the_rule() -> None:
    with pytest.raises(ValidationError) as excinfo:
        HardFilters(experience_years_min=10, experience_years_max=2)
    assert EXPERIENCE_RANGE_REVERSED_MSG in [e["msg"] for e in excinfo.value.errors()]
    assert HardFilters(experience_years_min=2, experience_years_max=6)


@pytest.mark.asyncio
async def test_search_endpoint_answers_422_with_the_message(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    resp = await app_client.post(
        "/api/search/candidates",
        json={"experience_years_min": 10, "experience_years_max": 2},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any(EXPERIENCE_RANGE_REVERSED_MSG in str(item) for item in detail)
