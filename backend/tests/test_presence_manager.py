"""Unit tests for in-memory presence tracking inside ConnectionManager."""

from __future__ import annotations

from typing import List

import pytest

from app.api.ws import ConnectionManager
from app.models.user import UserRole


class FakeUser:
    """Duck-typed stand-in for app.models.user.User."""

    def __init__(self, user_id: int, name: str, role: UserRole = UserRole.recruiter):
        self.id = user_id
        self.name = name
        self.email = f"{name.lower().replace(' ', '.')}@example.com"
        self.role = role


class FakeWebSocket:
    """Minimal async WebSocket stub that records every send_json payload."""

    def __init__(self):
        self.sent: List[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
def manager() -> ConnectionManager:
    return ConnectionManager()


@pytest.fixture
def user_a() -> FakeUser:
    return FakeUser(1, "User A")


@pytest.fixture
def user_b() -> FakeUser:
    return FakeUser(2, "User B")


def _last_update(ws: FakeWebSocket) -> dict:
    updates = [m for m in ws.sent if m.get("type") == "presence:update"]
    assert updates, "no presence:update broadcast received"
    return updates[-1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subscribe_single_user(manager, user_a):
    ws = FakeWebSocket()
    await manager.subscribe(user_a, ws, "candidate", 42)

    update = _last_update(ws)
    assert update["resource_type"] == "candidate"
    assert update["resource_id"] == 42
    assert len(update["viewers"]) == 1
    assert update["viewers"][0]["user_id"] == user_a.id
    assert update["viewers"][0]["name"] == "User A"
    assert update["viewers"][0]["editing"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multiple_tabs_one_viewer(manager, user_a):
    """Three tabs of the same user on the same resource = one viewer entry."""
    ws1, ws2, ws3 = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
    await manager.subscribe(user_a, ws1, "candidate", 42)
    await manager.subscribe(user_a, ws2, "candidate", 42)
    await manager.subscribe(user_a, ws3, "candidate", 42)

    # Every subscribe rebroadcasts; the latest snapshot still has exactly one viewer.
    update = _last_update(ws3)
    assert len(update["viewers"]) == 1
    assert update["viewers"][0]["user_id"] == user_a.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsubscribe_last_tab_drops_viewer(manager, user_a, user_b):
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    await manager.subscribe(user_a, ws_a, "candidate", 42)
    await manager.subscribe(user_b, ws_b, "candidate", 42)

    before = _last_update(ws_a)
    assert {v["user_id"] for v in before["viewers"]} == {1, 2}

    await manager.unsubscribe(user_b.id, ws_b, "candidate", 42)

    after = _last_update(ws_a)
    assert {v["user_id"] for v in after["viewers"]} == {1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsubscribe_not_last_tab_preserves_viewer(manager, user_a, user_b):
    """User A has two tabs; closing one leaves A present."""
    ws_a1 = FakeWebSocket()
    ws_a2 = FakeWebSocket()
    ws_b = FakeWebSocket()
    await manager.subscribe(user_a, ws_a1, "candidate", 42)
    await manager.subscribe(user_a, ws_a2, "candidate", 42)
    await manager.subscribe(user_b, ws_b, "candidate", 42)

    prior_updates = len([m for m in ws_b.sent if m.get("type") == "presence:update"])

    await manager.unsubscribe(user_a.id, ws_a2, "candidate", 42)

    # No broadcast expected — viewer set unchanged (A still has ws_a1)
    after_updates = len([m for m in ws_b.sent if m.get("type") == "presence:update"])
    assert after_updates == prior_updates

    snapshot = manager.get_viewers("candidate", 42)
    assert {v["user_id"] for v in snapshot} == {user_a.id, user_b.id}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_editing_toggles_field(manager, user_a, user_b):
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    await manager.subscribe(user_a, ws_a, "candidate", 42)
    await manager.subscribe(user_b, ws_b, "candidate", 42)

    await manager.set_editing(user_a.id, "candidate", 42, "notes", True)

    update = _last_update(ws_b)
    a_entry = next(v for v in update["viewers"] if v["user_id"] == user_a.id)
    assert a_entry["editing"] == ["notes"]

    await manager.set_editing(user_a.id, "candidate", 42, "notes", False)

    update = _last_update(ws_b)
    a_entry = next(v for v in update["viewers"] if v["user_id"] == user_a.id)
    assert a_entry["editing"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_editing_ignores_non_viewer(manager, user_a):
    """Editing signal from a user who never subscribed is a no-op."""
    ws = FakeWebSocket()
    await manager.connect(user_a.id, ws := FakeWebSocket())

    await manager.set_editing(user_a.id, "candidate", 99, "notes", True)

    assert manager.get_viewers("candidate", 99) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_cleans_up_presence(manager, user_a, user_b):
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()
    await manager.connect(user_a.id, ws_a)
    await manager.connect(user_b.id, ws_b)

    await manager.subscribe(user_a, ws_a, "candidate", 42)
    await manager.subscribe(user_b, ws_b, "candidate", 42)
    await manager.subscribe(user_a, ws_a, "job", 7)

    await manager.disconnect(user_a.id, ws_a)

    # User A dropped from both resources
    candidate_viewers = manager.get_viewers("candidate", 42)
    assert {v["user_id"] for v in candidate_viewers} == {user_b.id}

    job_viewers = manager.get_viewers("job", 7)
    assert job_viewers == []

    # User B's ws received a broadcast for candidate:42
    b_update = _last_update(ws_b)
    assert {v["user_id"] for v in b_update["viewers"]} == {user_b.id}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_with_multiple_tabs_keeps_viewer(manager, user_a, user_b):
    ws_a1 = FakeWebSocket()
    ws_a2 = FakeWebSocket()
    ws_b = FakeWebSocket()
    await manager.connect(user_a.id, ws_a1)
    await manager.connect(user_a.id, ws_a2)
    await manager.connect(user_b.id, ws_b)

    await manager.subscribe(user_a, ws_a1, "candidate", 42)
    await manager.subscribe(user_a, ws_a2, "candidate", 42)
    await manager.subscribe(user_b, ws_b, "candidate", 42)

    prior_b_updates = len(
        [m for m in ws_b.sent if m.get("type") == "presence:update"]
    )

    await manager.disconnect(user_a.id, ws_a1)

    # Viewer list didn't change — B should NOT receive a new broadcast
    after_b_updates = len(
        [m for m in ws_b.sent if m.get("type") == "presence:update"]
    )
    assert after_b_updates == prior_b_updates

    snapshot = manager.get_viewers("candidate", 42)
    assert {v["user_id"] for v in snapshot} == {user_a.id, user_b.id}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_viewers_snapshot_shape(manager, user_a):
    ws = FakeWebSocket()
    await manager.subscribe(user_a, ws, "job", 11)
    await manager.set_editing(user_a.id, "job", 11, "notes", True)

    snapshot = manager.get_viewers("job", 11)
    assert len(snapshot) == 1
    v = snapshot[0]
    assert v["user_id"] == user_a.id
    assert v["name"] == "User A"
    assert v["email"] == "user.a@example.com"
    assert v["role"] == UserRole.recruiter.value
    assert v["editing"] == ["notes"]
    assert isinstance(v["since"], str)
