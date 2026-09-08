"""Section-aware visibility and fan-out policy for user notifications.

Notification rows can outlive role and section-policy changes.  Their target
``user_id`` is therefore not sufficient authorization: every read, mutation,
email and realtime delivery must re-evaluate the recipient's current effective
section access.  The enum mapping below is exhaustive by design so a new
notification type cannot silently become visible to every authenticated user.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access,
    resolve_effective_section_access_for_users,
    section_access_for_user,
)


logger = logging.getLogger(__name__)


ALWAYS_VISIBLE_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.password_reset_requested,
        NotificationType.password_changed_by_admin,
    }
)

ADMIN_ONLY_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {NotificationType.ai_spend_alert}
)

# Context-sensitive types are handled separately below.  Every other enum
# value must appear here or in ``ALWAYS_VISIBLE_NOTIFICATION_TYPES``.
NOTIFICATION_SECTION_BY_TYPE: dict[NotificationType, ProductSection] = {
    NotificationType.recruitment_allocation_alert: ProductSection.pipeline,
    NotificationType.contract_ending: ProductSection.delivery,
    NotificationType.interview_scheduled: ProductSection.pipeline,
    NotificationType.candidate_added: ProductSection.sourcing,
    NotificationType.stage_changed: ProductSection.pipeline,
    NotificationType.new_application: ProductSection.sourcing,
    NotificationType.dl_stage_stale_6h: ProductSection.pipeline,
    NotificationType.client_feedback_eobd: ProductSection.pipeline,
    NotificationType.powercalling_kpi: ProductSection.insights,
    NotificationType.candidate_feedback_1h: ProductSection.pipeline,
    NotificationType.stage_stuck_7d: ProductSection.pipeline,
    NotificationType.champion_profile_updated: ProductSection.pipeline,
    NotificationType.contract_ending_90d: ProductSection.delivery,
    NotificationType.equipment_return_due_14d: ProductSection.delivery,
    NotificationType.client_order_ending_30d: ProductSection.delivery,
    NotificationType.match_digest: ProductSection.pipeline,
    NotificationType.post_interview_t15: ProductSection.pipeline,
    NotificationType.post_interview_t45: ProductSection.pipeline,
    NotificationType.post_interview_t2h_escalation: ProductSection.pipeline,
    NotificationType.suggest_next_step: ProductSection.pipeline,
    NotificationType.kpi_coach: ProductSection.insights,
    NotificationType.contract_activated: ProductSection.delivery,
    NotificationType.rejection_email_scheduled: ProductSection.pipeline,
    NotificationType.rejection_email_sent: ProductSection.pipeline,
    NotificationType.rejection_email_cancelled: ProductSection.pipeline,
    NotificationType.rejection_email_skipped: ProductSection.pipeline,
    NotificationType.rejection_email_failed: ProductSection.pipeline,
    NotificationType.marketplace_match: ProductSection.sourcing,
    NotificationType.stage_rule: ProductSection.pipeline,
    NotificationType.signature_sent: ProductSection.delivery,
    NotificationType.signature_signed: ProductSection.delivery,
    NotificationType.signature_rejected: ProductSection.delivery,
    NotificationType.signature_failed: ProductSection.delivery,
    NotificationType.framework_contract_expiring_30d: ProductSection.delivery,
    NotificationType.framework_contract_expiring_14d: ProductSection.delivery,
    NotificationType.framework_contract_expiring_7d: ProductSection.delivery,
    NotificationType.framework_contract_signed: ProductSection.delivery,
    NotificationType.client_order_ending_14d: ProductSection.delivery,
    NotificationType.client_order_ending_7d: ProductSection.delivery,
    NotificationType.saved_search_match: ProductSection.sourcing,
    NotificationType.similar_job_candidates: ProductSection.pipeline,
    NotificationType.job_deadline_7d: ProductSection.pipeline,
    NotificationType.job_deadline_3d: ProductSection.pipeline,
    NotificationType.job_deadline_1d: ProductSection.pipeline,
}

CONTEXTUAL_NOTIFICATION_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.job_chat_message,
        NotificationType.job_chat_mention,
        NotificationType.note_mention,
        NotificationType.pending_verification,
    }
)


def _has_section_read(user: User, section: ProductSection) -> bool:
    return section_access_for_user(user, section) >= SectionAccess.read


def _section_for_link(link: str | None) -> ProductSection | None:
    path = (link or "").split("?", 1)[0].split("#", 1)[0]
    if path.startswith("/contracts/b2b-generator"):
        return ProductSection.sourcing
    if path.startswith(
        (
            "/candidates",
            "/talents",
            "/sourcing",
            "/applications",
            "/cv-generator",
            "/talent-radar",
        )
    ):
        return ProductSection.sourcing
    if path.startswith(("/jobs", "/calendar")):
        return ProductSection.pipeline
    if path.startswith(
        (
            "/clients",
            "/contracts",
            "/contractors",
            "/manager",
            "/my-clients",
            "/my-relationships",
            "/order-mail",
        )
    ):
        return ProductSection.delivery
    if path.startswith("/insights"):
        return ProductSection.insights
    if path.startswith("/finance"):
        return ProductSection.finance
    return None


def user_can_receive_notification(
    user: User,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> bool:
    """Evaluate one row/event against the current request-local policy."""

    if not user.is_active:
        return False
    if user.has_role(UserRole.admin):
        return True
    if notification_type in ADMIN_ONLY_NOTIFICATION_TYPES:
        return False
    if notification_type in ALWAYS_VISIBLE_NOTIFICATION_TYPES:
        return True

    if notification_type in {
        NotificationType.job_chat_message,
        NotificationType.job_chat_mention,
    }:
        section = (
            ProductSection.sourcing
            if related_entity_type == "candidate_chat_message"
            else ProductSection.pipeline
        )
        return _has_section_read(user, section)

    if notification_type == NotificationType.note_mention:
        section = _section_for_link(link)
        return section is not None and _has_section_read(user, section)

    if notification_type == NotificationType.pending_verification:
        # Requests awaiting approval contain rate/budget values and remain
        # admin-only.  The same legacy enum is also used for the safe outcome
        # message sent back to the mover, whose link points at the Job.
        return bool(
            (link or "").startswith("/jobs/")
            and _has_section_read(user, ProductSection.pipeline)
        )

    section = NOTIFICATION_SECTION_BY_TYPE.get(notification_type)
    return section is not None and _has_section_read(user, section)


def notification_visibility_predicate(user: User) -> Any:
    """SQL predicate shared by list/count/read/update notification routes."""

    if user.has_role(UserRole.admin):
        return true()

    conditions: list[Any] = [
        Notification.notification_type.in_(ALWAYS_VISIBLE_NOTIFICATION_TYPES)
    ]
    allowed_fixed_types = [
        notification_type
        for notification_type, section in NOTIFICATION_SECTION_BY_TYPE.items()
        if _has_section_read(user, section)
    ]
    if allowed_fixed_types:
        conditions.append(Notification.notification_type.in_(allowed_fixed_types))

    if _has_section_read(user, ProductSection.pipeline):
        conditions.append(
            and_(
                Notification.notification_type.in_(
                    {
                        NotificationType.job_chat_message,
                        NotificationType.job_chat_mention,
                    }
                ),
                or_(
                    Notification.related_entity_type.is_(None),
                    Notification.related_entity_type != "candidate_chat_message",
                ),
            )
        )
        conditions.append(
            and_(
                Notification.notification_type == NotificationType.pending_verification,
                Notification.link.startswith("/jobs/", autoescape=True),
            )
        )
    if _has_section_read(user, ProductSection.sourcing):
        conditions.append(
            and_(
                Notification.notification_type.in_(
                    {
                        NotificationType.job_chat_message,
                        NotificationType.job_chat_mention,
                    }
                ),
                Notification.related_entity_type == "candidate_chat_message",
            )
        )

    note_link_conditions: list[Any] = []
    if _has_section_read(user, ProductSection.sourcing):
        note_link_conditions.extend(
            Notification.link.startswith(prefix, autoescape=True)
            for prefix in (
                "/candidates",
                "/talents",
                "/sourcing",
                "/applications",
                "/cv-generator",
                "/talent-radar",
                "/contracts/b2b-generator",
            )
        )
    if _has_section_read(user, ProductSection.pipeline):
        note_link_conditions.extend(
            Notification.link.startswith(prefix, autoescape=True)
            for prefix in ("/jobs", "/calendar")
        )
    if _has_section_read(user, ProductSection.delivery):
        note_link_conditions.extend(
            (
                Notification.link.startswith("/clients", autoescape=True),
                and_(
                    Notification.link.startswith("/contracts", autoescape=True),
                    ~Notification.link.startswith(
                        "/contracts/b2b-generator", autoescape=True
                    ),
                ),
                Notification.link.startswith("/contractors", autoescape=True),
                Notification.link.startswith("/manager", autoescape=True),
                Notification.link.startswith("/my-clients", autoescape=True),
                Notification.link.startswith("/my-relationships", autoescape=True),
                Notification.link.startswith("/order-mail", autoescape=True),
            )
        )
    if _has_section_read(user, ProductSection.insights):
        note_link_conditions.append(
            Notification.link.startswith("/insights", autoescape=True)
        )
    if _has_section_read(user, ProductSection.finance):
        note_link_conditions.append(
            Notification.link.startswith("/finance", autoescape=True)
        )
    if note_link_conditions:
        conditions.append(
            and_(
                Notification.notification_type == NotificationType.note_mention,
                or_(*note_link_conditions),
            )
        )

    return or_(*conditions) if conditions else false()


async def notification_recipient_has_access(
    db: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> bool:
    """Re-read a recipient and their effective policy before side effects."""

    user = await db.get(User, user_id, populate_existing=True)
    if user is None:
        return False
    await resolve_effective_section_access(db, user)
    return user_can_receive_notification(
        user,
        notification_type,
        related_entity_type=related_entity_type,
        link=link,
    )


async def filter_notification_recipients(
    db: AsyncSession,
    user_ids: Iterable[int],
    notification_type: NotificationType,
    *,
    related_entity_type: str | None = None,
    link: str | None = None,
) -> list[User]:
    """Batch-resolve active recipients without per-recipient policy queries."""

    ids = sorted(set(user_ids))
    if not ids:
        return []
    users = list(
        (
            await db.scalars(
                select(User).where(User.id.in_(ids), User.is_active.is_(True))
            )
        ).all()
    )
    await resolve_effective_section_access_for_users(db, users)
    return [
        user
        for user in users
        if user_can_receive_notification(
            user,
            notification_type,
            related_entity_type=related_entity_type,
            link=link,
        )
    ]


def user_can_receive_realtime_event(user: User, event: dict[str, Any]) -> bool:
    """Apply section ceilings to known realtime payload families."""

    event_type = str(event.get("type") or "")
    if event_type == "notification":
        data = event.get("data")
        if not isinstance(data, dict):
            return False
        raw_type = data.get("notification_type")
        try:
            notification_type = NotificationType(raw_type)
        except (TypeError, ValueError):
            logger.warning(
                "Dropping realtime notification with unknown type=%r for user_id=%s",
                raw_type,
                user.id,
            )
            return False
        return user_can_receive_notification(
            user,
            notification_type,
            related_entity_type=data.get("related_entity_type"),
            link=data.get("link"),
        )
    if event_type == "kpi_nudge":
        return _has_section_read(user, ProductSection.insights)
    if event_type == "champion_profile_changed" or event_type.startswith("chat:"):
        return _has_section_read(user, ProductSection.pipeline)
    if event_type.startswith("candidate-chat:"):
        return _has_section_read(user, ProductSection.sourcing)
    return True


def unmapped_notification_types() -> frozenset[NotificationType]:
    """Test hook: any value here is hidden for non-admins until classified."""

    return frozenset(NotificationType) - (
        ALWAYS_VISIBLE_NOTIFICATION_TYPES
        | ADMIN_ONLY_NOTIFICATION_TYPES
        | frozenset(NOTIFICATION_SECTION_BY_TYPE)
        | CONTEXTUAL_NOTIFICATION_TYPES
    )
