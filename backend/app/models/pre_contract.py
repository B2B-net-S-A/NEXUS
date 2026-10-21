"""Prośba o umowę przedwstępną dla osoby w rekrutacji (0505, decyzje Artura 21.10.2026).

Delivery Lead, Head of Recruitment albo sam rekruter prosi o przedwstępną dla
JEDNEJ osoby w JEDNEJ rekrutacji (para kandydat + rekrutacja) i mówi, na kiedy
ma być podpisana (przed wysłaniem CV, przed rozmową u klienta, przed umową B2B
albo do daty). Wystawia domyślnie rekruter prowadzący osobę. Każdy, kto
poprosił albo obserwuje, widzi stan i dostaje dzwonek przy każdej zmianie.

Treść umowy powstaje w Generatorze dokumentów (``b2b_contract_documents``,
rodzina ``preliminary``) — prośba tylko wskazuje wydany dokument
(``document_id``) i prowadzi jego drogę: wysłana → kandydat podpisał (dowolna
forma podpisu, decyzja 21.10) → podpisana przez firmę → obowiązuje do
``valid_until``. Pliki podpisane trafiają pod ``/pre_contracts/{id}/`` —
zawierają PESEL, więc pobiera je tylko ten, kto może prowadzić prośbę.

Każdy krok to wiersz ``pre_contract_events`` (kto, kiedy, co) — z niego panel
osoby rysuje historię, a dzwonek wskazuje zdarzenie (dzienny dedup dzwonków
liczy się per encja, więc dwa kroki jednego dnia nie zjadają się nawzajem).
"""

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

#: Na kiedy umowa ma być podpisana — etap, przed którym jest potrzebna.
NEEDED_BEFORE = ("cv_sent", "client_interview", "b2b_contract", "date")

#: Forma podpisu kandydata (decyzja 21.10.2026: każda forma).
SIGNATURE_FORMS = (
    "trusted_profile",
    "personal_signature",
    "qualified",
    "handwritten_scan",
    "other",
)

#: Jak prośba się skończyła. ``None`` = w toku.
CLOSE_REASONS = (
    "fulfilled",  # umowa B2B podpisana / proces zakończony zgodnie z planem
    "expired",  # minęła data ważności
    "cancelled",  # anulowana przez prowadzącego
    "withdrawn",  # prośbę wycofał proszący przed wysłaniem
    "candidate_refused",  # kandydat odmówił podpisu
    "candidate_withdrew",  # kandydat zrezygnował, umowa obowiązywała
)

#: Co kandydat zrobił, gdy zrezygnował z procesu objętego umową.
WITHDRAWAL_KINDS = ("no_show", "refused", "resigned", "bypassed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PreContractRequest(Base, TimestampMixin):
    __tablename__ = "pre_contract_requests"
    __table_args__ = (
        CheckConstraint(
            _in("needed_before", NEEDED_BEFORE), name="ck_pre_contract_needed_before"
        ),
        CheckConstraint(
            f"candidate_signature_form IS NULL OR {_in('candidate_signature_form', SIGNATURE_FORMS)}",
            name="ck_pre_contract_signature_form",
        ),
        CheckConstraint(
            f"close_reason IS NULL OR {_in('close_reason', CLOSE_REASONS)}",
            name="ck_pre_contract_close_reason",
        ),
        # Najwyżej jedna prośba w toku na parę — druga prośba dopisuje
        # proszącego do obserwujących.
        Index(
            "uq_pre_contract_open_per_pair",
            "candidate_id",
            "job_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )

    needed_before: Mapped[str] = mapped_column(String(24), nullable=False)
    needed_by: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Kto wystawia — domyślnie rekruter prowadzący osobę.
    assignee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candidate_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    candidate_signature_form: Mapped[Optional[str]] = mapped_column(
        String(24), nullable=True
    )
    candidate_file_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    candidate_file_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    company_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    company_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    company_file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Termin zawarcia umowy B2B po akceptacji klienta (wzór CeZ: 5 dni roboczych).
    b2b_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_reason: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Rezygnacja kandydata z procesu objętego umową — dowód do decyzji o karze.
    withdrawal: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Ostatnie przypomnienie sweepera (wygasa / kandydat milczy / termin B2B).
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<PreContractRequest id={self.id} candidate={self.candidate_id} "
            f"job={self.job_id} closed={self.close_reason}>"
        )


class PreContractWatcher(Base):
    """Kto widzi stan prośby i dostaje dzwonki (proszący, wystawiający, chętni)."""

    __tablename__ = "pre_contract_watchers"

    request_id: Mapped[int] = mapped_column(
        ForeignKey("pre_contract_requests.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PreContractEvent(Base):
    """Jeden krok prośby — historia w panelu osoby i encja dzwonka."""

    __tablename__ = "pre_contract_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("pre_contract_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Szczegóły bez danych wrażliwych (forma podpisu, data, powód).
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
