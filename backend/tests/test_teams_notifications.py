"""Tests for Teams notifications service + CRUD — Phase 7.6 of the M365 plan.

Two slices:

1. Service-level unit tests (no DB, no auth): Adaptive Card shape, kill-switch
   short-circuit, Graph request shape via :class:`httpx.MockTransport`, and the
   fan-out behavior of ``notify_teams`` against a stubbed session-style
   channel resolver.

2. API integration tests with the in-process ``app_client`` fixture: CRUD
   happy path, validation of unknown notification types, and uniqueness on
   (team_id, channel_id).

No real Graph calls are made — everything goes through ``MockTransport`` or
patches on ``settings.TEAMS_NOTIFICATIONS_ENABLED``.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.teams_channel import TeamsNotificationChannel
from app.models.user import User, UserRole
from app.services import teams_notifications
from app.services.teams_notifications import (
    NOTIFICATION_TYPES,
    TeamsConfig,
    TeamsNotConfigured,
    TeamsSendError,
    _reset_token_cache,
    _wrap_card_for_graph,
    build_candidate_card,
    build_contract_signed_card,
    build_decision_card,
    build_test_card,
    notify_teams,
    send_to_channel,
)


# Async tests get @pytest.mark.asyncio explicitly; sync card-shape tests do
# not (pytest-asyncio strict mode warns otherwise).


# ── Unit: Adaptive Card builders ────────────────────────────────────────────


def test_build_candidate_card_includes_facts_and_url() -> None:
    card = build_candidate_card(
        candidate_name="Jan Kowalski",
        role="Senior Python Developer",
        stage="cv_sent",
        recruiter="Anna Recruiter",
        profile_url="https://nexus.example/candidates/42",
    )
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.4"
    # Header text block prefixes with the default title.
    header = card["body"][0]
    assert "Nowy kandydat: Jan Kowalski" in header["text"]
    # FactSet contains the role + stage + recruiter.
    facts = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert facts["Rola:"] == "Senior Python Developer"
    assert facts["Etap:"] == "cv_sent"
    assert facts["Rekruter:"] == "Anna Recruiter"
    # Single OpenUrl action with the profile link.
    assert card["actions"][0]["type"] == "Action.OpenUrl"
    assert card["actions"][0]["url"] == "https://nexus.example/candidates/42"


def test_build_candidate_card_handles_missing_fields() -> None:
    card = build_candidate_card(
        candidate_name="Anna Nowak",
        role=None,
        stage=None,
        recruiter=None,
        profile_url="https://x/y",
    )
    facts = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert facts["Rola:"] == "—"
    assert facts["Etap:"] == "—"
    assert facts["Rekruter:"] == "—"


def test_build_decision_card_accepted_uses_good_color() -> None:
    card = build_decision_card(
        candidate_name="Jan Kowalski",
        decision="accepted",
        role="Backend Dev",
        actor="Manager",
        note=None,
        profile_url="https://x/y",
    )
    header = card["body"][0]
    assert header["color"] == "Good"
    assert header["text"] == "Weryfikacja zaakceptowana"


def test_build_decision_card_rejected_uses_attention_color_and_includes_note() -> None:
    card = build_decision_card(
        candidate_name="Jan Kowalski",
        decision="rejected",
        role="Backend Dev",
        actor="Manager",
        note="Stawka powyżej budżetu",
        profile_url="https://x/y",
    )
    header = card["body"][0]
    assert header["color"] == "Attention"
    assert header["text"] == "Weryfikacja odrzucona"
    facts = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert facts["Komentarz:"] == "Stawka powyżej budżetu"


def test_build_contract_signed_card_includes_dates_and_client() -> None:
    card = build_contract_signed_card(
        candidate_name="Jan Kowalski",
        client_name="Acme Corp",
        role="Senior",
        start_date="2026-06-01",
        contract_url="https://x/contracts/9",
    )
    facts = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert facts["Kandydat:"] == "Jan Kowalski"
    assert facts["Klient:"] == "Acme Corp"
    assert facts["Start:"] == "2026-06-01"
    assert card["actions"][0]["url"] == "https://x/contracts/9"


def test_build_test_card_has_two_text_blocks_and_action() -> None:
    card = build_test_card()
    assert len(card["body"]) >= 2
    assert card["body"][0]["text"] == "NEXUS — test powiadomień"
    assert card["actions"][0]["type"] == "Action.OpenUrl"


# ── Unit: Graph payload wrapping ────────────────────────────────────────────


def test_wrap_card_for_graph_serializes_card_to_string() -> None:
    card = build_test_card()
    wrapped = _wrap_card_for_graph(card)
    # Graph expects the card JSON as a string inside content.
    assert wrapped["body"]["contentType"] == "html"
    assert '<attachment id="1"></attachment>' in wrapped["body"]["content"]
    att = wrapped["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    parsed = json.loads(att["content"])
    assert parsed["type"] == "AdaptiveCard"


# ── Unit: kill-switch + config ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_to_channel_noop_when_kill_switch_off(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", False, raising=False)
    # MockTransport that would fail if reached — proves we short-circuit.
    transport = httpx.MockTransport(
        lambda req: pytest.fail(f"unexpected request: {req.url}")
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        sent = await send_to_channel(
            team_id="t1",
            channel_id="c1",
            card=build_test_card(),
            http_client=http_client,
        )
    assert sent is False


@pytest.mark.asyncio
async def test_notify_teams_noop_when_kill_switch_off(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", False, raising=False)
    # No DB session needed — the function returns 0 before any DB call.
    n = await notify_teams("candidate_added", {"candidate_name": "X"})
    assert n == 0


def test_teams_config_rejects_common_tenant(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "common", raising=False)
    monkeypatch.setattr(settings, "M365_TENANT_ID", "common", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "abc", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "def", raising=False)
    with pytest.raises(TeamsNotConfigured, match="common"):
        TeamsConfig.from_settings()


def test_teams_config_reuses_m365_creds(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "", raising=False)
    monkeypatch.setattr(settings, "M365_TENANT_ID", "tenant-guid-123", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(settings, "M365_CLIENT_ID", "m365-app", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "M365_CLIENT_SECRET", "shh", raising=False)
    cfg = TeamsConfig.from_settings()
    assert cfg.tenant_id == "tenant-guid-123"
    assert cfg.client_id == "m365-app"
    assert cfg.client_secret == "shh"


# ── Unit: Graph send with MockTransport ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_to_channel_posts_correct_graph_request(monkeypatch) -> None:
    from app.core.config import settings

    # Enable kill-switch + provide config.
    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "tenant-1", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "client-1", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "secret-1", raising=False)
    _reset_token_cache()

    # Patch token fetch to skip the OAuth round-trip.
    async def _fake_token(_config):
        return "fake-access-token"

    monkeypatch.setattr(
        teams_notifications, "_fetch_app_token", _fake_token, raising=True
    )

    seen_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["method"] = request.method
        seen_request["headers"] = dict(request.headers)
        seen_request["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "msg-1"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ok = await send_to_channel(
            team_id="team-abc",
            channel_id="19:channel-xyz",
            card=build_test_card(),
            http_client=client,
        )

    assert ok is True
    assert seen_request["method"] == "POST"
    assert (
        seen_request["url"]
        == "https://graph.microsoft.com/v1.0/teams/team-abc/channels/19:channel-xyz/messages"
    )
    assert seen_request["headers"]["authorization"] == "Bearer fake-access-token"
    # Body has the attachment shape + serialized card JSON.
    body = seen_request["body"]
    assert body["body"]["contentType"] == "html"
    assert "<attachment" in body["body"]["content"]
    parsed_card = json.loads(body["attachments"][0]["content"])
    assert parsed_card["type"] == "AdaptiveCard"


@pytest.mark.asyncio
async def test_send_to_channel_raises_on_403(monkeypatch) -> None:
    """Missing admin consent (typical 403) surfaces as TeamsSendError."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TEAMS_TENANT_ID", "tenant-1", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_ID", "client-1", raising=False)
    monkeypatch.setattr(settings, "TEAMS_CLIENT_SECRET", "secret-1", raising=False)
    _reset_token_cache()

    async def _fake_token(_config):
        return "fake-access-token"

    monkeypatch.setattr(
        teams_notifications, "_fetch_app_token", _fake_token, raising=True
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"code": "Forbidden", "message": "no consent"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TeamsSendError, match="403"):
            await send_to_channel(
                team_id="t",
                channel_id="c",
                card=build_test_card(),
                http_client=client,
            )


