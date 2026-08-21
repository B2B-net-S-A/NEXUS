"""Schema-level tests for Settings → AI panel (#5 from Traffit gap roadmap).

Pure Pydantic / quota-logic tests — no DB roundtrip. Integration coverage
(actual ``/api/settings/ai`` endpoints) lives in tests/test_api_integration.py
once we wire it through `app_client`.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.ai_feature import (
    FEATURE_DATA_SENT,
    FEATURE_LABELS,
    AIFeatureKey,
)
from app.schemas.ai_settings import (
    AISettingsOut,
    FeatureConfig,
    FeatureConfigUpdate,
    FeatureUsage,
    MasterToggleUpdate,
)
from app.services.ai_quota import (
    AIQuotaExceeded,
    QuotaState,
    _current_period_start,
)


class TestFeatureKeyEnum:
    def test_feature_keys_match_expected_set(self):
        # Traffit-parity baseline (5) + order_parser (odczyt PDF zamówienia,
        # 0214) + interaktywne CV: kafelki wymagań i chat klienta (0217).
        keys = {k.value for k in AIFeatureKey}
        assert keys == {
            "scoring",
            "job_description_generator",
            "cv_parser",
            "candidate_summary",
            "champion_draft",
            "order_parser",
            "cv_requirement_map",
            "cv_interactive_chat",
            # Fala 3 (0223): masowy backfill pól z CV — osobny kubełek,
            # żeby bieg na ~39 tys. CV nie wyczerpał limitu rekruterów.
            "cv_backfill",
            # 0230: cykliczna ekstrakcja faktów z notatek (notes_insights_sync).
            "notes_extraction",
            "champion_profile_parse",
        }

    def test_every_key_has_label_and_data_descriptor(self):
        for key in AIFeatureKey:
            assert key in FEATURE_LABELS, f"Missing label for {key.value}"
            assert key in FEATURE_DATA_SENT, f"Missing data descriptor for {key.value}"
            assert FEATURE_LABELS[key]
            assert len(FEATURE_DATA_SENT[key]) >= 1


class TestFeatureConfigSchema:
    def test_minimal_payload(self):
        cfg = FeatureConfig(
            feature=AIFeatureKey.scoring,
            enabled=True,
            monthly_limit=20000,
            label="Scoring kandydatów",
            data_sent_to_ai=["Treść CV"],
        )
        assert cfg.feature is AIFeatureKey.scoring
        assert cfg.monthly_limit == 20000

    def test_rejects_negative_limit(self):
        with pytest.raises(ValidationError):
            FeatureConfig(
                feature=AIFeatureKey.scoring,
                enabled=True,
                monthly_limit=-1,
                label="x",
            )

    def test_zero_limit_means_unlimited(self):
        cfg = FeatureConfig(
            feature=AIFeatureKey.cv_parser,
            enabled=True,
            monthly_limit=0,
            label="CV parser",
        )
        assert cfg.monthly_limit == 0


class TestFeatureUsageSchema:
    def test_is_exhausted_unlimited(self):
        usage = FeatureUsage(
            feature=AIFeatureKey.scoring,
            used=999_999,
            limit=0,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
        assert usage.is_exhausted is False

    def test_is_exhausted_under_cap(self):
        usage = FeatureUsage(
            feature=AIFeatureKey.scoring,
            used=10,
            limit=20,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
        assert usage.is_exhausted is False

    def test_is_exhausted_at_cap(self):
        usage = FeatureUsage(
            feature=AIFeatureKey.scoring,
            used=20,
            limit=20,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
        assert usage.is_exhausted is True


class TestPatchPayloads:
    def test_master_toggle_update(self):
        payload = MasterToggleUpdate(enabled=False)
        assert payload.enabled is False

    def test_feature_partial_update_enabled_only(self):
        payload = FeatureConfigUpdate(enabled=False)
        assert payload.enabled is False
        assert payload.monthly_limit is None

    def test_feature_partial_update_limit_only(self):
        payload = FeatureConfigUpdate(monthly_limit=500)
        assert payload.monthly_limit == 500
        assert payload.enabled is None

    def test_feature_update_rejects_negative_limit(self):
        with pytest.raises(ValidationError):
            FeatureConfigUpdate(monthly_limit=-100)


class TestQuotaState:
    def test_remaining_unlimited(self):
        state = QuotaState(used=42, limit=0, period_start=date(2026, 5, 1))
        assert state.remaining > 1_000_000

    def test_remaining_with_cap(self):
        state = QuotaState(used=18, limit=20, period_start=date(2026, 5, 1))
        assert state.remaining == 2

    def test_remaining_at_cap(self):
        state = QuotaState(used=20, limit=20, period_start=date(2026, 5, 1))
        assert state.remaining == 0

    def test_remaining_over_cap_clamps_to_zero(self):
        state = QuotaState(used=25, limit=20, period_start=date(2026, 5, 1))
        assert state.remaining == 0


class TestAIQuotaExceeded:
    def test_carries_feature_and_reason(self):
        exc = AIQuotaExceeded(
            AIFeatureKey.scoring,
            "Miesięczny limit wyczerpany",
            used=20000,
            limit=20000,
        )
        assert exc.feature is AIFeatureKey.scoring
        assert "limit wyczerpany" in exc.reason
        assert exc.used == 20000
        assert exc.limit == 20000


class TestPeriodStart:
    def test_first_of_current_month(self):
        period = _current_period_start()
        assert period.day == 1


class TestAISettingsOut:
    def test_round_trip_minimal(self):
        out = AISettingsOut(
            master_enabled=True,
            features=[
                FeatureConfig(
                    feature=AIFeatureKey.scoring,
                    enabled=True,
                    monthly_limit=20000,
                    label="Scoring",
                    data_sent_to_ai=["CV"],
                )
            ],
            usage=[
                FeatureUsage(
                    feature=AIFeatureKey.scoring,
                    used=5,
                    limit=20000,
                    period_start=date(2026, 5, 1),
                    period_end=date(2026, 5, 31),
                )
            ],
        )
        assert out.master_enabled is True
        assert len(out.features) == 1
        assert len(out.usage) == 1
