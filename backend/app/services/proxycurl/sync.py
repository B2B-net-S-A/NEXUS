"""Orchestration: fetch one candidate's LinkedIn profile → diff → persist.

The public entry point is `sync_candidate_linkedin(db, candidate)`. It is
called by both the scheduled loop (`app.tasks.linkedin_sync`) and the
on-demand API endpoint (`POST /api/candidates/{id}/sync-linkedin`). It
handles URL validation, client transport errors, snapshot history, and
the denormalized-field update that powers the list filter + badge.

All errors are funneled into the `linkedin_sync_status` enum on the
candidate — callers do NOT raise exceptions out of this function for
expected failure modes (profile-not-found, invalid URL, Proxycurl 5xx).
Unexpected exceptions propagate so the task loop can log them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.linkedin_snapshot import (
    CandidateLinkedinSnapshot,
    LinkedinChangeKind,
    LinkedinSyncStatus,
)
from app.services.proxycurl.client import (
    ProfileNotFound,
    ProxycurlClient,
    ProxycurlError,
    ProxycurlProfile,
    normalize_linkedin_url,
)
from app.services.proxycurl.diff import ChangeResult, compute_change

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    """Summary of a single sync attempt — returned to caller for logging/UI."""

    candidate_id: int
    status: LinkedinSyncStatus
    change_kind: Optional[LinkedinChangeKind]
    snapshot_id: Optional[int]
    error: Optional[str] = None


async def sync_candidate_linkedin(
    db: AsyncSession,
    candidate: Candidate,
    *,
    client: Optional[ProxycurlClient] = None,
) -> SyncResult:
    """Fetch the candidate's LinkedIn profile, classify change, persist.

    `client` injection is for tests. In production, a fresh client is
    created per call so HTTP connections don't leak between sessions.
    """

    # Guard: no URL → mark disabled so the scheduled loop stops retrying
    # this candidate until the user fills it in.
    if not candidate.linkedin:
        candidate.linkedin_sync_status = LinkedinSyncStatus.disabled
        candidate.linkedin_sync_error = None
        candidate.linkedin_synced_at = datetime.now(timezone.utc)
        await db.commit()
        return SyncResult(
            candidate_id=candidate.id,
            status=LinkedinSyncStatus.disabled,
            change_kind=None,
            snapshot_id=None,
        )

    normalized = normalize_linkedin_url(candidate.linkedin)
    if normalized is None:
        candidate.linkedin_sync_status = LinkedinSyncStatus.error
        candidate.linkedin_sync_error = "invalid_url"
        candidate.linkedin_synced_at = datetime.now(timezone.utc)
        await db.commit()
        return SyncResult(
            candidate_id=candidate.id,
            status=LinkedinSyncStatus.error,
            change_kind=None,
            snapshot_id=None,
            error="invalid_url",
        )

    prev_snapshot = await _load_latest_snapshot(db, candidate.id)
    prev_profile = _to_profile(prev_snapshot)

    owns_client = client is None
    try:
        if owns_client:
            client = ProxycurlClient()
        try:
            profile = await client.fetch_profile(normalized)
        finally:
            if owns_client:
                await client.close()
    except ProfileNotFound as exc:
        candidate.linkedin_sync_status = LinkedinSyncStatus.not_found
        candidate.linkedin_sync_error = "profile_not_found"
        candidate.linkedin_synced_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "Proxycurl 404 for candidate %s (%s)", candidate.id, exc.url
        )
        return SyncResult(
            candidate_id=candidate.id,
            status=LinkedinSyncStatus.not_found,
            change_kind=None,
            snapshot_id=None,
            error="profile_not_found",
        )
    except ProxycurlError as exc:
        status = (
            LinkedinSyncStatus.rate_limited
            if exc.status in (429, 503)
            else LinkedinSyncStatus.error
        )
        candidate.linkedin_sync_status = status
        candidate.linkedin_sync_error = f"proxycurl_{exc.status}"
        candidate.linkedin_synced_at = datetime.now(timezone.utc)
        await db.commit()
        logger.warning(
            "Proxycurl %s for candidate %s: %r", exc.status, candidate.id, exc.body
        )
        return SyncResult(
            candidate_id=candidate.id,
            status=status,
            change_kind=None,
            snapshot_id=None,
            error=f"proxycurl_{exc.status}",
        )

    change = compute_change(prev_profile, profile)
    now = datetime.now(timezone.utc)

    snapshot = CandidateLinkedinSnapshot(
        candidate_id=candidate.id,
        fetched_at=now,
        profile_json=profile.raw,
        current_company=change.current_company,
        current_title=change.current_title,
        current_started_at=change.current_started_at,
        changed_from_previous=change.changed_from_previous,
        change_kind=change.change_kind,
    )
    db.add(snapshot)
    await db.flush()  # populates snapshot.id before pruning

    candidate.linkedin_current_company = change.current_company
    candidate.linkedin_current_title = change.current_title
    candidate.linkedin_current_started_at = change.current_started_at
    candidate.linkedin_synced_at = now
    candidate.linkedin_sync_status = LinkedinSyncStatus.ok
    candidate.linkedin_sync_error = None
    # ONLY new employer sets the "changed jobs" timestamp — promotions at
    # the same company are visible in snapshot history but do not pollute
    # the `recently_changed_jobs` filter.
    if change.change_kind == LinkedinChangeKind.new_company:
        candidate.linkedin_employment_changed_at = now

    pruned = await prune_old_snapshots(db, candidate.id, keep=10)
    if pruned:
        logger.debug(
            "Pruned %d old snapshots for candidate %s", pruned, candidate.id
        )
    await db.commit()

    return SyncResult(
        candidate_id=candidate.id,
        status=LinkedinSyncStatus.ok,
        change_kind=change.change_kind,
        snapshot_id=snapshot.id,
    )


async def prune_old_snapshots(
    db: AsyncSession, candidate_id: int, *, keep: int = 10
) -> int:
    """Keep only the most-recent `keep` snapshots per candidate.

    Returns the number of rows deleted. Called inline after every new
    snapshot so disk stays bounded (10 * ~30 KB = 300 KB per candidate max).
    """

    stmt = (
        select(CandidateLinkedinSnapshot.id)
        .where(CandidateLinkedinSnapshot.candidate_id == candidate_id)
        .order_by(CandidateLinkedinSnapshot.fetched_at.desc())
        .offset(keep)
    )
    old_ids = (await db.execute(stmt)).scalars().all()
    if not old_ids:
        return 0
    await db.execute(
        delete(CandidateLinkedinSnapshot).where(
            CandidateLinkedinSnapshot.id.in_(old_ids)
        )
    )
    return len(old_ids)


async def _load_latest_snapshot(
    db: AsyncSession, candidate_id: int
) -> Optional[CandidateLinkedinSnapshot]:
    stmt = (
        select(CandidateLinkedinSnapshot)
        .where(CandidateLinkedinSnapshot.candidate_id == candidate_id)
        .order_by(CandidateLinkedinSnapshot.fetched_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _to_profile(
    snapshot: Optional[CandidateLinkedinSnapshot],
) -> Optional[ProxycurlProfile]:
    """Materialize a `ProxycurlProfile` from a persisted snapshot row.

    `raw` is populated from `profile_json` (may be empty dict) so callers
    that care about the full payload — e.g. re-running diff logic
    offline — can still get it. Diff logic only uses the `current_*`
    fields, which are denormalized on the snapshot row.
    """

    if snapshot is None:
        return None
    return ProxycurlProfile(
        raw=snapshot.profile_json or {},
        current_company=snapshot.current_company,
        current_title=snapshot.current_title,
        current_started_at=snapshot.current_started_at,
    )


__all__ = [
    "SyncResult",
    "sync_candidate_linkedin",
    "prune_old_snapshots",
]
