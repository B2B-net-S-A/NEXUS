"""Control-plane schemas for immutable legacy snapshots and cutovers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


WARSAW_TIMEZONE = "Europe/Warsaw"
MODULE_KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
METRIC_KEY_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,127}$"


class LegacySnapshotImportItem(BaseModel):
    """One historical metric that cannot be reconstructed from live ATS."""

    model_config = ConfigDict(extra="forbid")

    metric_key: str = Field(pattern=METRIC_KEY_PATTERN)
    metric_version: str = Field(min_length=1, max_length=32)
    scope: str = Field(min_length=1, max_length=64)
    scope_ref: str | None = Field(default=None, max_length=128)
    period_start: datetime
    period_end: datetime
    timezone: Literal[WARSAW_TIMEZONE] = WARSAW_TIMEZONE
    data: JsonValue
    source: str = Field(default="dynareporter", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=255)

    @field_validator(
        "metric_version",
        "scope",
        "scope_ref",
        "source",
        "source_ref",
    )
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_period(self) -> "LegacySnapshotImportItem":
        for field_name, value in (
            ("period_start", self.period_start),
            ("period_end", self.period_end),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must include a UTC offset")
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be later than period_start")
        return self


class LegacySnapshotImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshots: list[LegacySnapshotImportItem] = Field(
        min_length=1,
        max_length=1000,
    )


class LegacySnapshotImportResult(BaseModel):
    total: int
    inserted: int
    skipped: int
    conflicts: int
    inserted_keys: list[str] = Field(default_factory=list)
    skipped_keys: list[str] = Field(default_factory=list)
    conflict_keys: list[str] = Field(default_factory=list)


class LegacySnapshotRow(BaseModel):
    snapshot_key: str
    metric_key: str
    metric_version: str
    scope: str
    scope_ref: str | None
    period_start: datetime
    period_end: datetime
    timezone: str
    data: Any
    source: str
    source_ref: str | None
    checksum: str
    created_at: datetime


class LegacySnapshotList(BaseModel):
    snapshots: list[LegacySnapshotRow]
    limit: int
    offset: int


class AnalyticsCutoverUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cutover_at: datetime
    timezone: Literal[WARSAW_TIMEZONE] = WARSAW_TIMEZONE
    legacy_source: str = Field(
        default="dynareporter",
        min_length=1,
        max_length=64,
    )

    @field_validator("legacy_source")
    @classmethod
    def _strip_legacy_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("legacy_source cannot be blank")
        return normalized


class AnalyticsCutoverRow(BaseModel):
    module_key: str
    cutover_at: datetime
    timezone: str
    legacy_source: str
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class AnalyticsCutoverList(BaseModel):
    cutovers: list[AnalyticsCutoverRow]


class AnalyticsDataSource(str, Enum):
    legacy_snapshot = "legacy_snapshot"
    live_ats = "live_ats"


class AnalyticsCutoverResolution(BaseModel):
    module_key: str
    source: AnalyticsDataSource
    period_start: datetime
    period_end: datetime
    cutover_at: datetime | None
    legacy_source: str | None
