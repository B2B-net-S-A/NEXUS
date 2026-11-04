"""Jarvis: szkic maila do kandydata (27.10.2026).

Prośba „wyślij mu maila” kończyła się przyciskiem do profilu. Teraz Jarvis
pisze szkic, a człowiek wysyła go z okna maila NEXUSA. Adres i nazwisko
pochodzą z odczytu uprawnieniami pytającego, nie ze słów modelu.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.user import UserRole
from tests._jarvis_helpers import (
    ScriptedModel,
    enable_jarvis,
    fake_message,
    make_candidate,
    make_user,
    parse_sse,
    text_block,
    tool_block,
)

pytestmark = pytest.mark.asyncio


def _model(candidate_id: int) -> ScriptedModel:
    return ScriptedModel(
        [
            fake_message(
                tool_block(
                    "draft_email",
                    {
                        "candidate_id": candidate_id,
                        "subject": "Aktualne CV",
                        "body": "Dzień dobry,\nczy może Pan przesłać aktualne CV?",
                    },
                    "toolu_mail",
                )
            ),
            fake_message(text_block("Szkic gotowy.")),
        ]
    )


async def test_draft_carries_address_read_by_the_server(app_client, monkeypatch):
    candidate_id = await make_candidate("Szkicowa")
    model = _model(candidate_id)
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": "napisz mu maila"}, headers=headers
    )
    events = parse_sse(resp.text)
    drafts = [e["draft"] for e in events if e["type"] == "mail_draft"]
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft["candidate_id"] == candidate_id
    assert draft["email"].startswith("jarvis-cand-")
    assert draft["candidate_name"].startswith("Anna Szkicowa")
    assert draft["subject"] == "Aktualne CV"
    result = model.calls[1]["messages"][-1]["content"][0]
    assert "NIC nie zostało wysłane" in result["content"]

    detail = await app_client.get(
        f"/api/jarvis/conversations/{events[0]['conversation_id']}", headers=headers
    )
    rebuilt = [i["draft"] for i in detail.json()["items"] if i["kind"] == "mail_draft"]
    assert rebuilt == [
        {"candidate_id": candidate_id, "subject": "Aktualne CV", "body": draft["body"]}
    ]


async def test_no_email_goes_back_to_the_model_without_a_card(app_client, monkeypatch):
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Bez", lastname=f"Adresu-{uuid.uuid4().hex[:6]}", email=None
        )
        db.add(cand)
        await db.commit()
        candidate_id = cand.id
    model = _model(candidate_id)
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": "napisz mu maila"}, headers=headers
    )
    events = parse_sse(resp.text)
    assert not [e for e in events if e["type"] == "mail_draft"]
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "nie ma adresu" in result["content"]
