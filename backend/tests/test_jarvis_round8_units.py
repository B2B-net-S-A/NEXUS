"""Jarvis — runda 8 audytu (26.09.2026), jednostki bez bazy.

- R8-N1-2: karta akcji pokazuje KAŻDE pole tekstowe i ID, które „Zrób to”
  zapisze (test kontraktowy po wszystkich narzędziach zapisu);
- R8-N1-3: czas wydarzenia bez strefy jest odrzucany, karta mówi czas polski;
- R8-N1-4: pamięć składana z listy zapisanej w chwili wykonania;
- R8-N1-6: historia bez osieroconych i zdublowanych ``tool_result``, a tura
  bez blokady nie dopisuje wyników;
- R8-N1-8: odrzucone ``show_on_screen`` nie wraca w historii.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.jarvis import _conversation_items
from app.services.jarvis import agent, store
from app.services.jarvis.agent import ProposalRejected, prepare_proposal
from app.services.jarvis.store import INTERRUPTED_RESULT, repair_history
from app.services.jarvis.tools import TOOLS_BY_NAME, WRITE_TOOLS
from app.services.jarvis.transport import ToolResponse

# ── R8-N1-2: kontrakt karty ────────────────────────────────────────────────

# Pole zapisywane przez ``build``, którego karta świadomie nie pokazuje
# wprost — z powodem.
_CARD_EXEMPT = {
    ("move_candidate_stage", "stage_def_id"): (
        "karta pokazuje nazwę etapu docelowego z tablicy (_resolve_move_stage)"
    ),
    ("save_interview_debrief", "event_id"): (
        "kandydat i rekrutacja brane z wydarzenia (_resolve_debrief_event) "
        "i pokazane na karcie"
    ),
}

_START = "2026-09-29T10:00:00+02:00"
_END = "2026-09-29T11:30:00+02:00"


def _sample_args(tool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Argumenty-wartownicy dla każdego pola schematu + nazwy z „odczytu API”."""
    args: dict[str, Any] = {}
    display: dict[str, Any] = {}
    for index, (name, schema) in enumerate(tool.input_schema["properties"].items()):
        kind = schema.get("type")
        if "enum" in schema:
            args[name] = schema["enum"][0]
        elif kind == "string":
            if name == "start_time":
                args[name] = _START
            elif name == "end_time":
                args[name] = _END
            else:
                args[name] = f"TXT{name}END"
        elif kind == "integer":
            if name.endswith("_id"):
                args[name] = 700000 + index
                display[name] = f"NAZWA{name}END"
            else:
                args[name] = schema.get("minimum", 3)
        elif kind == "array":
            if schema["items"].get("type") == "integer":
                args[name] = [800001, 800002]
                display[name] = ["NAZWA1END", "NAZWA2END"]
            else:
                args[name] = [f"TXT{name}1END", f"TXT{name}2END"]
        elif kind == "boolean":
            args[name] = True
    return args, display


def _leaves(node: Any) -> list[Any]:
    if isinstance(node, dict):
        return [x for v in node.values() for x in _leaves(v)]
    if isinstance(node, list):
        return [x for v in node for x in _leaves(v)]
    return [node]


@pytest.mark.parametrize("tool", WRITE_TOOLS, ids=lambda t: t.name)
def test_every_written_text_and_id_is_visible_on_the_card(tool) -> None:
    args, display = _sample_args(tool)
    spec = tool.build(args)
    written = _leaves(spec.json) + [spec.path]
    shown = {**args, "_display": display}
    card = (
        (tool.preview(shown) if tool.preview else "")
        + "\n"
        + (tool.detail(shown) if tool.detail else "")
    )

    def is_written(value: Any) -> bool:
        if isinstance(value, int) and not isinstance(value, bool):
            return value in written or f"/{value}" in spec.path
        return any(isinstance(w, str) and str(value) in w for w in written)

    missing: list[str] = []
    for name, schema in tool.input_schema["properties"].items():
        if (tool.name, name) in _CARD_EXEMPT or "enum" in schema:
            continue
        value = args.get(name)
        if name.endswith("_time") and value:
            if is_written(datetime.fromisoformat(value).isoformat()):
                local = datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
                if local not in card:
                    missing.append(name)
        elif isinstance(value, str):
            if is_written(value) and value not in card:
                missing.append(name)
        elif isinstance(value, list):
            for position, item in enumerate(value):
                if not is_written(item):
                    continue
                expected = display[name][position] if name in display else str(item)
                if expected not in card:
                    missing.append(f"{name}[{position}]")
        elif name.endswith("_id") and is_written(value):
            if display[name] not in card:
                missing.append(name)
    assert not missing, (
        f"{tool.name}: „Zrób to” zapisze {missing}, a karta tego nie pokazuje"
    )


