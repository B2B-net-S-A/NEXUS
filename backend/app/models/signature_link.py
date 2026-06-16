"""Single-use signing links for the public ``/sign/{token}`` page.

A recruiter sends a contract for signature → for each party (consultant,
company representative) we mint a ``SignatureLink``: an opaque, single-use,
time-limited token tied to a ``document_signatures`` row. The public endpoint
validates the token, serves the contract PDF to the Szafir SDK component (or
starts a mSzafir One Shot session), and accepts the signed PAdES back.

Modelled on :class:`app.models.invite_link.CandidateInviteLink` but **true
single-use** (``used_at`` set on consumption) because a contract signature is
a one-shot legal act, not a reusable application form.

Plan: ``docs/in-house-qes-signature-plan.md`` §6 (Faza 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SignatureLink(Base):
    """Opaque single-use token granting a party access to the signing page."""

    __tablename__ = "signature_links"

    # ``secrets.token_urlsafe(36)`` — opaque, unguessable, not a JWT (the JWT
    # purpose-scoped layer lives on top in the public endpoint).
    token: Mapped[str] = mapped_column(Text, primary_key=True)

    signature_id: Mapped[int] = mapped_column(
        ForeignKey("document_signatures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which side this link is for: ``consultant`` | ``company``.
    party: Mapped[str] = mapped_column(String(16), nullable=False)
    # ``qes_signing`` (Szafir SDK / mSzafir) | ``upload_signed`` (Option B).
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)

    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, default=False
    )
    # NULL = niezużyty. Ustawiany przed commit na ścieżce konsumpcji →
    # single-use (kolejna próba z tym samym tokenem → 404 jednolicie).
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    signature = relationship("DocumentSignature", foreign_keys=[signature_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<SignatureLink sig={self.signature_id} party={self.party} "
            f"purpose={self.purpose} used={self.used_at is not None}>"
        )
