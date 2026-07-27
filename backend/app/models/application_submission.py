"""Pending public-apply submissions (P0-CAND-01 containment).

A public, reusable invite link plus a known e-mail used to let anyone
OVERWRITE a canonical ``Candidate`` (name, CV, contact, ownership, stage) via
``POST /api/public/apply/{token}``. That mutation path is now closed: when a
submitted e-mail matches an existing candidate the applicant data is parked
here as an immutable ``ApplicationSubmission`` (``status='pending_review'``)
and a recruiter decides — via ``/api/application-submissions/{id}/resolve`` —
whether to link the CV, merge selected fields, create a fresh candidate, or
reject it. The candidate is never touched by the public endpoint.

Design notes:
- Raw applicant fields are IMMUTABLE: they record exactly what was submitted.
- The CV is stored INERT — object storage key when configured, else a BYTEA
  fallback (mirrors ``candidate_documents`` dual storage) — and attached to no
  candidate until a resolve action.
- We store the invite link's SHA-256 digest, never the raw token: for legacy
  links the token IS the access secret, so this table must not widen a
  secret's DB footprint (same rationale as the token-hash-at-rest work).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.database import Base


class ApplicationSubmissionStatus(str, enum.Enum):
    """Lifecycle of a parked public-apply submission.

    Stored as a plain ``VARCHAR`` (CHECK-constrained) rather than a PG enum so
    the migration + entrypoint safety-net mirror stay trivially idempotent.
    """

    pending_review = "pending_review"  # awaiting recruiter triage
    linked = "linked"  # CV attached as a doc to the matched candidate
    merged = "merged"  # selected fields + CV merged into matched candidate
    created = "created"  # a brand-new candidate was created from this
    rejected = "rejected"  # dismissed, no candidate change


class ApplicationSubmission(Base):
    __tablename__ = "application_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Non-secret reference to the invite link (matches
    # ``CandidateInviteLink.token_sha256``). We deliberately do NOT persist the
    # raw invite token here.
    invite_link_token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=ApplicationSubmissionStatus.pending_review.value,
        index=True,
    )

    # ── Immutable raw applicant data ──────────────────────────────────────
    submitted_first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    submitted_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    submitted_linkedin: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    submitted_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # The candidate this e-mail matched (if any) — never mutated on submit.
    matched_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Inert CV storage (attached to NO candidate until resolve) ─────────
    cv_object_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cv_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cv_content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cv_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # BYTEA fallback when object storage is unconfigured (dev/CI). Deferred so
    # list SELECTs don't drag the blob.
    cv_file_content: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    raw_cv_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Raw applicant payload + UTM attribution, verbatim.
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