class _NamesTransport:
    """Odczyty API dla nazw na karcie: każdy kandydat nazywa się jak jego ID."""

    def __init__(self, notes: list[str] | None = None) -> None:
        self.notes = notes or []
        self.calls: list[str] = []

    async def call(self, spec):
        self.calls.append(spec.path)
        if spec.path.endswith("/quick-view"):
            cid = spec.path.split("/")[3]
            return ToolResponse(
                200, {"candidate": {"name": "Osoba", "lastname": f"Nr{cid}"}}
            )
        if spec.path == "/api/users/me/preferences":
            return ToolResponse(200, {"jarvis": {"notes": list(self.notes)}})
        return ToolResponse(404, None)


@pytest.mark.asyncio
async def test_bulk_add_card_names_every_person_and_shows_the_note() -> None:
    _args, preview = await prepare_proposal(
        _NamesTransport(),
        TOOLS_BY_NAME["add_candidates_to_job"],
        {"job_id": 1, "candidate_ids": [5, 6], "note": "TAJNE"},
    )
    assert "Osoba Nr5" in preview["text"] and "Osoba Nr6" in preview["text"]
    assert "TAJNE" in preview["body"]


# ── R8-N1-3: czas wydarzenia ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_card_shows_polish_time_for_utc_input() -> None:
    args, preview = await prepare_proposal(
        _NamesTransport(),
        TOOLS_BY_NAME["create_calendar_event"],
        {"title": "Prep", "start_time": "2026-09-29T10:00:00Z"},
    )
    # 10:00 UTC to 12:00 w Warszawie (CEST) — tyle zapisze kalendarz.
    assert "29.09.2026 12:00" in preview["text"]
    spec = TOOLS_BY_NAME["create_calendar_event"].build(args)
    assert spec.json["start_time"] == "2026-09-29T10:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["start_time", "end_time"])
async def test_event_without_timezone_is_rejected(key) -> None:
    args = {"title": "Prep", "start_time": "2026-09-29T10:00:00+02:00"}
    args[key] = "2026-09-29T10:00:00"
    with pytest.raises(ProposalRejected, match="strefę"):
        await prepare_proposal(
            _NamesTransport(), TOOLS_BY_NAME["create_calendar_event"], args
        )


# ── R8-N1-4: pamięć z chwili wykonania ─────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_is_merged_with_the_list_saved_at_execution() -> None:
    from app.services.jarvis.actions import _fresh_notes

    # Karta powstała przy liście ["A"], a w międzyczasie zapisano "B".
    stale = {"text": "C", "_notes": ["A", "C"]}
    fresh = await _fresh_notes(_NamesTransport(notes=["A", "B"]), stale)
    assert fresh["_notes"] == ["A", "B", "C"]
    spec = TOOLS_BY_NAME["remember_preference"].build(fresh)
    assert spec.json == {"jarvis": {"notes": ["A", "B", "C"]}}


# ── R8-N1-6: historia po utracie blokady ───────────────────────────────────


def _assistant(*tool_ids: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tid, "name": "x", "input": {}}
            for tid in tool_ids
        ],
    }


def _results(*tool_ids: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
            for tid in tool_ids
        ],
    }


