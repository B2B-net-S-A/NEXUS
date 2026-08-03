"""Remove live recruitment relationships when an account becomes Finance.

Finance is an exclusive, non-recruitment persona.  Hiding recruitment screens
is not enough: relationship rows can feed cache scopes, background recipients
and owner-based queries.  This helper is intentionally transactional so the
role change, relationship cleanup and session invalidation commit together.

Historical authorship (activities, notes, candidate ``created_by`` and audit
columns) is retained.  Only mutable ownership/assignment state and recruitment
notifications are removed.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import UserCompetenceCategory
from app.models.contact import Contact
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.saved_search import SavedSearch
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
    TacDeliveryLeadAssignment,
    TacLinkedInFarming,
)
from app.services.authorization_invalidation import (
    invalidate_delivery_lead_scope_for_client,
)


_FINANCE_SAFE_NOTIFICATION_TYPES = (
    NotificationType.password_reset_requested,
    NotificationType.password_changed_by_admin,
)


def _rowcount(result: object) -> int:
    return max(int(getattr(result, "rowcount", 0) or 0), 0)


async def _delete_legacy_relationships_if_present(
    db: AsyncSession,
    user_id: int,
) -> dict[str, int]:
    """Clean imported DynaReporter rosters without assuming restored schemas.

    Some developer databases legitimately predate migration 0113.  Checking
    ``to_regclass`` keeps a Finance role change usable there while production
    databases with the legacy tables still receive the required cleanup.
    """

    statements = {
        "dr_tac_delivery_lead_assignments": (
            "DELETE FROM dr_tac_delivery_lead_assignments "
            "WHERE tac_user_id = :uid OR delivery_lead_user_id = :uid"
        ),
        "dr_sourcer_category_assignments": (
            "DELETE FROM dr_sourcer_category_assignments WHERE user_id = :uid"
        ),
    }
    counts: dict[str, int] = {}
    for table_name, statement in statements.items():
        exists = await db.scalar(
            text("SELECT to_regclass(:qualified_name)"),
            {"qualified_name": f"public.{table_name}"},
        )
        if exists is None:
            counts[table_name] = 0
            continue
        result = await db.execute(text(statement), {"uid": user_id})
        counts[table_name] = _rowcount(result)
    return counts


async def clear_recruitment_access_for_finance(
    db: AsyncSession,
    user_id: int,
) -> dict[str, int]:
    """Clear mutable recruitment scope for ``user_id`` and return audit counts.

    The caller owns the surrounding transaction and must persist an Activity
    record with the returned counts.  The function is idempotent.
    """

    affected_client_ids = sorted(
        set(
            (
                await db.execute(
                    select(ClientTacAssignment.client_id).where(
                        ClientTacAssignment.tac_user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
    )

    counts: dict[str, int] = {}
    delete_specs: Iterable[tuple[str, object]] = (
        (
            "delivery_lead_client_assignments",
            delete(DeliveryLeadClientAssignment).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == user_id
            ),
        ),
        (
            "client_tac_assignments",
            delete(ClientTacAssignment).where(
                ClientTacAssignment.tac_user_id == user_id
            ),
        ),
        (
            "tac_delivery_lead_assignments",
            delete(TacDeliveryLeadAssignment).where(
                or_(
                    TacDeliveryLeadAssignment.tac_user_id == user_id,
                    TacDeliveryLeadAssignment.delivery_lead_user_id == user_id,
                )
            ),
        ),
        (
            "tac_linkedin_farming",
            delete(TacLinkedInFarming).where(TacLinkedInFarming.tac_user_id == user_id),
        ),
        (
            "user_competence_categories",
            delete(UserCompetenceCategory).where(
                UserCompetenceCategory.user_id == user_id
            ),
        ),
        (
            "job_collaborators",
            delete(JobCollaborator).where(JobCollaborator.user_id == user_id),
        ),
    )
    for name, statement in delete_specs:
        counts[name] = _rowcount(await db.execute(statement))

    update_specs: Iterable[tuple[str, object]] = (
        (
            "jobs_recruiter_owner",
            update(Job).where(Job.recruiter_id == user_id).values(recruiter_id=None),
        ),
        (
            "jobs_delivery_lead_owner",
            update(Job)
            .where(Job.delivery_lead_id == user_id)
            .values(delivery_lead_id=None),
        ),
        (
            "jobs_tac_owner",
            update(Job).where(Job.tac_id == user_id).values(tac_id=None),
        ),
        (
            "contact_relationship_owner",
            update(Contact)
            .where(Contact.key_relationship_owner_id == user_id)
            .values(key_relationship_owner_id=None),
        ),
        (
            "saved_search_alerts_disabled",
            update(SavedSearch)
            .where(
                SavedSearch.user_id == user_id,
                SavedSearch.notify_new_matches.is_(True),
            )
            .values(notify_new_matches=False, unseen_count=0),
        ),
    )
    for name, statement in update_specs:
        counts[name] = _rowcount(await db.execute(statement))

    counts["recruitment_notifications"] = _rowcount(
        await db.execute(
            delete(Notification).where(
                Notification.user_id == user_id,
                Notification.notification_type.notin_(_FINANCE_SAFE_NOTIFICATION_TYPES),
            )
        )
    )
    counts.update(await _delete_legacy_relationships_if_present(db, user_id))

    # A removed TAC changes the relationship-derived scope of every DL working
    # with the affected client.  Priority-only changes deliberately do not do
    # this; removal of the relationship itself does.
    invalidated = 0
    for client_id in affected_client_ids:
        invalidated += await invalidate_delivery_lead_scope_for_client(db, client_id)
    counts["delivery_lead_sessions_invalidated"] = invalidated
    return counts
