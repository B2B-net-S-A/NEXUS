"""Sprzedaż (Atlas → NEXUS): lejki, firmy, kontakty, szanse, aktywności, pliki (0601).

CHECK-i i indeksy są tu powtórzone z ``services/sales_schema.py`` (strażnik
``test_sales_core_migration_mirror.py`` porównuje model z DDL).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import sales_schema as schema


class SalesPipeline(Base, TimestampMixin):
    __tablename__ = "sales_pipelines"
    __table_args__ = (UniqueConstraint("key", name="uq_sales_pipelines_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    stages: Mapped[list["SalesPipelineStage"]] = relationship(
        back_populates="pipeline",
        order_by="SalesPipelineStage.position",
        cascade="all, delete-orphan",
    )


class SalesPipelineStage(Base, TimestampMixin):
    __tablename__ = "sales_pipeline_stages"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "key", name="uq_sales_pipeline_stages_key"),
        CheckConstraint(
            schema.CK_STAGE_OUTCOME, name="ck_sales_pipeline_stages_outcome"
        ),
        CheckConstraint(
            schema.CK_STAGE_PROBABILITY, name="ck_sales_pipeline_stages_probability"
        ),
        Index("ix_sales_pipeline_stages_pipeline", "pipeline_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("sales_pipelines.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    outcome: Mapped[str] = mapped_column(
        String(8), nullable=False, default="open", server_default="open"
    )
    qualifies: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    color: Mapped[Optional[str]] = mapped_column(String(16))

    pipeline: Mapped[SalesPipeline] = relationship(back_populates="stages")


class SalesCompany(Base, TimestampMixin):
    """Firma w kartotece sprzedaży — osobna od ``clients``, łączona po wygranej."""

    __tablename__ = "sales_companies"
    __table_args__ = (
        CheckConstraint(schema.CK_COMPANY_NAME, name="ck_sales_companies_name"),
        CheckConstraint(
            schema.CK_COMPANY_LIFECYCLE, name="ck_sales_companies_lifecycle"
        ),
        CheckConstraint(schema.CK_COMPANY_STATUS, name="ck_sales_companies_status"),
        CheckConstraint(schema.CK_COMPANY_TIER, name="ck_sales_companies_tier"),
        CheckConstraint(
            schema.CK_COMPANY_NO_SELF_PARENT,
            name="ck_sales_companies_no_self_parent",
        ),
        Index("ix_sales_companies_normalized_name", "normalized_name"),
        Index("ix_sales_companies_nip", "nip"),
        Index("ix_sales_companies_parent", "parent_company_id"),
        Index("ix_sales_companies_owner", "owner_user_id"),
        Index(
            "ix_sales_companies_owner_label",
            "owner_label",
            postgresql_where=text("owner_label IS NOT NULL"),
        ),
        Index(
            "ux_sales_companies_client",
            "client_id",
            unique=True,
            postgresql_where=text("client_id IS NOT NULL"),
        ),
        Index(
            "ux_sales_companies_external_ref",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    legal_name: Mapped[Optional[str]] = mapped_column(String(500))
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    nip: Mapped[Optional[str]] = mapped_column(String(15))
    krs: Mapped[Optional[str]] = mapped_column(String(20))
    regon: Mapped[Optional[str]] = mapped_column(String(14))
    domain: Mapped[Optional[str]] = mapped_column(String(255))
    website_url: Mapped[Optional[str]] = mapped_column(String(500))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    industry: Mapped[Optional[str]] = mapped_column(String(255))
    size_range: Mapped[Optional[str]] = mapped_column(String(40))
    hq_city: Mapped[Optional[str]] = mapped_column(String(120))
    hq_country: Mapped[Optional[str]] = mapped_column(String(2))
    description: Mapped[Optional[str]] = mapped_column(Text)
    lifecycle_stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="lead", server_default="lead"
    )
    tier: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source: Mapped[Optional[str]] = mapped_column(String(60))
    parent_company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="SET NULL")
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Opiekun z Atlasa bez konta w NEXUSIE (sam tekst) — do przypisania na konto.
    owner_label: Mapped[Optional[str]] = mapped_column(String(120))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Stan uzupełniania dat zatrudnienia osób z tej firmy (D3): kiedy, ile osób.
    dates_backfill: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    #: Ostatni zapis importu z Atlasa; ``updated_at > synced_at`` = zmienione w NEXUSIE.
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    parent: Mapped[Optional["SalesCompany"]] = relationship(
        remote_side="SalesCompany.id"
    )


class SalesContact(Base, TimestampMixin):
    """Osoba po stronie firmy (decydent, kupiec) — nie kandydat z bazy."""

    __tablename__ = "sales_contacts"
    __table_args__ = (
        CheckConstraint(schema.CK_CONTACT_NAME, name="ck_sales_contacts_name"),
        Index("ix_sales_contacts_company", "company_id"),
        Index(
            "ux_sales_contacts_external_ref",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="SET NULL")
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(120))
    last_name: Mapped[Optional[str]] = mapped_column(String(120))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(60))
    mobile_phone: Mapped[Optional[str]] = mapped_column(String(60))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    seniority: Mapped[Optional[str]] = mapped_column(String(40))
    department: Mapped[Optional[str]] = mapped_column(String(120))
    is_executive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(40))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    #: Ostatni zapis importu z Atlasa; ``updated_at > synced_at`` = zmienione w NEXUSIE.
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SalesOpportunity(Base, TimestampMixin):
    """Szansa sprzedażowa w lejku — zawsze przy firmie z kartoteki sprzedaży."""

    __tablename__ = "sales_opportunities"
    __table_args__ = (
        CheckConstraint(
            schema.CK_OPPORTUNITY_TITLE, name="ck_sales_opportunities_title"
        ),
        CheckConstraint(
            schema.CK_OPPORTUNITY_STATUS, name="ck_sales_opportunities_status"
        ),
        CheckConstraint(
            schema.CK_OPPORTUNITY_SERVICE_LINE,
            name="ck_sales_opportunities_service_line",
        ),
        CheckConstraint(
            schema.CK_OPPORTUNITY_PROBABILITY,
            name="ck_sales_opportunities_probability",
        ),
        Index("ix_sales_opportunities_company", "company_id"),
        Index("ix_sales_opportunities_stage", "pipeline_id", "stage_id"),
        Index("ix_sales_opportunities_owner", "owner_user_id"),
        Index("ix_sales_opportunities_status", "status"),
        Index(
            "ux_sales_opportunities_external_ref",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="RESTRICT"), nullable=False
    )
    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("sales_pipelines.id", ondelete="RESTRICT"), nullable=False
    )
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("sales_pipeline_stages.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="open", server_default="open"
    )
    service_line: Mapped[Optional[str]] = mapped_column(String(32))
    value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    mrr_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    one_off_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    margin_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    contract_months: Mapped[Optional[int]] = mapped_column(Integer)
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date)
    qualified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    won_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lost_reason: Mapped[Optional[str]] = mapped_column(String(500))
    primary_contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_contacts.id", ondelete="SET NULL")
    )
    #: Role, których klient szuka: ``[{"title", "count", "seniority", "skills"}]``.
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source: Mapped[Optional[str]] = mapped_column(String(60))
    campaign: Mapped[Optional[str]] = mapped_column(String(120))
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    keep_open_until: Mapped[Optional[date]] = mapped_column(Date)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_reason: Mapped[Optional[str]] = mapped_column(String(255))
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    #: Ostatni zapis importu z Atlasa; ``updated_at > synced_at`` = zmienione w NEXUSIE.
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    company: Mapped[SalesCompany] = relationship()
    stage: Mapped[SalesPipelineStage] = relationship()


class SalesOpportunityContact(Base):
    __tablename__ = "sales_opportunity_contacts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "opportunity_id", "contact_id", name="pk_sales_opportunity_contacts"
        ),
        CheckConstraint(
            schema.CK_OPPORTUNITY_CONTACT_ROLE,
            name="ck_sales_opportunity_contacts_role",
        ),
        Index("ix_sales_opportunity_contacts_contact", "contact_id"),
    )

    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("sales_opportunities.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("sales_contacts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Optional[str]] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesActivity(Base, TimestampMixin):
    """Telefon, mail, spotkanie, zadanie albo notatka — przy firmie i/lub szansie."""

    __tablename__ = "sales_activities"
    __table_args__ = (
        CheckConstraint(schema.CK_ACTIVITY_KIND, name="ck_sales_activities_kind"),
        CheckConstraint(
            schema.CK_ACTIVITY_PRIORITY, name="ck_sales_activities_priority"
        ),
        Index("ix_sales_activities_company", "company_id", "created_at"),
        Index("ix_sales_activities_opportunity", "opportunity_id", "created_at"),
        Index(
            "ix_sales_activities_open_tasks",
            "assignee_user_id",
            "due_at",
            postgresql_where=text("kind = 'task' AND done_at IS NULL"),
        ),
        Index(
            "ix_sales_activities_open_items",
            "assignee_user_id",
            "due_at",
            postgresql_where=text(
                f"kind IN ({schema.quoted(schema.TASK_KINDS)}) AND done_at IS NULL"
            ),
        ),
        CheckConstraint(
            schema.CK_ACTIVITY_DIRECTION, name="ck_sales_activities_direction"
        ),
        Index(
            "ux_sales_activities_external_ref",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="CASCADE")
    )
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_opportunities.id", ondelete="SET NULL")
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_contacts.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[Optional[str]] = mapped_column(String(8))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_source: Mapped[Optional[str]] = mapped_column(String(40))
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    #: Ostatni zapis importu z Atlasa; ``updated_at > synced_at`` = zmienione w NEXUSIE.
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Outlook: id wiadomości/wydarzenia, link do otwarcia, kierunek maila, czas.
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    web_link: Mapped[Optional[str]] = mapped_column(String(2000))
    direction: Mapped[Optional[str]] = mapped_column(String(3))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)


class SalesCompanyContact(Base):
    """Osoba w firmie — także w drugiej i kolejnej (``sales_contacts.company_id`` to firma główna)."""

    __tablename__ = "sales_company_contacts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "company_id", "contact_id", name="pk_sales_company_contacts"
        ),
        Index("ix_sales_company_contacts_contact", "contact_id"),
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="CASCADE")
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("sales_contacts.id", ondelete="CASCADE")
    )
    role: Mapped[Optional[str]] = mapped_column(String(60))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    started_at: Mapped[Optional[date]] = mapped_column(Date)
    ended_at: Mapped[Optional[date]] = mapped_column(Date)
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesFile(Base):
    __tablename__ = "sales_files"
    __table_args__ = (
        CheckConstraint(schema.CK_FILE_OWNER, name="ck_sales_files_owner"),
        Index("ix_sales_files_company", "company_id"),
        Index("ix_sales_files_opportunity", "opportunity_id"),
        Index(
            "ux_sales_files_external_ref",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="CASCADE")
    )
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_opportunities.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(120))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    folder: Mapped[Optional[str]] = mapped_column(String(120))
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_ref: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesLead(Base, TimestampMixin):
    """Sygnał zakupowy firmy w skrzynce leadów (0602)."""

    __tablename__ = "sales_leads"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_sales_leads_fingerprint"),
        CheckConstraint(schema.CK_LEAD_SOURCE, name="ck_sales_leads_source"),
        CheckConstraint(schema.CK_LEAD_STATUS, name="ck_sales_leads_status"),
        CheckConstraint(schema.CK_LEAD_SCORE, name="ck_sales_leads_score"),
        CheckConstraint(schema.CK_LEAD_TITLE, name="ck_sales_leads_title"),
        Index("ix_sales_leads_inbox", "status", "score", "signal_at"),
        Index("ix_sales_leads_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="new", server_default="new"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    company_name: Mapped[Optional[str]] = mapped_column(String(500))
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_companies.id", ondelete="SET NULL")
    )
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    signal_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    assignee_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_opportunities.id", ondelete="SET NULL")
    )
    dismissed_reason: Mapped[Optional[str]] = mapped_column(String(255))


class SalesOpportunityEvent(Base):
    """Jedna zmiana szansy: kto, kiedy, które pole, stara i nowa wartość (0618)."""

    __tablename__ = "sales_opportunity_events"
    __table_args__ = (
        CheckConstraint(
            schema.CK_OPPORTUNITY_EVENT_KIND,
            name="ck_sales_opportunity_events_kind",
        ),
        Index(
            "ix_sales_opportunity_events_opportunity", "opportunity_id", "created_at"
        ),
        Index("ix_sales_opportunity_events_field", "field", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("sales_opportunities.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    field: Mapped[Optional[str]] = mapped_column(String(40))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesTarget(Base, TimestampMixin):
    """Cele tygodniowe handlowca albo (``user_id`` pusty) cel netto MRR firmy (0623)."""

    __tablename__ = "sales_targets"
    __table_args__ = (
        CheckConstraint(
            "meetings >= 0 AND qualified >= 0 AND offers_stage >= 0",
            name="ck_sales_targets_weekly",
        ),
        CheckConstraint(
            "margin_goal_amount IS NULL OR margin_goal_amount >= 0",
            name="ck_sales_targets_margin",
        ),
        Index(
            "ux_sales_targets_user",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "ux_sales_targets_company",
            text("(user_id IS NULL)"),
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    meetings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    qualified: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Wejścia na etap „Oferta wysłana” — NEXUS nie ma ofert (decyzja 28.10.2026).
    offers_stage: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    margin_goal_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2))
    margin_goal_deadline: Mapped[Optional[date]] = mapped_column(Date)
    team: Mapped[Optional[str]] = mapped_column(String(60))
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
