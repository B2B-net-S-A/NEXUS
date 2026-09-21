"""Jarvis — jednostki bez modelu: naprawa historii, tag „via”, preferencje,
cennik narzędzi klienckich, zbieranie kandydatów do kasowania RODO."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.user import UserRole
from app.services.claude_client import _has_server_tools
from app.services.jarvis.agent import collect_entities, sanitize_args
from app.services.jarvis.prefs import JarvisPrefsUpdate, apply_update, effective_prefs
from app.services.jarvis.store import INTERRUPTED_RESULT, repair_history
from app.services.jarvis.tools import TOOLS_BY_NAME
from app.services.jarvis.via_tag import (
    VIA_INFO_KEY,
    internal_secret,
    is_internal_request,
    stamp_via,
)
from tests._jarvis_helpers import make_user

# ── naprawa historii ───────────────────────────────────────────────────────


def _user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _assistant_tool(tool_id):
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_id, "name": "x", "input": {}}],
    }


def test_orphan_tool_use_gets_a_synthetic_interrupted_result():
    history = [_user("a"), _assistant_tool("t1")]
    fixed = repair_history(history, window=20)
    assert fixed[-1]["role"] == "user"
    result = fixed[-1]["content"][0]
    assert result == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": INTERRUPTED_RESULT,
        "is_error": True,
    }


def test_orphan_before_next_user_turn_is_prefixed_into_that_turn():
    history = [_user("a"), _assistant_tool("t1"), _user("b")]
    fixed = repair_history(history, window=20)
    assert [m["role"] for m in fixed] == ["user", "assistant", "user"]
    assert fixed[2]["content"][0]["type"] == "tool_result"
    assert fixed[2]["content"][1]["text"] == "b"


def test_consecutive_same_role_messages_are_merged():
    fixed = repair_history([_user("a"), _user("b")], window=20)
    assert len(fixed) == 1
    assert [b["text"] for b in fixed[0]["content"]] == ["a", "b"]


def test_window_never_starts_with_tool_results():
    history = [
        _user("a"),
        _assistant_tool("t1"),
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "odp"}]},
        _user("b"),
    ]
    fixed = repair_history(history, window=3)
    assert fixed[0]["role"] == "user"
    assert fixed[0]["content"][0]["type"] == "text"


# ── argumenty i encje ──────────────────────────────────────────────────────


def test_sanitize_args_drops_undeclared_keys():
    tool = TOOLS_BY_NAME["create_note"]
    clean = sanitize_args(
        tool,
        {
            "candidate_id": 1,
            "content": "x",
            "_display": {"a": 1},
            "acknowledge_eligibility": True,
        },
    )
    assert clean == {"candidate_id": 1, "content": "x"}
    assert sanitize_args(tool, "nie słownik") == {}


def test_collect_entities_finds_candidates_in_args_rows_and_links():
    search = TOOLS_BY_NAME["search_candidates"]
    found = collect_entities(search, {}, {"items": [{"id": 5}, {"id": 6}]})
    assert found == {("candidate", 5), ("candidate", 6)}

    board = TOOLS_BY_NAME["get_job_board"]
    found = collect_entities(
        board, {"job_id": 1}, {"columns": [{"cards": [{"candidate_id": 9}]}]}
    )
    assert found == {("candidate", 9)}, "id rekrutacji nie może być wzięte za kandydata"

    profile = TOOLS_BY_NAME["get_candidate"]
    found = collect_entities(
        profile,
        {"candidate_id": 5},
        {"candidate": {"id": 5}, "current_recruitments": [{"id": 99}]},
    )
    assert found == {("candidate", 5)}, (
        "ID rekrutacji z zagnieżdżonej listy to nie kandydat"
    )

    note = TOOLS_BY_NAME["create_note"]
    assert collect_entities(note, {"candidate_id": 3}, None) == {("candidate", 3)}
    assert collect_entities(search, {}, {"x": "zobacz /candidates/77"}) == {
        ("candidate", 77)
    }


# ── cennik: narzędzia klienckie liczą się tokenami ─────────────────────────


def test_client_tools_keep_standard_pricing_server_tools_do_not():
    client_tools = [
        {"name": "a", "description": "b", "input_schema": {"type": "object"}}
    ]
    assert _has_server_tools(client_tools) is False
    assert _has_server_tools(None) is False
    # Wyszukiwarka ma znaną cenę (tokeny + 0,01 USD/wyszukiwanie) — jest wyceniana.
    assert (
        _has_server_tools([{"type": "web_search_20250305", "name": "web_search"}])
        is False
    )
    # Inne narzędzie serwerowe bez cennika zostaje „unpriced”.
    assert (
        _has_server_tools([{"type": "code_execution_20250825", "name": "code"}])
        is True
    )


def test_web_searches_are_added_to_the_cost():
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services.ai_metering import response_event

    def message(searches: int):
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=100,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            cache_creation=None,
            server_tool_use=SimpleNamespace(web_search_requests=searches),
        )
        return SimpleNamespace(
            usage=usage, model="claude-sonnet-5", id="msg_x", stop_reason="end_turn"
        )

    plain = response_event("op", message(0), model="claude-sonnet-5", latency_ms=1)
    web = response_event("op", message(3), model="claude-sonnet-5", latency_ms=1)
    assert web["estimated_cost_usd"] - plain["estimated_cost_usd"] == Decimal("0.03")


# ── tag „via jarvis” ───────────────────────────────────────────────────────


def test_only_the_process_secret_counts_as_internal():
    assert is_internal_request(internal_secret())
    assert not is_internal_request("")
    assert not is_internal_request(None)
    assert not is_internal_request("zgadnięty-sekret")
    info: dict = {}
    stamp_via(info, "zgadnięty-sekret")
    assert VIA_INFO_KEY not in info


@pytest.mark.asyncio
async def test_new_activities_in_a_stamped_session_are_tagged():
    user_id, _ = await make_user(UserRole.recruiter)
    marker = f"jarvis-test-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        stamp_via(db.info, internal_secret())
        db.add(
            Activity(
                entity_type="test",
                entity_id=1,
                action=marker,
                user_id=user_id,
                details={"a": 1},
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="test",
                entity_id=1,
                action=marker + "-plain",
                user_id=user_id,
                details={},
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = {
            a.action: a.details
            for a in (
                await db.execute(
                    select(Activity).where(Activity.action.like(marker + "%"))
                )
            ).scalars()
        }
    assert rows[marker] == {"a": 1, "via": "jarvis"}
    assert rows[marker + "-plain"] == {}


# ── preferencje ────────────────────────────────────────────────────────────


def test_effective_prefs_fall_back_to_defaults_on_garbage():
    assert effective_prefs(None).character == "robot"
    assert effective_prefs({"character": "unicorn", "name": "Maks"}).name == "Jarvis"
    prefs = effective_prefs({"character": "owl", "name": "Maks", "extra": 1})
    assert (prefs.character, prefs.name) == ("owl", "Maks")


def test_apply_update_cleans_the_name_and_rejects_markup():
    prefs = apply_update(effective_prefs({}), JarvisPrefsUpdate(name="  Pan   Sowa "))
    assert prefs.name == "Pan Sowa"
    with pytest.raises(ValueError):
        apply_update(effective_prefs({}), JarvisPrefsUpdate(name="<img>"))


@pytest.mark.asyncio
async def test_preferences_round_trip_and_locked_character(app_client):
    _, headers = await make_user(UserRole.recruiter)
    got = await app_client.get("/api/users/me/preferences", headers=headers)
    assert got.status_code == 200
    jarvis = got.json()["jarvis"]
    assert jarvis["character"] == "robot"
    assert "robot_gold" in jarvis["locked_characters"]
    assert "robot_gold" not in jarvis["unlocked_characters"]

    saved = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"character": "owl", "name": "Sowa", "accent": "green"}},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["jarvis"]["character"] == "owl"
    assert saved.json()["jarvis"]["name"] == "Sowa"
    assert saved.json()["kpi_coach_enabled"] is True

    locked = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"character": "robot_gold"}},
        headers=headers,
    )
    assert locked.status_code == 403
    assert "Ligi Mistrzów" in locked.json()["detail"]

    bad = await app_client.patch(
        "/api/users/me/preferences",
        json={"jarvis": {"accent": "neon"}},
        headers=headers,
    )
    assert bad.status_code == 422
