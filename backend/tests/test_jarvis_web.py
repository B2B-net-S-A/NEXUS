"""Jarvis — tryb internetu (21.09.2026): internet ALBO baza, nigdy oba.

Tura z przełącznikiem dostaje wyszukiwarkę Anthropic, ale NIE dostaje narzędzi
z danymi NEXUSA, historii rozmowy ani ID rekordu z ekranu — dane z bazy nie
mają jak trafić do zapytania wysłanego na zewnątrz.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.user import UserRole
from tests._jarvis_helpers import (
    ScriptedModel,
    enable_jarvis,
    fake_message,
    make_user,
    parse_sse,
    text_block,
)

pytestmark = pytest.mark.asyncio


def web_answer(text: str, url: str = "https://example.org/raport") -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="server_tool_use",
                id="srv_1",
                name="web_search",
                input={"query": "stawki senior go"},
            ),
            SimpleNamespace(
                type="web_search_tool_result",
                tool_use_id="srv_1",
                content=[
                    {"type": "web_search_result", "url": url, "title": "Raport płac IT"}
                ],
            ),
            SimpleNamespace(
                type="text",
                text=text,
                citations=[
                    {
                        "type": "web_search_result_location",
                        "url": url,
                        "title": "Raport płac IT",
                    }
                ],
            ),
        ],
        stop_reason="end_turn",
        id="msg_web",
        usage=None,
    )


async def test_web_turn_has_only_search_and_no_nexus_data(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(text_block("Najpierw zwykła odpowiedź z bazy.")),
            web_answer("Widełki senior Go w Warszawie to ok. 180–230 zł/h."),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    first = parse_sse(
        (
            await app_client.post(
                "/api/jarvis/chat",
                json={
                    "message": "Pytanie o bazę",
                    "screen": {
                        "path": "/candidates/5",
                        "entity": {"type": "candidate", "id": 5},
                    },
                },
                headers=headers,
            )
        ).text
    )
    conversation_id = first[0]["conversation_id"]

    resp = await app_client.post(
        "/api/jarvis/chat",
        json={
            "message": "Jakie są stawki senior Go w Warszawie?",
            "conversation_id": conversation_id,
            "web": True,
            "screen": {
                "path": "/candidates/5",
                "entity": {"type": "candidate", "id": 5},
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    events = parse_sse(resp.text)

    call = model.calls[1]
    names = {t.get("name") for t in call["tools"]}
    assert names == {"web_search", "search_help", "get_help_article", "open_screen"}
    web_tool = next(t for t in call["tools"] if t.get("name") == "web_search")
    assert web_tool["type"].startswith("web_search_")
    assert web_tool["max_uses"] == settings.JARVIS_WEB_MAX_SEARCHES_PER_TURN
    # Bez wcześniejszej rozmowy i bez ID rekordu z ekranu.
    assert len(call["messages"]) == 1
    sent = " ".join(b["text"] for b in call["messages"][0]["content"])
    assert "Pytanie o bazę" not in sent
    assert "#5" not in sent and "/candidates/5" not in sent
    assert "[Tryb internetu]" in sent

    steps = [e for e in events if e["type"] == "step" and e["tool"] == "web_search"]
    assert steps and "stawki senior go" in steps[0]["label"]
    sources = [e for e in events if e["type"] == "sources"]
    assert sources == [
        {
            "type": "sources",
            "items": [{"url": "https://example.org/raport", "title": "Raport płac IT"}],
        }
    ]

    detail = (
        await app_client.get(
            f"/api/jarvis/conversations/{conversation_id}", headers=headers
        )
    ).json()
    kinds = [i["kind"] for i in detail["items"]]
    assert "sources" in kinds
    assert not any(
        i.get("markdown", "").startswith("[Tryb internetu]") for i in detail["items"]
    )

    status = (await app_client.get("/api/jarvis/status", headers=headers)).json()
    assert status["web_enabled"] is True
    assert status["web_used_today"] == 1
    assert status["used_today"] == 2


async def test_sources_block_never_reaches_the_model(app_client, monkeypatch):
    """Zapisane źródła są dla interfejsu — następna tura nie może ich wysłać do API."""
    model = ScriptedModel(
        [web_answer("Odpowiedź z sieci."), fake_message(text_block("OK"))]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse(
        (
            await app_client.post(
                "/api/jarvis/chat",
                json={"message": "sieć", "web": True},
                headers=headers,
            )
        ).text
    )
    cid = events[0]["conversation_id"]
    await app_client.post(
        "/api/jarvis/chat",
        json={"message": "dalej", "conversation_id": cid},
        headers=headers,
    )
    types = {b["type"] for m in model.calls[1]["messages"] for b in m["content"]}
    assert "x_sources" not in types


async def test_pause_turn_continues_with_raw_blocks(app_client, monkeypatch):
    class Block(SimpleNamespace):
        def model_dump(self, exclude_none: bool = True):
            return dict(vars(self))

    paused = SimpleNamespace(
        content=[
            Block(
                type="server_tool_use",
                id="srv_1",
                name="web_search",
                input={"query": "x"},
            )
        ],
        stop_reason="pause_turn",
        id="m1",
        usage=None,
    )
    model = ScriptedModel([paused, web_answer("Gotowe.")])
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse(
        (
            await app_client.post(
                "/api/jarvis/chat",
                json={"message": "sieć", "web": True},
                headers=headers,
            )
        ).text
    )
    assert any(e["type"] == "message" and e["markdown"] == "Gotowe." for e in events)
    continued = model.calls[1]["messages"]
    assert continued[-1]["role"] == "assistant"
    assert continued[-1]["content"][0]["type"] == "server_tool_use"


async def test_daily_web_limit_and_kill_switch(app_client, monkeypatch):
    enable_jarvis(monkeypatch, ScriptedModel([]))
    _, headers = await make_user(UserRole.recruiter)

    monkeypatch.setattr(settings, "JARVIS_WEB_DAILY_LIMIT", 0)
    limited = await app_client.post(
        "/api/jarvis/chat", json={"message": "x", "web": True}, headers=headers
    )
    assert limited.status_code == 429
    assert "limit" in limited.json()["detail"]

    monkeypatch.setattr(settings, "JARVIS_WEB_DAILY_LIMIT", 20)
    monkeypatch.setattr(settings, "JARVIS_WEB_ENABLED", False)
    off = await app_client.post(
        "/api/jarvis/chat", json={"message": "x", "web": True}, headers=headers
    )
    assert off.status_code == 503


def test_domain_lists_shape_the_search_tool(monkeypatch):
    from app.services.jarvis.web import collect_sources, web_tool_definition

    monkeypatch.setattr(
        settings, "JARVIS_WEB_ALLOWED_DOMAINS", "nofluffjobs.com, justjoin.it"
    )
    monkeypatch.setattr(settings, "JARVIS_WEB_BLOCKED_DOMAINS", "linkedin.com")
    tool = web_tool_definition()
    assert tool["allowed_domains"] == ["nofluffjobs.com", "justjoin.it"]
    assert "blocked_domains" not in tool

    monkeypatch.setattr(settings, "JARVIS_WEB_ALLOWED_DOMAINS", "")
    assert web_tool_definition()["blocked_domains"] == ["linkedin.com"]

    # Tylko http(s) — `javascript:` z wyniku nie trafi na listę źródeł.
    blocks = [
        {
            "type": "text",
            "citations": [
                {"url": "javascript:alert(1)"},
                {"url": "https://ok.pl", "title": "OK"},
            ],
        }
    ]
    assert collect_sources(blocks) == [{"url": "https://ok.pl", "title": "OK"}]
