"""Pydantic schemas dla Job Chat (per-recruitment internal team chat)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatUserMini(BaseModel):
    """Minimalna karta użytkownika dla autora wiadomości / pinnera / mention'a."""

    id: int
    name: str
    email: str
    role: str

    model_config = {"from_attributes": True}


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    reply_to_message_id: Optional[int] = None


class ChatMessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class ReactionAggregate(BaseModel):
    """Agregacja reakcji per emoji — używana przez Job + Candidate chat."""

    emoji: str
    count: int
    user_ids: list[int]


class ChatMessageResponse(BaseModel):
    id: int
    job_id: int
    content: str  # gdy is_deleted=True → "[wiadomość usunięta]"
    author: Optional[ChatUserMini]
    reply_to_message_id: Optional[int]
    reply_to_preview: Optional[str]  # skrócony content cytowanej wiadomości
    is_edited: bool
    edited_at: Optional[datetime]
    is_deleted: bool
    pinned: bool
    pinned_at: Optional[datetime]
    pinned_by: Optional[int]
    mentions: list[int] = []  # user_ids
    reactions: list[ReactionAggregate] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReactionToggleResponse(BaseModel):
    """Odpowiedź na POST/DELETE reakcji — pełny stan reakcji wiadomości."""

    message_id: int
    reactions: list[ReactionAggregate]


class ReadByUser(BaseModel):
    """Element listy 'kto przeczytał' — derived z JobChatReadState."""

    user_id: int
    name: str
    read_at: datetime


class ChatMessageList(BaseModel):
    """Paginacja w stronę 'starsze' (scrollback): items zawsze DESC po created_at.

    `next_before_id` = id najstarszej w batchu → kolejny page request to
    `?before_id=next_before_id`.
    """

    items: list[ChatMessageResponse]
    has_more: bool
    next_before_id: Optional[int]


class ChatUnreadCount(BaseModel):
    job_id: int
    unread_count: int
    last_read_message_id: Optional[int]


class ChatPinResponse(BaseModel):
    """Zwracane przy POST/DELETE /pin — frontend invaliduje query."""

    message_id: int
    pinned: bool
