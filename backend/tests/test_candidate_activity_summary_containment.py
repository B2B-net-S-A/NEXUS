"""P0 regression tests for the unscoped candidate-summary cache containment."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import candidate_activity_summary as cas_api


async def test_get_activity_summary_never_serves_legacy_cache():
    db = SimpleNamespace(scalar=AsyncMock(return_value=1))

    response = await cas_api.get_activity_summary(
        candidate_id=1,
        current_user=SimpleNamespace(id=9),
        db=db,
    )

    assert response.candidate_id == 1
    assert response.summary is None
    db.scalar.assert_awaited_once()


async def test_get_activity_summary_preserves_candidate_not_found():
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await cas_api.get_activity_summary(
            candidate_id=999,
            current_user=SimpleNamespace(id=9),
            db=db,
        )

    assert exc_info.value.status_code == 404


async def test_refresh_activity_summary_is_fail_closed():
    with pytest.raises(HTTPException) as exc_info:
        await cas_api.refresh_activity_summary.__wrapped__(
            request=SimpleNamespace(),
            candidate_id=1,
            current_user=SimpleNamespace(id=9),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert "bezpiecznej regeneracji cache" in exc_info.value.detail
