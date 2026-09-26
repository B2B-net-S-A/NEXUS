"""A calendar event may precede its Teams meeting in Graph."""

from unittest.mock import AsyncMock

import pytest

from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError


class LookupClient:
    def __init__(self, responses):
        self.get = AsyncMock(side_effect=responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_eventual_meeting_is_found_before_recording_setup(monkeypatch):
    client = LookupClient([{"value": []}, {"value": [{"id": "meeting"}]}])
    sleep = AsyncMock()
    monkeypatch.setattr(teams_prep_graph, "_client", lambda: client)
    monkeypatch.setattr(teams_prep_graph.asyncio, "sleep", sleep)

    assert await teams_prep_graph.find_online_meeting("organizer", "join'url") == "meeting"
    assert client.get.await_count == 2
    sleep.assert_awaited_once_with(1)
    assert client.get.call_args.kwargs["params"] == {
        "$filter": "JoinWebUrl eq 'join''url'"
    }


@pytest.mark.asyncio
async def test_missing_meeting_has_bounded_wait(monkeypatch):
    client = LookupClient([{"value": []}] * 6)
    sleep = AsyncMock()
    monkeypatch.setattr(teams_prep_graph, "_client", lambda: client)
    monkeypatch.setattr(teams_prep_graph.asyncio, "sleep", sleep)

    assert await teams_prep_graph.find_online_meeting("organizer", "url") is None
    assert client.get.await_count == 6
    assert sleep.await_count == 5


@pytest.mark.asyncio
async def test_access_denied_is_not_retried(monkeypatch):
    client = LookupClient([GraphRequestError(403, {"error": "denied"})])
    sleep = AsyncMock()
    monkeypatch.setattr(teams_prep_graph, "_client", lambda: client)
    monkeypatch.setattr(teams_prep_graph.asyncio, "sleep", sleep)

    with pytest.raises(GraphRequestError):
        await teams_prep_graph.find_online_meeting("organizer", "url")
    assert client.get.await_count == 1
    sleep.assert_not_awaited()
