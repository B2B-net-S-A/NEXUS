"""Graph tenant controls: recover a transcript when speaker attribution is off."""

from __future__ import annotations

import pytest

from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError


class FakeClient:
    def __init__(self, first_error: GraphRequestError | None = None) -> None:
        self.first_error = first_error
        self.requests: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def download(self, url: str, *, headers: dict | None = None) -> bytes:
        self.requests.append((url, headers))
        if len(self.requests) == 1 and self.first_error:
            raise self.first_error
        return b"00:00:01.000 --> 00:00:02.000\nHello.\n"


@pytest.mark.asyncio
async def test_transcript_without_speaker_attribution_uses_plain_format(monkeypatch):
    client = FakeClient(
        GraphRequestError(
            403,
            {"error": {"innerError": {"code": "SpeakerAttributionNotAllowed"}}},
        )
    )
    monkeypatch.setattr(teams_prep_graph, "_client", lambda: client)

    content = await teams_prep_graph.transcript_vtt("user", "meeting", "transcript")

    assert "Hello." in content
    assert client.requests[0][0].endswith("/content?$format=text/vtt")
    assert client.requests[1] == (
        "/users/user/onlineMeetings/meeting/transcripts/transcript/content",
        {"Accept": "application/vnd.microsoft.graph.transcript+text"},
    )


@pytest.mark.asyncio
async def test_disabled_transcript_api_is_not_retried_as_plain_text(monkeypatch):
    client = FakeClient(
        GraphRequestError(
            403,
            {"error": {"innerError": {"code": "GraphAccessToTranscriptsDisabled"}}},
        )
    )
    monkeypatch.setattr(teams_prep_graph, "_client", lambda: client)

    with pytest.raises(GraphRequestError):
        await teams_prep_graph.transcript_vtt("user", "meeting", "transcript")
    assert len(client.requests) == 1
