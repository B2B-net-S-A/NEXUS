"""Pydantic schemas for Settings → AI panel.

Mirrors `app.models.ai_feature` ORM models.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.ai_feature import AIFeatureKey


class FeatureConfig(BaseModel):
    """One row from `ai_features` + computed labels for the UI."""

    feature: AIFeatureKey
    enabled: bool
    monthly_limit: int = Field(
        ...,
        ge=0,
        description="0 = unlimited; positive = monthly call cap",
    )

    # Display-only (not editable):
    model: str = Field(
        "",
        description="Efektywny model LLM (z rejestru ai_models) — funkcja → model.",
    )
    label: str = Field(..., description="Human-readable PL label")
    data_sent_to_ai: List[str] = Field(
        default_factory=list,
        description="Bullet list of what the LLM receives — surfaced to admin.",
    )

    model_config = {"from_attributes": True}


class FeatureUsage(BaseModel):
    """Current-month usage summary for a feature."""

    feature: AIFeatureKey
    used: int = Field(0, ge=0)
    input_tokens: int = Field(0, ge=0, description="Suma tokenów wejścia w okresie.")
    output_tokens: int = Field(0, ge=0, description="Suma tokenów wyjścia w okresie.")
    provider_calls: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    estimated_cost_usd: float | None = None
    unpriced_calls: int = 0
    legacy_usage_present: bool = False
    operations_without_response: int = 0
    limit: int = Field(0, ge=0, description="0 = unlimited")
    period_start: date
    period_end: date = Field(
        ...,
        description="Last day of the current month (UTC) — quota window end.",
    )

    @property
    def is_exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit


class SpendAlertStatus(BaseModel):
    in_app_enabled: bool = True
    slack_configured: bool = False
    pending_deliveries: int = 0
    last_delivered_at: datetime | None = None


class AISettingsOut(BaseModel):
    """Response for ``GET /settings/ai``."""

    master_enabled: bool
    features: List[FeatureConfig]
    usage: List[FeatureUsage]
    spend_alerts: SpendAlertStatus = Field(default_factory=SpendAlertStatus)


class FeatureConfigUpdate(BaseModel):
    """Patch payload for ``PATCH /settings/ai/features/{feature}``."""

    enabled: Optional[bool] = None
    monthly_limit: Optional[int] = Field(None, ge=0)


class MasterToggleUpdate(BaseModel):
    """Patch payload for ``PATCH /settings/ai/master``."""

    enabled: bool


class QuotaCheckResult(BaseModel):
    """Internal result of `quota_service.check_and_increment`.

    Exposed indirectly via 503 response when quota is exhausted.
    """

    allowed: bool
    reason: Optional[str] = None
    used: int = 0
    limit: int = 0
