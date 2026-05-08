"""Multi-row source attribution for candidate applications.

Today ``Candidate.source_enum`` records a single first-touch source
("linkedin"/"pracuj"/...). For ROI attribution per channel we need to
record EACH application/touch separately — a candidate may apply via
LinkedIn for job A, then via the company career page for job B, then
get found via Aktywny Search for job C.

Inspired by Traffit's profile sidebar showing
``Dodany manualnie • 08/05/2026 / E-mail • 09/05/2026``.

Why a separate table (not extending Candidate.source_enum):
- One-to-many: a candidate can have many source observations.
- Time-aware: each row keeps `captured_at` for funnel analytics.
- UTM-aware: Pracuj.pl applications can carry the campaign that brought them.

Why not append to ``activities`` (the timeline log):
- Separate concern. Activity rows are user-facing event entries
  ("Martyna assigned to stage X"). Source events are mostly silent
  attribution, queried by /reports/sources for aggregates.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SourceChannel(str, enum.Enum):
    """Channel that triggered the candidate-job touch.

    Distinct from `CandidateSource` (legacy first-touch field on Candidate):
    that enum captures coarse "where did we first hear about them" while
    SourceChannel captures every individual touch with its UTM context.
    """

    manual = "manual"  # Recruiter typed the candidate in
    aktywny_search = "aktywny_search"  # Inbound LinkedIn search match
    cv_upload = "cv_upload"  # Drag-drop CV upload
    email = "email"  # Apply via email reply
    posting = "posting"  # Application via published job ad
    referral = "referral"  # Referral from another person
    import_csv = "import_csv"  # Bulk import (Traffit / TalentRadar)


CHANNEL_LABELS: dict[SourceChannel, str] = {
    SourceChannel.manual: "Dodany manualnie",
    SourceChannel.aktywny_search: "Aktywny Search",
    SourceChannel.cv_upload: "CV upload",
    SourceChannel.email: "E-mail",
    SourceChannel.posting: "Ogłoszenie o pracy",
    SourceChannel.referral: "Polecenie",
    SourceChannel.import_csv: "Import danych",
}


class CandidateSourceEvent(Base):
    """One observation of (candidate, channel, time, UTM).

    A single candidate can have many rows — captured each time we observe
    a new touch. Used by /reports/sources to attribute hires per channel
    and (for posting-channel rows) per UTM campaign.
    """

    __tablename__ = "candidate_source_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel: Mapped[SourceChannel] = mapped_column(
        Enum(SourceChannel, name="sourcechannel"),
        nullable=False,
        index=True,
    )

    # Optional FK to a specific job — present when the source event is tied
    # to an application (posting/email/cv_upload often are). NULL for generic
    # "found this person via Aktywny Search" entries with no job context.
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── UTM tracking — populated for posting-channel events from query
    # params on the public /apply landing page. Capped at String(120) to
    # match common GA dimensions; longer strings get truncated upstream.
    utm_source: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    utm_medium: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    utm_term: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    utm_content: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # Free-form note: e.g. "via Maja's referral" for SourceChannel.referral.
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # When the touch happened (allowed to differ from created_at if we're
    # backfilling historical data from imports).
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
