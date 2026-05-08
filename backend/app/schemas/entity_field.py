"""Pydantic schemas for Settings → Konfiguracja pól (#7)."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.entity_field import EntityType, FieldType

# JSON-key constraint: starts with a lowercase letter, then alnum/underscore.
# Matches common JS/Python identifier-safe naming so the renderer can use it
# as a property name without escaping.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


class FieldChoice(BaseModel):
    """One option for select / radio / multi_select fields."""

    value: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=200)


class EntityFieldDefOut(BaseModel):
    id: int
    entity_type: EntityType
    key: str
    label_pl: str
    label_en: Optional[str]
    help_text: Optional[str]
    field_type: FieldType
    options: Dict[str, Any]
    required: bool
    section: Optional[str]
    ordinal: int
    archived: bool
    last_edited_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EntityFieldDefCreate(BaseModel):
    entity_type: EntityType
    key: str = Field(..., min_length=1, max_length=60)
    label_pl: str = Field(..., min_length=1, max_length=200)
    label_en: Optional[str] = Field(None, max_length=200)
    help_text: Optional[str] = Field(None, max_length=500)
    field_type: FieldType
    options: Dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    section: Optional[str] = Field("middle", max_length=40)
    ordinal: int = Field(0, ge=0)

    @field_validator("key")
    @classmethod
    def _key_is_identifier_safe(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError(
                "key must match /^[a-z][a-z0-9_]*$/ (lowercase + underscores)"
            )
        return v


class EntityFieldDefUpdate(BaseModel):
    label_pl: Optional[str] = Field(None, min_length=1, max_length=200)
    label_en: Optional[str] = Field(None, max_length=200)
    help_text: Optional[str] = Field(None, max_length=500)
    options: Optional[Dict[str, Any]] = None
    required: Optional[bool] = None
    section: Optional[str] = Field(None, max_length=40)
    ordinal: Optional[int] = Field(None, ge=0)
    archived: Optional[bool] = None


class FieldTypeInfo(BaseModel):
    """Metadata for the field-type picker in the editor UI."""

    value: FieldType
    label: str


class SchemaListResponse(BaseModel):
    """Full schema for one entity type. Used by the editor and by the
    form renderer downstream.
    """

    entity_type: EntityType
    fields: List[EntityFieldDefOut]
