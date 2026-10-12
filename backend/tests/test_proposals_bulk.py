"""Schema-level tests for ``/api/jobs/{id}/proposals/bulk``.

Pure Pydantic / response-shape tests — no DB roundtrip. Integration tests
that exercise the actual SQL path live in tests/test_api_integration.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.proposals_bulk import (
    BulkProposalsRequest,
    BulkProposalsResponse,
    BulkSkippedRow,
    BulkWarningRow,
    ClosedCardInfo,
    _closed_card_label,
    _closed_stage_label,
)


class TestRequestValidation:
    def test_minimal_request(self):
        req = BulkProposalsRequest(candidate_ids=[1])
        assert req.candidate_ids == [1]
        assert req.note is None
        assert req.tags == []
        assert req.initial_stage_def_id is None

    def test_rejects_empty_candidate_list(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=[])

    def test_caps_at_100_candidates(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=list(range(1, 102)))

    def test_accepts_exactly_100_candidates(self):
        req = BulkProposalsRequest(candidate_ids=list(range(1, 101)))
        assert len(req.candidate_ids) == 100

    def test_caps_tags_at_20(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=[1], tags=[f"tag{i}" for i in range(21)])

    def test_caps_note_at_2000_chars(self):
        with pytest.raises(ValidationError):
            BulkProposalsRequest(candidate_ids=[1], note="x" * 2001)

    def test_accepts_initial_stage_override(self):
        req = BulkProposalsRequest(candidate_ids=[1], initial_stage_def_id=42)
        assert req.initial_stage_def_id == 42


class TestResponseShape:
    def test_skip_reason_literals(self):
        # Sanity-check the Literal type — invalid reason should raise.
        with pytest.raises(ValidationError):
            BulkSkippedRow(candidate_id=1, reason="invalid_reason")  # type: ignore[arg-type]

    def test_full_response(self):
        resp = BulkProposalsResponse(
            added=[1, 2, 3],
            skipped=[
                BulkSkippedRow(candidate_id=4, reason="already_in_job"),
                BulkSkippedRow(candidate_id=5, reason="blacklisted"),
            ],
            total_added=3,
            total_skipped=2,
        )
        assert resp.total_added == 3
        assert resp.total_skipped == 2
        assert resp.skipped[0].reason == "already_in_job"
        assert resp.skipped[1].reason == "blacklisted"
        assert resp.warnings == []  # defaults to empty

    def test_client_conflicts_are_warnings_not_skip_reasons(self):
        """17.09.2026: a client conflict is a warning — the candidate IS added."""
        for reason in ("client_blacklist", "client_nda", "client_competitor"):
            row = BulkWarningRow(candidate_id=1, reason=reason, reason_label="…")
            assert row.reason == reason
            assert row.reason_label == "…"
            with pytest.raises(ValidationError):
                BulkSkippedRow(candidate_id=1, reason=reason)  # type: ignore[arg-type]

    def test_eligibility_maps_client_conflicts_to_warnings(self):
        from app.api.proposals_bulk import (
            _SKIP_REASON_BY_ELIGIBILITY,
            _WARNING_REASON_BY_ELIGIBILITY,
        )
        from app.services.candidate_job_eligibility import EligibilityReason

        for reason in (
            EligibilityReason.client_blacklist,
            EligibilityReason.client_nda,
            EligibilityReason.client_competitor,
        ):
            assert reason in _WARNING_REASON_BY_ELIGIBILITY
            assert reason not in _SKIP_REASON_BY_ELIGIBILITY

    def test_warnings_on_added_candidates(self):
        resp = BulkProposalsResponse(
            added=[1, 2],
            skipped=[],
            warnings=[
                BulkWarningRow(
                    candidate_id=1,
                    reason="current_employment",
                    reason_label="Kandydat obecnie pracuje u tego klienta",
                ),
                BulkWarningRow(candidate_id=2, reason="excluded_by_candidate"),
            ],
            total_added=2,
            total_skipped=0,
        )
        assert len(resp.warnings) == 2
        assert resp.warnings[0].reason == "current_employment"

    def test_invalid_warning_reason_rejected(self):
        with pytest.raises(ValidationError):
            BulkWarningRow(candidate_id=1, reason="not_a_reason")  # type: ignore[arg-type]

    def test_serialization_roundtrip(self):
        resp = BulkProposalsResponse(
            added=[10],
            skipped=[BulkSkippedRow(candidate_id=11, reason="candidate_not_found")],
            total_added=1,
            total_skipped=1,
        )
        data = resp.model_dump()
        assert data["added"] == [10]
        assert data["skipped"][0]["reason"] == "candidate_not_found"
        # Round-trip
        rehydrated = BulkProposalsResponse.model_validate(data)
        assert rehydrated == resp


class TestClosedCard:
    """12.10.2026: zamknięta karta w tej rekrutacji to nie „już w rekrutacji”.

    Rekruter dostawał „Pominięto: 1” bez powodu, a osoba stała w „Zamkniętych”
    z odrzuceniem sprzed kilku dni. Etykieta mówi teraz etap, dzień i osobę,
    a wiersz niesie cel ruchu, którym okno kartę przywraca.
    """

    def test_skip_row_carries_the_closed_card_and_the_restore_target(self):
        row = BulkSkippedRow(
            candidate_id=7,
            reason="closed_in_job",
            reason_label="…",
            closed=ClosedCardInfo(
                candidate_name="Ewa Testowa",
                state_version=2,
                restore_stage="new",
            ),
        )
        data = row.model_dump(mode="json")
        assert data["closed"]["restore_stage"] == "new"
        assert data["closed"]["restore_stage_def_id"] is None
        # Pozostałe powody nie niosą karty.
        assert BulkSkippedRow(candidate_id=1, reason="already_in_job").closed is None

    def test_label_gives_stage_day_in_company_calendar_and_person(self):
        # 22:30 UTC to w Warszawie już następny dzień.
        closed_at = datetime(2026, 10, 8, 22, 30, tzinfo=timezone.utc)
        assert (
            _closed_card_label("Odrzucony", closed_at, "Jan Testowy")
            == "Zamknięta karta w tej rekrutacji: Odrzucony 09.10.2026 (Jan Testowy)"
        )
        assert (
            _closed_card_label("Wycofany", closed_at, None)
            == "Zamknięta karta w tej rekrutacji: Wycofany 09.10.2026"
        )

    def test_callers_asking_only_whether_a_card_exists_read_both_reasons(self):
        from typing import get_args

        from app.api.proposals_bulk import IN_JOB_SKIP_REASONS, SkipReason

        assert IN_JOB_SKIP_REASONS == {"already_in_job", "closed_in_job"}
        assert IN_JOB_SKIP_REASONS <= set(get_args(SkipReason))

    def test_stage_label_prefers_the_template_name(self):
        assert (
            _closed_stage_label("Odrzucony przez klienta", "rejected")
            == "Odrzucony przez klienta"
        )
        # Wiersz bez etapu szablonu (import, stare rekrutacje) — nazwa z kodu.
        assert _closed_stage_label(None, "withdrawn") == "Wycofany"
        assert _closed_stage_label("  ", "rejected") == "Odrzucony"
