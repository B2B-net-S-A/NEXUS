"""Admin endpoints for candidate data-quality jobs and read-only reports.

- ``POST /api/admin/candidates/backfill-names`` — recover name/email/phone for
  Traffit candidates imported as ``"? ?"`` by parsing their stored CV. Returns
  immediately; the job runs in the background (parsing N CVs through the LLM
  takes minutes). Idempotent + resumable.
- ``GET  /api/admin/candidates/backfill-names/status`` — live progress.
- ``POST /api/admin/candidates/backfill-cc`` — classify candidates into the 5
  competence categories (primary + up to 2 secondary) in bulk. Runs in the
  background; idempotent + resumable. ``only_missing`` (default true) touches
  only unclassified profiles.
- ``GET  /api/admin/candidates/backfill-cc/status`` — live progress.
- ``GET  /api/admin/candidates/suspected-name-overwrites`` — bounded review
  report for current identity values that differ from the latest unresolved
  manual submission or were preserved by the first-sync bootstrap guard. It
  never repairs data or backfills identity ownership.

RBAC: admin only (``AdminUser`` dependency).
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import AsyncSessionLocal, get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.services import candidate_audit
from app.services.candidate_cc_assignment import backfill_candidate_ccs
from app.services.cv_backfill import backfill_missing_names

logger = logging.getLogger(__name__)

router = APIRouter()

# Single-flight in-memory job state. A backfill is a one-off operation; if the
# container restarts mid-run the job is resumable (it only targets rows still
# marked "?"), so we don't need durable state.
_JOB: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "resolved": 0,
    "unresolved": 0,
    "errors": 0,
    "started_at": None,
    "finished_at": None,
    "limit": None,
    "last_error": None,
}


async def _run_backfill(limit: Optional[int], prefer_llm: bool) -> None:
    _JOB.update(
        running=True,
        total=0,
        processed=0,
        resolved=0,
        unresolved=0,
        errors=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit=limit,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_missing_names(
                db, limit=limit, prefer_llm=prefer_llm, progress=_JOB
            )
    except Exception as e:  # noqa: BLE001 — never crash the background task
        _JOB["last_error"] = repr(e)
        logger.exception("[backfill-names] job crashed")
    finally:
        _JOB["running"] = False
        _JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/backfill-names")
async def trigger_backfill_names(
    _admin: AdminUser,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Cap the number of candidates processed this run (e.g. for "
        "a small verification batch). Omit to process all remaining '?' rows.",
    ),
    prefer_llm: bool = Query(
        default=True,
        description="Use the LLM CV parser (name+email+phone+skills). When "
        "false, falls back to regex + filename-derived name only.",
    ),
) -> dict[str, Any]:
    """Kick a name-backfill run in the background. Admin only."""
    if _JOB["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A backfill run is already in progress",
        )
    asyncio.create_task(_run_backfill(limit, prefer_llm))
    return {"status": "started", "limit": limit, "prefer_llm": prefer_llm}


@router.get("/backfill-names/status")
async def backfill_names_status(_admin: AdminUser) -> dict[str, Any]:
    """Current backfill progress (in-memory; resets on container restart)."""
    return dict(_JOB)


# ── Competence-category backfill ────────────────────────────────────────────
# Separate single-flight state from the name backfill so both can be inspected
# independently. Resumable: with only_missing=True a restart just re-selects the
# still-unclassified rows.
_CC_JOB: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "assigned": 0,
    "skipped": 0,
    "errors": 0,
    "by_primary": {},
    "only_missing": True,
    "start_after_id": 0,
    "last_id": 0,
    "started_at": None,
    "finished_at": None,
    "limit": None,
    "last_error": None,
}


async def _run_cc_backfill(
    limit: Optional[int], only_missing: bool, start_after_id: int
) -> None:
    _CC_JOB.update(
        running=True,
        total=0,
        processed=0,
        assigned=0,
        skipped=0,
        errors=0,
        by_primary={},
        only_missing=only_missing,
        start_after_id=start_after_id,
        last_id=start_after_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit=limit,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_candidate_ccs(
                db,
                limit=limit,
                only_missing=only_missing,
                start_after_id=start_after_id,
                progress=_CC_JOB,
            )
    except Exception as e:  # noqa: BLE001 — never crash the background task
        _CC_JOB["last_error"] = repr(e)
        logger.exception("[backfill-cc] job crashed")
    finally:
        _CC_JOB["running"] = False
        _CC_JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/backfill-cc")
async def trigger_backfill_cc(
    _admin: AdminUser,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Cap the number of candidates classified this run (e.g. for "
        "a small verification batch). Omit to process all matching rows.",
    ),
    only_missing: bool = Query(
        default=True,
        description="When true (default), classify only candidates with no "
        "primary competence category yet — the safe migration path that never "
        "touches already-classified or manually-curated profiles. Set false to "
        "re-classify every candidate (still skips manual assignments).",
    ),
    start_after_id: int = Query(
        default=0,
        ge=0,
        description="Resume cursor: scan only candidates with id > this value. "
        "Pass the `last_id` watermark from a previous (interrupted) run so a "
        "container restart continues the pass instead of rescanning the "
        "low-signal skipped convoy from id 0.",
    ),
) -> dict[str, Any]:
    """Kick a competence-category backfill in the background. Admin only."""
    if _CC_JOB["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A competence-category backfill is already in progress",
        )
    asyncio.create_task(_run_cc_backfill(limit, only_missing, start_after_id))
    return {
        "status": "started",
        "limit": limit,
        "only_missing": only_missing,
        "start_after_id": start_after_id,
    }


@router.get("/backfill-cc/status")
async def backfill_cc_status(_admin: AdminUser) -> dict[str, Any]:
    """Current competence-category backfill progress (in-memory)."""
    return dict(_CC_JOB)


# ── Fala 3: masowe uzupełnianie pól z CV ────────────────────────────────────
# Osobny stan single-flight — bieg trwa godziny i musi być obserwowalny
# niezależnie od backfillu nazwisk/CC. Prod nie ma wygodnego CLI, więc admin
# endpoint jest ścieżką produkcyjną; CLI (scripts/backfill_cv_fields.py) — dev.

_CV_FIELDS_JOB: dict[str, Any] = {"running": False}


async def _run_cv_fields_backfill(
    limit: Optional[int], after_id: int, calibration_log: Optional[str]
) -> None:
    from app.services.cv_field_backfill import backfill_cv_fields

    _CV_FIELDS_JOB.clear()
    _CV_FIELDS_JOB.update(
        running=True,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit=limit,
        after_id=after_id,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_cv_fields(
                db,
                limit=limit,
                after_id=after_id,
                progress=_CV_FIELDS_JOB,
                calibration_log_path=calibration_log,
            )
    except Exception as e:  # noqa: BLE001 — never crash the background task
        _CV_FIELDS_JOB["last_error"] = repr(e)
        logger.exception("[cv-fields-backfill] job crashed")
    finally:
        _CV_FIELDS_JOB["running"] = False
        _CV_FIELDS_JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/backfill-cv-fields")
async def trigger_backfill_cv_fields(
    _admin: AdminUser,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Sufit wierszy w tym biegu (np. 200 na kalibrację). "
        "Bez limitu bieg idzie do końca scope'u albo do CV_BACKFILL_MAX_CALLS.",
    ),
    after_id: int = Query(
        default=0,
        ge=0,
        description="Wznów od tego candidate_id (kursor z pola last_id statusu).",
    ),
    dry_run: bool = Query(
        default=True,
        description="Domyślnie TYLKO pomiar scope'u (zero LLM, zero zapisów). "
        "Bieg płatny wymaga jawnego dry_run=false.",
    ),
    calibration_log: Optional[str] = Query(
        default=None,
        description="Ścieżka JSONL wewnątrz kontenera; każdy wiersz = surowy "
        "wynik parsowania + usage, do ręcznej oceny jakości na próbce.",
    ),
) -> dict[str, Any]:
    """Masowe uzupełnianie skills/city/years z tekstu CV (Fala 3). Admin only.

    Zapis wyłącznie w pola PUSTE (polityka FILL_EMPTY z #1094); `[]` w skills
    liczy się jako puste. Kwota: AIFeatureKey.cv_backfill — osobny kubełek od
    interaktywnego cv_parser.
    """
    if dry_run:
        from app.services.cv_field_backfill import count_scope

        async with AsyncSessionLocal() as db:
            scope = await count_scope(db, after_id=after_id)
        return {"status": "dry_run", **scope}

    if _CV_FIELDS_JOB.get("running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cv-fields backfill run is already in progress",
        )
    asyncio.create_task(_run_cv_fields_backfill(limit, after_id, calibration_log))
    return {"status": "started", "limit": limit, "after_id": after_id}


@router.get("/backfill-cv-fields/status")
async def backfill_cv_fields_status(_admin: AdminUser) -> dict[str, Any]:
    """Live progress biegu (in-memory; kursor last_id pozwala wznowić po restarcie)."""
    return dict(_CV_FIELDS_JOB)


# ── Read-only audit: manual identity submissions overwritten later ───────────

_NAME_OVERWRITE_REPORT_VERSION = "candidate-name-overwrite-suspects-v2"
_NAME_OVERWRITE_LIMITATIONS = (
    {
        "code": "submitted_values_only",
        "detail": (
            "Activity stores values submitted by the PATCH request, not the value "
            "that existed before the request."
        ),
    },
    {
        "code": "submitted_does_not_prove_intent",
        "detail": (
            "Candidate forms can submit name and lastname while the user edits a "
            "different field, so a logged key is not proof of an intentional rename."
        ),
    },
    {
        "code": "latest_submission_only",
        "detail": (
            "Only the latest logged submission per field is compared. An older "
            "correction followed by another logged payload cannot be reconstructed "
            "safely. A later explicit restore from Traffit resolves that field and "
            "suppresses the older submission."
        ),
    },
    {
        "code": "source_attribution_is_current_only",
        "detail": (
            "A Traffit snapshot, when present, describes current source data and does "
            "not prove which historical writer changed the canonical value."
        ),
    },
    {
        "code": "no_automatic_repair",
        "detail": (
            "Rows are review candidates only. This report must not be used to "
            "backfill manual locks or restore values automatically."
        ),
    },
    {
        "code": "paged_live_view",
        "detail": (
            "Pages are separate live reads, not one long database snapshot. Rerun "
            "from after_candidate_id=0 after concurrent edits or sync activity."
        ),
    },
    {
        "code": "page_scoped_counts",
        "detail": (
            "page_matched_candidates and page_matched_fields describe only the "
            "current cursor page. Follow next_after_candidate_id until done=true "
            "and aggregate all pages for a complete report."
        ),
    },
)


def _identity_difference_kind(submitted: str, current: str) -> str:
    """Classify presentation-only differences without dropping them from review."""

    def _presentation_key(value: str) -> str:
        collapsed = " ".join(value.split())
        return unicodedata.normalize("NFC", collapsed).casefold()

    if _presentation_key(submitted) == _presentation_key(current):
        return "presentation_only"
    return "material"


@router.get("/suspected-name-overwrites")
async def suspected_name_overwrites(
    _admin: AdminUser,
    response: Response,
    after_candidate_id: int = Query(
        default=0,
        ge=0,
        description=(
            "Bounded scan cursor. Pass next_after_candidate_id from the previous "
            "response until done=true."
        ),
    ),
    scan_limit: int = Query(
        default=2_000,
        ge=1,
        le=5_000,
        description="Maximum Traffit candidates inspected in this page.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List current identity values that differ from the latest logged submission.

    This is deliberately a suspect report, not an attribution engine. It exposes
    only the two identity fields under review and has no apply/repair path. Full
    ``Activity.details`` and candidate custom fields are never serialized (they
    may contain unrelated PII). Result counters are explicitly page-scoped.
    """

    response.headers["Cache-Control"] = "private, no-store"

    identity_state_expr = Candidate.custom_fields["_nexus_identity"].label(
        "identity_state"
    )
    candidate_result = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Candidate.external_id,
            Candidate.external_deleted_at,
            Candidate.updated_at,
            identity_state_expr,
        )
        .where(
            Candidate.external_source == "traffit",
            Candidate.id > after_candidate_id,
        )
        .order_by(Candidate.id.asc())
        .limit(scan_limit + 1)
    )
    candidate_rows = list(candidate_result.all())
    has_more = len(candidate_rows) > scan_limit
    scanned_rows = candidate_rows[:scan_limit]

    if not scanned_rows:
        return {
            "query_version": _NAME_OVERWRITE_REPORT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "verdict": "suspects_only_not_proof",
            "scan": {
                "after_candidate_id": after_candidate_id,
                "scan_limit": scan_limit,
                "scanned_candidates": 0,
                "first_candidate_id": None,
                "last_candidate_id": None,
                "next_after_candidate_id": None,
                "done": True,
            },
            "count_scope": "current_page",
            "page_matched_candidates": 0,
            "page_matched_fields": 0,
            "candidates": [],
            "limitations": list(_NAME_OVERWRITE_LIMITATIONS),
        }

    candidate_ids = [row.id for row in scanned_rows]
    common_submission_filters = (
        Activity.entity_type == "candidate",
        Activity.entity_id.in_(candidate_ids),
        Activity.action == "updated",
        Activity.external_source == "manual",
        Activity.user_id.is_not(None),
        func.jsonb_typeof(Activity.details) == "object",
    )
    common_restore_filters = (
        Activity.entity_type == "candidate",
        Activity.entity_id.in_(candidate_ids),
        Activity.action == candidate_audit.IDENTITY_RESTORED_FROM_TRAFFIT,
        Activity.external_source == "audit",
        func.jsonb_typeof(Activity.details) == "object",
        func.jsonb_typeof(Activity.details["fields"]) == "array",
    )
    identity_evidence = union_all(
        select(
            Activity.id.label("activity_id"),
            Activity.entity_id.label("candidate_id"),
            Activity.user_id.label("actor_user_id"),
            Activity.created_at.label("occurred_at"),
            literal("name").label("field"),
            literal("submission").label("evidence_kind"),
            Activity.details["name"].as_string().label("submitted_value"),
        ).where(
            *common_submission_filters,
            func.jsonb_typeof(Activity.details["name"]) == "string",
        ),
        select(
            Activity.id.label("activity_id"),
            Activity.entity_id.label("candidate_id"),
            Activity.user_id.label("actor_user_id"),
            Activity.created_at.label("occurred_at"),
            literal("lastname").label("field"),
            literal("submission").label("evidence_kind"),
            Activity.details["lastname"].as_string().label("submitted_value"),
        ).where(
            *common_submission_filters,
            func.jsonb_typeof(Activity.details["lastname"]) == "string",
        ),
        select(
            Activity.id.label("activity_id"),
            Activity.entity_id.label("candidate_id"),
            Activity.user_id.label("actor_user_id"),
            Activity.created_at.label("occurred_at"),
            literal("name").label("field"),
            literal("restore").label("evidence_kind"),
            literal(None).label("submitted_value"),
        ).where(
            *common_restore_filters,
            Activity.details.contains({"fields": ["name"]}),
        ),
        select(
            Activity.id.label("activity_id"),
            Activity.entity_id.label("candidate_id"),
            Activity.user_id.label("actor_user_id"),
            Activity.created_at.label("occurred_at"),
            literal("lastname").label("field"),
            literal("restore").label("evidence_kind"),
            literal(None).label("submitted_value"),
        ).where(
            *common_restore_filters,
            Activity.details.contains({"fields": ["lastname"]}),
        ),
    ).subquery()
    ranked_evidence = select(
        identity_evidence,
        func.row_number()
        .over(
            partition_by=(
                identity_evidence.c.candidate_id,
                identity_evidence.c.field,
                identity_evidence.c.evidence_kind,
            ),
            order_by=(
                identity_evidence.c.occurred_at.desc(),
                identity_evidence.c.activity_id.desc(),
            ),
        )
        .label("evidence_rank"),
    ).subquery()
    activity_result = await db.execute(
        select(
            ranked_evidence.c.activity_id,
            ranked_evidence.c.candidate_id,
            ranked_evidence.c.actor_user_id,
            ranked_evidence.c.occurred_at,
            ranked_evidence.c.field,
            ranked_evidence.c.evidence_kind,
            ranked_evidence.c.submitted_value,
        )
        .where(ranked_evidence.c.evidence_rank == 1)
        .order_by(
            ranked_evidence.c.candidate_id.asc(),
            ranked_evidence.c.field.asc(),
            ranked_evidence.c.evidence_kind.asc(),
        )
    )

    latest_by_field: dict[tuple[int, str], dict[str, Any]] = {}
    latest_restore_by_field: dict[tuple[int, str], dict[str, Any]] = {}
    for row in activity_result.all():
        evidence = {
            "activity_id": row.activity_id,
            "occurred_at": row.occurred_at,
            "actor_user_id": row.actor_user_id,
        }
        if row.evidence_kind == "restore":
            latest_restore_by_field[(row.candidate_id, row.field)] = evidence
        else:
            latest_by_field[(row.candidate_id, row.field)] = {
                **evidence,
                "value": row.submitted_value,
            }

    suspects: list[dict[str, Any]] = []
    page_matched_fields = 0
    for candidate in scanned_rows:
        raw_identity = candidate.identity_state
        identity_state_valid = isinstance(raw_identity, dict)
        identity = raw_identity if identity_state_valid else {}
        field_suspects: list[dict[str, Any]] = []

        for field, current_value in (
            ("name", candidate.name),
            ("lastname", candidate.lastname),
        ):
            logged = latest_by_field.get((candidate.id, field))
            restored = latest_restore_by_field.get((candidate.id, field))
            if logged is not None and restored is not None:
                restore_order = (restored["occurred_at"], restored["activity_id"])
                submission_order = (logged["occurred_at"], logged["activity_id"])
                if restore_order > submission_order:
                    logged = None

            source_value_raw = identity.get(f"traffit_{field}")
            source_value = (
                source_value_raw if isinstance(source_value_raw, str) else None
            )
            if source_value is None:
                source_alignment = "snapshot_unavailable"
            elif source_value == current_value:
                source_alignment = "matches_current_traffit_snapshot"
            else:
                source_alignment = "does_not_match_current_traffit_snapshot"

            ownership_reason_raw = identity.get(f"{field}_ownership_reason")
            ownership_reason = (
                ownership_reason_raw if isinstance(ownership_reason_raw, str) else None
            )
            bootstrap_review = ownership_reason == "bootstrap_mismatch"
            logged_mismatch = logged is not None and logged["value"] != current_value
            if not bootstrap_review and not logged_mismatch:
                continue

            submitted_at = logged["occurred_at"] if logged_mismatch else None
            updated_after_submission = bool(
                candidate.updated_at
                and submitted_at
                and candidate.updated_at > submitted_at
            )
            reasons: list[str] = []
            if bootstrap_review:
                reasons.append("bootstrap_mismatch_requires_review")
            if logged_mismatch:
                reasons.append("latest_logged_submission_differs_from_current")
            if updated_after_submission:
                reasons.append("candidate_updated_after_submission")
            if source_alignment == "matches_current_traffit_snapshot":
                reasons.append("current_matches_latest_traffit_snapshot")

            manual_lock_active = identity.get(f"{field}_manual") is True
            if manual_lock_active and logged_mismatch and not bootstrap_review:
                reasons.append("manual_lock_did_not_preserve_logged_submission")

            comparison_value = logged["value"] if logged_mismatch else source_value
            difference_kind = (
                _identity_difference_kind(comparison_value, current_value)
                if comparison_value is not None and comparison_value != current_value
                else None
            )

            field_suspects.append(
                {
                    "field": field,
                    "status": "review_required" if bootstrap_review else "suspect",
                    "current_value": current_value,
                    "last_logged_submission_value": (
                        logged["value"] if logged_mismatch else None
                    ),
                    "difference_kind": difference_kind,
                    "activity_id": logged["activity_id"] if logged_mismatch else None,
                    "submitted_at": submitted_at.isoformat() if submitted_at else None,
                    "submitted_by_user_id": (
                        logged["actor_user_id"] if logged_mismatch else None
                    ),
                    "candidate_updated_after_submission": updated_after_submission,
                    "manual_lock_active": manual_lock_active,
                    "ownership_reason": ownership_reason,
                    "traffit_snapshot_value": source_value,
                    "traffit_source_updated_at": (
                        identity.get("traffit_source_updated_at")
                        if isinstance(identity.get("traffit_source_updated_at"), str)
                        else None
                    ),
                    "source_alignment": source_alignment,
                    "suspect_reasons": reasons,
                }
            )

        if not field_suspects:
            continue
        page_matched_fields += len(field_suspects)
        suspects.append(
            {
                "candidate_id": candidate.id,
                "traffit_external_id": candidate.external_id,
                "profile_path": f"/candidates/{candidate.id}",
                "candidate_updated_at": candidate.updated_at.isoformat()
                if candidate.updated_at
                else None,
                "external_deleted_at": candidate.external_deleted_at.isoformat()
                if candidate.external_deleted_at
                else None,
                "identity_state_present": identity_state_valid,
                "fields": field_suspects,
            }
        )

    first_id = scanned_rows[0].id
    last_id = scanned_rows[-1].id
    return {
        "query_version": _NAME_OVERWRITE_REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "verdict": "suspects_only_not_proof",
        "scan": {
            "after_candidate_id": after_candidate_id,
            "scan_limit": scan_limit,
            "scanned_candidates": len(scanned_rows),
            "first_candidate_id": first_id,
            "last_candidate_id": last_id,
            "next_after_candidate_id": last_id if has_more else None,
            "done": not has_more,
        },
        "count_scope": "current_page",
        "page_matched_candidates": len(suspects),
        "page_matched_fields": page_matched_fields,
        "candidates": suspects,
        "limitations": list(_NAME_OVERWRITE_LIMITATIONS),
    }
