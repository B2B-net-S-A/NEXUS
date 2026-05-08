"""Drag-drop schema editor storage (Traffit gap #7).

Lets admins define custom fields per entity (Candidate, Job) without a
deploy. Mirrors Traffit's "Konfiguracja pól" panel where each entity has
a 3-column drag-drop layout with system fields + custom fields of various
types (text, number, select, ...).

Why a single ``entity_field_defs`` table (not per-entity tables):
- Adding a custom field on Candidate vs Job is the same operation.
- The form renderer reads the table once per page render.
- Per-tenant variants are out of scope; if we ever need them, ``org_id``
  goes here.

Storage of values:
- Custom field VALUES live on the parent entity's existing JSONB column
  (``Candidate.custom_fields`` or ``Job.custom_fields``), keyed by the
  field's ``key``. So custom fields are read with one extra DB lookup
  for the schema, not a join per field.

Why we still hardcode the type values as an enum (instead of putting
them in the dictionary table from #8):
- The renderer needs to know how to validate + render each type. A new
  type value requires a code change anyway, so a DB-driven type vocab
  buys nothing.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class EntityType(str, enum.Enum):
    """Which entity the custom field belongs to.

    Limited to the two we actively edit in the UI. Adding ``user`` or
    ``client`` is a row-set + UI tab away.
    """

    candidate = "candidate"
    job = "job"


class FieldType(str, enum.Enum):
    """Renderable field types.

    Names mirror Traffit's vocabulary so admins migrating from Traffit
    keep mental model consistent. Validation rules:

    - ``text`` / ``long_text`` — string, optional max_length in `options`
    - ``number`` — int/float, optional min/max in `options`
    - ``checkbox`` — boolean
    - ``radio`` / ``select`` / ``multi_select`` — value from `options.choices`
    - ``date`` / ``datetime`` — ISO 8601 string
    - ``file`` / ``files`` — Object Storage object key(s)
    - ``location`` — {country, city} pair
    - ``link`` — URL string
    """

    text = "text"
    long_text = "long_text"
    number = "number"
    checkbox = "checkbox"
    radio = "radio"
    select = "select"
    multi_select = "multi_select"
    date = "date"
    datetime = "datetime"
    file = "file"
    files = "files"
    location = "location"
    link = "link"


class EntityFieldDef(Base, TimestampMixin):
    """One custom field definition for a given entity type.

    The triple (entity_type, key) is unique — no two custom fields on the
    same entity can share a JSON key.
    """

    __tablename__ = "entity_field_defs"
    __table_args__ = (
        UniqueConstraint("entity_type", "key", name="uq_entity_field_defs_entity_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entityfieldtype"),
        nullable=False,
        index=True,
    )

    # Stable identifier used as the JSON key on Candidate/Job.custom_fields.
    # Must match /^[a-z][a-z0-9_]*$/ at the API layer; we don't enforce
    # in DB to avoid migration churn if the regex evolves.
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label_pl: Mapped[str] = mapped_column(String(200), nullable=False)
    label_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    help_text: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    field_type: Mapped[FieldType] = mapped_column(
        Enum(FieldType, name="entityfieldtypeenum"),
        nullable=False,
    )

    # Per-type options bag:
    # - select/radio/multi_select: {"choices": [{"value": "x", "label": "X"}]}
    # - text/long_text: {"max_length": 500}
    # - number: {"min": 0, "max": 100}
    # - file/files: {"max_size_bytes": ..., "allowed_extensions": [...]}
    # Validation lives in the form renderer; this is just the config bag.
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 3-column drag-drop layout: section is "left" / "middle" / "right" or
    # custom section names. Ordinal orders fields within a section.
    section: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True, default="middle"
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )


# Mapping of FieldType to a Polish label, surfaced in the picker on the
# editor UI.
FIELD_TYPE_LABELS: dict[FieldType, str] = {
    FieldType.text: "Tekst",
    FieldType.long_text: "Długi tekst",
    FieldType.number: "Liczba",
    FieldType.checkbox: "Pole wyboru",
    FieldType.radio: "Radio",
    FieldType.select: "Wybór",
    FieldType.multi_select: "Wybór wielokrotny",
    FieldType.date: "Data",
    FieldType.datetime: "Data i godzina",
    FieldType.file: "Plik",
    FieldType.files: "Pliki",
    FieldType.location: "Lokalizacja",
    FieldType.link: "Link",
}


__all__: List[str] = [
    "EntityType",
    "FieldType",
    "EntityFieldDef",
    "FIELD_TYPE_LABELS",
]
