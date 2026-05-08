"""Schema-level tests for multi-source attribution (#4 from Traffit gap roadmap).

Pure Pydantic / vocabulary tests — DB integration coverage will be added
once the apply form starts populating these rows in production.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.candidate_source_event import CHANNEL_LABELS, SourceChannel
from app.schemas.candidate_source_event import (
    CandidateSourceEventCreate,
    CandidateSourceEventOut,
    SourceFunnelRow,
    SourceReportResponse,
)


class TestSourceChannelVocabulary:
    def test_seven_channels(self):
        keys = {c.value for c in SourceChannel}
        assert keys == {
            "manual",
            "aktywny_search",
            "cv_upload",
            "email",
            "posting",
            "referral",
            "import_csv",
        }

    def test_polish_labels_exist_for_every_channel(self):
        for ch in SourceChannel:
            assert ch in CHANNEL_LABELS, f"Missing label for {ch.value}"
            assert CHANNEL_LABELS[ch].strip()


class TestEventCreate:
    def test_minimal(self):
        payload = CandidateSourceEventCreate(channel=SourceChannel.manual)
        assert payload.channel is SourceChannel.manual
        assert payload.utm_source is None
        assert payload.captured_at is None

    def test_with_utm(self):
        payload = CandidateSourceEventCreate(
            channel=SourceChannel.posting,
            utm_source="linkedin",
            utm_medium="cpc",
            utm_campaign="may26-data-engineers",
            utm_term="senior",
            utm_content="banner-1",
        )
        assert payload.utm_campaign == "may26-data-engineers"

    def test_rejects_oversized_utm(self):
        with pytest.raises(ValidationError):
            CandidateSourceEventCreate(
                channel=SourceChannel.posting,
                utm_source="x" * 121,
            )

    def test_rejects_oversized_note(self):
        with pytest.raises(ValidationError):
            CandidateSourceEventCreate(
                channel=SourceChannel.referral,
                note="x" * 501,
            )

    def test_rejects_unknown_channel(self):
        with pytest.raises(ValidationError):
            CandidateSourceEventCreate.model_validate({"channel": "indeed"})


class TestFunnelRow:
    def test_default_hire_rate(self):
        row = SourceFunnelRow(
            channel=SourceChannel.posting,
            channel_label="Ogłoszenie",
            candidates_total=10,
            hired=2,
            hire_rate_pct=20.0,
        )
        assert row.hire_rate_pct == 20.0

    def test_zero_total_implies_zero_rate(self):
        row = SourceFunnelRow(
            channel=SourceChannel.posting,
            channel_label="Ogłoszenie",
            candidates_total=0,
            hired=0,
            hire_rate_pct=0.0,
        )
        assert row.candidates_total == 0
        assert row.hire_rate_pct == 0.0


class TestEventOutSchema:
    def test_full_payload(self):
        now = datetime.now(timezone.utc)
        out = CandidateSourceEventOut(
            id=1,
            candidate_id=42,
            channel=SourceChannel.email,
            channel_label="E-mail",
            job_id=None,
            utm_source=None,
            utm_medium=None,
            utm_campaign=None,
            utm_term=None,
            utm_content=None,
            note=None,
            captured_at=now,
            created_at=now,
        )
        assert out.channel is SourceChannel.email
        assert out.channel_label == "E-mail"


class TestReportResponse:
    def test_empty_period(self):
        now = datetime.now(timezone.utc)
        report = SourceReportResponse(period_start=now, period_end=now, rows=[])
        assert report.rows == []
