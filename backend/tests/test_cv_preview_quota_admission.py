"""Podgląd dwóch wariantów jest zawsze dopuszczony i zawsze naliczony jako 2 jednostki.

NEXUS nie ma limitów AI (17.09.2026), więc „sprawdzenie pojemności przed zapisem"
zniknęło. Zostało to, na czym stoi raport zużycia: jedna operacja z `units=2`,
autor, identyfikator zwracany wołającemu i ta sama semantyka transakcji
(kolejka trwała zapisuje razem ze swoim zadaniem, reszta commituje osobno).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import database
from app.models.ai_feature import AIFeatureKey
from app.services import ai_quota


@pytest.mark.asyncio
@pytest.mark.parametrize("used", [0, 9, 10_000])
@pytest.mark.parametrize("queued", [False, True])
async def test_preview_pair_is_always_admitted_and_metered(monkeypatch, used, queued):
    monkeypatch.setattr(
        ai_quota,
        "get_feature_config",
        AsyncMock(return_value=SimpleNamespace(enabled=False, monthly_limit=10)),
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
    assert state.used == used + 2
    if queued:
        factory.assert_not_called()
        ledger.commit.assert_not_awaited()
        ledger.flush.assert_awaited_once()
    else:
        ledger.commit.assert_awaited_once()


def test_gate_module_no_longer_raises_quota_errors():
    """Strażnik: `raise AIQuotaExceeded` nie może wrócić do bramki dopuszczenia."""
    import inspect

    source = inspect.getsource(ai_quota.check_and_increment)
    assert "raise AIQuotaExceeded" not in source
    assert "get_master_enabled" not in source