# ── Integration: CRUD API ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def cleanup_teams_channels() -> AsyncIterator[int]:
    """Wipe rows before + after each test that touches the table."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TeamsNotificationChannel))
        suffix = uuid.uuid4().hex[:8]
        creator = User(
            email=f"teams-channel-{suffix}@example.com",
            password_hash=hash_password("T3ams_fixture_pass!"),
            name=f"Teams Fixture {suffix}",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(creator)
        await db.commit()
        await db.refresh(creator)
        creator_id = creator.id
    yield creator_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(TeamsNotificationChannel))
        await db.execute(delete(User).where(User.id == creator_id))
        await db.commit()


@pytest.mark.asyncio
async def test_list_channels_empty(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    r = await app_client.get("/api/teams-channels", headers=app_auth_headers)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_channel_happy_path(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    r = await app_client.post(
        "/api/teams-channels",
        headers=app_auth_headers,
        json={
            "workspace_label": "ATS Deals",
            "team_id": "team-uuid",
            "channel_id": "19:channel-xyz",
            "notification_types": ["candidate_added", "contract_signed"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workspace_label"] == "ATS Deals"
    assert body["enabled"] is True
    assert set(body["notification_types"]) == {"candidate_added", "contract_signed"}

    r = await app_client.get("/api/teams-channels", headers=app_auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_create_channel_rejects_unknown_type(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    r = await app_client.post(
        "/api/teams-channels",
        headers=app_auth_headers,
        json={
            "workspace_label": "Bad",
            "team_id": "t",
            "channel_id": "c",
            "notification_types": ["candidate_added", "made_up_type"],
        },
    )
    assert r.status_code == 422
    detail_text = json.dumps(r.json())
    assert "made_up_type" in detail_text


@pytest.mark.asyncio
async def test_create_channel_409_on_duplicate(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    payload = {
        "workspace_label": "First",
        "team_id": "team-1",
        "channel_id": "channel-1",
        "notification_types": ["candidate_added"],
    }
    r1 = await app_client.post(
        "/api/teams-channels", headers=app_auth_headers, json=payload
    )
    assert r1.status_code == 201
    payload["workspace_label"] = "Second"
    r2 = await app_client.post(
        "/api/teams-channels", headers=app_auth_headers, json=payload
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_patch_channel_toggles_enabled(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    r = await app_client.post(
        "/api/teams-channels",
        headers=app_auth_headers,
        json={
            "workspace_label": "Test",
            "team_id": "t",
            "channel_id": "c",
            "notification_types": ["candidate_added"],
        },
    )
    cid = r.json()["id"]

    r = await app_client.patch(
        f"/api/teams-channels/{cid}",
        headers=app_auth_headers,
        json={"enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_channel(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
) -> None:
    r = await app_client.post(
        "/api/teams-channels",
        headers=app_auth_headers,
        json={
            "workspace_label": "Del",
            "team_id": "t",
            "channel_id": "c",
            "notification_types": ["candidate_added"],
        },
    )
    cid = r.json()["id"]
    r = await app_client.delete(f"/api/teams-channels/{cid}", headers=app_auth_headers)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_test_endpoint_reports_killswitch_off(
    app_client: AsyncClient,
    app_auth_headers: dict,
    cleanup_teams_channels: int,
    monkeypatch,
) -> None:
    """Test button surfaces a readable error when integration is disabled."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", False, raising=False)
    r = await app_client.post(
        "/api/teams-channels",
        headers=app_auth_headers,
        json={
            "workspace_label": "ToTest",
            "team_id": "t",
            "channel_id": "c",
            "notification_types": ["candidate_added"],
        },
    )
    cid = r.json()["id"]

    r = await app_client.post(
        f"/api/teams-channels/{cid}/test", headers=app_auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is False
    assert "TEAMS_NOTIFICATIONS_ENABLED" in (body.get("detail") or "")


# ── Integration: trigger fan-out via stubbed sender ─────────────────────────


@pytest.mark.asyncio
async def test_notify_teams_fans_out_to_subscribed_channels(
    cleanup_teams_channels: int,
    monkeypatch,
) -> None:
    """Two enabled channels subscribed to `candidate_added` → two sends.

    Stubs ``fire_and_forget_send`` so we can assert how many calls landed
    without doing any HTTP. The kill-switch must be on for the function to
    reach the fan-out branch.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "TEAMS_NOTIFICATIONS_ENABLED", True, raising=False)

    async with AsyncSessionLocal() as db:
        db.add(
            TeamsNotificationChannel(
                workspace_label="Subscribed A",
                team_id="t-a",
                channel_id="c-a",
                notification_types=["candidate_added"],
                enabled=True,
                created_by_user_id=cleanup_teams_channels,
            )
        )
        db.add(
            TeamsNotificationChannel(
                workspace_label="Subscribed B",
                team_id="t-b",
                channel_id="c-b",
                notification_types=["candidate_added", "contract_signed"],
                enabled=True,
                created_by_user_id=cleanup_teams_channels,
            )
        )
        db.add(
            TeamsNotificationChannel(
                workspace_label="Wrong event",
                team_id="t-c",
                channel_id="c-c",
                notification_types=["contract_signed"],
                enabled=True,
                created_by_user_id=cleanup_teams_channels,
            )
        )
        db.add(
            TeamsNotificationChannel(
                workspace_label="Disabled",
                team_id="t-d",
                channel_id="c-d",
                notification_types=["candidate_added"],
                enabled=False,
                created_by_user_id=cleanup_teams_channels,
            )
        )
        await db.commit()

    sender = AsyncMock()
    with patch.object(teams_notifications, "fire_and_forget_send", sender):
        attempted = await notify_teams(
            "candidate_added",
            {
                "candidate_name": "Jan Kowalski",
                "role": "Dev",
                "stage": "new",
                "recruiter": "Anna",
                "profile_url": "https://nexus.example/c/1",
            },
        )

    # Only 2 channels match: Subscribed A + B. Wrong event and Disabled
    # excluded by the JSONB containment + partial index filter.
    assert attempted == 2
    assert sender.await_count == 2


def test_notification_types_constant_exposes_expected_keys() -> None:
    """Guard against accidental rename — the FE chip set relies on these."""
    assert NOTIFICATION_TYPES == frozenset(
        {
            "candidate_added",
            "decision_accepted",
            "decision_rejected",
            "contract_signed",
        }
    )
