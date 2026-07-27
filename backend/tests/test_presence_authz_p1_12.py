"""NEXUS-P1-12: WebSocket presence authorization + payload minimization.

One finding, two regressions on the raw WebSocket presence path:

1. **IDOR / authorization bypass** — any authenticated account (including the
   read-only viewer/client ``user`` role) could ``presence:subscribe`` to an
   arbitrary ``candidate:{id}`` / ``job:{id}`` channel and watch who is editing
   it. The WS path bypassed every HTTP authorization guard.
2. **PII leak** — the broadcast viewer payload carried each colleague's email
   AND role.

Containment: ``presence_subscribe_allowed`` reuses the role-based candidate-read
capability (union of primary ``users.role`` + secondary ``users.roles``; there
is no per-resource ACL in NEXUS), and the payload now carries only ``user_id`` +
display ``name``.

These assert the extracted authorization function and the payload builder
directly — a live Starlette WebSocket handshake is unnecessary and flaky for a
pure authz/redaction guarantee.
"""

import pytest

from app.api.ws import ConnectionManager, ViewerInfo, presence_subscribe_allowed
from app.models.user import User, UserRole


class _FakeWS:
    """Minimal stand-in for a Starlette WebSocket (presence broadcasts call
    ``send_json`` on subscribed sockets)."""

    async def send_json(self, *args, **kwargs):
        return None


# ── (a) unauthorized rejected / (b) authorized accepted ──────────────────────


@pytest.mark.parametrize(
    "role",
    [
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
def test_operational_roles_may_subscribe(role: UserRole):
    user = User(id=1, name="Op", email="op@example.com", role=role)
    assert presence_subscribe_allowed(user) is True


def test_viewer_role_may_not_subscribe():
    """The read-only viewer/client ``user`` role is refused (fail-closed)."""
    viewer = User(id=2, name="Viewer", email="v@example.com", role=UserRole.user)
    assert presence_subscribe_allowed(viewer) is False


def test_secondary_role_grants_subscribe():
    """Hybrid persona: primary viewer, secondary recruiter → allowed via the
    multi-role union (never a bare ``role ==`` comparison)."""
    user = User(
        id=3,
        name="Hybrid",
        email="h@example.com",
        role=UserRole.user,
        roles=[UserRole.user.value, UserRole.recruiter.value],
    )
    assert presence_subscribe_allowed(user) is True


@pytest.mark.asyncio
async def test_subscribe_handler_drops_viewer_admits_operational():
    """End-to-end through ``_handle_presence_message``: a viewer's subscribe is
    silently dropped for BOTH candidate and job channels; an operational role is
    admitted and appears in the snapshot."""
    from app.api.ws import _handle_presence_message, manager

    ws = _FakeWS()
    viewer = User(id=970001, name="V", email="v@example.com", role=UserRole.user)
    for resource_type in ("candidate", "job"):
        await _handle_presence_message(
            viewer,
            ws,
            {
                "type": "presence:subscribe",
                "resource_type": resource_type,
                "resource_id": 970001,
            },
        )
        assert manager.get_viewers(resource_type, 970001) == []

    recruiter = User(
        id=970002, name="R", email="r@example.com", role=UserRole.recruiter
    )
    await _handle_presence_message(
        recruiter,
        ws,
        {"type": "presence:subscribe", "resource_type": "job", "resource_id": 970002},
    )
    viewers = manager.get_viewers("job", 970002)
    assert len(viewers) == 1 and viewers[0]["user_id"] == 970002


@pytest.mark.asyncio
async def test_editing_signal_gated_for_viewer():
    """A viewer cannot even announce an ``editing`` flag on a channel."""
    from app.api.ws import _handle_presence_message, manager

    ws = _FakeWS()
    viewer = User(id=970003, name="V", email="v@example.com", role=UserRole.user)
    await _handle_presence_message(
        viewer,
        ws,
        {
            "type": "presence:editing",
            "resource_type": "candidate",
            "resource_id": 970003,
            "field": "phone",
            "active": True,
        },
    )
    assert manager.get_viewers("candidate", 970003) == []


# ── (c) payload contains no email/role ───────────────────────────────────────


def test_payload_omits_email_and_role():
    mgr = ConnectionManager()
    key = "candidate:42"
    mgr._viewers[key] = {7: set()}
    mgr._user_info[7] = ViewerInfo(user_id=7, name="Jan Kowalski")
    # The "who is editing" signal must still surface — that is presence's job.
    mgr._editing[key] = {7: {"phone"}}

    payload = mgr._build_viewers_payload(key)
    assert len(payload) == 1
    entry = payload[0]
    assert entry["user_id"] == 7
    assert entry["name"] == "Jan Kowalski"
    assert "email" not in entry
    assert "role" not in entry
    assert entry["editing"] == ["phone"]


def test_viewer_info_struct_stores_only_id_and_name():
    """Belt-and-suspenders: email/role are not even cached, so no future payload
    change can accidentally re-leak them."""
    assert set(ViewerInfo.__dataclass_fields__) == {"user_id", "name"}
