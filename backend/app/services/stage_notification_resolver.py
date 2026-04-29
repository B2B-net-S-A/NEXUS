"""Resolver odbiorców powiadomień stage transition.

Wejście: ``CandidateStage`` po ruchu + poprzedni ``CandidateStage`` (jeśli był)
+ ``Job`` + ``Candidate`` + ``mover_user_id``.

Wyjście: lista ``ResolvedRecipient(user_id, notify_inapp, notify_email)``.

Logika:
1. **Forward-only** — jeśli previous_stage.stage_def.order >= new_stage.stage_def.order,
   zwróć [] (cofnięcie kandydata nie wysyła notyfikacji). Pierwszy ruch
   (previous_stage is None) traktujemy jako forward.
2. **Override priority** — jeśli istnieje ≥1 aktywny override dla pary
   (job.client_id, stage_def_id), użyj ich; inaczej baseline rules.
3. **Recipient resolution** — wg ``RecipientType``.
4. **Self-suppression** — usuń ``mover_user_id``.
5. **Aktywni** — User.is_active=True.
6. **Merge** — ten sam user w kilku regułach: OR(in-app), OR(email).
7. **None drop** — reguła bez user_id (np. ``client_head_dl`` bez head'a) →
   warning log + skip (bezpieczniej niż spam wszystkich DL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.stage_notification import (
    ClientStageNotificationOverride,
    RecipientType,
    StageNotificationRule,
)
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedRecipient:
    """Pojedynczy odbiorca po rozwiązaniu reguł.

    ``notify_inapp``/``notify_email`` to OR ze wszystkich reguł targetujących
    tego usera — jeden wpis per user_id niezależnie ile reguł go wskazuje.
    """

    user_id: int
    notify_inapp: bool
    notify_email: bool


# Wszystkie reguły mają ten sam shape (typeshare-friendly).
@dataclass(frozen=True)
class _RuleSnapshot:
    recipient_type: RecipientType
    specific_user_id: Optional[int]
    role: Optional[str]
    notify_inapp: bool
    notify_email: bool


def _snapshot_rule(rule: StageNotificationRule) -> _RuleSnapshot:
    return _RuleSnapshot(
        recipient_type=rule.recipient_type,
        specific_user_id=rule.specific_user_id,
        role=rule.role,
        notify_inapp=rule.notify_inapp,
        notify_email=rule.notify_email,
    )


def _snapshot_override(rule: ClientStageNotificationOverride) -> _RuleSnapshot:
    return _RuleSnapshot(
        recipient_type=rule.recipient_type,
        specific_user_id=rule.specific_user_id,
        role=rule.role,
        notify_inapp=rule.notify_inapp,
        notify_email=rule.notify_email,
    )


async def _baseline_rules(db: AsyncSession, stage_def_id: int) -> list[_RuleSnapshot]:
    rows = await db.execute(
        select(StageNotificationRule).where(
            StageNotificationRule.stage_def_id == stage_def_id,
            StageNotificationRule.is_active.is_(True),
        )
    )
    return [_snapshot_rule(r) for r in rows.scalars().all()]


async def _client_overrides(
    db: AsyncSession, *, client_id: int, stage_def_id: int
) -> list[_RuleSnapshot]:
    rows = await db.execute(
        select(ClientStageNotificationOverride).where(
            ClientStageNotificationOverride.client_id == client_id,
            ClientStageNotificationOverride.stage_def_id == stage_def_id,
            ClientStageNotificationOverride.is_active.is_(True),
        )
    )
    return [_snapshot_override(r) for r in rows.scalars().all()]


async def _resolve_user_ids_for_rule(
    db: AsyncSession,
    *,
    rule: _RuleSnapshot,
    job: Job,
    candidate: Candidate,
) -> list[int]:
    """Zwraca listę user_id wynikającą z reguły. Może być pusta (None drop)."""
    rt = rule.recipient_type
    if rt == RecipientType.job_delivery_lead:
        if job.delivery_lead_id:
            return [job.delivery_lead_id]
        logger.warning(
            "stage_notif: job_delivery_lead unresolved for job=%s (delivery_lead_id is NULL)",
            job.id,
        )
        return []

    if rt == RecipientType.job_recruiter:
        if job.recruiter_id:
            return [job.recruiter_id]
        logger.warning(
            "stage_notif: job_recruiter unresolved for job=%s (recruiter_id is NULL)",
            job.id,
        )
        return []

    if rt == RecipientType.client_head_dl:
        if not job.client_id:
            logger.warning(
                "stage_notif: client_head_dl unresolved — job=%s has no client_id",
                job.id,
            )
            return []
        head = await db.scalar(
            select(DeliveryLeadClientAssignment.delivery_lead_user_id).where(
                DeliveryLeadClientAssignment.client_id == job.client_id,
                DeliveryLeadClientAssignment.is_head.is_(True),
            )
        )
        if head is None:
            logger.warning(
                "stage_notif: client_head_dl unresolved for client=%s (no head DL)",
                job.client_id,
            )
            return []
        return [head]

    if rt == RecipientType.client_primary_tac:
        if not job.client_id:
            logger.warning(
                "stage_notif: client_primary_tac unresolved — job=%s has no client_id",
                job.id,
            )
            return []
        tac = await db.scalar(
            select(ClientTacAssignment.tac_user_id).where(
                ClientTacAssignment.client_id == job.client_id,
                ClientTacAssignment.is_primary.is_(True),
            )
        )
        if tac is None:
            logger.warning(
                "stage_notif: client_primary_tac unresolved for client=%s (no primary TAC)",
                job.client_id,
            )
            return []
        return [tac]

    if rt == RecipientType.specific_user:
        if rule.specific_user_id is None:
            logger.warning(
                "stage_notif: specific_user rule has NULL specific_user_id — skipping"
            )
            return []
        return [rule.specific_user_id]

    if rt == RecipientType.role:
        if rule.role is None:
            logger.warning("stage_notif: role-based rule has NULL role — skipping")
            return []
        try:
            role_enum = UserRole(rule.role)
        except ValueError:
            logger.warning(
                "stage_notif: role %r is not a valid UserRole — skipping", rule.role
            )
            return []
        rows = await db.execute(
            select(User.id).where(User.role == role_enum, User.is_active.is_(True))
        )
        return list(rows.scalars().all())

    if rt == RecipientType.candidate_creator:
        if candidate.created_by:
            return [candidate.created_by]
        logger.warning(
            "stage_notif: candidate_creator unresolved — candidate=%s has no created_by",
            candidate.id,
        )
        return []

    logger.warning("stage_notif: unknown recipient_type=%r — skipping", rt)
    return []


async def _filter_active_users(db: AsyncSession, user_ids: set[int]) -> set[int]:
    """Zwraca podzbiór ID-ków, dla których ``users.is_active = TRUE``."""
    if not user_ids:
        return set()
    rows = await db.execute(
        select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))
    )
    return set(rows.scalars().all())


async def resolve_recipients(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover_user_id: Optional[int],
) -> list[ResolvedRecipient]:
    """Główny wywoływany resolver. Patrz docstring modułu."""
    if new_stage.stage_def_id is None:
        logger.debug(
            "stage_notif: new_stage=%s has no stage_def_id (legacy enum-only) — skip",
            new_stage.id,
        )
        return []

    # Wczytujemy stage_def-y obu stage'y w jednym roundtripie żeby porównać
    # `order`. Forward-only check — przy cofnięciu nie powiadamiamy.
    stage_def_ids = {new_stage.stage_def_id}
    if previous_stage is not None and previous_stage.stage_def_id is not None:
        stage_def_ids.add(previous_stage.stage_def_id)

    rows = await db.execute(
        select(PipelineStageDef).where(PipelineStageDef.id.in_(stage_def_ids))
    )
    stage_defs_by_id = {sd.id: sd for sd in rows.scalars().all()}

    new_stage_def = stage_defs_by_id.get(new_stage.stage_def_id)
    if new_stage_def is None:
        logger.warning(
            "stage_notif: stage_def_id=%s not found — skip",
            new_stage.stage_def_id,
        )
        return []

    if (
        previous_stage is not None
        and previous_stage.stage_def_id is not None
        and previous_stage.stage_def_id in stage_defs_by_id
    ):
        prev_def = stage_defs_by_id[previous_stage.stage_def_id]
        if prev_def.order >= new_stage_def.order:
            logger.debug(
                "stage_notif: backward move (prev order=%s, new order=%s) — no notify",
                prev_def.order,
                new_stage_def.order,
            )
            return []

    # Override priority — jeśli klient ma override dla tego stage'a, baseline
    # zostaje pominięty.
    rules: list[_RuleSnapshot] = []
    if job.client_id:
        rules = await _client_overrides(
            db, client_id=job.client_id, stage_def_id=new_stage.stage_def_id
        )
    if not rules:
        rules = await _baseline_rules(db, new_stage.stage_def_id)

    if not rules:
        logger.debug(
            "stage_notif: no active rules for stage_def=%s — no notify",
            new_stage.stage_def_id,
        )
        return []

    # Resolwer: per-user merge channels.
    inapp_by_user: dict[int, bool] = {}
    email_by_user: dict[int, bool] = {}

    for rule in rules:
        user_ids = await _resolve_user_ids_for_rule(
            db, rule=rule, job=job, candidate=candidate
        )
        for uid in user_ids:
            if uid is None:
                continue
            if mover_user_id is not None and uid == mover_user_id:
                continue  # self-suppression
            inapp_by_user[uid] = inapp_by_user.get(uid, False) or rule.notify_inapp
            email_by_user[uid] = email_by_user.get(uid, False) or rule.notify_email

    if not inapp_by_user and not email_by_user:
        return []

    # Filtruj nieaktywnych userów (np. urlopowy admin może być w role-based regule).
    candidate_ids = set(inapp_by_user.keys()) | set(email_by_user.keys())
    active_ids = await _filter_active_users(db, candidate_ids)

    return [
        ResolvedRecipient(
            user_id=uid,
            notify_inapp=inapp_by_user.get(uid, False),
            notify_email=email_by_user.get(uid, False),
        )
        for uid in sorted(active_ids)
        if inapp_by_user.get(uid) or email_by_user.get(uid)
    ]


__all__ = ["ResolvedRecipient", "resolve_recipients"]
