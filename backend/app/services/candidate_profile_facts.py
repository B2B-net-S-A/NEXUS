"""Canonical persistence/query service for typed candidate-profile facts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import job_scope_clause
from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_share_token import CVShareToken
from app.models.interview_feedback import InterviewFeedback
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_note import ScreeningNote
from app.models.user import User
from app.schemas.candidate_profile_facts import CandidateLanguageWrite
from app.schemas.pipeline import STAGE_LABELS
from app.services import candidate_audit
from app.services.candidate_identity_quarantine import source_is_eligible_clause


class CandidateNotFoundError(LookupError):
    """Raised when a candidate-scoped fact targets a missing candidate."""


class ProfileFactsVersionConflictError(RuntimeError):
    """Raised after row locking when the supplied OCC version is stale."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"profile facts version is {current_version}")


async def get_candidate_with_languages(
    db: AsyncSession,
    candidate_id: int,
    *,
    for_update: bool = False,
) -> tuple[Candidate, list[CandidateLanguage]]:
    candidate_stmt = select(Candidate).where(Candidate.id == candidate_id)
    if for_update:
        candidate_stmt = candidate_stmt.with_for_update()
    else:
        # Keep the collection rows and its ETag version in one consistent
        # snapshot. Automated/manual writers lock this same candidate row with
        # FOR UPDATE before changing either side, so a short KEY SHARE lock
        # prevents a v1 ETag from being paired with v2 rows at READ COMMITTED.
        candidate_stmt = candidate_stmt.with_for_update(read=True, key_share=True)
    candidate = await db.scalar(candidate_stmt)
    if candidate is None:
        raise CandidateNotFoundError

    rows = list(
        (
            await db.scalars(
                select(CandidateLanguage)
                .where(
                    CandidateLanguage.candidate_id == candidate_id,
                    CandidateLanguage.deleted_at.is_(None),
                )
                .order_by(
                    CandidateLanguage.language_name.asc(),
                    CandidateLanguage.language_code.asc(),
                )
            )
        ).all()
    )
    return candidate, rows


def _language_audit_snapshot(row: CandidateLanguage) -> dict[str, object]:
    return {
        "language_code": row.language_code,
        "language_name": row.language_name,
        "cefr_level": row.cefr_level,
        "is_native": row.is_native,
        "is_level_unknown": row.is_level_unknown,
    }


def _legacy_language_projection(
    languages: Sequence[CandidateLanguageWrite],
) -> list[dict[str, object]]:
    """Keep old read paths alive while the normalized table becomes canonical."""

    projected: list[dict[str, object]] = []
    for language in languages:
        level: str
        if language.is_native:
            level = "native"
        elif language.is_level_unknown:
            level = "unknown"
        else:
            # Validator guarantees a CEFR value in this branch.
            level = str(language.cefr_level)
        projected.append(
            {
                "code": language.language_code.upper(),
                "lang": language.language_name,
                "level": level,
            }
        )
    return projected


