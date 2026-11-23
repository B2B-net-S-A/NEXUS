"""Jarvis: „Klient coś zmienił” — karta do okna w Profilu Championa (23.11.2026).

Jarvis NIC nie zapisuje: daje kartę z przyciskiem „Pokaż i popraw”, a listę
zmian przygotowuje i zapisuje okno na stronie rekrutacji. Kartę dostaje tylko
ktoś, kto redaguje tę rekrutację (`can_edit` z detalu). Dane fikcyjne.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.jarvis import agent
from app.services.jarvis.capabilities import WRITE
from app.services.jarvis.tools import TOOLS_BY_NAME, RequestSpec
from app.services.jarvis.transport import ToolResponse

TEXT = "Klient teraz wymaga Pythona jako musi mieć, SAFe odpada."


class _Transport:
    def __init__(self, response: ToolResponse) -> None:
        self.response = response
        self.calls: list[RequestSpec] = []

    async def call(self, spec: RequestSpec) -> ToolResponse:
        self.calls.append(spec)
        return self.response


def test_tool_only_proposes_and_is_listed_as_prepared_not_done():
    tool = TOOLS_BY_NAME["propose_client_change"]
    assert tool.tier == "link" and tool.undo is None
    assert tool.description.startswith("PROPONUJE")
    assert set(tool.input_schema["required"]) == {"job_id", "text", "summary"}
    assert any("propose_client_change" in tools for _label, tools in WRITE)


@pytest.mark.asyncio
async def test_editor_gets_a_card_with_text_and_nothing_is_written():
    transport = _Transport(
        ToolResponse(200, {"id": 42, "title": "Analityk danych", "can_edit": True})
    )
    events: list[dict[str, Any]] = []
    result = await agent._client_change(
        transport,
        {"job_id": 42, "text": TEXT, "summary": "+ Python (musi mieć), − SAFe"},
        "toolu_1",
        events,
    )
    assert [(c.method, c.path) for c in transport.calls] == [("GET", "/api/jobs/42")]
    assert events == [
        {
            "type": "client_change",
            "proposal": {
                "job_id": 42,
                "job_title": "Analityk danych",
                "text": TEXT,
                "summary": "+ Python (musi mieć), − SAFe",
            },
        }
    ]
    assert "NIC nie zostało zmienione" in result["content"]
    assert not result.get("is_error")


@pytest.mark.asyncio
async def test_person_who_cannot_edit_gets_no_card():
    transport = _Transport(ToolResponse(200, {"id": 42, "can_edit": False}))
    events: list[dict[str, Any]] = []
    result = await agent._client_change(
        transport, {"job_id": 42, "text": TEXT, "summary": ""}, "toolu_2", events
    )
    assert events == []
    assert result["is_error"] is True


@pytest.mark.asyncio
async def test_hidden_job_and_bad_args_get_no_card():
    events: list[dict[str, Any]] = []
    hidden = await agent._client_change(
        _Transport(ToolResponse(403, {"detail": "Brak dostępu"})),
        {"job_id": 42, "text": TEXT, "summary": ""},
        "toolu_3",
        events,
    )
    no_job = await agent._client_change(
        _Transport(ToolResponse(200, {})), {"text": TEXT}, "toolu_4", events
    )
    short = await agent._client_change(
        _Transport(ToolResponse(200, {"can_edit": True})),
        {"job_id": 42, "text": "Python"},
        "toolu_5",
        events,
    )
    assert events == []
    assert hidden["is_error"] and no_job["is_error"] and short["is_error"]


# ── Przez czat (z bazą) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_card_survives_in_history(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus
    from app.models.user import UserRole
    from tests._jarvis_helpers import (
        ScriptedModel,
        enable_jarvis,
        fake_message,
        make_user,
        parse_sse,
        text_block,
        tool_block,
    )

    async with AsyncSessionLocal() as db:
        from app.models.client import Client

        client = Client(name="Bank Przykładowy (Jarvis)")
        db.add(client)
        await db.flush()
        job = Job(
            title="Analityk danych (przykład)",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "propose_client_change",
                    {"job_id": job_id, "text": TEXT, "summary": "+ Python"},
                    "toolu_cc",
                )
            ),
            fake_message(text_block("Przygotowałem kartę.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": TEXT}, headers=headers
    )
    events = parse_sse(resp.text)
    cards = [e["proposal"] for e in events if e["type"] == "client_change"]
    assert [(c["job_id"], c["text"]) for c in cards] == [(job_id, TEXT)]

    detail = await app_client.get(
        f"/api/jarvis/conversations/{events[0]['conversation_id']}", headers=headers
    )
    rebuilt = [
        i["proposal"] for i in detail.json()["items"] if i["kind"] == "client_change"
    ]
    assert rebuilt == [{"job_id": job_id, "text": TEXT, "summary": "+ Python"}]
