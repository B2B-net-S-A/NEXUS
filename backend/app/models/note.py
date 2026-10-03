import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import note_kinds


# 0399: wpisy zapisane przez automaty (auto-match z CV i ze scrapera JJIT)
# — lista notatek chowa je domyślnie za „Pokaż systemowe”.
SYSTEM_NOTE_SOURCE = "system"


class NoteType(str, enum.Enum):
    call = "call"
    meeting = "meeting"
    email = "email"
    general = "general"
    interview = "interview"


class Note(Base, TimestampMixin):
    """
    Notatka powiązana z kandydatem i/lub ofertą pracy.
    """

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[NoteType] = mapped_column(
        Enum(NoteType), default=NoteType.general, nullable=False
    )

    # Powiązania — notatka może być przy kandydacie, ofercie, kontrakcie lub
    # ich kombinacji. Wszystkie FK są nullable + ON DELETE SET NULL.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id"), index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    # Zewnętrzne pochodzenie notatki (np. "fireflies:<transcript_id>") —
    # dedup przy re-syncu + lookup audio dla briefingu DL.
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    # Strukturalna tożsamość źródła (integracja dwukierunkowa Traffit).
    # `source_ref` zostaje dla kompatybilności i czytelnych linków audytowych.
    external_source: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    source_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Notatki w Traffit są append-only — korekta tworzy nową notatkę wskazującą
    # na zastąpioną lokalną, zamiast mutować zdalną historię.
    supersedes_note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    # Link do nagrania (Fireflies CDN). Może wygasać — briefing kopiuje
    # audio do Object Storage zamiast polegać na tym URL-u.
    audio_url: Mapped[Optional[str]] = mapped_column(Text)

    # 0399: przypięcie wspólne dla zespołu — przypięta notatka jest pierwsza
    # na liście, w szybkim podglądzie kandydata i w doku osoby w rekrutacji.
    pinned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 0399: odpowiedź na notatkę — JEDEN poziom (odpowiedź na odpowiedź = 422).
    # Odpowiedź dziedziczy kandydata i rekrutację notatki głównej; usunięcie
    # notatki głównej kasuje odpowiedzi (ON DELETE CASCADE).
    parent_note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 0412: rodzaj notatki (`services/note_kinds.py`) — nadaje go nasłuch
    # niżej przy zapisie przez ORM, a wierszom z surowego SQL (import
    # Traffita) `note_kind_backfill.classify_pending`. NULL = jeszcze
    # nieuzupełniony; czytelnicy traktują go jak zwykłą notatkę.
    kind: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)

    # Relationships
    candidate = relationship("Candidate", back_populates="notes")
    job = relationship("Job", back_populates="notes")
    contract = relationship(
        "Contract", back_populates="contract_notes", foreign_keys=[contract_id]
    )
    author = relationship(
        "User", back_populates="authored_notes", foreign_keys=[author_id]
    )
    mentions = relationship(
        "NoteMention",
        back_populates="note",
        cascade="all, delete-orphan",
    )
    supersedes_note = relationship(
        "Note", remote_side="Note.id", foreign_keys=[supersedes_note_id]
    )
    # Tylko do odczytu i bez kaskady ORM: odpowiedzi kasuje baza (CASCADE).
    parent_note = relationship(
        "Note",
        remote_side="Note.id",
        foreign_keys=[parent_note_id],
        viewonly=True,
    )

    __table_args__ = (
        Index(
            "ux_notes_external_source_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "ix_notes_candidate_source_created",
            "candidate_id",
            "external_source",
            "source_created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Note id={self.id} type={self.note_type} candidate={self.candidate_id}>"
        )


def _note_type_value(note: Note) -> Optional[str]:
    value = note.note_type
    return value.value if isinstance(value, NoteType) else value


@event.listens_for(Note, "before_insert")
def _set_note_kind_on_insert(_mapper, _connection, target: Note) -> None:
    target.kind = note_kinds.classify(
        target.content,
        note_type=_note_type_value(target),
        external_source=target.external_source,
    )


@event.listens_for(Note, "before_update")
def _set_note_kind_on_update(_mapper, _connection, target: Note) -> None:
    attrs = inspect(target).attrs
    if not any(
        getattr(attrs, name).history.has_changes()
        for name in ("content", "note_type", "external_source")
    ):
        return
    target.kind = note_kinds.classify(
        target.content,
        note_type=_note_type_value(target),
        external_source=target.external_source,
    )
