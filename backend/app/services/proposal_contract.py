"""Version proposal snapshots independently of mutable data invalidation flags."""

import hashlib

PROPOSAL_INPUT_VERSION = "proposal-canonical-fit-v4"


def proposal_fingerprint(query_text: str) -> str:
    return f"{PROPOSAL_INPUT_VERSION}:{hashlib.sha256(query_text.encode()).hexdigest()}"


def snapshot_is_stale(snapshot, *, context_fingerprint: str | None = None) -> bool:
    if snapshot.status != "ready":
        return bool(snapshot.stale)
    if (
        context_fingerprint is not None
        and snapshot.input_fingerprint != proposal_fingerprint(context_fingerprint)
    ):
        return True
    return bool(snapshot.stale) or not (snapshot.input_fingerprint or "").startswith(
        f"{PROPOSAL_INPUT_VERSION}:"
    )


async def snapshot_is_stale_for_viewer(db, snapshot, job, user_id: int) -> bool:
    """Compare the saved fit context with the viewer's current Radar/C2 context."""
    if snapshot.status != "ready" or snapshot_is_stale(snapshot):
        return snapshot_is_stale(snapshot)
    from app.services.scoring_service import resolve_active_profile
    from app.services.request_matching_context import build_request_context

    profile = await resolve_active_profile(db, user_id=user_id, client_id=job.client_id)
    context = build_request_context(job, profile)
    return snapshot_is_stale(snapshot, context_fingerprint=context.fingerprint)
