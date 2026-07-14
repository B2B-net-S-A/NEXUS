"""Canonical analytics v1 building blocks.

The package intentionally has no dependency on FastAPI's authentication module.
Pure capability and period helpers can therefore be reused by auth, routers,
background comparisons and tests without introducing import cycles.
"""

from app.analytics.capabilities import (
    AnalyticsCapability,
    analytics_capability_values,
    capabilities_for_user,
    has_analytics_capability,
)

__all__ = [
    "AnalyticsCapability",
    "analytics_capability_values",
    "capabilities_for_user",
    "has_analytics_capability",
]
