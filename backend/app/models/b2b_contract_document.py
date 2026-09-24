"""Dokumenty pochodne umowy: aneksy, rozwiązania, umowa przedwstępna.

Osobna tabela, NIE kolumna „typ dokumentu” w ``b2b_generated_contracts``: ten
rejestr jest rejestrem UMÓW — kilkanaście miejsc (numeracja, potwierdzenie
podpisu, zakładki statusów, cykl życia kontraktu, poczta zamówień, backfill
kontaktu) zakłada, że każdy jego wiersz to umowa B2B. Aneks wpisany tam
zabrałby numer z puli umów albo zostałby „aktywowany” jak umowa.

Dokumenty nie mają własnego numeru (decyzja Artura 23.09.2026) — identyfikuje
je typ, data i umowa bazowa („Aneks z dnia 01.10.2026 do umowy 1487/2026”).

Generowanie niczego nie zmienia w kontraktach — skutki (krok stawki, data
końca, dane firmy) wchodzą dopiero przy „Oznacz jako podpisany”
(``effect_applied_at``), tak jak umowa B2B zakłada kontrakt dopiero po
podpisie obustronnym.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

# Słowniki żyją w module bez zależności — czyta je też siatka DDL w
# ``entrypoint.sh`` (``services/b2b_documents/constants.py``).
from app.services.b2b_documents.constants import (  # noqa: E402
    B2B_DOCUMENT_STATUSES,
    B2B_DOCUMENT_TYPES,
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class B2BContractDocument(Base, TimestampMixin):
    __tablename__ = "b2b_contract_documents"
    __table_args__ = (
        CheckConstraint(
            _in_list("document_type", B2B_DOCUMENT_TYPES),
            name="ck_b2b_contract_documents_type",
        ),
        CheckConstraint(
            _in_list("status", B2B_DOCUMENT_STATUSES),
            name="ck_b2b_contract_documents_status",
        ),
        CheckConstraint(
            "language IN ('pl', 'en')",
            name="ck_b2b_contract_documents_language",
        ),
        CheckConstraint(
            "signature_status IN ('unsigned', 'signed_both')",
            name="ck_b2b_contract_documents_signature_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="pl")
    # Umowa bazowa z rejestru. NULL wyłącznie dla umowy przedwstępnej, która
    # poprzedza umowę. CASCADE: rodzica usunąć można tylko niepodpisanego, a
    # dokument do umowy, której nie ma, nie ma sensu.
    parent_generated_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Pola formularza BEZ danych wrażliwych (PESEL, dowód, adres zamieszkania):
    # te trafiają wyłącznie do wydanego pliku. Ponowne pobranie prosi o nie
    # jeszcze raz (``sensitive_fields`` w rejestrze typów).
    render_payload: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="issued", server_default="issued"
    )
    signature_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unsigned", server_default="unsigned"
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    effect_applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Co podpis zmienił (id aneksu, kontraktu, daty) — bez kwot i nazwisk.
    effect_summary: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    cancelled_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<B2BContractDocument id={self.id} type={self.document_type} "
            f"parent={self.parent_generated_contract_id}>"
        )
