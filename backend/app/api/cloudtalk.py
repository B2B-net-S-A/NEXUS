"""CloudTalk REST endpoints — agents listing/mapping + click-to-call.

All endpoints return HTTP 503 when ``settings.CLOUDTALK_ENABLED`` is False
(the kill-switch). Agent mapping persists ``users.cloudtalk_agent_id`` so
the inbound webhook can resolve ``Call.user_id`` and the outbound endpoint
knows which CloudTalk seat to ring.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.models.call import Call, CallDirection, CallStatus
from app.models.candidate import Candidate
from app.models.user import User
from app.services.cloudtalk import (
    CloudTalkAuthError,
    CloudTalkClient,
    CloudTalkConfig,
    CloudTalkError,
)
from app.services.dedup_service import _normalize_phone

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_enabled() -> None:
    if not settings.CLOUDTALK_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CloudTalk integration disabled (CLOUDTALK_ENABLED=false)",
        )


# ── Schemas ─────────────────────────────────────────────────────────────────


class CloudTalkAgent(BaseModel):
    id: int
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[str] = None
    default_number: Optional[str] = None
    linked_user_id: Optional[int] = None
    linked_user_email: Optional[str] = None


class AgentAssignRequest(BaseModel):
    user_id: int


class SyncAgentsResponse(BaseModel):
    linked: int
    unmatched: list[CloudTalkAgent]
    already_linked: int


class InitiateCallRequest(BaseModel):
    candidate_id: int


class InitiateCallResponse(BaseModel):
    call_id: int
    candidate_id: int
    phone: str
    cloudtalk_response: dict


# ── Helpers ────────────────────────────────────────────────────────────────


async def _build_agent_list(
    db: AsyncSession, raw_agents: list[dict]
) -> list[CloudTalkAgent]:
    """Annotate CloudTalk agents with linked-user info (one query)."""
    by_id: dict[int, dict] = {}
    for a in raw_agents:
        try:
            agent_id = int(a.get("id"))
        except (TypeError, ValueError):
            continue
        by_id[agent_id] = a

    users_map: dict[int, User] = {}
    if by_id:
        result = await db.execute(
            select(User).where(User.cloudtalk_agent_id.in_(list(by_id.keys())))
        )
        for u in result.scalars().all():
            if u.cloudtalk_agent_id is not None:
                users_map[u.cloudtalk_agent_id] = u

    out: list[CloudTalkAgent] = []
    for agent_id, a in by_id.items():
        linked = users_map.get(agent_id)
        out.append(
            CloudTalkAgent(
                id=agent_id,
                firstname=a.get("firstname"),
                lastname=a.get("lastname"),
                email=a.get("email"),
                default_number=a.get("default_number") or a.get("phone"),
                linked_user_id=linked.id if linked else None,
                linked_user_email=linked.email if linked else None,
            )
        )
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/agents", response_model=list[CloudTalkAgent])
async def list_cloudtalk_agents(
    current_user: AdminUser,  # noqa: ARG001 — auth gate only
    db: AsyncSession = Depends(get_db),
):
    """List CloudTalk agents with linked-user annotation."""
    _require_enabled()
    try:
        cfg = CloudTalkConfig.from_settings()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        async with CloudTalkClient(cfg) as ct:
            raw = await ct.list_agents(limit=100)
    except CloudTalkAuthError as exc:
        logger.warning(
            "CloudTalk auth failed — check CLOUDTALK_API_KEY_ID/SECRET: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CloudTalk integration not configured (auth failed)",
        ) from exc
    except CloudTalkError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CloudTalk error: {exc.status}",
        ) from exc

    return await _build_agent_list(db, raw)


@router.post("/agents/{agent_id}/assign")
async def assign_agent_to_user(
    agent_id: int,
    payload: AgentAssignRequest,
    current_user: AdminUser,  # noqa: ARG001 — auth gate only
    db: AsyncSession = Depends(get_db),
):
    """Bind a CloudTalk agent to a Nexus user.

    Idempotent: setting the same mapping twice is a no-op. Setting a
    different user clears the previous owner of that agent_id (UNIQUE
    constraint).
    """
    _require_enabled()

    target = await db.scalar(select(User).where(User.id == payload.user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {payload.user_id} not found",
        )

    # Clear any other user currently owning this agent_id.
    other = await db.scalar(
        select(User)
        .where(User.cloudtalk_agent_id == agent_id)
        .where(User.id != payload.user_id)
    )
    if other is not None:
        other.cloudtalk_agent_id = None

    target.cloudtalk_agent_id = agent_id
    await db.commit()
    return {"user_id": target.id, "cloudtalk_agent_id": agent_id, "status": "ok"}


@router.delete("/agents/{agent_id}/assign")
async def unassign_agent(
    agent_id: int,
    current_user: AdminUser,  # noqa: ARG001 — auth gate only
    db: AsyncSession = Depends(get_db),
):
    """Remove the mapping for a CloudTalk agent."""
    _require_enabled()
    user = await db.scalar(select(User).where(User.cloudtalk_agent_id == agent_id))
    if user is None:
        return {"status": "noop"}
    user.cloudtalk_agent_id = None
    await db.commit()
    return {"status": "ok", "former_user_id": user.id}


@router.post("/sync-agents", response_model=SyncAgentsResponse)
async def sync_agents(
    current_user: AdminUser,  # noqa: ARG001 — auth gate only
    db: AsyncSession = Depends(get_db),
):
    """Fetch CloudTalk agents and auto-link them to users by email match.

    Returns counts of newly-linked / already-linked / unmatched. Users that
    already have a different ``cloudtalk_agent_id`` are left alone — the UI
    is the only path to overwrite an existing mapping.
    """
    _require_enabled()
    try:
        cfg = CloudTalkConfig.from_settings()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        async with CloudTalkClient(cfg) as ct:
            raw = await ct.list_agents(limit=100)
    except CloudTalkAuthError as exc:
        logger.warning(
            "CloudTalk auth failed — check CLOUDTALK_API_KEY_ID/SECRET: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CloudTalk integration not configured (auth failed)",
        ) from exc
    except CloudTalkError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CloudTalk error: {exc.status}",
        ) from exc

    linked = 0
    already = 0
    unmatched: list[CloudTalkAgent] = []

    for a in raw:
        try:
            agent_id = int(a.get("id"))
        except (TypeError, ValueError):
            continue

        email = (a.get("email") or "").strip().lower()
        if not email:
            unmatched.append(
                CloudTalkAgent(
                    id=agent_id,
                    firstname=a.get("firstname"),
                    lastname=a.get("lastname"),
                )
            )
            continue

        user = await db.scalar(select(User).where(User.email.ilike(email)))
        if user is None:
            unmatched.append(
                CloudTalkAgent(
                    id=agent_id,
                    firstname=a.get("firstname"),
                    lastname=a.get("lastname"),
                    email=email,
                )
            )
            continue

        if user.cloudtalk_agent_id == agent_id:
            already += 1
            continue
        if user.cloudtalk_agent_id is None:
            user.cloudtalk_agent_id = agent_id
            linked += 1

    await db.commit()
    return SyncAgentsResponse(
        linked=linked, already_linked=already, unmatched=unmatched
    )


@router.post("/initiate-call", response_model=InitiateCallResponse)
async def initiate_call(
    payload: InitiateCallRequest,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Trigger CloudTalk to ring the current user's softphone, then dial
    the candidate's phone.

    Pre-conditions:
      - ``CLOUDTALK_ENABLED=true``
      - ``current_user.cloudtalk_agent_id is not None`` (412 otherwise)
      - candidate has a non-empty ``phone`` (400 otherwise)

    On success we stub a ``Call`` row with ``status=initiated`` so the UI
    can show an in-progress indicator immediately. The CloudTalk webhook
    (Phase 1) will UPDATE the same row by ``cloudtalk_call_id`` once the
    call ends and the transcript/recording become available.
    """
    _require_enabled()

    if current_user.cloudtalk_agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "Your account is not mapped to a CloudTalk agent. Open "
                "Settings → Integrations → CloudTalk and assign your agent."
            ),
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == payload.candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )
    if not candidate.phone or not _normalize_phone(candidate.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate has no phone number",
        )

    try:
        cfg = CloudTalkConfig.from_settings()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        async with CloudTalkClient(cfg) as ct:
            response = await ct.initiate_call(
                agent_id=current_user.cloudtalk_agent_id,
                phone_number=candidate.phone,
            )
    except CloudTalkAuthError as exc:
        logger.warning(
            "CloudTalk auth failed — check CLOUDTALK_API_KEY_ID/SECRET: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CloudTalk integration not configured (auth failed)",
        ) from exc
    except CloudTalkError as exc:
        logger.warning(
            "CloudTalk initiate_call failed for user=%s candidate=%s: %s",
            current_user.id,
            candidate.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CloudTalk initiate failed: {exc.status}",
        ) from exc

    # Stub the Call row. cloudtalk_call_id may be in the response — if not,
    # the webhook will INSERT a fresh row later (a duplicate, but harmless
    # because we don't unique-constrain on user/candidate/started_at and
    # the UI dedups by id anyway). When present, we save it so the webhook
    # UPSERT matches and updates this same row.
    ct_call_id: Optional[str] = None
    if isinstance(response, dict):
        data = response.get("data") or response.get("responseData") or response
        if isinstance(data, dict):
            raw_id = data.get("call_id") or data.get("id")
            if raw_id is not None:
                ct_call_id = str(raw_id)

    call = Call(
        candidate_id=candidate.id,
        user_id=current_user.id,
        direction=CallDirection.outbound,
        status=CallStatus.initiated,
        cloudtalk_call_id=ct_call_id,
        cloudtalk_agent_id=current_user.cloudtalk_agent_id,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    return InitiateCallResponse(
        call_id=call.id,
        candidate_id=candidate.id,
        phone=candidate.phone,
        cloudtalk_response=response if isinstance(response, dict) else {},
    )
