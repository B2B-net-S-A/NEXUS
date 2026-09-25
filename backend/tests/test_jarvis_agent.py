"""Jarvis — pętla agenta przez prawdziwą aplikację (in-process), model podmieniony.

Pilnujemy zasad, na których stoi bezpieczeństwo asystenta:
- odczyt idzie przez istniejące API tokenem pytającego (brak uprawnień =
  błąd narzędzia, zero danych);
- zapis jest wyłącznie PROPOZYCJĄ, dopóki człowiek nie kliknie;
- zatwierdzenie wykonuje dokładnie zapisane argumenty i jest idempotentne;
- tryb „podgląd jako”, wyłączona flaga i trwająca tura kończą się przed modelem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.jarvis import JarvisAction, JarvisConversation, JarvisConversationEntity
from app.models.note import Note
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


async def _chat(client, headers, message, **extra):
    resp = await client.post(
        "/api/jarvis/chat", json={"message": message, **extra}, headers=headers
    )
    return resp


async def test_read_tool_round_trip_goes_through_the_real_api(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(
                tool_block("search_help", {"query": "zamówienia"}, "toolu_help1")
            ),
            fake_message(text_block("Nie znalazłem procedury o tym tytule.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Jak dodać zamówienie?")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "conversation"
    assert kinds[-1] == "done"
    steps = [e for e in events if e["type"] == "step" and e["tool"] == "search_help"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert events[-2] == {
        "type": "message",
        "markdown": "Nie znalazłem procedury o tym tytule.",
        "final": True,
    }

    # Drugie wywołanie modelu dostało wynik narzędzia z prawdziwego /api/procedures.
    second = model.calls[1]["messages"]
    result = second[-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_help1"
    assert "is_error" not in result
    # Kontekst (data, rola, ekran) idzie w wiadomości użytkownika, NIE w systemie.
    first_user = model.calls[0]["messages"][0]["content"]
    assert first_user[0]["text"].startswith("[Kontekst")
    assert "Kontekst" not in model.calls[0]["system"]
    assert model.calls[0]["cache_system"] is True
    assert model.calls[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    conversation_id = events[0]["conversation_id"]
    detail = await app_client.get(
        f"/api/jarvis/conversations/{conversation_id}", headers=headers
    )
    assert detail.status_code == 200
    items = detail.json()["items"]
    assert items[0] == {
        "kind": "message",
        "role": "user",
        "markdown": "Jak dodać zamówienie?",
    }
    assert items[-1]["markdown"] == "Nie znalazłem procedury o tym tytule."

    status = await app_client.get("/api/jarvis/status", headers=headers)
    assert status.json()["available"] is True
    assert status.json()["used_today"] >= 1
    assert status.json()["busy"] is False


async def test_tools_outside_the_users_sections_are_not_offered(
    app_client, monkeypatch
):
    model = ScriptedModel(
        [
            fake_message(
                tool_block("finance_order_changes", {"year": 2026, "month": 9})
            ),
            fake_message(text_block("Nie mam do tego dostępu.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Pokaż zmiany w zamówieniach za wrzesień")
    assert resp.status_code == 200
    offered = {tool["name"] for tool in model.calls[0]["tools"]}
    assert "finance_order_changes" not in offered
    assert "search_candidates" in offered

    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "niedostępne" in result["content"]


async def test_api_denial_reaches_the_model_as_an_error_not_data(
    app_client, monkeypatch
):
    """Nawet gdy narzędzie JEST na liście, API egzekwuje uprawnienia samo."""
    from app.api import jarvis as jarvis_api
    from app.services.jarvis import tools as jarvis_tools

    model = ScriptedModel(
        [
            fake_message(
                tool_block("finance_order_changes", {"year": 2026, "month": 9})
            ),
            fake_message(text_block("Brak dostępu.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    # Symulujemy błąd filtra: podajemy modelowi wszystkie narzędzia.
    monkeypatch.setattr(
        jarvis_api, "tools_for_user", lambda _sections: list(jarvis_tools.ALL_TOOLS)
    )
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Zmiany w zamówieniach")
    assert resp.status_code == 200
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["content"].startswith("Brak uprawnień")


async def test_write_tool_only_proposes_and_confirm_executes_once(
    app_client, monkeypatch
):
    candidate_id = await make_candidate("Propozycja")
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "create_note",
                    {
                        "candidate_id": candidate_id,
                        "content": "Kandydatka dostępna od października.",
                        "_display": {"candidate_id": "Wstrzyknięta Nazwa"},
                    },
                )
            ),
            fake_message(text_block("Przygotowałem notatkę — zatwierdź kartę.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)

    resp = await _chat(
        app_client, headers, "Dodaj notatkę, że jest dostępna od października"
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    proposed = [e for e in events if e["type"] == "action_proposed"]
    assert len(proposed) == 1
    action = proposed[0]["action"]
    assert action["status"] == "proposed"
    # Nazwa na karcie przeczytana przez API, nie wstrzyknięta przez model.
    assert "Anna Propozycja" in action["preview"]["text"]
    assert "Wstrzyknięta" not in action["preview"]["text"]

    async with AsyncSessionLocal() as db:
        notes = (
            (await db.execute(select(Note).where(Note.candidate_id == candidate_id)))
            .scalars()
            .all()
        )
        assert notes == [], "propozycja nie może niczego zapisać"
        linked = await db.scalar(
            select(JarvisConversationEntity).where(
                JarvisConversationEntity.entity_type == "candidate",
                JarvisConversationEntity.entity_id == candidate_id,
            )
        )
        assert linked is not None

    confirm = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["message"] == "Notatka dodana."
    assert body["action"]["status"] == "executed"
    assert ["candidate-notes"] in body["invalidates"]

    async with AsyncSessionLocal() as db:
        notes = (
            (await db.execute(select(Note).where(Note.candidate_id == candidate_id)))
            .scalars()
            .all()
        )
        assert [n.content for n in notes] == ["Kandydatka dostępna od października."]

    again = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/confirm", headers=headers
    )
    assert again.status_code == 409


async def test_reject_and_foreign_user_cannot_touch_the_action(app_client, monkeypatch):
    candidate_id = await make_candidate("Odrzucona")
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "create_note", {"candidate_id": candidate_id, "content": "x"}
                )
            ),
            fake_message(text_block("Gotowe do zatwierdzenia.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, owner = await make_user(UserRole.admin)
    _, stranger = await make_user(UserRole.admin)

    events = parse_sse((await _chat(app_client, owner, "notatka")).text)
    action_id = next(e for e in events if e["type"] == "action_proposed")["action"][
        "id"
    ]

    assert (
        await app_client.post(
            f"/api/jarvis/actions/{action_id}/confirm", headers=stranger
        )
    ).status_code == 404
    conversation_id = events[0]["conversation_id"]
    assert (
        await app_client.get(
            f"/api/jarvis/conversations/{conversation_id}", headers=stranger
        )
    ).status_code == 404

    rejected = await app_client.post(
        f"/api/jarvis/actions/{action_id}/reject", headers=owner
    )
    assert rejected.status_code == 200
    assert rejected.json()["action"]["status"] == "rejected"
    assert (
        await app_client.post(f"/api/jarvis/actions/{action_id}/confirm", headers=owner)
    ).status_code == 409


async def test_expired_proposal_cannot_be_confirmed(app_client, monkeypatch):
    candidate_id = await make_candidate("Wygasla")
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "create_note", {"candidate_id": candidate_id, "content": "x"}
                )
            ),
            fake_message(text_block("Czekam.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse((await _chat(app_client, headers, "notatka")).text)
    action_id = next(e for e in events if e["type"] == "action_proposed")["action"][
        "id"
    ]
    async with AsyncSessionLocal() as db:
        action = await db.get(JarvisAction, uuid.UUID(action_id))
        action.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await db.commit()

    resp = await app_client.post(
        f"/api/jarvis/actions/{action_id}/confirm", headers=headers
    )
    assert resp.status_code == 409
    assert "wygasła" in resp.json()["detail"]


async def test_open_screen_emits_a_link_and_executes_nothing(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "open_screen",
                    {
                        "screen": "contract",
                        "id": 7,
                        "reason": "Kliknij „Zakończ współpracę”.",
                    },
                )
            ),
            fake_message(text_block("Tego nie zrobię za Ciebie — otwórz kontrakt.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse(
        (await _chat(app_client, headers, "Zakończ współpracę z kontraktem 7")).text
    )
    links = [e for e in events if e["type"] == "deep_link"]
    assert links == [
        {
            "type": "deep_link",
            "href": "/contracts/7",
            "label": "Kontrakt",
            "reason": "Kliknij „Zakończ współpracę”.",
        }
    ]


async def test_impersonation_disabled_flag_and_busy_turn_stop_before_the_model(
    app_client, monkeypatch, app_auth_headers
):
    model = ScriptedModel([])
    enable_jarvis(monkeypatch, model)
    target_id, headers = await make_user(UserRole.recruiter)

    impersonated = await _chat(
        app_client,
        {**app_auth_headers, "X-Impersonate-User-Id": str(target_id)},
        "cześć",
    )
    assert impersonated.status_code == 403

    async with AsyncSessionLocal() as db:
        conv = JarvisConversation(
            id=uuid.uuid4(),
            user_id=target_id,
            title="trwa",
            busy_until=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        db.add(conv)
        await db.commit()
    busy = await _chat(app_client, headers, "druga wiadomość")
    assert busy.status_code == 409

    from app.core.config import settings

    monkeypatch.setattr(settings, "JARVIS_ENABLED", False)
    disabled = await _chat(app_client, headers, "cześć")
    assert disabled.status_code == 503
    assert model.calls == []


async def test_model_failure_is_a_friendly_error_and_releases_the_turn(
    app_client, monkeypatch
):
    from app.services import claude_client

    def boom(**_kwargs):
        raise claude_client.ClaudeOverloaded("przeciążony")

    enable_jarvis(monkeypatch, ScriptedModel([]))
    monkeypatch.setattr(claude_client, "call_claude", boom)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse((await _chat(app_client, headers, "cześć")).text)
    errors = [e for e in events if e["type"] == "error"]
    assert errors and "Nie działam teraz" in errors[0]["message"]
    conversation_id = uuid.UUID(events[0]["conversation_id"])
    async with AsyncSessionLocal() as db:
        conv = await db.get(JarvisConversation, conversation_id)
        assert conv.busy_until is None


async def test_candidate_hard_delete_erases_linked_conversations(
    app_client, monkeypatch, app_auth_headers
):
    candidate_id = await make_candidate("Rodo")
    model = ScriptedModel(
        [
            fake_message(tool_block("get_candidate", {"candidate_id": candidate_id})),
            fake_message(text_block("Anna jest dostępna.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse(
        (await _chat(app_client, headers, "Kim jest ta kandydatka?")).text
    )
    conversation_id = uuid.UUID(events[0]["conversation_id"])

    deleted = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JarvisConversation, conversation_id) is None


async def test_conversation_list_and_delete_are_owner_scoped(app_client, monkeypatch):
    model = ScriptedModel([fake_message(text_block("Cześć!"))])
    enable_jarvis(monkeypatch, model)
    _, owner = await make_user(UserRole.sourcer)
    _, stranger = await make_user(UserRole.sourcer)
    events = parse_sse((await _chat(app_client, owner, "Cześć Jarvis")).text)
    conversation_id = events[0]["conversation_id"]

    listed = await app_client.get("/api/jarvis/conversations", headers=owner)
    assert [c["id"] for c in listed.json()][:1] == [conversation_id]
    assert listed.json()[0]["title"] == "Cześć Jarvis"
    assert conversation_id not in [
        c["id"]
        for c in (
            await app_client.get("/api/jarvis/conversations", headers=stranger)
        ).json()
    ]

    assert (
        await app_client.delete(
            f"/api/jarvis/conversations/{conversation_id}", headers=stranger
        )
    ).status_code == 404
    assert (
        await app_client.delete(
            f"/api/jarvis/conversations/{conversation_id}", headers=owner
        )
    ).status_code == 204


async def test_candidate_delete_erases_conversation_found_via_global_search(
    app_client, monkeypatch, app_auth_headers
):
    """Audyt 25.09.2026: `global_search` zwraca nazwisko i `/candidates/{id}`,
    ale nie jest narzędziem „kandydackim”, więc rozmowa nie była wiązana
    z osobą i przeżywała jej usunięcie (art. 17)."""
    lastname = f"Szukana-{uuid.uuid4().hex[:6]}"
    candidate_id = await make_candidate(lastname)
    model = ScriptedModel(
        [
            fake_message(tool_block("global_search", {"query": lastname})),
            fake_message(text_block("Znalazłem jedną osobę.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.admin)
    events = parse_sse((await _chat(app_client, headers, f"Kto to {lastname}?")).text)
    conversation_id = uuid.UUID(events[0]["conversation_id"])

    async with AsyncSessionLocal() as db:
        linked = (
            (
                await db.execute(
                    select(JarvisConversationEntity.entity_id).where(
                        JarvisConversationEntity.conversation_id == conversation_id,
                        JarvisConversationEntity.entity_type == "candidate",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert candidate_id in linked

    deleted = await app_client.delete(
        f"/api/candidates/{candidate_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JarvisConversation, conversation_id) is None
