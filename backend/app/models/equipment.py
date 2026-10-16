"""„Ludzie w NEXUSIE” — modele: Sprzęt i protokoły (0461).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

Egzemplarz (``EquipmentItem``) należy do modelu z cennika; historia powstaje
z wydań (``EquipmentAssignment``) — dokładnie jeden posiadacz: konto NEXUSA,
kontrakt konsultanta albo osoba zewnętrzna. Protokół zamraża pozycje
i wartości w chwili wydania (``EquipmentProtocolLine``). PUK, klucza BitLocker,
PESEL-u ani prywatnego e-maila tu nie ma i nie będzie (decyzja D10).
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import equipment_extras_schema as extras_schema
from app.services import equipment_schema as schema


def _unique_when_present(column: str) -> Index:
    return Index(
        f"ux_equipment_items_{column}",
        column,
        unique=True,
        postgresql_where=text(f"{column} IS NOT NULL"),
    )


class EquipmentModel(Base, TimestampMixin):
    """Pozycja cennika: model w kategorii z ceną (D5)."""

    __tablename__ = "equipment_models"
    __table_args__ = (
        UniqueConstraint("category", "name", name="uq_equipment_models_category_name"),
        CheckConstraint(schema.CK_MODEL_CATEGORY, name="ck_equipment_models_category"),
        CheckConstraint(schema.CK_MODEL_NAME, name="ck_equipment_models_name"),
        CheckConstraint(schema.CK_MODEL_PRICE, name="ck_equipment_models_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    price_pln: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EquipmentItem(Base, TimestampMixin):
    """Egzemplarz: jeden laptop, telefon, karta SIM albo karta dostępu."""

    __tablename__ = "equipment_items"
    __table_args__ = (
        CheckConstraint(schema.CK_ITEM_STATUS, name="ck_equipment_items_status"),
        CheckConstraint(schema.CK_ITEM_OWNERSHIP, name="ck_equipment_items_ownership"),
        *(_unique_when_present(column) for column in schema.ITEM_UNIQUE_COLUMNS),
        Index("ix_equipment_items_model", "model_id"),
        Index("ix_equipment_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_models.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    imei: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    iccid: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    access_card_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="na_stanie", server_default="na_stanie"
    )
    ownership: Mapped[str] = mapped_column(
        String(16), nullable=False, default="nasz", server_default="nasz"
    )
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EquipmentExternalPerson(Base, TimestampMixin):
    """Osoba bez konta NEXUSA, której wydajemy sprzęt (np. uczestnik Akademii)."""

    __tablename__ = "equipment_external_people"
    __table_args__ = (
        CheckConstraint(
            schema.CK_EXTERNAL_NAME, name="ck_equipment_external_people_name"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    work_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EquipmentProtocol(Base, TimestampMixin):
    """Protokół wydania albo zwrotu; treść zamrożona w chwili sporządzenia."""

    __tablename__ = "equipment_protocols"
    __table_args__ = (
        UniqueConstraint("year", "seq", name="uq_equipment_protocols_year_seq"),
        UniqueConstraint("number", name="uq_equipment_protocols_number"),
        CheckConstraint(schema.CK_PROTOCOL_KIND, name="ck_equipment_protocols_kind"),
        CheckConstraint(
            schema.CK_PROTOCOL_STATUS, name="ck_equipment_protocols_status"
        ),
        CheckConstraint(
            schema.CK_PROTOCOL_METHOD, name="ck_equipment_protocols_method"
        ),
        CheckConstraint(schema.CK_PROTOCOL_YEAR, name="ck_equipment_protocols_year"),
        CheckConstraint(schema.CK_PROTOCOL_SEQ, name="ck_equipment_protocols_seq"),
        CheckConstraint(
            schema.CK_PROTOCOL_SIGNED, name="ck_equipment_protocols_signed"
        ),
        CheckConstraint(
            schema.CK_PROTOCOL_CONFIRMED, name="ck_equipment_protocols_confirmed"
        ),
        Index("ix_equipment_protocols_status", "status"),
        Index("ix_equipment_protocols_contract", "contract_id"),
        Index("ix_equipment_protocols_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol_date: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    external_person_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_external_people.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 0462: uczestnik edycji Akademii jako posiadacz.
    academy_application_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("academy_applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    holder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    holder_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issuer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issuer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    template_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="oczekuje", server_default="oczekuje"
    )
    signature_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="brak", server_default="brak"
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    signed_file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class EquipmentAssignment(Base, TimestampMixin):
    """Wydanie egzemplarza jednemu posiadaczowi (zwrot zamyka wiersz)."""

    __tablename__ = "equipment_assignments"
    __table_args__ = (
        CheckConstraint(
            extras_schema.CK_ASSIGNMENT_ONE_HOLDER,
            name="ck_equipment_assignments_one_holder",
        ),
        CheckConstraint(
            schema.CK_ASSIGNMENT_CONDITION, name="ck_equipment_assignments_condition"
        ),
        CheckConstraint(
            schema.CK_ASSIGNMENT_RETURN_ORDER,
            name="ck_equipment_assignments_return_order",
        ),
        CheckConstraint(
            schema.CK_ASSIGNMENT_RETURN_COMPLETE,
            name="ck_equipment_assignments_return_complete",
        ),
        Index(
            "ux_equipment_assignments_active",
            "item_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL"),
        ),
        Index("ix_equipment_assignments_user", "user_id"),
        Index("ix_equipment_assignments_contract", "contract_id"),
        Index("ix_equipment_assignments_external", "external_person_id"),
        Index("ix_equipment_assignments_academy", "academy_application_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_items.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    external_person_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_external_people.id", ondelete="RESTRICT"),
        nullable=True,
    )
    academy_application_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("academy_applications.id", ondelete="RESTRICT"),
        nullable=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    returned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    return_condition: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    return_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issue_protocol_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_protocols.id", ondelete="SET NULL"), nullable=True
    )
    return_protocol_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_protocols.id", ondelete="SET NULL"), nullable=True
    )
    issued_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    returned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EquipmentProtocolLine(Base):
    """Pozycja protokołu — migawka nazwy, numeru i wartości z chwili wydania."""

    __tablename__ = "equipment_protocol_lines"
    __table_args__ = (
        UniqueConstraint(
            "protocol_id", "position", name="uq_equipment_protocol_lines_position"
        ),
        CheckConstraint(
            schema.CK_LINE_CATEGORY, name="ck_equipment_protocol_lines_category"
        ),
        CheckConstraint(
            schema.CK_LINE_QUANTITY, name="ck_equipment_protocol_lines_quantity"
        ),
        CheckConstraint(schema.CK_LINE_VALUE, name="ck_equipment_protocol_lines_value"),
        CheckConstraint(
            schema.CK_LINE_CONDITION, name="ck_equipment_protocol_lines_condition"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_protocols.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_items.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_assignments.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    identifier: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    quantity: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    unit_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    condition: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class EquipmentProtocolLink(Base):
    """Jednorazowy link do podpisu; w bazie tylko SHA-256 tokenu (D8)."""

    __tablename__ = "equipment_protocol_links"
    __table_args__ = (
        UniqueConstraint("token_sha256", name="uq_equipment_protocol_links_token"),
        Index("ix_equipment_protocol_links_protocol", "protocol_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_protocols.id", ondelete="CASCADE"), nullable=False
    )
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EquipmentTask(Base, TimestampMixin):
    """„Do zrobienia” recepcji; ``source_key`` czyni zakładanie idempotentnym."""

    __tablename__ = "equipment_tasks"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_equipment_tasks_source_key"),
        CheckConstraint(schema.CK_TASK_KIND, name="ck_equipment_tasks_kind"),
        CheckConstraint(schema.CK_TASK_STATUS, name="ck_equipment_tasks_status"),
        Index("ix_equipment_tasks_status_due", "status", "due_on"),
        Index("ix_equipment_tasks_academy", "academy_application_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="otwarte", server_default="otwarte"
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    external_person_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_external_people.id", ondelete="CASCADE"),
        nullable=True,
    )
    academy_application_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("academy_applications.id", ondelete="CASCADE"),
        nullable=True,
    )
    protocol_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_protocols.id", ondelete="CASCADE"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_reminded_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class EquipmentImportBatch(Base):
    """Partia importu pliku recepcji (plik nie jest przechowywany)."""

    __tablename__ = "equipment_import_batches"
    __table_args__ = (
        CheckConstraint(
            schema.CK_IMPORT_BATCH_STATUS, name="ck_equipment_import_batches_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="nowa", server_default="nowa"
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    applied_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EquipmentImportRow(Base):
    """Wiersz arkusza po oczyszczeniu z decyzją (przyjmij, pomiń, konflikt…)."""

    __tablename__ = "equipment_import_rows"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "sheet", "row_number", name="uq_equipment_import_rows_position"
        ),
        CheckConstraint(
            schema.CK_IMPORT_DECISION, name="ck_equipment_import_rows_decision"
        ),
        Index("ix_equipment_import_rows_batch", "batch_id", "decision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("equipment_import_batches.id", ondelete="CASCADE"), nullable=False
    )
    sheet: Mapped[str] = mapped_column(String(120), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    holder_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    holder_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_items.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
