"""Candidate invite links (Phase: self-service application).

A recruiter generates a time-limited, multi-use link tied to a specific
published job. The public endpoint validates the token, reads the form
payload, and creates (or merges) a candidate with `created_by` set to the
recruiter — so ownership is attributed to whoever posted the link.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CandidateInviteLink(Base):
    __tablename__ = "candidate_invite_links"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    use_count: Mapped[int] = mapped_column(
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
