"""Jarvis — runda 8 audytu (26.09.2026), ścieżki z bazą.

- R8-N1-1: czat i potwierdzenie akcji oddają połączenie requestu do puli
  przed długą pracą (tura SSE, wywołanie in-process);
- R8-N1-4: dwie karty „zapamiętaj” zatwierdzone po kolei zostawiają obie
  notatki;
- R8-N1-5: akcja nigdy nie zostaje w ``confirmed`` — błąd wykonania kończy
  się ``failed``, a osierocone ``confirmed`` (deploy w trakcie) dostaje
  „nie wiadomo” i notatkę w rozmowie;
- R8-N1-7: start procesu zdejmuje blokady tur zostawione przez ubitą turę.

Każdy test zostawia stan zakończony (żadnej wiszącej blokady ani akcji
``confirmed``) — baza CI jest wspólna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.jarvis import JarvisAction, JarvisConversation, JarvisMessage
from app.models.user import UserRole
from app.services.jarvis import store
from tests._jarvis_helpers import (
    ScriptedModel,
    enable_jarvis,
    fake_message,
    make_user,
    parse_sse,
    text_block,
    tool_block,
)

pytestmark = pytest.mark.asyncio


def _spy_release(monkeypatch) -> list[bool]:
    from app.api import jarvis as jarvis_api
    from app.core.database import release_idle_connection

    released: list[bool] = []

    async def _spy(db):
        released.append(await release_idle_connection(db))
        return released[-1]

    monkeypatch.setattr(jarvis_api, "release_idle_connection", _spy)
    return released


async def test_chat_returns_the_request_connection_before_the_turn(
    app_client, monkeypatch
) -> None:
    enable_jarvis(monkeypatch, ScriptedModel([fake_message(text_block("Cześć."))]))
    released = _spy_release(monkeypatch)
    _, headers = await make_user(UserRole.recruiter)

    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": "cześć"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert any(e["type"] == "message" for e in parse_sse(resp.text))
    # True = transakcja requestu (auth, snapshot uprawnień) zamknięta przed
    # turą — połączenie wróciło do puli, a nie czekało „idle in transaction”.
    assert released == [True]


async def test_confirm_returns_the_request_connection_before_executing(
    app_client, monkeypatch
) -> None:
    from app.api import jarvis as jarvis_api
    from app.services.jarvis.actions import ActionOutcome

    enable_jarvis(monkeypatch, ScriptedModel([]))
    released = _spy_release(monkeypatch)
    seen: list[list[bool]] = []

    async def _confirm(action_id, *, user_id, identity):
        seen.append(list(released))
        return ActionOutcome(action={"id": str(action_id)}, message="ok")

    monkeypatch.setattr(jarvis_api.jarvis_actions, "confirm_action", _confirm)
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.post(
        f"/api/jarvis/actions/{uuid.uuid4()}/confirm", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert seen == [[True]], "połączenie oddane PRZED wykonaniem akcji"


async def test_two_memory_cards_confirmed_in_turn_keep_both_notes(
    app_client, monkeypatch
) -> None:
    model = ScriptedModel(
        [
            fake_message(
                tool_block("remember_preference", {"text": "Odpowiadaj krócej"}),
                tool_block("remember_preference", {"text": "Moi klienci to PKO"}),
            ),
            fake_message(text_block("Zatwierdź obie karty.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    events = parse_sse(
        (
            await app_client.post(
                "/api/jarvis/chat",
                json={"message": "zapamiętaj dwie rzeczy"},
                headers=headers,
            )
        ).text
    )
    actions = [e["action"]["id"] for e in events if e["type"] == "action_proposed"]
    assert len(actions) == 2
    for action_id in actions:
        resp = await app_client.post(
            f"/api/jarvis/actions/{action_id}/confirm", headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["action"]["status"] == "executed"

    prefs = await app_client.get("/api/users/me/preferences", headers=headers)
    assert prefs.status_code == 200, prefs.text
    assert prefs.json()["jarvis"]["notes"] == [
        "Odpowiadaj krócej",
        "Moi klienci to PKO",
    ]


async def _conversation_with_action(user_id: int, args: dict) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(JarvisConversation(id=conversation_id, user_id=user_id, title="r8"))
        await db.commit()
    return await store.create_action(
        conversation_id=conversation_id,
        user_id=user_id,
        tool_use_id=f"toolu_{uuid.uuid4().hex[:10]}",
        tool_name="create_note",
        args=args,
        preview={"text": "Dodam notatkę"},
    )


async def test_invalid_stored_args_finish_the_action_as_failed(
    app_client, monkeypatch
) -> None:
    enable_jarvis(monkeypatch, ScriptedModel([]))
    user_id, headers = await make_user(UserRole.recruiter)
    # Args sprzed zmiany schematu (np. po deployu): build nie przejdzie.
    action_id = await _conversation_with_action(
        user_id, {"candidate_id": "nie-liczba", "content": "x"}
    )

    resp = await app_client.post(
        f"/api/jarvis/actions/{action_id}/confirm", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"]["status"] == "failed"
    async with AsyncSessionLocal() as db:
        action = await db.get(JarvisAction, action_id)
        assert action.status == "failed"
        assert not (action.result or {}).get("uncertain")


async def test_crash_after_the_call_marks_the_action_uncertain(
    app_client, monkeypatch
) -> None:
    from app.services.jarvis import actions as jarvis_actions

    enable_jarvis(monkeypatch, ScriptedModel([]))
    user_id, headers = await make_user(UserRole.recruiter)
    action_id = await _conversation_with_action(
        user_id, {"candidate_id": 1, "content": "x"}
    )

    async def _boom(self, spec):
        raise RuntimeError("połączenie zerwane w trakcie")

    monkeypatch.setattr(jarvis_actions.JarvisTransport, "call", _boom)
    resp = await app_client.post(
        f"/api/jarvis/actions/{action_id}/confirm", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["action"]
    assert body["status"] == "failed"
    assert body["result"]["uncertain"] is True


async def test_orphaned_confirmed_action_gets_uncertain_and_a_note() -> None:
    user_id, _headers = await make_user(UserRole.recruiter)
    action_id = await _conversation_with_action(
        user_id, {"candidate_id": 1, "content": "x"}
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(JarvisAction)
            .where(JarvisAction.id == action_id)
            .values(
                status="confirmed",
                decided_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        await db.commit()

    await store.expire_stale_actions(15)

    async with AsyncSessionLocal() as db:
        action = await db.get(JarvisAction, action_id)
        assert action.status == "failed"
        assert action.result["uncertain"] is True
        notes = (
            (
                await db.execute(
                    select(JarvisMessage.content).where(
                        JarvisMessage.conversation_id == action.conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any(
        block.get("text", "").startswith("[Wynik akcji] Wykonanie przerwane")
        for content in notes
        for block in content
    )


async def test_restart_releases_turn_locks_left_by_a_killed_turn(
    app_client, monkeypatch
) -> None:
    enable_jarvis(monkeypatch, ScriptedModel([fake_message(text_block("Jestem."))]))
    user_id, headers = await make_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add(
            JarvisConversation(
                id=uuid.uuid4(),
                user_id=user_id,
                title="ubita deployem",
                busy_until=datetime.now(timezone.utc) + timedelta(seconds=150),
            )
        )
        await db.commit()

    assert await store.release_turns_after_restart() >= 1

    resp = await app_client.post(
        "/api/jarvis/chat", json={"message": "jesteś?"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
