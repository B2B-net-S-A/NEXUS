"""A two-variant preview must be admitted before either unit is recorded."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import database
from app.models.ai_feature import AIFeatureKey
from app.services import ai_quota


@pytest.mark.asyncio
@pytest.mark.parametrize("used, admitted", [(9, False), (8, True)])
@pytest.mark.parametrize("queued", [False, True])
async def test_preview_pair_capacity_is_checked_before_durable_record(
    monkeypatch, used, admitted, queued
):
    monkeypatch.setattr(ai_quota, "get_master_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ai_quota,
        "get_feature_config",
        AsyncMock(return_value=SimpleNamespace(enabled=True, monthly_limit=10)),
    )
    monkeypatch.setattr(
        ai_quota, "get_total_usage_for_period", AsyncMock(return_value=used)
    )
    ledger = MagicMock()
    ledger.commit = AsyncMock()
    ledger.flush = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=ledger)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)

    if not admitted:
        with pytest.raises(ai_quota.AIQuotaExceeded) as error:
            await ai_quota.check_and_increment(
                ledger,
                AIFeatureKey.cv_generator,
                user_id=17,
                units=2,
                commit_with_caller=queued,
            )
        assert (error.value.used, error.value.limit) == (9, 10)
        factory.assert_not_called()
        ledger.add.assert_not_called()
        ledger.commit.assert_not_awaited()
        return

    state = await ai_quota.check_and_increment(
        ledger,
        AIFeatureKey.cv_generator,
        user_id=17,
        units=2,
        commit_with_caller=queued,
    )
    ledger.add.assert_called_once()
    operation = ledger.add.call_args.args[0]
    assert operation.units == 2
    assert operation.actor_key == "user:17"
    assert operation.id == state.operation_id
    assert state.used == 10
    if queued:
        factory.assert_not_called()
        ledger.commit.assert_not_awaited()
        ledger.flush.assert_awaited_once()
    else:
        ledger.commit.assert_awaited_once()
