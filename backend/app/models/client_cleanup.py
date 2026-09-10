"""Raport jednorazowego czyszczenia zakładki „Nieaktywni klienci" (0303).

``ClientCleanupRun`` to wykonana operacja wraz z listą B (klienci wstrzymani
od usunięcia z opisem znalezionych powiązań). ``PurgedClient`` to lista A —
i jednocześnie nagrobek, który nie pozwala nocnemu syncowi Traffita odtworzyć
usuniętego klienta. Dlatego wiersz nie ma FK do ``clients`` (klienta już nie
ma) i nie znika razem z raportem (RESTRICT).
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientCleanupRun(Base):
    __tablename__ = "client_cleanup_runs"
    __table_args__ = (UniqueConstraint("kind", name="uq_client_cleanup_runs_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Jedna operacja danego rodzaju — UNIQUE jest bezpiecznikiem
    # jednorazowości, a nie tylko etykietą.
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    executed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Zdenormalizowane — konto może zniknąć, raport nie.
    executed_by_name: Mapped[Optional[str]] = mapped_column(String(255))
    candidates_count: Mapped[int] = mapped_column(Integer, nullable=False)
    kept_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    held_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Lista B: [{client_id, name, reasons: [{code, label, count, ...}]}].
    held: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class PurgedClient(Base):
    __tablename__ = "purged_clients"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_purged_clients_client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("client_cleanup_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Id usuniętego klienta — bez FK, bo wiersza ``clients`` już nie ma.
    client_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    legal_name: Mapped[Optional[str]] = mapped_column(String(255))
    nip: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[Optional[str]] = mapped_column(String(32))
    external_source: Mapped[Optional[str]] = mapped_column(String(50))
    external_id: Mapped[Optional[str]] = mapped_column(String(100))
    client_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Zakresy portfela, aliasy i wpisy dziennika w chwili usunięcia — żeby
    # decyzję dało się odtworzyć po fakcie.
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    purged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
