"""Log wygenerowanych umów B2B — numeracja + audyt.

Standalone render (bez rekordu `Contract`) zapisuje tu wiersz przy pobraniu
finalnego DOCX. `contract_number` jest zawsze kanoniczny („1434/2026”), a `seq`
to jego liczbowy prefiks — stąd UNIQUE(year, seq) gwarantuje na poziomie DB,
że numer umowy nie powtórzy się w obrębie roku (race-safe, w odróżnieniu od
samego SELECT-checku w API).

Legacy (wiersze sprzed PR #469, id 5-7 na prod): `seq` był licznikiem wierszy
niezależnym od numeru — dlatego constraint NIE jest na (year, contract_number)
(prod ma historyczny duplikat „1434/2026”, którego nie ruszamy bez decyzji).
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BGeneratedContract(Base, TimestampMixin):
    __tablename__ = "b2b_generated_contracts"
    __table_args__ = (
        Index("uq_b2b_generated_contracts_year_seq", "year", "seq", unique=True),
        CheckConstraint(
            "signature_status IN ('unsigned', 'signed_both')",
            name="ck_b2b_generated_contracts_signature_status",
        ),
        CheckConstraint(
            "signature_source IS NULL OR "
            "signature_source IN ('manual_confirmation', 'validated_upload')",
            name="ck_b2b_generated_contracts_signature_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_number: Mapped[str] = mapped_column(String(64), nullable=False)
    partner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="pl", nullable=False)
    signing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Business state of the generated legal document. This is deliberately a
    # varchar + CHECK (not a PostgreSQL enum) so the one-way workflow remains
    # additively deployable and easy to extend without enum DDL.
    signature_status: Mapped[str] = mapped_column(
        String(32), default="unsigned", server_default="unsigned", nullable=False
    )
    # ``manual_confirmation`` is an audited declaration by a trusted user. It
    # must never be confused with DocumentSignature/QES evidence.
    signature_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # RESTRICT is intentional: once a signed generated document points at a
    # Contract, hard-deleting that Contract would destroy its audit linkage.
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Surowy payload `/render` (B2BRenderRequest jako JSON) — pozwala odtworzyć i
    # pobrać DOCX ponownie z zakładki „Wygenerowane umowy". NULL = wiersz sprzed
    # tej funkcji (re-download niedostępny). JSON+wariant JSONB by działał też na
    # SQLite w testach (constraint-test tworzy tabelę na sqlite).
    render_payload: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<B2BGeneratedContract id={self.id} number={self.contract_number!r}>"
