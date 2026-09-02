"""Zamówienia z maila: dziennik załączników i stan pętli pobierania.

``order_mail_documents`` — jeden wiersz na załącznik PDF (albo na wiadomość
bez PDF-a), z drabiną wyniku. Świadomie OSOBNA od ``email_attachments``:
tamte kolumny (``is_cv_candidate``, ``parsed_candidate_id``) znaczą co innego,
a skrzynka zamówień nie jest pocztą rekrutera — jej wiadomości nie mogą
lądować na osiach czasu kandydatów.

Każda wiadomość dostaje wpis, także zignorowana. Ticket mówi „bez kolejki
weryfikacji" i to jest prawda dla KOLEJKI operatora; dziennik admina musi
umieć odpowiedzieć „czy zamówienie BIK za sierpień w ogóle przyszło?" — błąd,
którego nie da się przypisać, albo zasypuje, albo znika (lekcja z syncu Traffita).

Idempotencja: dwa częściowe indeksy unikalne — (wiadomość, SHA załącznika) dla
załączników i (wiadomość) dla wpisów bez PDF-a. Coolify restartuje kontener
przy każdym pushu na main, więc bieg przerwany w połowie musi dać się
powtórzyć bez duplikatów. Duplikat TREŚCI (ten sam PDF w nowym mailu) jest
osobnym wpisem ``duplicate_attachment`` wskazującym na pierwowzór — a nie
naruszeniem unikalności — bo o nim też trzeba wiedzieć.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

OUTCOME_RECEIVED = "received"
OUTCOME_IGNORED_NO_PDF = "ignored_no_pdf"
OUTCOME_IGNORED_SENDER = "ignored_sender"
OUTCOME_DUPLICATE = "duplicate_attachment"
OUTCOME_UNRECOGNIZED = "unrecognized_client"
OUTCOME_NEEDS_REVIEW = "needs_review"
OUTCOME_AUTO_APPLIED = "auto_applied"
OUTCOME_APPLIED = "applied"
OUTCOME_DISMISSED = "dismissed"
OUTCOME_FAILED = "failed"
OUTCOMES: tuple[str, ...] = (
    OUTCOME_RECEIVED,
    OUTCOME_IGNORED_NO_PDF,
    OUTCOME_IGNORED_SENDER,
    OUTCOME_DUPLICATE,
    OUTCOME_UNRECOGNIZED,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_AUTO_APPLIED,
    OUTCOME_APPLIED,
    OUTCOME_DISMISSED,
    OUTCOME_FAILED,
)
#: Wyniki, które operator widzi w kolejce (reszta to dziennik admina).
QUEUE_OUTCOMES: tuple[str, ...] = (OUTCOME_NEEDS_REVIEW,)

GATE_AUTO = "auto"
GATE_REVIEW = "review"
GATE_VERDICTS: tuple[str, ...] = (GATE_AUTO, GATE_REVIEW)

CONNECTION_PURPOSE_PERSONAL = "personal"
CONNECTION_PURPOSE_ORDERS = "orders"


class OrderMailDocument(Base, TimestampMixin):
    __tablename__ = "order_mail_documents"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('received','ignored_no_pdf','ignored_sender',"
            "'duplicate_attachment','unrecognized_client','needs_review',"
            "'auto_applied','applied','dismissed','failed')",
            name="ck_order_mail_documents_outcome",
        ),
        CheckConstraint(
            "gate_verdict IS NULL OR gate_verdict IN ('auto','review')",
            name="ck_order_mail_documents_gate_verdict",
        ),
        Index(
            "uq_order_mail_documents_message_attachment",
            "internet_message_id",
            "attachment_sha256",
            unique=True,
            postgresql_where="attachment_sha256 IS NOT NULL",
        ),
        Index(
            "uq_order_mail_documents_message_no_attachment",
            "internet_message_id",
            unique=True,
            postgresql_where="attachment_sha256 IS NULL",
        ),
        Index("ix_order_mail_documents_sha", "attachment_sha256"),
        Index("ix_order_mail_documents_outcome", "outcome"),
        Index("ix_order_mail_documents_client", "client_id"),
        Index("ix_order_mail_documents_received", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("m365_connections.id", ondelete="SET NULL"), index=True
    )
    # RFC 5322: Message-ID do 998 znaków; Graph zwraca go jako internetMessageId.
    internet_message_id: Mapped[str] = mapped_column(String(998), nullable=False)
    m365_message_id: Mapped[Optional[str]] = mapped_column(String(512))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sender_email: Mapped[Optional[str]] = mapped_column(String(320))
    sender_domain: Mapped[Optional[str]] = mapped_column(String(255))
    subject: Mapped[Optional[str]] = mapped_column(String(1000))

    attachment_name: Mapped[Optional[str]] = mapped_column(String(255))
    attachment_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    attachment_size: Mapped[Optional[int]] = mapped_column(Integer)
    storage_path: Mapped[Optional[str]] = mapped_column(String(512))
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("order_mail_documents.id", ondelete="SET NULL")
    )

    outcome: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OUTCOME_RECEIVED
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
    client_key: Mapped[Optional[str]] = mapped_column(String(64))
    identification_method: Mapped[Optional[str]] = mapped_column(String(16))
    identification_reason: Mapped[Optional[str]] = mapped_column(Text)
    client_policy: Mapped[Optional[str]] = mapped_column(String(128))
    #: Pełny wynik odczytu (pola dokumentu + wiersze osób) — źródło dla kolejki.
    extraction: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    #: Metadane kompletności tekstu: strony, OCR, cap, re-ekstrakcja, ucięcie.
    document_meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    gate_verdict: Mapped[Optional[str]] = mapped_column(String(16))
    gate_reasons: Mapped[Optional[list[Any]]] = mapped_column(JSONB)
    #: Plan zapisu (P4): co zostałoby/zostało utworzone i gdzie.
    proposal: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    applied_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL")
    )
    applied_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL")
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: NULL = zapis automatyczny (aktor systemowy).
    applied_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)

    client = relationship("Client", foreign_keys=[client_id])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OrderMailDocument id={self.id} outcome={self.outcome!r} "
            f"client={self.client_key!r} sha={(self.attachment_sha256 or '')[:12]}>"
        )


class OrderMailSyncState(Base):
    """Jednowierszowy stan pętli (``id = 1``) — watermark w bazie, nie w pamięci.

    Coolify restartuje kontener przy każdym pushu na main; timer w pamięci
    startowałby od zera i albo pomijał slot, albo odpalał bieg przy każdym
    deployu. ``last_seen_received_at`` to najpóźniejszy ``receivedDateTime``
    przetworzonej wiadomości — następny bieg pyta od niego minus nakładka.
    """

    __tablename__ = "order_mail_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_status: Mapped[Optional[str]] = mapped_column(String(20))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_seen_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
