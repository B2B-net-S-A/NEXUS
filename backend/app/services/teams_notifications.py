"""Microsoft Teams notifications via Graph API — Phase 7.6 of the M365 plan.

Builds Adaptive Cards for ATS events (candidate added, verification decision,
contract signed) and posts them to configured Teams channels.

Auth model: application-only via OAuth 2.0 client credentials flow. A single
AAD app principal does the posting — no per-user OAuth here, because the
ATS-event notifications are system-driven, not user-driven. The AAD app needs
the **Application** permission ``ChannelMessage.Send`` with admin consent
granted; without it Graph returns 403 and the send fails (logged, swallowed —
this is fire-and-forget from the trigger sites).

Token caching: the client_credentials token is cached in-process for ~80% of
its `expires_in` so we don't hit the token endpoint on every event. The cache
is a module-level dict because the AAD app principal is one identity for the
whole process (unlike per-user delegated tokens in
:mod:`app.services.m365.graph_client`).

Notification types (mirrored on the FE):
    candidate_added       — POST /api/candidates created a row
    decision_accepted     — pipeline.accept_verification
    decision_rejected     — pipeline.reject_verification
    contract_signed       — contracts.finalize_contract_draft or .activate

All cards link back to the relevant Nexus page via Action.OpenUrl. The base
URL comes from ``settings.PUBLIC_BASE_URL``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.recruitment_pipeline import CandidateStage
from app.models.teams_channel import TeamsNotificationChannel
from app.services.client_identity import client_display_name

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
ADAPTIVE_CARD_VERSION = "1.4"
ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"

# All supported notification type keys. Kept as a frozenset so unknown keys
# can be rejected at the API layer (validate user input early).
NOTIFICATION_TYPES: frozenset[str] = frozenset(
    {
        "candidate_added",
        "decision_accepted",
        "decision_rejected",
        "contract_signed",
    }
)


# ── Exceptions ───────────────────────────────────────────────────────────────


class TeamsNotConfigured(RuntimeError):
    """Raised when the kill-switch is on but a caller forced a send anyway."""


class TeamsSendError(RuntimeError):
    """Graph returned a non-2xx response we cannot interpret as success."""


# ── Config resolution ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TeamsConfig:
    """Resolved AAD client credentials. Reuses the M365 app registration when
    Teams-specific settings are blank — admins typically grant
    ``ChannelMessage.Send`` on the same app that already holds Mail/Calendar
    permissions, so a separate AAD app is unnecessary.
    """

    tenant_id: str
    client_id: str
    client_secret: str

    @classmethod
    def from_settings(cls) -> "TeamsConfig":
        tenant = (settings.TEAMS_TENANT_ID or settings.M365_TENANT_ID or "").strip()
        client_id = (settings.TEAMS_CLIENT_ID or settings.M365_CLIENT_ID or "").strip()
        client_secret = (
            settings.TEAMS_CLIENT_SECRET or settings.M365_CLIENT_SECRET or ""
        ).strip()
        if not tenant or tenant == "common":
            raise TeamsNotConfigured(
                "TEAMS_TENANT_ID (or M365_TENANT_ID) must be a concrete tenant "
                "GUID for client_credentials flow — 'common' is not allowed."
            )
        if not client_id or not client_secret:
            raise TeamsNotConfigured(
                "TEAMS_CLIENT_ID and TEAMS_CLIENT_SECRET (or the M365_ fallbacks) "
                "must be set with admin consent for ChannelMessage.Send."
            )
        return cls(tenant_id=tenant, client_id=client_id, client_secret=client_secret)


# ── App-only token cache ─────────────────────────────────────────────────────


_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


async def _fetch_app_token(config: TeamsConfig) -> str:
    """Return a cached or freshly minted application access token.

    Cache TTL is 80% of `expires_in` so the next call refreshes before the
    token actually dies — prevents racing the clock when the token is used in
    a long-running trigger.
    """
    now = time.monotonic()
    cached = _token_cache.get("token")
    expires_at = float(_token_cache.get("expires_at") or 0.0)
    if cached and expires_at > now:
        return cached

    async with _token_lock:
        # Re-check inside the lock — another coroutine may have refreshed.
        now = time.monotonic()
        cached = _token_cache.get("token")
        expires_at = float(_token_cache.get("expires_at") or 0.0)
        if cached and expires_at > now:
            return cached

        url = f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
        if resp.status_code >= 400:
            raise TeamsSendError(
                f"Token endpoint returned {resp.status_code}: {resp.text[:300]}"
            )
        body = resp.json()
        token = body["access_token"]
        expires_in = int(body.get("expires_in", 3600))
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + (expires_in * 0.8)
        return token


def _reset_token_cache() -> None:
    """Test helper — drop the cached token so a fresh fetch happens."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


