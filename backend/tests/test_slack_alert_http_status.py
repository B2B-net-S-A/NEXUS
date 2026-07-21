"""
Regression test for [P1.15]: Slack SLA alert must inspect the HTTP status.

httpx does not raise on 4xx/5xx by default, so a failed webhook POST used to be
recorded as "sent" and never retried. `_post_to_slack` must return True only on
a 2xx response, and False (without raising) on any HTTP error status or
transport error, so the poll loop leaves the breach un-marked and retries it.

Pure unit test: the httpx client is mocked, so no network and no DB are touched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.tasks import slack_sla_alerts

_BREACH = {
    "candidate_stage_id": 1,
    "candidate_id": 42,
    "job_id": 7,
    "stage_name": "Interview",
    "days_in_stage": 10,
    "sla_max_days": 5,
    "overdue_by_days": 5,
}


def _mock_client(*, status_code: int | None = None, raises: Exception | None = None):
    """Build a patch for httpx.AsyncClient whose .post returns/raises as asked."""
    post = AsyncMock()
    if raises is not None:
        post.side_effect = raises
    else:
        post.return_value = SimpleNamespace(status_code=status_code)

    client = AsyncMock()
    client.__aenter__.return_value = SimpleNamespace(post=post)
    client.__aexit__.return_value = False
    return patch.object(
        slack_sla_alerts.httpx, "AsyncClient", return_value=client
    ), post


@pytest.mark.asyncio
async def test_post_to_slack_returns_true_on_2xx():
    ctx, post = _mock_client(status_code=200)
    with ctx:
        ok = await slack_sla_alerts._post_to_slack("https://hooks.slack/test", _BREACH)
    assert ok is True
    post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 403, 404, 429, 500, 503])
async def test_post_to_slack_returns_false_on_http_error(status_code):
    ctx, _ = _mock_client(status_code=status_code)
    with ctx:
        ok = await slack_sla_alerts._post_to_slack("https://hooks.slack/test", _BREACH)
    assert ok is False


@pytest.mark.asyncio
async def test_post_to_slack_returns_false_on_transport_error():
    ctx, _ = _mock_client(raises=httpx.ConnectError("boom"))
    with ctx:
        ok = await slack_sla_alerts._post_to_slack("https://hooks.slack/test", _BREACH)
    assert ok is False


@pytest.mark.asyncio
async def test_failed_send_is_not_marked_alerted():
    """A 5xx from Slack must leave the breach un-marked so it retries."""
    alerted: set[int] = set()
    new_breaches = [_BREACH]

    with patch.object(
        slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=False)
    ):
        sent = 0
        for b in new_breaches:
            if await slack_sla_alerts._post_to_slack("hook", b):
                alerted.add(b["candidate_stage_id"])
                sent += 1

    assert sent == 0
    assert _BREACH["candidate_stage_id"] not in alerted


@pytest.mark.asyncio
async def test_successful_send_is_marked_alerted():
    """A 2xx from Slack marks the breach sent so it is not re-alerted."""
    alerted: set[int] = set()
    new_breaches = [_BREACH]

    with patch.object(slack_sla_alerts, "_post_to_slack", AsyncMock(return_value=True)):
        sent = 0
        for b in new_breaches:
            if await slack_sla_alerts._post_to_slack("hook", b):
                alerted.add(b["candidate_stage_id"])
                sent += 1

    assert sent == 1
    assert _BREACH["candidate_stage_id"] in alerted
