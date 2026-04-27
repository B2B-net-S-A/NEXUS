"""Pydantic schemas dla Candidate Chat."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.job_chat import ChatUserMini


class CandidateChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    reply_to_message_id: Optional[int] = None


class CandidateChatMessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class ReactionAggregate(BaseModel):
    """Agregacja reakcji per emoji."""

    emoji: str
    count: int
    user_ids: list[int]


class ReadByUser(BaseModel):
    """Element listy 'kto przeczytał'."""

    user_id: int
    name: str
    read_at: datetime


class CandidateChatMessageResponse(BaseModel):
    id: int
    candidate_id: int
    content: str
    author: Optional[ChatUserMini]
    reply_to_message_id: Optional[int]
    reply_to_preview: Optional[str]
    is_edited: bool
    edited_at: Optional[datetime]
    is_deleted: bool
    pinned: bool
    pinned_at: Optional[datetime]
    pinned_by: Optional[int]
    mentions: list[int] = []
    reactions: list[ReactionAggregate] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CandidateChatMessageList(BaseModel):
    items: list[CandidateChatMessageResponse]
    has_more: bool
    next_before_id: Optional[int]


class CandidateChatUnreadCount(BaseModel):
    candidate_id: int
    unread_count: int
    last_read_message_id: Optional[int]


class CandidateChatPinResponse(BaseModel):
    message_id: int
    pinned: bool


class ReactionToggleResponse(BaseModel):
    """Odpowiedź na POST/DELETE reakcji — pełny stan reakcji wiadomości."""

    message_id: int
    reactions: list[ReactionAggregate]
