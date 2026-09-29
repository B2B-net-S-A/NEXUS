"""„Champion po ludzku” — wspólna baza wiedzy i teksty rekrutacji (migracja 0402).

Decyzje Artura 29.09.2026: rekruter ma w minutę zrozumieć, kogo szuka i co
powiedzieć kandydatowi. Wiedza OGÓLNA (co to jest technologia, czym zajmuje
się rola) powstaje raz — z researchu w internecie — i jest wspólna dla
wszystkich rekrutacji. AI na bieżąco pisze tylko teksty jednej rekrutacji.

* ``plain_terms`` — słowniczek technologii. Klucz ``term_key`` to nazwa
  kanoniczna (``skill_normalize.canonical_of``), BEZ FK do ``skills``: id
  różnią się między bazami, a zasiew idzie po nazwie. Nowe terminy NIE są
  dopisywane do ``skill_aliases`` — to zmieniłoby scoring i wyszukiwanie.
* ``role_profiles`` — biblioteka ról zbudowana z historii rekrutacji.
* ``job_plain_briefs`` — teksty jednej rekrutacji w OSOBNEJ tabeli, nie
  w ``jobs.champion_profile``: ``champion_intake.fingerprint`` hashuje cały
  profil, więc zapis w tle dawałby fałszywe 409 przy imporcie dokumentu.
* ``plain_knowledge_events`` — historia poprawek terminów i ról (bez FK:
  przeżywa usunięcie wiersza i konta).

``status`` = ``researching`` to ZAJĘCIE wiersza na czas researchu (wstawione
``ON CONFLICT DO NOTHING``) — research nie trzyma blokady ani połączenia.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")

ORIGINS = ("seed", "ai", "manual")
STATUSES = ("ready", "researching", "failed")


class PlainTerm(Base):
    __tablename__ = "plain_terms"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('seed','ai','manual')", name="ck_plain_terms_origin"
        ),
        CheckConstraint(
            "status IN ('ready','researching','failed')",
            name="ck_plain_terms_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    does: Mapped[Optional[str]] = mapped_column(Text)
    cv_hints: Mapped[Optional[list]] = mapped_column(_JSON)
    confused_with: Mapped[Optional[str]] = mapped_column(Text)
    sources: Mapped[Optional[list]] = mapped_column(_JSON)
    origin: Mapped[str] = mapped_column(
        String(10), nullable=False, default="seed", server_default="seed"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="ready", server_default="ready"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class RoleProfile(Base):
    __tablename__ = "role_profiles"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('seed','ai','manual')", name="ck_role_profiles_origin"
        ),
        CheckConstraint(
            "status IN ('ready','researching','failed')",
            name="ck_role_profiles_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    example: Mapped[Optional[str]] = mapped_column(Text)
    day_to_day: Mapped[Optional[list]] = mapped_column(_JSON)
    candidate_questions: Mapped[Optional[list]] = mapped_column(_JSON)
    typical_skills: Mapped[Optional[list]] = mapped_column(_JSON)
    # {"title_words": [...], "skills": [...], "category": "slug"|null}
    match_rules: Mapped[Optional[dict]] = mapped_column(_JSON)
    sources: Mapped[Optional[list]] = mapped_column(_JSON)
    origin: Mapped[str] = mapped_column(
        String(10), nullable=False, default="seed", server_default="seed"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="ready", server_default="ready"
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class JobPlainBrief(Base):
    __tablename__ = "job_plain_briefs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('none','ready','failed')", name="ck_job_plain_briefs_status"
        ),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="none", server_default="none"
    )
    inputs_hash: Mapped[Optional[str]] = mapped_column(String(64))
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    model: Mapped[Optional[str]] = mapped_column(String(80))
    one_liner: Mapped[Optional[str]] = mapped_column(Text)
    example: Mapped[Optional[str]] = mapped_column(Text)
    day_to_day: Mapped[Optional[list]] = mapped_column(_JSON)
    pitch: Mapped[Optional[str]] = mapped_column(Text)
    candidate_qa: Mapped[Optional[list]] = mapped_column(_JSON)
    screening_plain: Mapped[Optional[list]] = mapped_column(_JSON)
    term_notes: Mapped[Optional[dict]] = mapped_column(_JSON)
    message: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlainKnowledgeEvent(Base):
    __tablename__ = "plain_knowledge_events"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('term','role')", name="ck_plain_knowledge_events_type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(10), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changes: Mapped[Optional[dict]] = mapped_column(_JSON)
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    user_name: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