def test_late_results_of_a_lost_turn_do_not_break_the_history() -> None:
    history = [
        {"role": "user", "content": [{"type": "text", "text": "A"}]},
        _assistant("X"),
        {"role": "user", "content": [{"type": "text", "text": "B"}]},
        _assistant("Y"),
        _results("X"),  # spóźnione wyniki starej tury
        _results("Y", "Y"),
    ]
    fixed = repair_history(history, window=20)
    for index, message in enumerate(fixed):
        if message["role"] != "user":
            continue
        ids = [
            b["tool_use_id"]
            for b in message["content"]
            if b.get("type") == "tool_result"
        ]
        assert len(ids) == len(set(ids)), "zdublowany tool_result"
        prev = fixed[index - 1] if index else None
        allowed = {
            b["id"]
            for b in (prev or {}).get("content", [])
            if b.get("type") == "tool_use"
        }
        assert set(ids) <= allowed, "tool_result bez pary w poprzedniej wiadomości"
    # X dostaje „przerwane”, Y — prawdziwy wynik.
    after_x = fixed[2]["content"][0]
    assert after_x["tool_use_id"] == "X"
    assert after_x["content"] == INTERRUPTED_RESULT


@pytest.mark.asyncio
async def test_turn_without_its_lock_does_not_store_tool_results(monkeypatch) -> None:
    from app.services import claude_client

    extended: list[int] = []

    async def _extend(claim, lock_seconds):
        extended.append(1)
        # Pierwsze przedłużenie (przed modelem) się udaje, drugie (przed
        # zapisem wyników) już nie — rozmowę przejęła inna tura.
        if len(extended) == 1:
            return store.TurnClaim(claim.conversation_id, datetime.now(timezone.utc))
        return None

    appended: list[tuple[str, list]] = []

    async def _append(conversation_id, role, content):
        appended.append((role, content))

    async def _handle(*_a, **_k):
        return {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}

    def _model(**_kwargs):
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id="t1", name="search_help", input={})
            ],
            stop_reason="tool_use",
        )

    monkeypatch.setattr(store, "extend_turn", _extend)
    monkeypatch.setattr(store, "append_message", _append)
    monkeypatch.setattr(agent, "_handle_tool", _handle)
    monkeypatch.setattr(claude_client, "call_claude", _model)
    state = agent._TurnState(  # noqa: SLF001
        conversation_id=uuid.uuid4(),
        claim=store.TurnClaim(uuid.uuid4(), datetime.now(timezone.utc)),
    )
    events = [
        e
        async for e in agent._steps(  # noqa: SLF001
            SimpleNamespace(web=False),
            state,
            [],
            {"search_help": TOOLS_BY_NAME["search_help"]},
            [],
            "claude-test",
            [],
            float("inf"),
            object(),
        )
    ]
    assert events[-1]["code"] == "turn_lost"
    assert all(
        not any(b.get("type") == "tool_result" for b in content)
        for _role, content in appended
    ), "wyniki tury bez blokady nie mogą trafić do historii"


# ── R8-N1-8: odrzucone podświetlenie ───────────────────────────────────────


def test_rejected_show_on_screen_is_not_replayed_as_a_highlight() -> None:
    from app.data.screen_guides import load_guides

    valid = next(a.id for g in load_guides().values() for a in g.anchors)

    def use(tool_id: str, anchor: str) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "id": tool_id,
            "name": "show_on_screen",
            "input": {"anchor": anchor},
        }

    def result(tool_id: str, error: bool) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": "Nie ma takiego elementu." if error else "ok",
        }
        if error:
            block["is_error"] = True
        return block

    messages = [
        (
            "assistant",
            [use("bad", "nie.ma"), use("refused", valid), use("good", valid)],
        ),
        ("user", [result("bad", True), result("refused", True), result("good", False)]),
    ]
    highlights = [
        item
        for item in _conversation_items(messages, [])
        if item["kind"] == "highlight"
    ]
    assert [h["anchor"] for h in highlights] == [valid]
    assert highlights[0]["label"] != "Element ekranu"
