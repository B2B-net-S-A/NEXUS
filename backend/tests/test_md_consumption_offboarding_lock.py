"""The MD importer must serialize with contract offboarding on the line row."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import md_consumption
from app.models.client_order import ClientOrderStatus


@pytest.mark.asyncio
async def test_stale_md_match_is_rejected_after_locked_line_was_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = SimpleNamespace(id=41)
    matched_before_offboarding = SimpleNamespace(id=73, order_group_id=group.id)
    locked_after_offboarding = SimpleNamespace(
        id=73,
        order_group_id=group.id,
        order_group=group,
        status=ClientOrderStatus.completed,
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=locked_after_offboarding))
    apply = AsyncMock()
    monkeypatch.setattr(md_consumption, "apply_md_consumption", apply)

    with pytest.raises(HTTPException) as exc:
        await md_consumption._apply_to_line(
            db,
            match_order=matched_before_offboarding,
            group=group,
            period_month="2026-08",
            md_reported=5,
            import_id=9,
            user_id=11,
        )

    assert exc.value.status_code == 409
    assert "Obsada zamówienia zmieniła się" in exc.value.detail
    apply.assert_not_awaited()
