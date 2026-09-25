"""Jarvis — powiązania z kandydatem, „Zatrzymaj” i blokada tury (audyt 25.09.2026).

Bez bazy: `store` podmieniony. Pilnujemy trzech rzeczy:
- rozmowa wiąże się z kandydatem po KAŻDYM narzędziu, które zwróciło jego
  `candidate_id` albo link `/candidates/{id}` (`global_search`, kalendarz,
  powiadomienia) — i to od razu, nie dopiero na końcu tury (art. 17 RODO);
- „Zatrzymaj” sprzed tury nie przerywa nowej tury tej rozmowy;
- tura zwalnia wyłącznie WŁASNĄ blokadę (żeton), a blokada jest przedłużana.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.jarvis import agent, store
from app.services.jarvis.tools import TOOLS_BY_NAME

pytestmark = pytest.mark.asyncio


class _StoreSpy:
    def __init__(self) -> None:
        self.linked: list[set] = []
        self.released: list[store.TurnClaim] = []
        self.extended: list[store.TurnClaim] = []

    async def link_entities(self, conversation_id, entities):
        self.linked.append(set(entities))

    async def release_turn(self, claim):
        self.released.append(claim)

    async def extend_turn(self, claim, lock_seconds):
        self.extended.append(claim)
        return store.TurnClaim(claim.conversation_id, datetime.now(timezone.utc))


@pytest.fixture
def spy(monkeypatch) -> _StoreSpy:
    s = _StoreSpy()
    monkeypatch.setattr(store, "link_entities", s.link_entities)
    monkeypatch.setattr(store, "release_turn", s.release_turn)
    monkeypatch.setattr(store, "extend_turn", s.extend_turn)
    return s


@pytest.mark.parametrize(
    ("tool_name", "shaped"),
    [
        (
            "global_search",
            {"candidates": [{"id": 4242, "name": "Anna X", "url": "/candidates/4242"}]},
        ),
        ("list_calendar_events", [{"id": 9, "candidate_id": 4242, "title": "Prep"}]),
        ("list_notifications", [{"id": 1, "link": "/candidates/4242?tab=activity"}]),
    ],
)
async def test_read_tools_link_candidates_immediately(
    spy, monkeypatch, tool_name, shaped
) -> None:
    tool = TOOLS_BY_NAME[tool_name]

    async def _execute_read(transport, tool_, args):
        return True, "wynik", shaped

    monkeypatch.setattr(agent, "execute_read", _execute_read)
    state = agent._TurnState(conversation_id=uuid.uuid4())  # noqa: SLF001

    await agent._handle_tool(  # noqa: SLF001
        SimpleNamespace(),
        state,
        {tool.name: tool},
        object(),
        {"id": "toolu_1", "name": tool.name, "input": {}},
        [],
    )

    assert ("candidate", 4242) in state.entities
    # Zapisane od razu po narzędziu, nie dopiero w `_finish_turn`.
    assert spy.linked and ("candidate", 4242) in spy.linked[-1]


async def test_stale_cancel_does_not_stop_a_new_turn(spy, monkeypatch) -> None:
    cid = uuid.uuid4()
    agent.request_cancel(cid)
    seen: list[bool] = []

    async def _loop(turn, state):
        seen.append(agent._cancelled(state))  # noqa: SLF001
        if False:  # pragma: no cover — generator
            yield {}

    monkeypatch.setattr(agent, "_run_loop", _loop)
    claim = store.TurnClaim(cid, datetime.now(timezone.utc))
    events = [e async for e in agent.run_turn(SimpleNamespace(screen=None), claim)]

    assert seen == [False]
    assert events[-1] == {"type": "done"}


async def test_turn_releases_only_its_own_lock(spy, monkeypatch) -> None:
    cid = uuid.uuid4()

    async def _loop(turn, state):
        if False:  # pragma: no cover — generator
            yield {}

    monkeypatch.setattr(agent, "_run_loop", _loop)
    claim = store.TurnClaim(cid, datetime.now(timezone.utc))
    [e async for e in agent.run_turn(SimpleNamespace(screen=None), claim)]

    assert spy.released == [claim]


async def test_lost_lock_stops_the_turn_before_the_model(spy, monkeypatch) -> None:
    async def _lost(claim, lock_seconds):
        return None

    monkeypatch.setattr(store, "extend_turn", _lost)
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
            {},
            [],
            "claude-test",
            [],
            float("inf"),
            object(),
        )
    ]
    assert events and events[0]["type"] == "error"
    assert events[0]["code"] == "turn_lost"


def test_max_tokens_per_step_default_is_4000() -> None:
    assert type(settings).model_fields["JARVIS_MAX_TOKENS_PER_STEP"].default == 4000
