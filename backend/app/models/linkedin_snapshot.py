"""LinkedIn employment tracking models.

Persists periodic snapshots of each candidate's LinkedIn profile so we can
detect job changes (new employer / title). Complements denormalized flags on
`Candidate` — flags power list filters + badges, this table powers audit +
diff detection and lets us re-run diff logic retroactively without paying
Proxycurl twice.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class LinkedinSyncStatus(str, enum.Enum):
    """Status of the last LinkedIn sync attempt for a candidate.

    `disabled` is the default — the candidate has no `linkedin` URL or the
    Proxycurl integration is turned off globally. `not_found` means Proxycurl
    returned 404 (profile removed / private). `error` covers malformed URL
    or unknown upstream failure — user-visible in the detail view.
    """

    ok = "ok"
    not_found = "not_found"
    error = "error"
    rate_limited = "rate_limited"
    disabled = "disabled"


class LinkedinChangeKind(str, enum.Enum):
    """Classification of what changed vs the previous snapshot."""

    first_snapshot = "first_snapshot"
    no_change = "no_change"
    new_company = "new_company"
    new_title_same_company = "new_title_same_company"


class CandidateLinkedinSnapshot(Base, TimestampMixin):
    """One fetched Proxycurl profile for a candidate at a point in time.

    Full JSON retained (`profile_json`) so diff logic can be re-run later
    without paying Proxycurl again. Pruned via `sync.prune_old_snapshots`
    (keep last 10 per candidate) after each new insert.
    """

    __tablename__ = "candidate_linkedin_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Timestamp of the Proxycurl fetch itself.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Full Proxycurl payload — kept verbatim for re-analysis.
    profile_json: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Derived fast-path fields extracted from profile_json.experiences[0]
    # where ends_at is None.
    current_company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_started_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Diff vs previous snapshot (scoped per candidate).
    changed_from_previous: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    change_kind: Mapped[LinkedinChangeKind] = mapped_column(
        Enum(LinkedinChangeKind, name="linkedinchangekind"),
        default=LinkedinChangeKind.first_snapshot,
        nullable=False,
    )

    candidate = relationship("Candidate", back_populates="linkedin_snapshots")

    __table_args__ = (
        Index(
            "ix_linkedin_snap_candidate_fetched",
            "candidate_id",
            "fetched_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateLinkedinSnapshot id={self.id} "
            f"candidate_id={self.candidate_id} "
            f"company={self.current_company!r} "
            f"kind={self.change_kind.value}>"
        )
