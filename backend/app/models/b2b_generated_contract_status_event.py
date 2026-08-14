"""Dziennik zmian statusu handlowego wygenerowanej umowy B2B.

Powstał, bo powrót z „Zawieszonej" na „Aktywną" MUSI wyczyścić `closure_reason`
/ `closure_date` / `closure_reason_other` — wymusza to
`ck_b2b_generated_contracts_closure_coherence`. Bez osobnego zapisu data i powód
zakończenia poprzedniego projektu przepadałyby przy każdym przywróceniu
kontraktora do gry, a to jest dokładnie ta informacja, o którą pyta się później
(„ile razy ten kontraktor był bez projektu i dlaczego").

Kolumna „poprzednie zawieszenie" na samej umowie byłaby gorsza dwukrotnie:
pamiętałaby wyłącznie ostatnie zdarzenie i dublowałaby semantykę pól, które już
istnieją.

To NIE zastępuje `Activity` — tamten log jest ogólnym audytem „kto co kliknął"
i obejmuje też wiersze sprzed migracji 0226. Ten dziennik jest wąski, typowany
i serwowany użytkownikowi w dialogu „Historia statusów".
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class B2BGeneratedContractStatusEvent(Base):
    __tablename__ = "b2b_generated_contract_status_events"
    __table_args__ = (
        Index("ix_b2b_gc_status_events_contract", "generated_contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # CASCADE, nie RESTRICT: `DELETE /generated/{id}` istnieje i zwalnia numer
    # umowy do ponownego użycia. RESTRICT zamieniłby dziennik w blokadę tej
    # operacji — a dziennik ma dokumentować życie umowy, nie przedłużać je.
    generated_contract_id: Mapped[int] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Nullowalne: pierwszy wpis dla umowy sprzed wdrożenia dziennika nie ma
    # udokumentowanego stanu wyjściowego. Zmyślenie go („pewnie active") byłoby
    # fałszywym zapisem w rejestrze, który ma służyć jako dowód.
    from_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Data zakończenia projektu (przy `suspended`) albo umowy (przy `closed`) —
    # kopia `closure_date` z momentu zdarzenia. Przy powrocie na `active` NULL.
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reason_other: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Projekt i klient przypisane przy przywróceniu umowy na `active`. Dla
    # pozostałych przejść NULL.
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    changed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<B2BGeneratedContractStatusEvent id={self.id} "
            f"contract={self.generated_contract_id} "
            f"{self.from_status}->{self.to_status}>"
        )