# ── Profile URL helper ───────────────────────────────────────────────────────


def _public_base() -> str:
    """Return the public app URL without trailing slash for link building."""
    return (settings.PUBLIC_BASE_URL or "https://nexus.dynaminds.pl").rstrip("/")


# ── Adaptive Card builders ───────────────────────────────────────────────────


def _card_envelope(body: list[dict], actions: list[dict]) -> dict[str, Any]:
    """Return a complete Adaptive Card JSON envelope."""
    return {
        "type": "AdaptiveCard",
        "$schema": ADAPTIVE_CARD_SCHEMA,
        "version": ADAPTIVE_CARD_VERSION,
        "body": body,
        "actions": actions,
    }


def build_candidate_card(
    *,
    candidate_name: str,
    role: Optional[str],
    stage: Optional[str],
    recruiter: Optional[str],
    profile_url: str,
    title: str = "Nowy kandydat",
) -> dict[str, Any]:
    """Build an Adaptive Card for a candidate-added event.

    All fields are stringified by the FactSet renderer, so we pass them as-is.
    Missing optional fields render as an em-dash to keep card layout stable
    even when the source row is partial.
    """
    facts = [
        {"title": "Rola:", "value": role or "—"},
        {"title": "Etap:", "value": stage or "—"},
        {"title": "Rekruter:", "value": recruiter or "—"},
    ]
    body = [
        {
            "type": "TextBlock",
            "text": f"{title}: {candidate_name}",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {"type": "FactSet", "facts": facts},
    ]
    actions = [{"type": "Action.OpenUrl", "title": "Zobacz profil", "url": profile_url}]
    return _card_envelope(body, actions)


def build_decision_card(
    *,
    candidate_name: str,
    decision: str,  # "accepted" | "rejected"
    role: Optional[str],
    actor: Optional[str],
    note: Optional[str],
    profile_url: str,
) -> dict[str, Any]:
    """Build an Adaptive Card for a verification accept/reject decision."""
    is_accept = decision == "accepted"
    title_pl = "Weryfikacja zaakceptowana" if is_accept else "Weryfikacja odrzucona"
    facts = [
        {"title": "Kandydat:", "value": candidate_name},
        {"title": "Rola:", "value": role or "—"},
        {"title": "Decyzja:", "value": "Akceptacja" if is_accept else "Odrzucenie"},
        {"title": "Manager:", "value": actor or "—"},
    ]
    if note:
        facts.append({"title": "Komentarz:", "value": note})
    body = [
        {
            "type": "TextBlock",
            "text": title_pl,
            "weight": "Bolder",
            "size": "Medium",
            "color": "Good" if is_accept else "Attention",
            "wrap": True,
        },
        {"type": "FactSet", "facts": facts},
    ]
    actions = [{"type": "Action.OpenUrl", "title": "Zobacz profil", "url": profile_url}]
    return _card_envelope(body, actions)


def build_contract_signed_card(
    *,
    candidate_name: str,
    client_name: Optional[str],
    role: Optional[str],
    start_date: Optional[str],
    contract_url: str,
) -> dict[str, Any]:
    """Build an Adaptive Card for a contract finalize/activate event."""
    facts = [
        {"title": "Kandydat:", "value": candidate_name},
        {"title": "Klient:", "value": client_name or "—"},
        {"title": "Rola:", "value": role or "—"},
        {"title": "Start:", "value": start_date or "—"},
    ]
    body = [
        {
            "type": "TextBlock",
            "text": f"Umowa podpisana: {candidate_name}",
            "weight": "Bolder",
            "size": "Medium",
            "color": "Good",
            "wrap": True,
        },
        {"type": "FactSet", "facts": facts},
    ]
    actions = [{"type": "Action.OpenUrl", "title": "Zobacz umowę", "url": contract_url}]
    return _card_envelope(body, actions)


def build_test_card() -> dict[str, Any]:
    """Card used by the /test endpoint to verify a channel is wired up."""
    body = [
        {
            "type": "TextBlock",
            "text": "NEXUS — test powiadomień",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "TextBlock",
            "text": (
                "Jeśli widzisz tę wiadomość, integracja NEXUS ↔ Teams działa. "
                "Możesz teraz włączyć typy powiadomień w panelu ustawień."
            ),
            "wrap": True,
        },
    ]
    actions = [
        {
            "type": "Action.OpenUrl",
            "title": "Otwórz NEXUS",
            "url": _public_base(),
        }
    ]
    return _card_envelope(body, actions)


# ── Graph send ───────────────────────────────────────────────────────────────


def _wrap_card_for_graph(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap an Adaptive Card in the Graph chat-message attachment envelope.

    Graph expects the card JSON to be serialized as a string inside an
    `attachments[].content` field — the message body references it by
    attachment id (a uuid-ish string we generate locally).
    """
    attachment_id = "1"
    return {
        "body": {
            "contentType": "html",
            "content": f'<attachment id="{attachment_id}"></attachment>',
        },
        "attachments": [
            {
                "id": attachment_id,
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": json.dumps(card),
            }
        ],
    }


async def send_to_channel(
    *,
    team_id: str,
    channel_id: str,
    card: dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """POST an Adaptive Card to a Teams channel via Graph.

    Returns True on 2xx, raises :class:`TeamsSendError` otherwise. Callers in
    trigger sites typically want fire-and-forget — wrap with
    :func:`fire_and_forget_send` which swallows errors.

    `http_client` is injectable for tests (httpx.MockTransport). In production
    we create a short-lived client per call — the request is one-shot and the
    semaphore in :mod:`graph_client` doesn't apply because we're not using a
    per-user token here.
    """
    if not settings.TEAMS_NOTIFICATIONS_ENABLED:
        logger.debug(
            "Teams send skipped (kill-switch off): team=%s channel=%s",
            team_id,
            channel_id,
        )
        return False

    config = TeamsConfig.from_settings()
    token = await _fetch_app_token(config)

    url = f"{GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
    payload = _wrap_card_for_graph(card)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(url, headers=headers, json=payload)
    finally:
        if owns_client:
            await client.aclose()

    if 200 <= resp.status_code < 300:
        return True
    # 401 means the cached token is stale (rare — we refresh at 80% TTL) or
    # revoked. Drop the cache so the next attempt re-fetches.
    if resp.status_code == 401:
        _reset_token_cache()
    raise TeamsSendError(f"Graph POST {url} -> {resp.status_code}: {resp.text[:300]}")


async def fire_and_forget_send(
    *,
    team_id: str,
    channel_id: str,
    card: dict[str, Any],
) -> None:
    """Send a card, swallow any error.

    Used by trigger sites that must NOT block the user response on a Teams
    failure. Errors are logged at WARN with channel context so they show up
    in Grafana/Sentry without poisoning the calling request.
    """
    try:
        await send_to_channel(team_id=team_id, channel_id=channel_id, card=card)
    except Exception as exc:  # noqa: BLE001 — intentional swallow
        logger.warning(
            "Teams notification send failed for team=%s channel=%s: %s",
            team_id,
            channel_id,
            exc,
        )


# ── Trigger fan-out ──────────────────────────────────────────────────────────


async def _channels_for_event(
    db: AsyncSession, event_type: str
) -> list[TeamsNotificationChannel]:
    """Return all enabled channels subscribed to `event_type`.

    Uses the JSONB containment operator `@>` so the partial index on
    `enabled=true` + the planner's @> filter run in a single index scan.
    """
    stmt = (
        select(TeamsNotificationChannel)
        .where(TeamsNotificationChannel.enabled.is_(True))
        .where(
            TeamsNotificationChannel.notification_types.contains(  # type: ignore[attr-defined]
                [event_type]
            )
        )
    )
    return list((await db.execute(stmt)).scalars().all())


def _build_card_for_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch to the right card builder based on event type."""
    if event_type == "candidate_added":
        return build_candidate_card(
            candidate_name=payload["candidate_name"],
            role=payload.get("role"),
            stage=payload.get("stage"),
            recruiter=payload.get("recruiter"),
            profile_url=payload["profile_url"],
        )
    if event_type in ("decision_accepted", "decision_rejected"):
        return build_decision_card(
            candidate_name=payload["candidate_name"],
            decision="accepted" if event_type == "decision_accepted" else "rejected",
            role=payload.get("role"),
            actor=payload.get("actor"),
            note=payload.get("note"),
            profile_url=payload["profile_url"],
        )
    if event_type == "contract_signed":
        return build_contract_signed_card(
            candidate_name=payload["candidate_name"],
            client_name=payload.get("client_name"),
            role=payload.get("role"),
            start_date=payload.get("start_date"),
            contract_url=payload["contract_url"],
        )
    raise ValueError(f"Unknown Teams notification event type: {event_type}")


async def notify_teams(
    event_type: str,
    payload: dict[str, Any],
    *,
    db: Optional[AsyncSession] = None,
) -> int:
    """Send an event card to every enabled channel subscribed to `event_type`.

    Returns the number of channels we attempted to deliver to (NOT a success
    count — every send is fire-and-forget). Returns 0 immediately when the
    kill-switch is off so the caller's DB query is also skipped.

    Owns its own session by default so the function is safe to schedule via
    ``asyncio.create_task(...)`` after the caller's request has returned. Pass
    `db` explicitly only from tests or other contexts where the caller wants
    to share a session.
    """
    if not settings.TEAMS_NOTIFICATIONS_ENABLED:
        return 0
    if event_type not in NOTIFICATION_TYPES:
        logger.warning("notify_teams ignored unknown event_type=%r", event_type)
        return 0

    if db is None:
        async with AsyncSessionLocal() as own_db:
            return await _notify_teams_inner(own_db, event_type, payload)
    return await _notify_teams_inner(db, event_type, payload)


async def _notify_teams_inner(
    db: AsyncSession, event_type: str, payload: dict[str, Any]
) -> int:
    channels = await _channels_for_event(db, event_type)
    if not channels:
        return 0

    try:
        card = _build_card_for_event(event_type, payload)
    except (KeyError, ValueError) as exc:
        logger.warning(
            "notify_teams could not build card for event=%s: %s", event_type, exc
        )
        return 0

    sends = [
        fire_and_forget_send(team_id=c.team_id, channel_id=c.channel_id, card=card)
        for c in channels
    ]
    # asyncio.gather with return_exceptions so a single bad channel doesn't
    # abort the rest. Each send already swallows its own errors via
    # fire_and_forget_send, so this is belt-and-suspenders.
    await asyncio.gather(*sends, return_exceptions=True)
    return len(channels)


# ── Payload helpers used by trigger call sites ──────────────────────────────


def candidate_payload(
    *,
    candidate: Candidate,
    recruiter_name: Optional[str],
    role: Optional[str] = None,
    stage: Optional[str] = None,
) -> dict[str, Any]:
    """Build the candidate_added payload from an ORM row."""
    full_name = f"{candidate.name} {candidate.lastname}".strip()
    return {
        "candidate_name": full_name or f"#{candidate.id}",
        "role": role,
        "stage": stage,
        "recruiter": recruiter_name,
        "profile_url": f"{_public_base()}/candidates/{candidate.id}",
    }


def decision_payload(
    *,
    candidate: Candidate,
    stage: CandidateStage,
    actor_name: Optional[str],
    role: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Build the decision_{accepted,rejected} payload."""
    full_name = f"{candidate.name} {candidate.lastname}".strip()
    return {
        "candidate_name": full_name or f"#{candidate.id}",
        "role": role,
        "actor": actor_name,
        "note": note,
        "profile_url": f"{_public_base()}/candidates/{candidate.id}",
    }


def contract_payload(
    *,
    contract: Contract,
    candidate_name: str,
    client_name: Optional[str],
    role: Optional[str] = None,
) -> dict[str, Any]:
    """Build the contract_signed payload."""
    start = contract.start_date.isoformat() if contract.start_date else None
    return {
        "candidate_name": candidate_name,
        "client_name": client_name,
        "role": role,
        "start_date": start,
        "contract_url": f"{_public_base()}/contracts/{contract.id}",
    }


# ── Higher-level trigger helpers (resolve ORM rows in own session) ──────────


async def notify_decision_by_stage_id(
    candidate_stage_id: int,
    *,
    decision: str,  # "accepted" | "rejected"
    actor_name: Optional[str],
    note: Optional[str] = None,
) -> int:
    """Background-task helper for pipeline accept/reject endpoints.

    Owns its own AsyncSession so callers can ``asyncio.create_task(...)`` after
    their request returns. Returns 0 if the stage row is gone (e.g. deleted
    between the trigger and the task firing).
    """
    if not settings.TEAMS_NOTIFICATIONS_ENABLED:
        return 0
    event_type = "decision_accepted" if decision == "accepted" else "decision_rejected"
    async with AsyncSessionLocal() as db:
        from app.models.job import Job

        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.id == candidate_stage_id)
        )
        if stage is None:
            return 0
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == stage.candidate_id)
        )
        if candidate is None:
            return 0
        job = await db.scalar(select(Job).where(Job.id == stage.job_id))
        role = job.title if job is not None else None
        payload = decision_payload(
            candidate=candidate,
            stage=stage,
            actor_name=actor_name,
            role=role,
            note=note,
        )
        return await notify_teams(event_type, payload, db=db)


async def notify_contract_signed_by_id(
    contract_id: int,
) -> int:
    """Background-task helper for contract finalize/activate endpoints."""
    if not settings.TEAMS_NOTIFICATIONS_ENABLED:
        return 0
    async with AsyncSessionLocal() as db:
        from sqlalchemy.orm import selectinload

        from app.models.client import Client
        from app.models.job import Job

        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(
                selectinload(Contract.candidate),
                selectinload(Contract.client),
                selectinload(Contract.job),
            )
        )
        if contract is None:
            return 0
        candidate_name = (
            f"{contract.candidate.name} {contract.candidate.lastname}".strip()
            if contract.candidate
            else f"#{contract.candidate_id}"
        )
        client_name = (
            client_display_name(contract.client)
            if isinstance(contract.client, Client)
            else None
        )
        role = contract.job.title if isinstance(contract.job, Job) else None
        payload = contract_payload(
            contract=contract,
            candidate_name=candidate_name,
            client_name=client_name,
            role=role,
        )
        return await notify_teams("contract_signed", payload, db=db)
