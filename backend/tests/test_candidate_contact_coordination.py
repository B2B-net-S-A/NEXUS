"""Focused, host-native tests for candidate contact coordination."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import String

from app.models.call import Call
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactOpportunity,
)
from app.schemas.candidate_contact import ContactAttemptCreate
from app.services.candidate_contact import ContactConflict, ContactValidationError
from app.services.candidate_contact_coordination import (
    _event_attempt_key,
    _is_eod_overdue,
    _normalise_job_outcomes,
    _normalise_source,
    initial_contact_due_at,
    next_business_day_at,
)


def test_initial_due_at_cutoff_is_inclusive_in_warsaw_summer() -> None:
    # 14:00 UTC is exactly 16:00 CEST.
    at_cutoff = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
    after_cutoff = datetime(2026, 7, 27, 14, 0, 1, tzinfo=timezone.utc)

    assert initial_contact_due_at(at_cutoff) == datetime(
        2026, 7, 27, 16, 0, tzinfo=timezone.utc
    )
    assert initial_contact_due_at(after_cutoff) == datetime(
        2026, 7, 28, 8, 0, tzinfo=timezone.utc
    )


def test_initial_due_at_skips_weekend_and_is_dst_safe() -> None:
    friday_after_cutoff = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)
    winter_before_cutoff = datetime(2026, 1, 12, 14, 0, tzinfo=timezone.utc)

    assert initial_contact_due_at(friday_after_cutoff) == datetime(
        2026, 8, 3, 8, 0, tzinfo=timezone.utc
    )
    # 14:00 UTC == 15:00 CET; same-day 18:00 CET == 17:00 UTC.
    assert initial_contact_due_at(winter_before_cutoff) == datetime(
        2026, 1, 12, 17, 0, tzinfo=timezone.utc
    )


def test_next_business_day_at_never_returns_weekend() -> None:
    friday = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    assert next_business_day_at(friday) == datetime(
        2026, 8, 3, 8, 0, tzinfo=timezone.utc
    )


def test_eod_overdue_catches_up_after_weekend_restart() -> None:
    contact_case = SimpleNamespace(
        state="queued",
        due_at=datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc),
    )

    assert not _is_eod_overdue(
        contact_case,
        datetime(2026, 7, 31, 15, 59, tzinfo=timezone.utc),
    )
    assert _is_eod_overdue(
        contact_case,
        datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
    )
    assert _is_eod_overdue(
        contact_case,
        datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc),
    )


def test_callback_after_18_waits_for_next_business_day_turnover() -> None:
    # Monday 18:00 UTC == 20:00 CEST, after the local daily turnover.
    contact_case = SimpleNamespace(
        state="callback_due",
        due_at=datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc),
        assigned_at=None,
    )

    assert not _is_eod_overdue(
        contact_case,
        datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc),
    )
    assert not _is_eod_overdue(
        contact_case,
        datetime(2026, 7, 28, 15, 59, tzinfo=timezone.utc),
    )
    assert _is_eod_overdue(
        contact_case,
        datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        ("pipeline", "pipeline"),
        ("nexus_pipeline", "pipeline"),
        ("nexus_pipeline_bulk", "pipeline"),
        ("shortlist", "shortlist"),
        ("nexus_shortlist", "shortlist"),
        ("nexus_shortlist_promotion", "shortlist"),
        ("traffit", "traffit"),
        ("traffit_pipeline_import", "traffit"),
    ],
)
def test_runtime_source_aliases_are_canonical(source: str, canonical: str) -> None:
    assert _normalise_source(source) == canonical


def test_attempt_contract_uses_job_id_and_requires_callback_when_needed() -> None:
    body = ContactAttemptCreate(
        expected_version=2,
        outcome="connected",
        opportunity_outcomes=[{"job_id": 41, "outcome": "interested"}],
    )
    assert body.opportunity_outcomes[0].job_id == 41
    assert _normalise_job_outcomes(body.opportunity_outcomes) == {41: "interested"}

    with pytest.raises(ValidationError):
        ContactAttemptCreate(
            expected_version=2,
            outcome="callback_requested",
            opportunity_outcomes=[{"job_id": 41, "outcome": "interested"}],
        )


def test_callback_requested_accepts_any_complete_job_outcomes() -> None:
    body = ContactAttemptCreate(
        expected_version=1,
        outcome="callback_requested",
        callback_at=datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
        opportunity_outcomes=[
            {"job_id": 1, "outcome": "interested"},
            {"job_id": 2, "outcome": "not_interested"},
        ],
    )
    assert [item.job_id for item in body.opportunity_outcomes] == [1, 2]


def test_event_idempotency_key_is_bounded_for_max_header() -> None:
    raw = "x" * 160
    assert len(_event_attempt_key(raw)) < 160
    assert len(_event_attempt_key(raw, "job:2147483647")) < 160
    assert _event_attempt_key(raw) == _event_attempt_key(raw)


def test_models_use_varchar_and_database_capacity_fences() -> None:
    case_table = CandidateContactCase.__table__
    opportunity_table = CandidateContactOpportunity.__table__

    assert isinstance(case_table.c.state.type, String)
    assert isinstance(opportunity_table.c.outcome.type, String)
    assert not opportunity_table.c.linked_at.nullable
    assert "source_cursor_created_at" in opportunity_table.c
    assert "source_cursor_external_id" in opportunity_table.c
    constraints = {constraint.name for constraint in case_table.constraints}
    assert "ck_candidate_contact_cases_queue_slot" in constraints
    assert "ck_candidate_contact_cases_actionable_slot" in constraints
    indexes = {index.name: index for index in case_table.indexes}
    assert indexes["ux_candidate_contact_cases_owner_slot"].unique
    assert (
        indexes["ux_candidate_contact_cases_owner_slot"].dialect_options["postgresql"][
            "where"
        ]
        is not None
    )


def test_call_reuses_one_partial_idempotency_index() -> None:
    table = Call.__table__
    assert "contact_case_id" in table.c
    assert "contact_outcome" in table.c
    assert "contact_request_hash" in table.c
    index = next(
        item
        for item in table.indexes
        if item.name == "ux_calls_contact_idempotency_key"
    )
    assert index.unique
    assert index.dialect_options["postgresql"]["where"] is not None


def test_public_conflict_contract_is_distinct_from_validation() -> None:
    assert issubclass(ContactConflict, ContactValidationError)


def test_migration_is_linear_from_current_head_and_has_entrypoint_mirror() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "alembic/versions/0200_candidate_contact_coordination.py"
    ).read_text()
    entrypoint = (root / "entrypoint.sh").read_text()

    assert 'down_revision = "0199_candidate_stage_removals"' in migration
    for table in (
        "candidate_contact_cases",
        "candidate_contact_opportunities",
        "candidate_contact_events",
        "candidate_contact_traffit_cursors",
        "candidate_contact_traffit_ledger",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
        assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint
    assert "linked_at TIMESTAMPTZ NOT NULL" in migration
    assert "source_cursor_created_at TIMESTAMPTZ" in migration
    assert "source_cursor_external_id VARCHAR(255)" in migration
    assert "source_cursor_created_at TIMESTAMPTZ" in entrypoint
    assert "source_cursor_external_id VARCHAR(255)" in entrypoint
    assert "trg_candidate_contact_events_immutable" in migration
    assert "BEFORE UPDATE OR DELETE ON candidate_contact_events" in migration
    assert "trg_candidate_contact_events_immutable" in entrypoint
