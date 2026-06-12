"""Unit tests for the AssemblyAI client — no network, no DB.

The load-bearing assertion is the EU AI Act guard: the transcription request
must NEVER carry ``sentiment_analysis`` (or any affect feature). Also pins the
EU endpoint, Polish language code, and the dual-channel / speaker-labels split.
"""

from __future__ import annotations

import json

import httpx

from app.services.assemblyai.client import AssemblyAIClient, AssemblyAIConfig


def _make_client(handler) -> AssemblyAIClient:
    cfg = AssemblyAIConfig(base_url="https://api.eu.assemblyai.com", api_key="k-test")
    client = AssemblyAIClient(cfg)
    # Bypass __aenter__ and inject a MockTransport-backed http client.
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


async def test_submit_transcription_is_polish_and_never_sentiment():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "t1", "status": "queued"})

    client = _make_client(handler)
    transcript_id = await client.submit_transcription(
        "https://upload/audio", language_code="pl"
    )
    await client._http.aclose()

    assert transcript_id == "t1"
    body = captured["body"]
    assert body["language_code"] == "pl"
    assert body.get("speaker_labels") is True
    # The whole point — emotion inference is banned in recruitment (AI Act).
    assert "sentiment_analysis" not in body
    assert "auto_highlights" not in body  # no affect-adjacent features either
    assert captured["url"].startswith("https://api.eu.assemblyai.com")
    assert captured["auth"] == "k-test"


async def test_dual_channel_excludes_speaker_labels_and_sentiment():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "t2"})

    client = _make_client(handler)
    await client.submit_transcription("https://upload/a", dual_channel=True)
    await client._http.aclose()

    body = captured["body"]
    assert body["dual_channel"] is True
    assert "speaker_labels" not in body
    assert "sentiment_analysis" not in body


async def test_upload_returns_upload_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/upload"
        assert request.content == b"audio-bytes"
        return httpx.Response(200, json={"upload_url": "https://cdn/eu/abc"})

    client = _make_client(handler)
    url = await client.upload(b"audio-bytes")
    await client._http.aclose()

    assert url == "https://cdn/eu/abc"


async def test_retries_then_raises_on_persistent_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    cfg = AssemblyAIConfig(
        base_url="https://api.eu.assemblyai.com", api_key="k", max_retries=0
    )
    client = AssemblyAIClient(cfg)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        raised = False
        try:
            await client.get_transcription("tX")
        except Exception:  # AssemblyAIError
            raised = True
        assert raised
        assert calls["n"] == 1  # max_retries=0 → exactly one attempt
    finally:
        await client._http.aclose()
