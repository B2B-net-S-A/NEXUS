"""Pure-function tests for `services.request_history`.

Heavier integration paths (Qdrant + DB fixtures + endpoint dedup) are deferred
to the manual smoke / Chrome MCP run on `nexus.dynaminds.pl` — see
`docs/request-history-completion-report.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.request_history import (
    RequestHistoryEntry,
    SAME_TRAIN_BOOST,
    SQL_FAST_PATH_LIMIT,
    _build_query_text,
    aggregate_meta_counts,
)


def _make_entry(
    job_id: int,
    *,
    similarity: float = 0.9,
    similarity_source: str = "voyage",
    same_train: bool = False,
    is_in_progress: bool = False,
) -> RequestHistoryEntry:
    return RequestHistoryEntry(
        job_id=job_id,
        title=f"Job {job_id}",
        train_name=None,
        same_train=same_train,
        seniority=None,
        status="closed",
        is_in_progress=is_in_progress,
        outcome="filled",
        close_reason=None,
        similarity=similarity,
        similarity_source=similarity_source,  # type: ignore[arg-type]
        closed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        tth_days=200,
        client_id=42,
        client_name="Acme",
        champion_name="Jan Kowalski",
        champion_candidate_id=10,
        champions_count=1,
        candidates_count=15,
        fee_rate=2500,
        fee_currency="PLN",
        rate_unit="monthly",
        tac_name="Anna T.",
        delivery_lead_name="Bartek D.",
    )


def test_aggregate_meta_counts_empty():
    assert aggregate_meta_counts([]) == {
        "sql_count": 0,
        "voyage_count": 0,
        "total": 0,
    }


def test_aggregate_meta_counts_split_correctly():
    entries = [
        _make_entry(1, similarity_source="sql_same_client"),
        _make_entry(2, similarity_source="sql_same_client"),
        _make_entry(3, similarity_source="voyage"),
    ]
    counts = aggregate_meta_counts(entries)
    assert counts == {"sql_count": 2, "voyage_count": 1, "total": 3}


def test_build_query_text_concatenates_title_and_description():
    text = _build_query_text(title="Senior Java Dev", raw_description="React + AWS")
    assert "Senior Java Dev" in text
    assert "React + AWS" in text


def test_build_query_text_truncates_description_to_1200_chars():
    long_desc = "x" * 5000
    text = _build_query_text(title="Role", raw_description=long_desc)
    # Title (4) + space (1) + capped desc (1200) = 1205
    assert len(text) <= 1205
    assert text.startswith("Role")


def test_build_query_text_handles_missing_description():
    assert _build_query_text(title="Solo", raw_description=None) == "Solo"


def test_build_query_text_returns_empty_when_both_missing():
    assert _build_query_text(title="", raw_description=None) == ""


def test_request_history_entry_immutable():
    """Frozen dataclass — mutation must raise."""
    e = _make_entry(1)
    try:
        e.title = "Mutated"  # type: ignore[misc]
    except Exception:
        return  # FrozenInstanceError variants
    raise AssertionError("RequestHistoryEntry should be frozen")


def test_constants_are_sane():
    assert 0 < SAME_TRAIN_BOOST < 0.5
    assert SQL_FAST_PATH_LIMIT >= 10
