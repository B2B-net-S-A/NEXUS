"""Auto-add JobCollaborators from a Competence Category assignment.

Given a job + resolved CC, inserts rows into `job_collaborators` with
`source='auto_cc'` for users whose `user_competence_categories.priority=1`
(1st priority sourcerzy) OR `is_primary=true` (główna CC usera — DL/TAC).

Idempotent: existing rows with same (job_id, user_id) are skipped silently
via ON CONFLICT (unique constraint `uq_job_collaborators_job_user`).
Rows previously flagged `removed_from_auto_cc=true` are left alone — DL
decyzja trzyma się.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competence_category import UserCompetenceCategory
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

logger = logging.getLogger(__name__)


async def auto_add_cc_collaborators(
    db: AsyncSession,
    job_id: int,
    competence_category_id: int,
    added_by: int | None = None,
) -> list[int]:
    """Insert auto_cc collaborators for the given CC. Returns inserted user ids."""
    # Resolve users: priority=1 OR is_primary=true for this CC
    result = await db.execute(
        select(UserCompetenceCategory.user_id).where(
            UserCompetenceCategory.competence_category_id == competence_category_id,
            (UserCompetenceCategory.priority == 1)
            | (UserCompetenceCategory.is_primary.is_(True)),
        )
    )
    candidate_user_ids = sorted({row[0] for row in result.all()})
    if not candidate_user_ids:
        logger.info(
            "[auto_cc] CC %s has no priority=1 / primary users — nothing to add.",
            competence_category_id,
        )
        return []

    # Insert with ON CONFLICT DO NOTHING so re-calls are idempotent
    stmt = (
        pg_insert(JobCollaborator)
        .values(
            [
                {
                    "job_id": job_id,
                    "user_id": uid,
                    "added_by": added_by,
                    "source": JobCollaboratorSource.auto_cc.value,
                }
                for uid in candidate_user_ids
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["job_id", "user_id"],
        )
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(
        "[auto_cc] job=%s cc=%s attempted=%d (idempotent, final count may be lower)",
        job_id,
        competence_category_id,
        len(candidate_user_ids),
    )
    return candidate_user_ids
