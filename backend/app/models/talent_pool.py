from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.core.database import Base


class TalentPool(Base):
    """Pula talentów — zbiór kandydatów według kategorii/technologii."""

    __tablename__ = "talent_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criteria: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Cached member-centroid vector for pool suggestion (Qdrant collection
    # `nexus_pool_centroids`). Invalidated by setting `centroid_updated_at` to
    # NULL on membership changes; recomputed lazily on next suggestion call.
    centroid_vector_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    centroid_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Pula należy do jednej CC (migracja 0041_ai_cc_matching). NULL = "ogólna"
    # pula bez przypisania do kategorii (backward-compat dla istniejących pul).
    competence_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Targ kandydatów (migracja 0051). Flaga singletona — partial unique index
    # `ux_talent_pools_marketplace_singleton` pilnuje że JEDEN rekord w systemie
    # może mieć is_marketplace=true. Zarządzane przez marketplace_service.
    is_marketplace: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        index=True,
    )

    # Pula osobista / indywidualna (migracja 0137). False = pula firmowa /
    # wspólna (domyślne — wszystkie istniejące pule). True = pula utworzona
    # przez konkretnego usera na jego własny użytek. Widoczna dla całego zespołu
    # (oznaczona właścicielem = `created_by`), ale dodawać/usuwać kandydatów oraz
    # skasować pulę może TYLKO właściciel lub admin. Egzekwowane w
    # api/talent_pools.py (`_assert_can_modify_pool`).
    is_personal: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        index=True,
    )

    # External source tracking — Traffit / future imports.
    # Migracja 0074 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )
    memberships = relationship(
        "TalentPoolMembership", back_populates="pool", cascade="all, delete-orphan"
    )

    @property
    def candidate_count(self) -> int:
        return len(self.memberships)

    def __repr__(self) -> str:
        return f"<TalentPool id={self.id} name={self.name}>"


class TalentPoolMembership(Base):
    """Przynależność kandydata do puli talentów."""

    __tablename__ = "talent_pool_memberships"
    __table_args__ = (
        UniqueConstraint("talent_pool_id", "candidate_id", name="uq_pool_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    talent_pool_id: Mapped[int] = mapped_column(
        ForeignKey("talent_pools.id"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Skąd kandydat trafił do poola. NULL = legacy/manual przed wdrożeniem
    # auto-triggerów. Obecne wartości: "cv_sent", "manual", "imported",
    # "auto_availability" (targ — wstawiony automatycznie po availability_status).
    source_event: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Z którego JO kandydat przyszedł (dla source_event="cv_sent" zawsze
    # ustawione). NULL gdy źródło nie jest powiązane z konkretnym JO.
    source_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Targ kandydatów (migracja 0051). Data wygaśnięcia ręcznego wrzutu na targ.
    # NULL dla auto-entry (source_event="auto_availability") — wtedy o zniknięciu
    # decyduje zmiana availability_status na not_looking. Dla wpisów ręcznych
    # (source_event="manual") default = dzisiaj + MARKETPLACE_DEFAULT_DURATION_DAYS.
    marketplace_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Relationships
    pool = relationship("TalentPool", back_populates="memberships")
    # passive_deletes=True: the backref makes ``Candidate.pool_memberships`` a
    # one-to-many whose default on parent-delete is to NULL this row's
    # ``candidate_id`` — but it's NOT NULL, so that raises a NotNullViolation
    # (the real cause of "Network Error" on hard-deleting a candidate that
    # belongs to a pool). Defer to the DB-level ON DELETE CASCADE (migration
    # 0146) instead of letting the ORM touch these rows.
    candidate = relationship(
        "Candidate", backref=backref("pool_memberships", passive_deletes=True)
    )
    added_by_user = relationship("User", foreign_keys=[added_by])
    source_job = relationship("Job", foreign_keys=[source_job_id])

    def __repr__(self) -> str:
        return f"<TalentPoolMembership pool={self.talent_pool_id} candidate={self.candidate_id}>"
