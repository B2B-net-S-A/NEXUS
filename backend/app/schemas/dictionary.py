"""Pydantic schemas for editable dictionaries (#8)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DictionaryItemOut(BaseModel):
    id: int
    key: str
    label_pl: str
    label_en: Optional[str]
    ordinal: int
    archived: bool
    last_edited_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DictionaryOut(BaseModel):
    id: int
    slug: str
    label_pl: str
    description: Optional[str]
    enforced: bool
    items: List[DictionaryItemOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DictionaryItemCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    label_pl: str = Field(..., min_length=1, max_length=200)
    label_en: Optional[str] = Field(None, max_length=200)
    ordinal: int = Field(0, ge=0)


class DictionaryItemUpdate(BaseModel):
    key: Optional[str] = Field(None, min_length=1, max_length=80)
    label_pl: Optional[str] = Field(None, min_length=1, max_length=200)
    label_en: Optional[str] = Field(None, max_length=200)
    ordinal: Optional[int] = Field(None, ge=0)
    archived: Optional[bool] = None


class DictionarySummary(BaseModel):
    """Light response for the dictionary index page (no items)."""

    slug: str
    label_pl: str
    description: Optional[str]
    enforced: bool
    item_count: int

    model_config = {"from_attributes": True}
