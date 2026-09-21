"""Candidate invite links (Phase: self-service application).

A recruiter generates a time-limited, multi-use link tied to a specific
published job. The public endpoint validates the token, reads the form
payload, and creates (or merges) a candidate with `created_by` set to the
recruiter — so ownership is attributed to whoever posted the link.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


INVITE_LINK_KINDS = ("job", "recruiter")


class CandidateInviteLink(Base):
    """Link aplikacyjny: do rekrutacji (``kind='job'``) albo stały rekrutera.

    0339 (strona kariery): link ``recruiter`` nie ma rekrutacji ani terminu —
    CV trafia do bazy i do „Moich ludzi" właściciela. Link ``job`` dostaje
    czytelny ``slug`` i domyślnie żyje do zamknięcia rekrutacji
    (``expires_at IS NULL``).
    """

    __tablename__ = "candidate_invite_links"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('job', 'recruiter')", name="ck_candidate_invite_links_kind"
        ),
        CheckConstraint(
            "(kind = 'job' AND job_id IS NOT NULL) OR "
            "(kind = 'recruiter' AND job_id IS NULL AND slug IS NOT NULL)",
            name="ck_candidate_invite_links_kind_shape",
        ),
        Index(
            "ux_candidate_invite_links_slug",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
        ),
        Index(
            "ux_candidate_invite_links_one_recruiter_link",
            "created_by",
            unique=True,
            postgresql_where=text("kind = 'recruiter' AND revoked = false"),
        ),
    )

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="job", default="job"
    )
    slug: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    # Frozen sourcing authority at link creation. A later plan supersede must
    # not discard a legitimate inbound application or reattribute its origin.
    origin_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    priority_compliant_at_create: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # NULL = bez terminu (link rekrutacji żyje do jej zamknięcia, stały link
    # rekrutera — do odwołania).
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    use_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False, default=0
    )
    # Wejścia na publiczną stronę linku (GET), osobno od zgłoszeń (use_count).
    visit_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False, default=0
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Hash-at-rest v2 (migracja 0183). Unlike champion/signature/engagement,
    # the invite LIST must reconstruct each link's URL (frontend "copy link"),
    # so a one-way hash alone would lose the URL. Two columns solve both needs:
    #   token_sha256 — deterministic, for the /apply lookup and revoke
    #   token_ct     — Fernet ciphertext of the raw secret, so the list can
    #                  decrypt and show the URL; a DB leak without the key is
    #                  useless. PK holds a non-secret v2$ revoke key.
    # Graceful: if the encryption key is unset, mint falls back to the legacy
    # plaintext-PK path — no regression, just no improvement, until a key lands.
    token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    token_ct: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])
    job = relationship("Job", foreign_keys=[job_id])
