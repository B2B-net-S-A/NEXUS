"""Pydantic schemas for Settings → AI panel.

Mirrors `app.models.ai_feature` ORM models.
"""

from datetime import date
from decimal import Decimal
from typing import Any, List, Optional

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
    monthly_budget_usd: Decimal = Field(Decimal("0"), ge=0)

    # Display-only (not editable):
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
    limit: int = Field(0, ge=0, description="0 = unlimited")
    period_start: date
    period_end: date = Field(
        ...,
        description="Last day of the current month (UTC) — quota window end.",
    )
    cost_usd: Decimal = Field(Decimal("0"), ge=0)
    p95_latency_ms: int = Field(0, ge=0)
    error_rate: float = Field(0, ge=0, le=1)
    health: str = "ok"

    @property
    def is_exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit


class AISettingsOut(BaseModel):
    """Response for ``GET /settings/ai``."""

    master_enabled: bool
    features: List[FeatureConfig]
    usage: List[FeatureUsage]
    active_registry_version: str = "v1_current"
    routing_lock_version: int = 1
    routes: dict[str, Any] = Field(default_factory=dict)
    compliance: dict[str, Any] = Field(default_factory=dict)
    rollouts: dict[str, Any] = Field(default_factory=dict)


class FeatureConfigUpdate(BaseModel):
    """Patch payload for ``PATCH /settings/ai/features/{feature}``."""

    enabled: Optional[bool] = None
    monthly_limit: Optional[int] = Field(None, ge=0)
    monthly_budget_usd: Optional[Decimal] = Field(None, ge=0)
    model_config = {"extra": "forbid"}


class FeatureConfigPatch(FeatureConfigUpdate):
    feature: AIFeatureKey


class AISettingsPatch(BaseModel):
    master_enabled: Optional[bool] = None
    features: List[FeatureConfigPatch] = Field(default_factory=list)
    model_config = {"extra": "forbid"}


class MasterToggleUpdate(BaseModel):
    """Patch payload for ``PATCH /settings/ai/master``."""

    enabled: bool
    model_config = {"extra": "forbid"}


class QuotaCheckResult(BaseModel):
    """Internal result of `quota_service.check_and_increment`.

    Exposed indirectly via 503 response when quota is exhausted.
    """

    allowed: bool
    reason: Optional[str] = None
    used: int = 0
    limit: int = 0
