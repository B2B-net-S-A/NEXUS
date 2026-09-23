"""Jarvis 2 (23.09.2026): pomoc na ekranie, „Zatrzymaj”, ucięte odpowiedzi,
nowe narzędzia, pamięć, telemetria i strumieniowanie tekstu.

Pętla przez prawdziwą aplikację (in-process), model podmieniony — jak
``test_jarvis_agent.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.jarvis import JarvisUiEvent
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

pytestmark = pytest.mark.asyncio


async def _chat(client, headers, message, **extra):
    return await client.post(
        "/api/jarvis/chat", json={"message": message, **extra}, headers=headers
    )


# ── A: „Zatrzymaj”, ucięta odpowiedź, open_screen bez id ────────────────────


async def test_cancel_stops_the_loop_before_the_next_model_call(
    app_client, monkeypatch
):
    from app.services.jarvis import agent

    model = ScriptedModel(
        [
            fake_message(
                tool_block("search_help", {"query": "zamówienia"}, "toolu_c1")
            ),
            fake_message(text_block("To nie powinno paść.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    flag = {"on": False}
    real_call = model.__call__

    def calling_then_cancel(**kwargs):
        response = real_call(**kwargs)
        flag["on"] = True  # użytkownik kliknął „Zatrzymaj” w trakcie kroku
        return response

    from app.services import claude_client

    monkeypatch.setattr(claude_client, "call_claude", calling_then_cancel)
    monkeypatch.setattr(agent, "_cancelled", lambda _state: flag["on"])
    _, headers = await make_user(UserRole.recruiter)

    resp = await _chat(app_client, headers, "Jak dodać zamówienie?")
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    assert len(model.calls) == 1, "po przerwaniu model nie może być wołany ponownie"
    messages = [e for e in events if e["type"] == "message"]
    assert messages[-1]["markdown"] == agent.CANCELLED_MESSAGE
    assert events[-1]["type"] == "done"


async def test_cancel_route_is_owner_only(app_client, monkeypatch):
    model = ScriptedModel([fake_message(text_block("Cześć."))])
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    _, other = await make_user(UserRole.recruiter)
    events = parse_sse((await _chat(app_client, headers, "Cześć")).text)
    conversation_id = events[0]["conversation_id"]

    ok = await app_client.post(
        f"/api/jarvis/conversations/{conversation_id}/cancel", headers=headers
    )
    assert ok.status_code == 204
    foreign = await app_client.post(
        f"/api/jarvis/conversations/{conversation_id}/cancel", headers=other
    )
    assert foreign.status_code == 404


async def test_truncated_answer_gets_a_note_and_drops_the_cut_tool_call(
    app_client, monkeypatch
):
    from app.services.jarvis import agent

    cut = fake_message(
        text_block("Oto długa odpowiedź"),
        tool_block("search_help", {"query": "x"}, "toolu_cut"),
    )
    cut.stop_reason = "max_tokens"
    model = ScriptedModel([cut])
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)

    events = parse_sse((await _chat(app_client, headers, "Opowiedz wszystko")).text)
    final = [e for e in events if e["type"] == "message"][-1]
    assert final["markdown"].endswith(agent.TRUNCATED_NOTE)
    assert final["final"] is True
    assert not [e for e in events if e["type"] == "step"], "ucięte narzędzie nie rusza"
    assert len(model.calls) == 1


async def test_open_screen_without_id_explains_what_is_missing(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "open_screen", {"screen": "candidate", "reason": "tam"}, "toolu_os"
                )
            ),
            fake_message(text_block("Najpierw ustalę ID.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    await _chat(app_client, headers, "Otwórz profil")
    result = model.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "wymaga id rekordu" in result["content"]


# ── A6: Pomoc z rankingiem ──────────────────────────────────────────────────


def test_help_search_folds_polish_characters_and_ranks_titles_first():
    from app.services import help_search

    assert help_search.fold("Zamówienie Łódź") == "zamowienie lodz"
    docs = [
        (1, "Karta klienta", "Tu jest mowa o zamówieniu tylko raz."),
        (2, "Zamówienia z PDF", "## Dodawanie zamówienia z PDF\nKrok 1: wgraj PDF."),
    ]
    ranked = help_search.rank("jak dodać zamowienie z pdf", docs)
    assert [r.key for r in ranked][0] == 2
    assert ranked[0].excerpt and "PDF" in ranked[0].excerpt
    assert help_search.rank("jak co", docs) == []


async def test_ranked_procedure_search_finds_a_sentence_question(app_client):
    _, headers = await make_user(UserRole.recruiter)
    resp = await app_client.get(
        "/api/procedures",
        params={"q": "jak dodać zamówienie z pdf", "ranked": "true"},
        headers=headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "pytanie zdaniem musi coś znaleźć"
    assert rows[0]["slug"] == "zamowienia-instrukcja-delivery-lead"
    assert rows[0]["excerpt"]
    # Bez `ranked` zostaje dotychczasowe wyszukiwanie ekranu Pomocy (AND słów).
    plain = await app_client.get(
        "/api/procedures", params={"q": "jak dodać zamówienie z pdf"}, headers=headers
    )
    assert all(r.get("excerpt") is None for r in plain.json())


# ── B/C: przewodniki ekranów ────────────────────────────────────────────────


async def test_screen_guides_hide_anchors_the_person_cannot_see(app_client):
    _, recruiter = await make_user(UserRole.recruiter)
    _, admin = await make_user(UserRole.admin)
    listed = await app_client.get("/api/help/screens", headers=recruiter)
    assert listed.status_code == 200
    by_key = {g["key"]: g for g in listed.json()}
    assert "jobs.board" in by_key
    assert "sources" not in by_key["jobs.board"]
    recruiter_ids = {a["id"] for a in by_key["jobs.list"]["anchors"]}
    assert "jobs.list.new" not in recruiter_ids
    admin_guide = (
        await app_client.get("/api/help/screens/jobs.list", headers=admin)
    ).json()
    assert "jobs.list.new" in {a["id"] for a in admin_guide["anchors"]}

    missing = await app_client.get("/api/help/screens/nie.ma", headers=recruiter)
    assert missing.status_code == 404


def test_context_block_names_the_screen_guide_and_the_clock():
    from app.services.jarvis.prompt import context_block

    today = datetime(2026, 9, 23, 14, 5).date()
    block = context_block(
        user_name="Ala",
        roles=["recruiter"],
        today=today,
        now=datetime(2026, 9, 23, 14, 5),
        screen={
            "path": "/jobs/5",
            "entity": {"type": "job", "id": 5},
            "key": "jobs.board",
        },
        assistant_name="Jarvis",
        notes=["Odpowiadaj krótko"],
    )
    assert "godz. 14:05" in block
    assert "Tablica rekrutacji" in block
    assert "• Odpowiadaj krótko" in block
    unknown = context_block(
        user_name="Ala",
        roles=[],
        today=today,
        screen={"path": "/x", "key": "nie.ma"},
        assistant_name=None,
    )
    assert "klucz przewodnika" not in unknown


async def test_show_on_screen_accepts_only_anchors_of_the_current_screen(
    app_client, monkeypatch
):
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "show_on_screen",
                    {"anchor": "finance.modes", "reason": "tu"},
                    "toolu_bad",
                ),
                tool_block(
                    "show_on_screen",
                    {"anchor": "jobs.board.columns", "reason": "przeciągnij"},
                    "toolu_ok",
                ),
            ),
            fake_message(text_block("Pokazałem kolumny.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    resp = await _chat(
        app_client,
        headers,
        "Gdzie przesuwam kandydatów?",
        screen={
            "path": "/jobs/1",
            "entity": {"type": "job", "id": 1},
            "key": "jobs.board",
        },
    )
    events = parse_sse(resp.text)
    highlights = [e for e in events if e["type"] == "highlight"]
    assert highlights == [
        {
            "type": "highlight",
            "anchor": "jobs.board.columns",
            "label": "Kolumny tablicy",
            "reason": "przeciągnij",
        }
    ]
    results = model.calls[1]["messages"][-1]["content"]
    bad = next(r for r in results if r["tool_use_id"] == "toolu_bad")
    assert bad["is_error"] is True and "jobs.board.columns" in bad["content"]

    detail = await app_client.get(
        f"/api/jarvis/conversations/{events[0]['conversation_id']}", headers=headers
    )
    kinds = [i["kind"] for i in detail.json()["items"]]
    assert "highlight" in kinds


# ── G: nowe narzędzia ───────────────────────────────────────────────────────


def test_explain_match_never_forces_a_paid_refresh():
    from app.services.jarvis.tools import TOOLS_BY_NAME

    spec = TOOLS_BY_NAME["explain_match"].build({"candidate_id": 1, "job_id": 2})
    assert "refresh" not in (spec.params or {})


def test_debrief_card_shows_everything_that_will_be_saved():
    from app.services.jarvis.tools import TOOLS_BY_NAME

    tool = TOOLS_BY_NAME["save_interview_debrief"]
    args = {
        "event_id": 9,
        "outcome": "good",
        "offer_acceptance": "likely",
        "candidate_comment": "Klient zadowolony.",
        "questions": ["Jak skalujesz Kafkę?", "  "],
    }
    spec = tool.build(args)
    assert spec.method == "PUT"
    assert spec.json["questions"] == ["Jak skalujesz Kafkę?"]
    assert "no_client_questions" not in spec.json
    assert "poszło dobrze" in tool.preview(args)
    assert "banku pytań" in tool.detail(args)


async def test_board_tasks_tool_reads_the_real_queue(app_client, monkeypatch):
    model = ScriptedModel(
        [
            fake_message(tool_block("my_board_tasks", {}, "toolu_bt")),
            fake_message(text_block("Kolejka pusta.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    _, headers = await make_user(UserRole.recruiter)
    await _chat(app_client, headers, "Co mam dziś zrobić?")
    result = model.calls[1]["messages"][-1]["content"][0]
    assert "is_error" not in result, result
    assert '"dl_review"' in result["content"] and '"count"' in result["content"]


# ── H: pamięć, telemetria, strumień ─────────────────────────────────────────


async def test_notes_preferences_are_validated(app_client):
    _, headers = await make_user(UserRole.recruiter)
    too_many = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"notes": [f"pozycja {i}" for i in range(11)]}},
        headers=headers,
    )
    assert too_many.status_code == 422
    bad = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"notes": ["<b>x</b>"]}},
        headers=headers,
    )
    assert bad.status_code == 422
    ok = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"notes": ["Odpowiadaj krótko", ""], "screen_tips": False}},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["jarvis"]["notes"] == ["Odpowiadaj krótko"]
    assert ok.json()["jarvis"]["screen_tips"] is False


async def test_remember_preference_appends_after_confirmation(app_client, monkeypatch):
    _, headers = await make_user(UserRole.recruiter)
    await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"notes": ["Pierwsza"]}},
        headers=headers,
    )
    model = ScriptedModel(
        [
            fake_message(
                tool_block(
                    "remember_preference", {"text": "Druga", "_notes": ["wstrzyk"]}
                )
            ),
            fake_message(text_block("Przygotowałem.")),
        ]
    )
    enable_jarvis(monkeypatch, model)
    events = parse_sse((await _chat(app_client, headers, "Zapamiętaj: Druga")).text)
    action = next(e for e in events if e["type"] == "action_proposed")["action"]
    confirm = await app_client.post(
        f"/api/jarvis/actions/{action['id']}/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    prefs = (await app_client.get("/api/users/me/preferences", headers=headers)).json()
    assert prefs["jarvis"]["notes"] == ["Pierwsza", "Druga"]


async def test_ui_events_are_recorded_and_summarised(app_client):
    user_id, headers = await make_user(UserRole.recruiter)
    _, admin = await make_user(UserRole.admin)
    ok = await app_client.post(
        "/api/jarvis/ui-events",
        json={"event": "bubble_shown", "screen_key": "jobs.board"},
        headers=headers,
    )
    assert ok.status_code == 204
    bad = await app_client.post(
        "/api/jarvis/ui-events", json={"event": "kliknal_cos"}, headers=headers
    )
    assert bad.status_code == 422
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JarvisUiEvent).where(JarvisUiEvent.user_id == user_id)
        )
        assert row is not None and row.screen_key == "jobs.board"
    forbidden = await app_client.get("/api/jarvis/ui-events/summary", headers=headers)
    assert forbidden.status_code == 403
    summary = await app_client.get("/api/jarvis/ui-events/summary", headers=admin)
    assert summary.status_code == 200
    assert any(r["screen_key"] == "jobs.board" for r in summary.json()["rows"])


async def test_old_ui_events_are_purged():
    from app.services.jarvis import store

    user_id, _ = await make_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add(
            JarvisUiEvent(
                user_id=user_id,
                event="guide_opened",
                created_at=datetime.now(timezone.utc) - timedelta(days=120),
            )
        )
        await db.commit()
    assert await store.purge_old_ui_events() >= 1
    async with AsyncSessionLocal() as db:
        left = await db.scalar(
            select(JarvisUiEvent).where(
                JarvisUiEvent.user_id == user_id, JarvisUiEvent.event == "guide_opened"
            )
        )
        assert left is None


async def test_text_deltas_stream_before_the_full_message(app_client, monkeypatch):
    responses = [fake_message(text_block("Cześć, jak mogę pomóc?"))]
    calls: list[dict] = []

    def streaming_model(**kwargs):
        calls.append(kwargs)
        assert kwargs.get("stream_response") is True
        callback = kwargs["on_text_delta"]
        callback("Cześć, ")
        callback(None)  # ponowienie — pokazany tekst do wyrzucenia
        callback("Cześć, jak ")
        callback("mogę pomóc?")
        return responses.pop(0)

    enable_jarvis(monkeypatch, ScriptedModel([]))
    from app.services import claude_client

    monkeypatch.setattr(claude_client, "call_claude", streaming_model)
    _, headers = await make_user(UserRole.recruiter)
    events = parse_sse((await _chat(app_client, headers, "Hej")).text)
    kinds = [e["type"] for e in events]
    assert kinds.index("delta") < kinds.index("message")
    assert "delta_reset" in kinds
    assert [e["text"] for e in events if e["type"] == "delta"] == [
        "Cześć, ",
        "Cześć, jak ",
        "mogę pomóc?",
    ]
    assert events[-2]["markdown"] == "Cześć, jak mogę pomóc?"


def test_claude_client_forwards_only_raw_text_deltas():
    from app.services.claude_client import _forward_text_delta

    seen: list = []
    _forward_text_delta(
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="ab"),
        ),
        seen.append,
    )
    _forward_text_delta(SimpleNamespace(type="text", text="ab"), seen.append)
    _forward_text_delta(
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="input_json_delta", partial_json="{"),
        ),
        seen.append,
    )
    assert seen == ["ab"]
