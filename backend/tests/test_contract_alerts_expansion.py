"""Smoke tests for contract_alerts expansion — 90d threshold + equipment + client order."""

from app.tasks.contract_alerts import THRESHOLDS_DAYS


def test_90d_threshold_present():
    assert 90 in THRESHOLDS_DAYS
    # Ordered from longest horizon to shortest is not required, but 7 should
    # remain the tightest threshold.
    assert 7 in THRESHOLDS_DAYS
    assert min(THRESHOLDS_DAYS) == 7
    assert max(THRESHOLDS_DAYS) == 90


def test_alerts_cycle_stats_keys_include_expansion():
    """run_contract_alerts_cycle should expose keys for the new triggers."""
    import asyncio

    from app.tasks.contract_alerts import run_contract_alerts_cycle

    stats = asyncio.get_event_loop().run_until_complete(run_contract_alerts_cycle())
    # Only the *shape* is asserted — actual counts depend on DB data.
    for key in (
        "promoted_ending",
        "promoted_ended",
        "notifications_created",
        "compliance_alerts",
        "equipment_return_alerts",
        "client_order_alerts",
        "slack_sent",
    ):
        assert key in stats