async def replace_candidate_languages(
    db: AsyncSession,
    *,
    candidate_id: int,
    languages: Sequence[CandidateLanguageWrite],
    expected_version: int,
    actor_id: int,
) -> tuple[Candidate, list[CandidateLanguage]]:
    """Atomically replace active language facts using collection-level OCC."""

    candidate_stmt = (
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    candidate = await db.scalar(candidate_stmt)
    if candidate is None:
        raise CandidateNotFoundError
    if candidate.languages_version != expected_version:
        raise ProfileFactsVersionConflictError(candidate.languages_version)

    all_rows = list(
        (
            await db.scalars(
                select(CandidateLanguage)
                .where(CandidateLanguage.candidate_id == candidate_id)
                .order_by(CandidateLanguage.id.asc())
            )
        ).all()
    )
    old_snapshot = [
        _language_audit_snapshot(row) for row in all_rows if row.deleted_at is None
    ]
    existing_by_code = {row.language_code: row for row in all_rows}
    desired_by_code = {language.language_code: language for language in languages}
    now = datetime.now(timezone.utc)

    for code, row in existing_by_code.items():
        desired = desired_by_code.get(code)
        if desired is None:
            if row.deleted_at is None:
                row.deleted_at = now
                # A manual omission is a locked tombstone. Automated writers
                # must not resurrect it on the next CV/import sync.
                row.provenance = "manual"
                row.manual_lock = True
                row.source_ref = None
                row.updated_by = actor_id
                row.version += 1
            continue

        row.language_name = desired.language_name
        row.cefr_level = desired.cefr_level
        row.is_native = desired.is_native
        row.is_level_unknown = desired.is_level_unknown
        row.provenance = "manual"
        row.manual_lock = True
        row.source_ref = None
        row.deleted_at = None
        row.updated_by = actor_id
        row.version += 1

    for code, desired in desired_by_code.items():
        if code in existing_by_code:
            continue
        db.add(
            CandidateLanguage(
                candidate_id=candidate_id,
                language_code=desired.language_code,
                language_name=desired.language_name,
                cefr_level=desired.cefr_level,
                is_native=desired.is_native,
                is_level_unknown=desired.is_level_unknown,
                provenance="manual",
                manual_lock=True,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

    candidate.languages = _legacy_language_projection(languages)
    candidate.languages_version += 1
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.LANGUAGES_REPLACED,
        user_id=actor_id,
        entity_id=candidate_id,
        details={
            "old_version": expected_version,
            "new_version": candidate.languages_version,
            "old_languages": old_snapshot,
            "new_languages": [
                {
                    "language_code": language.language_code,
                    "language_name": language.language_name,
                    "cefr_level": language.cefr_level,
                    "is_native": language.is_native,
                    "is_level_unknown": language.is_level_unknown,
                }
                for language in languages
            ],
        },
    )
    await db.flush()

    active_rows = list(
        (
            await db.scalars(
                select(CandidateLanguage)
                .where(
                    CandidateLanguage.candidate_id == candidate_id,
                    CandidateLanguage.deleted_at.is_(None),
                )
                .order_by(
                    CandidateLanguage.language_name.asc(),
                    CandidateLanguage.language_code.asc(),
                )
            )
        ).all()
    )
    return candidate, active_rows


async def get_candidate_profile_rate(
    db: AsyncSession,
    candidate_id: int,
    *,
    for_update: bool = False,
) -> Candidate:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    if for_update:
        stmt = stmt.with_for_update()
    candidate = await db.scalar(stmt)
    if candidate is None:
        raise CandidateNotFoundError
    return candidate


async def update_candidate_profile_rate(
    db: AsyncSession,
    *,
    candidate_id: int,
    amount: Decimal | None,
    expected_version: int,
    actor_id: int,
) -> Candidate:
    candidate = await get_candidate_profile_rate(
        db,
        candidate_id,
        for_update=True,
    )
    if candidate.profile_rate_version != expected_version:
        raise ProfileFactsVersionConflictError(candidate.profile_rate_version)

    old_amount = candidate.expected_rate_hourly
    old_currency = candidate.expected_rate_currency
    normalized_amount = amount.quantize(Decimal("0.01")) if amount is not None else None
    now = datetime.now(timezone.utc)
    candidate.expected_rate_hourly = normalized_amount
    candidate.expected_rate_currency = "PLN" if normalized_amount is not None else None
    candidate.profile_rate_version += 1
    candidate.profile_rate_updated_at = now

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.PROFILE_RATE_CHANGED,
        user_id=actor_id,
        entity_id=candidate_id,
        details={
            "old_amount": str(old_amount) if old_amount is not None else None,
            "old_currency": old_currency,
            "new_amount": (
                str(normalized_amount) if normalized_amount is not None else None
            ),
            "new_currency": "PLN" if normalized_amount is not None else None,
            "unit": "hour",
            "tax_basis": "net",
            "contract_type": "b2b",
            "old_version": expected_version,
            "new_version": candidate.profile_rate_version,
        },
    )
    from app.services.match_score_cache import mark_stale_for_candidate

    await mark_stale_for_candidate(db, candidate_id)
    await db.flush()
    return candidate


def build_recent_recruitments_stmt(
    *,
    candidate_id: int,
    current_user: User,
    limit: int,
):
    """Build one deterministic, resource-scoped recent-recruitments query."""

    safe_limit = min(max(limit, 1), 5)
    ranked_stages = (
        select(
            CandidateStage.id.label("latest_stage_id"),
            CandidateStage.job_id.label("job_id"),
            CandidateStage.stage.label("stage"),
            CandidateStage.moved_at.label("latest_stage_moved_at"),
            func.row_number()
            .over(
                partition_by=CandidateStage.job_id,
                order_by=(
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                ),
            )
            .label("stage_rank"),
        )
        .where(CandidateStage.candidate_id == candidate_id)
        .subquery("ranked_candidate_stages")
    )
    latest_stages = (
        select(
            ranked_stages.c.latest_stage_id,
            ranked_stages.c.job_id,
            ranked_stages.c.stage,
            ranked_stages.c.latest_stage_moved_at,
        )
        .where(ranked_stages.c.stage_rank == 1)
        .subquery("latest_candidate_stages")
    )
    note_activity = (
        select(
            Note.job_id.label("job_id"),
            func.max(func.coalesce(Note.source_created_at, Note.created_at)).label(
                "last_note_at"
            ),
        )
        .where(
            Note.candidate_id == candidate_id,
            Note.job_id.is_not(None),
            Note.source_deleted_at.is_(None),
            source_is_eligible_clause(
                candidate_id_column=Note.candidate_id,
                source_id_column=Note.id,
                source_kind="note",
            ),
        )
        .group_by(Note.job_id)
        .subquery("candidate_note_activity")
    )
    feedback_activity = (
        select(
            InterviewFeedback.job_id.label("job_id"),
            func.max(
                func.coalesce(
                    InterviewFeedback.updated_at,
                    InterviewFeedback.created_at,
                )
            ).label("last_feedback_at"),
        )
        .where(
            InterviewFeedback.candidate_id == candidate_id,
            InterviewFeedback.job_id.is_not(None),
        )
        .group_by(InterviewFeedback.job_id)
        .subquery("candidate_feedback_activity")
    )
    screening_activity = (
        select(
            ScreeningNote.job_id.label("job_id"),
            func.max(ScreeningNote.created_at).label("last_screening_at"),
        )
        .where(
            ScreeningNote.candidate_id == candidate_id,
            ScreeningNote.job_id.is_not(None),
        )
        .group_by(ScreeningNote.job_id)
        .subquery("candidate_screening_activity")
    )
    cv_share_activity = (
        select(
            CandidateStageCV.job_id.label("job_id"),
            func.max(CVShareToken.created_at).label("last_cv_sent_at"),
        )
        .join(
            CVShareToken,
            CVShareToken.candidate_stage_cv_id == CandidateStageCV.id,
        )
        .where(CandidateStageCV.candidate_id == candidate_id)
        .group_by(CandidateStageCV.job_id)
        .subquery("candidate_cv_share_activity")
    )
    last_activity_at = func.greatest(
        latest_stages.c.latest_stage_moved_at,
        func.coalesce(
            note_activity.c.last_note_at,
            latest_stages.c.latest_stage_moved_at,
        ),
        func.coalesce(
            feedback_activity.c.last_feedback_at,
            latest_stages.c.latest_stage_moved_at,
        ),
        func.coalesce(
            screening_activity.c.last_screening_at,
            latest_stages.c.latest_stage_moved_at,
        ),
        func.coalesce(
            cv_share_activity.c.last_cv_sent_at,
            latest_stages.c.latest_stage_moved_at,
        ),
    ).label("last_activity_at")

    return (
        select(
            Job.id.label("job_id"),
            Job.title.label("job_title"),
            Client.id.label("client_id"),
            Client.name.label("client_name"),
            latest_stages.c.latest_stage_id,
            latest_stages.c.stage,
            last_activity_at,
        )
        .join(latest_stages, latest_stages.c.job_id == Job.id)
        .join(Client, Client.id == Job.client_id)
        .outerjoin(note_activity, note_activity.c.job_id == Job.id)
        .outerjoin(feedback_activity, feedback_activity.c.job_id == Job.id)
        .outerjoin(screening_activity, screening_activity.c.job_id == Job.id)
        .outerjoin(cv_share_activity, cv_share_activity.c.job_id == Job.id)
        .where(job_scope_clause(current_user, Job.id))
        .order_by(last_activity_at.desc(), latest_stages.c.latest_stage_id.desc())
        .limit(safe_limit)
    )


async def get_recent_recruitments(
    db: AsyncSession,
    *,
    candidate_id: int,
    current_user: User,
    limit: int,
) -> list[dict[str, object]]:
    candidate_exists = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id)
    )
    if candidate_exists is None:
        raise CandidateNotFoundError

    result = await db.execute(
        build_recent_recruitments_stmt(
            candidate_id=candidate_id,
            current_user=current_user,
            limit=limit,
        )
    )
    items: list[dict[str, object]] = []
    for row in result.mappings().all():
        stage = row["stage"]
        items.append(
            {
                "job_id": row["job_id"],
                "job_title": row["job_title"],
                "client_id": row["client_id"],
                "client_name": row["client_name"],
                "latest_stage_id": row["latest_stage_id"],
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, str(stage)),
                "last_activity_at": row["last_activity_at"],
            }
        )
    return items
