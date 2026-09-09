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
