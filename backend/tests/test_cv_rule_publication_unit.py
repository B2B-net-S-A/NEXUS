"""CV-17: draft isolation, atomic publication, immutable history and conflicts."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import client_cv_rules as api
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_publication import ClientCvRulePublication


def context():
    client = SimpleNamespace(
        id=26, cv_content_mode_cap="tailored", cv_interactive_enabled=True
    )
    rule = ClientCvRule(client_id=26, version=3, edit_revision=4)
    api._apply_payload(
        rule,
        api.ClientCvRulePayload(
            filename_pattern="OLD_{IMIE_NAZWISKO}",
            cv_language="pl",
            max_roles=5,
        ),
    )
    rule.confirmed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rule.confirmed_by = 7
    db = AsyncMock()
    db.add = Mock()
    actor = SimpleNamespace(id=8, name="Delivery Lead")
    return client, rule, db, actor


def changed_payload(confirm=False):
    return api.ClientCvRulePayload(
        filename_pattern="NEW_{IMIE_NAZWISKO}",
        cv_language="en",
        max_roles=2,
        cv_content_mode_cap="basic",
        cv_interactive_enabled=False,
        confirm=confirm,
    )


async def test_saving_draft_preserves_published_recipe_flags_and_version():
    client, rule, db, actor = context()
    original = api._rule_state(rule, client)
    await api._store_recipe(db, client, rule, changed_payload(), actor)
    assert api._rule_state(rule, client) == original
    assert rule.confirmed_by == 7
    assert rule.confirmed_at == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert rule.version == 3
    assert rule.edit_revision == 5
    assert rule.draft_payload["cv_language"] == "en"
    assert rule.draft_payload["cv_interactive_enabled"] is False
    assert not any(
        isinstance(c.args[0], ClientCvRulePublication) for c in db.add.call_args_list
    )


async def test_publication_applies_complete_recipe_and_freezes_snapshot():
    client, rule, db, actor = context()
    await api._store_recipe(db, client, rule, changed_payload(True), actor)
    assert rule.cv_language == "en" and rule.max_roles == 2
    assert client.cv_content_mode_cap == "basic"
    assert client.cv_interactive_enabled is False
    assert rule.version == 4 and rule.edit_revision == 5
    assert rule.draft_payload is None
    published = [
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], ClientCvRulePublication)
    ]
    assert len(published) == 1
    assert published[0].recipe == api._rule_state(rule, client)
    rule.cv_language = "pl"
    assert published[0].recipe["cv_language"] == "en"
    db.commit.assert_awaited_once()


async def test_republishing_identical_recipe_does_not_duplicate_version():
    client, rule, db, actor = context()
    await api._store_recipe(
        db,
        client,
        rule,
        api.ClientCvRulePayload(
            **api._rule_state(rule, client),
            confirm=True,
        ),
        actor,
    )
    assert rule.version == 3
    assert not any(
        isinstance(c.args[0], ClientCvRulePublication) for c in db.add.call_args_list
    )


@pytest.mark.parametrize("expected", [None, 0, 3, 5])
async def test_stale_or_missing_revision_rejected_before_mutation(
    monkeypatch, expected
):
    client, rule, db, _ = context()
    monkeypatch.setattr(api, "_rule_for", AsyncMock(return_value=rule))
    with pytest.raises(HTTPException) as error:
        await api._lock_rule_edit(db, client, expected)
    assert error.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_current_revision_may_edit(monkeypatch):
    client, rule, db, _ = context()
    monkeypatch.setattr(api, "_rule_for", AsyncMock(return_value=rule))
    assert await api._lock_rule_edit(db, client, 4) is rule
    db.execute.assert_awaited_once()


async def test_restoration_creates_draft_without_reverting_live_flags(monkeypatch):
    client, rule, db, actor = context()
    snapshot = api._recipe_payload(changed_payload(), client)
    publication = ClientCvRulePublication(client_id=26, version=1, recipe=snapshot)
    db.get.return_value = publication
    monkeypatch.setattr(api, "_client_or_404", AsyncMock(return_value=client))
    monkeypatch.setattr(api, "_require_client_rule_access", AsyncMock())
    monkeypatch.setattr(api, "_lock_rule_edit", AsyncMock(return_value=rule))
    monkeypatch.setattr(api, "_client_label", lambda _: "Test Client")
    before = api._rule_state(rule, client)
    await api.restore_cv_rule_version(26, 1, actor, db, expected_revision=4)
    assert api._rule_state(rule, client) == before
    assert rule.draft_payload == snapshot
    assert rule.edit_revision == 5


async def test_preview_uses_queued_recipe_without_reading_changed_rule(monkeypatch):
    from app.models.client_cv_rule_preview import ClientCvRulePreview
    from app.services.cv_generator_b2b.standalone_service import GenerationResult

    client, _, db, _ = context()
    row = ClientCvRulePreview(
        id=1,
        client_id=26,
        recipe_snapshot=api._recipe_payload(changed_payload(), client),
    )
    db.get.return_value = row
    manager = Mock()
    manager.__aenter__ = AsyncMock(return_value=db)
    manager.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(api, "AsyncSessionLocal", lambda: manager)
    current_rule = AsyncMock(side_effect=AssertionError("must not read current rule"))
    monkeypatch.setattr(api, "_rule_for", current_rule)
    generate = AsyncMock(
        return_value=GenerationResult(
            candidate_name="Test",
            filename="test.docx",
            docx_bytes=b"docx",
            warnings=[],
            processing_time_ms=1,
            render_payload={},
            job_id=1,
        )
    )
    source = object()
    load_source = AsyncMock(return_value=source)
    monkeypatch.setattr(api, "load_candidate_generation_source", load_source)
    monkeypatch.setattr(api, "generate_cv_from_candidate_source", generate)
    await api._run_rule_preview_job_inner(
        1, client_id=26, candidate_id=2, stage_id=3, language="en"
    )
    assert row.status == "ready"
    load_source.assert_awaited_once()
    assert generate.await_count == 2
    assert all(call.args == (source,) for call in generate.call_args_list)
    assert generate.call_args_list[0].kwargs["client_rule"].cv_language == "en"
    assert (
        generate.call_args_list[0].kwargs["client_policy_override"][
            "cv_content_mode_cap"
        ]
        == "basic"
    )
    current_rule.assert_not_awaited()


def test_invalid_historical_draft_returns_actionable_422():
    _, rule, _, _ = context()
    rule.draft_payload = {"filename_pattern": "B2B_STANOWISKO_IMIE_NAZWISKO"}
    with pytest.raises(HTTPException) as caught:
        api._editable_rule(rule)
    assert caught.value.status_code == 422
    assert "Reguła wymaga poprawienia" in caught.value.detail


async def test_delete_audits_reset_client_flags(monkeypatch):
    client, rule, db, actor = context()
    client.cv_content_mode_cap = "basic"
    client.cv_interactive_enabled = False
    monkeypatch.setattr(api, "_client_or_404", AsyncMock(return_value=client))
    monkeypatch.setattr(api, "_require_client_rule_access", AsyncMock())
    monkeypatch.setattr(api, "_lock_rule_edit", AsyncMock(return_value=rule))
    record = Mock()
    monkeypatch.setattr(api, "_record_event", record)
    await api.delete_client_cv_rule(26, actor, db, expected_revision=4)
    assert record.call_args.kwargs["changes"] == {
        "cv_content_mode_cap": {"from": "basic", "to": None},
        "cv_interactive_enabled": {"from": False, "to": True},
    }


async def test_deleted_recipe_revision_survives_on_client(monkeypatch):
    client, rule, db, actor = context()
    monkeypatch.setattr(api, "_client_or_404", AsyncMock(return_value=client))
    monkeypatch.setattr(api, "_require_client_rule_access", AsyncMock())
    monkeypatch.setattr(api, "_lock_rule_edit", AsyncMock(return_value=rule))
    await api.delete_client_cv_rule(26, actor, db, expected_revision=4)
    assert client.cv_rule_edit_revision == 5
    read = api._to_read(None, client=client, client_id=26, client_name="Test")
    assert read.edit_revision == 5
