"""Editable taxonomy storage (Traffit gap #8).

Replaces a class of hardcoded enums (industries, contract types, rejection
reasons, ...) with database rows so admins can extend taxonomies without
a deploy. Mirrors Traffit's Settings → Słowniki section which exposes
~25 dictionaries to admin users.

Why a single generic ``dictionaries`` + ``dictionary_items`` instead of
one table per taxonomy:
- Adding a new taxonomy is a row insert, not a migration.
- Admin UI is a single CRUD page that switches the dictionary slug.
- Existing enum values are migrated by seeding rows with key=enum_value
  so call sites can keep using strings while taxonomies become editable.

Why not delete the old enums:
- Many lookups use string equality (``WHERE source_enum = 'pracuj'``)
  against legacy data. Keeping enum values stable prevents data churn.
- New taxonomies (``industry``, ``rejection_reason``) live entirely in
  this table; old enum-backed taxonomies are mirrored here for the UI
  but the enum stays as the system-of-record until a per-taxonomy
  migration retires it.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class Dictionary(Base, TimestampMixin):
    """A named taxonomy (e.g. 'industry', 'rejection_reason').

    ``slug`` is the stable identifier used by code lookups. ``label_pl``
    is admin-facing; we don't currently expose a multi-language UI but
    the field is sized for future use.
    """

    __tablename__ = "dictionaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    label_pl: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # When True, callers must use values from this table (no fallback to
    # enums). When False, enum-backed taxonomies treat the rows as a
    # presentation overlay only (UI shows the row's label, but storage
    # still uses the enum value).
    enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    items: Mapped[List["DictionaryItem"]] = relationship(
        back_populates="dictionary",
        cascade="all, delete-orphan",
        order_by="DictionaryItem.ordinal",
    )


class DictionaryItem(Base, TimestampMixin):
    """One value inside a dictionary.

    ``key`` is the stable identifier callers send back to the API
    (matches the legacy enum value where applicable). ``label_pl`` is
    what users see in the UI; ordinal controls display order in pickers.

    Archived items remain in the table so historical references stay
    resolvable, but UI dropdowns hide them by default.
    """

    __tablename__ = "dictionary_items"
    __table_args__ = (
        UniqueConstraint("dictionary_id", "key", name="uq_dictionary_items_dict_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    dictionary_id: Mapped[int] = mapped_column(
        ForeignKey("dictionaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label_pl: Mapped[str] = mapped_column(String(200), nullable=False)
    label_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_edited_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )

    dictionary: Mapped[Dictionary] = relationship(back_populates="items")
