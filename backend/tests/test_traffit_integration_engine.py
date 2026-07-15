"""Unit tests for deterministic integration primitives and durable queues."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.logging_config import SensitivePathFilter, redact_sensitive_path
from app.services.traffit.field_contracts import (
    candidate_to_traffit,
    normalize_metadata,
)
from app.services.traffit.inbound import _effective_reconcile_cursor
from app.models.skill import Skill  # noqa: F401 - register relationship target
from app.api import traffit_integration as traffit_integration_api
from app.services.traffit import outbound
from app.services.traffit.outbound import _remote_to_local_snapshot
from app.services.traffit.merge import snapshot_hash, three_way_merge
from app.services.traffit.outbox import (
    OutboxCommand,
    _enqueue_command,
    enqueue_traffit_event,
)
from app.services.traffit.webhook import (
    assert_webhook_authorized,
    identify_webhook,
    ingest_webhook,
    secret_hash,
)


def test_three_way_merge_auto_merges_disjoint_fields() -> None:
    result = three_way_merge(
        {"email": "old@example.com", "phone": "111"},
        {"email": "new@example.com", "phone": "111"},
        {"email": "old@example.com", "phone": "222"},
    )
    assert result.conflicts == []
    assert result.merged == {"email": "new@example.com", "phone": "222"}
    assert result.apply_to_nexus == {"phone": "222"}
    assert result.apply_to_traffit == {"email": "new@example.com"}


def test_three_way_merge_preserves_same_field_conflict() -> None:
    result = three_way_merge(
        {"location": "Warszawa"},
        {"location": "Kraków"},
        {"location": "Gdańsk"},
    )
    assert result.is_conflicted
    assert result.merged == {"location": "Warszawa"}
    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}
    conflict = result.conflicts[0]
    assert conflict.field_path == "location"
    assert conflict.nexus_value == "Kraków"
    assert conflict.traffit_value == "Gdańsk"


def test_three_way_merge_handles_nested_custom_fields_and_stable_hash() -> None:
    base = {"custom_fields": {"_Position": "Dev", "_Level": "Mid"}}
    result = three_way_merge(
        base,
        {"custom_fields": {"_Position": "Lead", "_Level": "Mid"}},
        {"custom_fields": {"_Position": "Dev", "_Level": "Senior"}},
    )
    assert result.merged == {"custom_fields": {"_Level": "Senior", "_Position": "Lead"}}
    assert snapshot_hash(result.merged) == snapshot_hash(
        {"custom_fields": {"_Position": "Lead", "_Level": "Senior"}}
    )


def test_remote_snapshot_preserves_unmapped_shared_baseline_fields() -> None:
    base = {
        "email": "old@example.com",
        "source": "referral",
        "availability_date": "2026-08-01",
        "custom_fields": {
            "traffit_Position": "Backend",
            "local_contract_note": "retain",
        },
    }

    remote = _remote_to_local_snapshot(
        {
            "id": 42,
            "email": "remote@example.com",
            "_Position": "Backend",
        },
        base=base,
    )
    result = three_way_merge(
        base,
        {**base, "email": "nexus@example.com"},
        remote,
    )

    assert result.apply_to_nexus == {}
    assert result.apply_to_traffit == {}
    assert result.conflicts[0].field_path == "email"
    assert result.merged["source"] == "referral"
    assert result.merged["availability_date"] == "2026-08-01"
    assert result.merged["custom_fields"]["local_contract_note"] == "retain"
    assert remote["custom_fields"]["traffit_Position"] == "Backend"


@pytest.mark.asyncio
async def test_candidate_update_keeps_complete_shared_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {
        "email": "old@example.com",
        "source": "referral",
        "availability_date": "2026-08-01",
        "custom_fields": {
            "_Position": "Backend",
            "local_contract_note": "retain",
        },
    }
    link = SimpleNamespace(base_snapshot=base)
    event = SimpleNamespace(
        payload={"fields": {"email": "new@example.com"}},
        candidate_id=41,
    )
    client = SimpleNamespace(
        get_json=AsyncMock(
            return_value={
                "id": 42,
                "email": "old@example.com",
                "_Position": "Backend",
            }
        ),
        patch_json=AsyncMock(),
    )
    upsert_link = AsyncMock()
    monkeypatch.setattr(
        outbound,
        "_employee_id",
        AsyncMock(return_value=("42", link)),
    )
    monkeypatch.setattr(
        outbound,
        "_adapt_candidate_payload",
        AsyncMock(
            return_value=(
                {
                    "email": "new@example.com",
                    "custom_fields": {"_Position": "Lead"},
                },
                {"email": "new@example.com", "_Position": "Lead"},
                [],
            )
        ),
    )
    monkeypatch.setattr(outbound, "_upsert_candidate_link", upsert_link)

    result = await outbound._candidate_update(
        SimpleNamespace(),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        event,  # type: ignore[arg-type]
    )

    assert result.status == "succeeded"
    client.patch_json.assert_awaited_once_with(
        "/employees/42",
        {"email": "new@example.com", "_Position": "Lead"},
    )
    shared = upsert_link.await_args.args[3]
    assert shared == {
        "email": "new@example.com",
        "source": "referral",
        "availability_date": "2026-08-01",
        "custom_fields": {
            "_Position": "Lead",
            "local_contract_note": "retain",
        },
    }


def test_shadow_reconcile_cursor_is_read_independently_from_live_cursor() -> None:
    live_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    shadow_at = datetime(2026, 7, 12, 8, 30, tzinfo=timezone.utc)
    state = SimpleNamespace(
        cursor_at=live_at,
        cursor_external_id="live-10",
        cursor_payload={
            "shadow_cursor_at": shadow_at.isoformat(),
            "shadow_cursor_external_id": "shadow-99",
        },
    )

    assert _effective_reconcile_cursor(state, dry_run=True) == (
        shadow_at,
        "shadow-99",
    )
    assert _effective_reconcile_cursor(state, dry_run=False) == (
        live_at,
        "live-10",
    )


def test_metadata_contract_normalizes_and_quarantines_unknown_type() -> None:
    contracts = normalize_metadata(
        {
            "fields": [
                {"name": "email", "type": "email", "required": True},
                {"name": "candidate_languages", "type": "array"},
                {"name": "_SID", "type": "quantum-widget"},
            ]
        },
        "patch",
    )
    assert [item.adapter for item in contracts] == ["string", "list", "unsupported"]
    assert contracts[2].local_path == "custom_fields._SID"
    payload, quarantined = candidate_to_traffit(
        {
            "email": "ada@example.com",
            "languages": [{"lang": "pl", "level": "C2"}],
            "custom_fields": {"_SID": "x"},
        },
        contracts,
    )
    assert payload == {"email": "ada@example.com", "candidate_languages": ["pl"]}
    assert quarantined == ["_SID"]


def test_webhook_auth_and_identity_are_deterministic() -> None:
    body = b'{"type":"candidate_updated","employee":{"id":42}}'
    assert_webhook_authorized(
        url_secret="secret",
        expected_secret_hash=secret_hash("secret"),
        raw_body=body,
    )
    first = identify_webhook(
        "sub", {"type": "candidate_updated", "employee": {"id": 42}}
    )
    second = identify_webhook(
        "sub", {"employee": {"id": 42}, "type": "candidate_updated"}
    )
    assert first.dedupe_key == second.dedupe_key
    assert first.remote_entity_type == "employee"
    assert first.remote_entity_id == "42"


def test_traffit_webhook_url_secret_is_redacted_from_access_logs() -> None:
    path = "/api/integrations/traffit/webhooks/sub-1/super-secret-token?x=1"
    assert redact_sensitive_path(path) == (
        "/api/integrations/traffit/webhooks/sub-1/[REDACTED]?x=1"
    )
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "POST", path, "1.1", 202),
        None,
    )
    assert SensitivePathFilter().filter(record) is True
    assert "super-secret-token" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


class _FakeSession:
    def __init__(self, scalar_results: list[Any] | None = None) -> None:
        self.scalar_results = list(scalar_results or [])
        self.added: list[Any] = []
        self.calls: list[str] = []

    async def scalar(self, _query: Any) -> Any:
        self.calls.append("scalar")
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def execute(self, _query: Any, _params: Any = None) -> None:
        self.calls.append("advisory_lock")

    def add(self, value: Any) -> None:
        self.calls.append("add")
        self.added.append(value)

    async def flush(self) -> None:
        self.calls.append("flush")

    def begin_nested(self) -> "_FakeNestedTransaction":
        self.calls.append("begin_nested")
        return _FakeNestedTransaction()


class _FakeNestedTransaction:
    async def __aenter__(self) -> "_FakeNestedTransaction":
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False


@pytest.mark.asyncio
async def test_outbox_sequence_is_allocated_under_partition_advisory_lock() -> None:
    db = _FakeSession([7])
    event = await _enqueue_command(
        db,  # type: ignore[arg-type]
        OutboxCommand(
            event_type="candidate.update",
            aggregate_type="candidate",
            aggregate_id=12,
            candidate_id=12,
            payload={"fields": {"email": "new@example.com"}},
        ),
    )
    assert event is not None
    assert event.sequence == 8
    assert event.status == "pending"
    assert db.calls[:2] == ["advisory_lock", "scalar"]


@pytest.mark.asyncio
async def test_public_enqueue_fails_before_database_when_master_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRAFFIT_INTEGRATION_ENABLED", "false")
    db = _FakeSession()
    event = await enqueue_traffit_event(
        db,  # type: ignore[arg-type]
        "candidate.update",
        "candidate",
        12,
        {"fields": {"email": "new@example.com"}},
        candidate_id=12,
    )
    assert event is None
    assert db.calls == []


@pytest.mark.asyncio
async def test_inbox_ingest_is_durable_and_idempotent() -> None:
    db = _FakeSession([None])
    payload = {"type": "candidate_updated", "employee": {"id": 42}}
    event, created = await ingest_webhook(
        db,  # type: ignore[arg-type]
        subscription_id="sub",
        payload=payload,
        request_id="evt-1",
    )
    assert created is True
    assert event.status == "pending"
    assert event.remote_entity_id == "42"
    assert db.added == [event]

    duplicate_db = _FakeSession([event])
    duplicate, created = await ingest_webhook(
        duplicate_db,  # type: ignore[arg-type]
        subscription_id="sub",
        payload=payload,
        request_id="evt-1",
    )
    assert created is False
    assert duplicate is event
    assert duplicate_db.added == []


def test_actionable_conflict_filter_includes_manual_review_queue() -> None:
    assert traffit_integration_api._conflict_status_values("actionable") == (
        "open",
        "manual_action_required",
    )


@pytest.mark.asyncio
async def test_eventless_custom_field_resolution_queues_nested_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = SimpleNamespace(
        id=17,
        status="open",
        entity_type="candidate",
        nexus_entity_id=41,
        candidate_id=41,
        entity_link_id=81,
        outbox_event_id=None,
        field_path="custom_fields._SID",
        conflict_type="same_field_changed",
        nexus_value="Lead",
        traffit_value="Developer",
    )
    link = SimpleNamespace(
        id=81,
        status="conflict",
        base_snapshot={"custom_fields": {"_SID": "Developer"}},
    )
    db = SimpleNamespace(
        get=AsyncMock(side_effect=[conflict, link]),
        flush=AsyncMock(),
    )
    queued = SimpleNamespace(id=99)
    enqueue = AsyncMock(return_value=queued)
    monkeypatch.setattr(traffit_integration_api, "enqueue_traffit_event", enqueue)

    await traffit_integration_api.resolve_conflict(
        17,
        traffit_integration_api.ConflictResolution(resolution="nexus"),
        SimpleNamespace(id=7),
        db,  # type: ignore[arg-type]
    )

    assert enqueue.await_args.args[4]["fields"] == {"custom_fields": {"_SID": "Lead"}}
    assert link.status == "pending"


@pytest.mark.asyncio
async def test_manual_delete_worker_reuses_api_review_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = SimpleNamespace(
        id=31,
        outbox_event_id=21,
        status="manual_action_required",
    )
    link = SimpleNamespace(id=81, status="pending")
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=existing),
        get=AsyncMock(return_value=link),
    )
    record_conflict = AsyncMock()
    monkeypatch.setattr(outbound, "_record_conflict", record_conflict)
    event = SimpleNamespace(
        id=21,
        event_type="candidate.delete_requested",
        aggregate_type="candidate",
        aggregate_id=41,
        candidate_id=41,
        entity_link_id=81,
        payload={"action": "delete"},
    )

    result = await outbound._manual_action(db, event)  # type: ignore[arg-type]

    assert result.status == "manual_action_required"
    record_conflict.assert_not_awaited()
    assert link.status == "manual_action_required"
