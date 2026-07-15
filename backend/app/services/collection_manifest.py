"""Versioned Qdrant collection manifest (plan PR6).

A collection must contain exactly one
``provider × model × dimension × text_schema_version`` so old and new vectors
never mix. This module derives a deterministic *physical* collection name from a
manifest and the *stable* alias that call sites resolve through — enabling a
blue-green swap (build a challenger collection, then repoint the alias) without
a code deploy.

Collection names in Qdrant must be filesystem/URL-safe; model names like
``voyage-3-large`` are sanitised to ``voyage_3_large``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Stable aliases that application reads/writes resolve through. Repointing an
# alias to a new physical collection is the atomic blue-green switch.
CANDIDATE_ALIAS = "nexus_candidates_active"
JOB_ALIAS = "nexus_jobs_active"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", value.strip().lower()).strip("_")


@dataclass(frozen=True)
class CollectionManifest:
    """Everything that must be identical for vectors to share a collection."""

    entity_type: str  # "candidate" | "job"
    provider: str  # "voyage"
    model: str  # "voyage-3-large"
    dimension: int  # 1024
    text_schema_version: str  # "text-v1-legacy"
    entity_schema_version: str = "entity-v1"

    @property
    def base(self) -> str:
        return "nexus_candidates" if self.entity_type == "candidate" else "nexus_jobs"

    @property
    def alias(self) -> str:
        return CANDIDATE_ALIAS if self.entity_type == "candidate" else JOB_ALIAS

    def collection_name(self) -> str:
        """Deterministic physical collection name for this manifest."""
        return "__".join(
            [
                self.base,
                f"{_slug(self.provider)}_{_slug(self.model)}",
                f"d{self.dimension}",
                f"t{_slug(self.text_schema_version)}",
                f"e{_slug(self.entity_schema_version)}",
            ]
        )

    def as_dict(self) -> dict:
        return asdict(self)

    def matches(self, other: "CollectionManifest") -> bool:
        """Two manifests are compatible iff every space-defining field matches."""
        return (
            self.provider == other.provider
            and self.model == other.model
            and self.dimension == other.dimension
            and self.text_schema_version == other.text_schema_version
            and self.entity_schema_version == other.entity_schema_version
        )
