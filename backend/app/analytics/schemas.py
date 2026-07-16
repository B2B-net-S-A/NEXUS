"""Wspólna koperta odpowiedzi Analytics v1 (plan §4.5).

Każdy endpoint ``/api/analytics/v1/*`` zwraca ten sam kształt:

    {
      "schema_version": "1",
      "metric_version": "...",
      "generated_at": "...",
      "scope": {...},
      "period": {"kind", "start", "end", "timezone"},
      "quality": {"status", "warnings", "source_watermarks"},
      "data": {...}
    }

Kwoty w ``data`` są ZAWSZE decimal-stringami z walutą PLN (PR 6 dokłada
konwersję FX); viewer-safe schematy fizycznie nie zawierają pól
finansowych (osobne modele, PR 3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


class QualityStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    unavailable = "unavailable"


class PeriodPayload(BaseModel):
    kind: str
    start: str
    end: str
    timezone: str


class QualityPayload(BaseModel):
    status: QualityStatus = QualityStatus.complete
    # Czytelne ostrzeżenia (np. "CloudTalk wyłączony — rozmowy niedostępne",
    # "brak kursu NBP dla EUR"). Frontend renderuje jako stan partial.
    warnings: list[str] = Field(default_factory=list)
    # Watermarki źródeł: nazwa źródła → ISO timestamp ostatniej synchronizacji
    # (np. {"traffit": "...", "cloudtalk": "..."}). Puste = same live ATS.
    source_watermarks: dict[str, str] = Field(default_factory=dict)


class AnalyticsEnvelope(BaseModel):
    schema_version: str = SCHEMA_VERSION
    metric_version: str
    generated_at: datetime
    scope: dict[str, Any]
    period: PeriodPayload
    quality: QualityPayload
    data: dict[str, Any]


def build_envelope(
    *,
    metric_version: str,
    scope: dict[str, Any],
    period: PeriodPayload | dict[str, Any],
    data: dict[str, Any],
    quality: QualityPayload | None = None,
) -> AnalyticsEnvelope:
    """Zbuduj kopertę — jedyna ścieżka konstrukcji odpowiedzi analytics."""
    if isinstance(period, dict):
        period = PeriodPayload(**period)
    return AnalyticsEnvelope(
        metric_version=metric_version,
        generated_at=datetime.now(timezone.utc),
        scope=scope,
        period=period,
        quality=quality or QualityPayload(),
        data=data,
    )
