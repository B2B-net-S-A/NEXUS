from types import SimpleNamespace

from app.services.proposal_contract import proposal_fingerprint, snapshot_is_stale


def test_legacy_ready_snapshots_need_refresh_even_if_data_was_not_edited():
    for old_stamp in (None, "a" * 64, "proposal-old-policy:hash"):
        assert snapshot_is_stale(
            SimpleNamespace(status="ready", stale=False, input_fingerprint=old_stamp)
        )
    current = SimpleNamespace(
        status="ready", stale=False, input_fingerprint=proposal_fingerprint("Python")
    )
    assert not snapshot_is_stale(current)
    current.stale = True
    assert snapshot_is_stale(current)


def test_pending_snapshot_is_not_an_obsolete_ranking():
    assert not snapshot_is_stale(
        SimpleNamespace(status="pending", stale=False, input_fingerprint=None)
    )


def test_request_content_is_preserved_in_versioned_fingerprint():
    text = "intro" * 3000
    assert proposal_fingerprint(text + " Django") != proposal_fingerprint(
        text + " Java"
    )


def test_context_change_invalidates_ready_snapshot_without_mutating_flag():
    snap = SimpleNamespace(
        status="ready", stale=False, input_fingerprint=proposal_fingerprint("context-A")
    )
    assert not snapshot_is_stale(snap, context_fingerprint="context-A")
    assert snapshot_is_stale(snap, context_fingerprint="context-B")
    assert snap.stale is False


async def test_viewer_freshness_uses_current_user_client_profile_and_full_request(
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from app.services.proposal_contract import snapshot_is_stale_for_viewer
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import DEFAULT_PROFILE, WeightProfile
    from tests.test_scoring_service import make_job

    job = make_job(client_id=8, description="X" * 9000 + "Python")
    context = build_request_context(job, DEFAULT_PROFILE)
    snap = SimpleNamespace(
        status="ready",
        stale=False,
        input_fingerprint=proposal_fingerprint(context.fingerprint),
    )
    profile = AsyncMock(return_value=DEFAULT_PROFILE)
    monkeypatch.setattr("app.services.scoring_service.resolve_active_profile", profile)
    assert not await snapshot_is_stale_for_viewer(None, snap, job, 42)
    profile.assert_awaited_once_with(None, user_id=42, client_id=8)
    job.description += " Django"
    assert await snapshot_is_stale_for_viewer(None, snap, job, 42)
    job.description = "X" * 9000 + "Python"
    profile.return_value = WeightProfile(
        id=99,
        name="Viewer",
        semantic=10,
        skills=90,
        salary=0,
        location=0,
        availability=0,
        champion_fit=0,
    )
    assert await snapshot_is_stale_for_viewer(None, snap, job, 43)
