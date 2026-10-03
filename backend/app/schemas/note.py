from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.note import NoteType


class NoteCreate(BaseModel):
    content: str
    note_type: NoteType = NoteType.general
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    # 0399: odpowiedź na notatkę. Kandydata i rekrutację bierze serwer
    # z notatki głównej — wartości z żądania są wtedy ignorowane.
    parent_note_id: Optional[int] = Field(default=None, ge=1)


class NoteUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1)
    note_type: Optional[NoteType] = None

    # Runda 10 (R10-N6-5): pole pominięte = bez zmian, ale jawne `null` szło
    # przez `exclude_unset` do kolumn NOT NULL i kończyło się 500 przy commicie.
    @field_validator("content", "note_type", mode="before")
    @classmethod
    def _reject_null(cls, value):
        if value is None:
            raise ValueError("Pole nie może być puste (null).")
        return value


class NoteResponse(BaseModel):
    id: int
    content: str
    note_type: NoteType
    candidate_id: Optional[int]
    job_id: Optional[int]
    author_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    parent_note_id: Optional[int] = None
    pinned_at: Optional[datetime] = None
    # 0412: rodzaj notatki (`services/note_kinds.py`); `content_hidden` = rola
    # nie widzi treści (stawka do klienta) i `content` niesie zdanie zastępcze.
    kind: Optional[str] = None
    content_hidden: bool = False

    model_config = {"from_attributes": True}


class NoteList(BaseModel):
    items: list[NoteResponse]
    total: int


class EnrichedNoteResponse(NoteResponse):
    """Note + denormalized display fields for the Notatki tab.

    `author_name`/`author_email` come from a User outerjoin (NULL for legacy
    Traffit imports). `content_rendered` resolves `$$user_NN$$` Traffit mention
    tokens to "@Imię Nazwisko"; raw `content` stays intact for editing.
    `job_title` shows which recruitment a note is pinned to (NULL = general).
    """

    author_name: Optional[str] = None
    author_email: Optional[str] = None
    content_rendered: Optional[str] = None
    job_title: Optional[str] = None
    # 0399: `external_source` = pochodzenie (traffit, system, trainee_call…);
    # `is_system` = wpis automatu, domyślnie schowany za „Pokaż systemowe”.
    external_source: Optional[str] = None
    is_system: bool = False
    pinned_by_name: Optional[str] = None
    # Odpowiedzi (jeden poziom, od najstarszej). Lista notatek NIE liczy ich
    # jako osobnych notatek; odpowiedź zawsze ma tu pustą listę.
    replies: list["EnrichedNoteResponse"] = Field(default_factory=list)


class EnrichedNoteList(BaseModel):
    items: list[EnrichedNoteResponse]
    # Liczba notatek głównych (bez odpowiedzi).
    total: int


EnrichedNoteResponse.model_rebuild()
