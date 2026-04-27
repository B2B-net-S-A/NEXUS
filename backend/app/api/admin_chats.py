"""Admin global chat view — Feature 10.

Endpoint dla adminów: agregowany strumień wszystkich chatów (job + candidate)
across the entire system. Cel: audyt + szybki przegląd "co się działo
ostatnio" bez konieczności wchodzenia w każdy projekt z osobna.

Tylko `admin` (nie `head_of_recruitment`!) — to jest superpower do
audytu. Niech HoR przesz wnioskuje przez Job Chat tab jak wszyscy inni.
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_chat import CandidateChatMessage
from app.models.job import Job
from app.models.job_chat import JobChatMessage
from app.models.user import User

router = APIRouter()


class GlobalChatItem(BaseModel):
    chat_type: Literal["job", "candidate"]
    message_id: int
    parent_id: int  # job_id or candidate_id
    parent_label: str  # job title or candidate name
    author_id: Optional[int]
    author_name: Optional[str]
    content: str  # placeholder if deleted
    is_deleted: bool
    created_at: datetime


class GlobalChatList(BaseModel):
    items: list[GlobalChatItem]
    has_more: bool


@router.get("/global-chats", response_model=GlobalChatList)
async def global_chats(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    chat_type: Optional[Literal["job", "candidate"]] = Query(None),
    search: Optional[str] = Query(None, min_length=1, max_length=200),
) -> GlobalChatList:
    """Recent messages across ALL job + candidate chats (admin-only audit feed).

    Filtry:
      - `chat_type=job|candidate` — ogranicz do jednego typu
      - `search=foo` — FTS po treści (`plainto_tsquery('simple', q)`)
    """
    items: list[GlobalChatItem] = []

    if chat_type in (None, "job"):
        q = (
            select(
                JobChatMessage.id,
                JobChatMessage.job_id,
                JobChatMessage.author_id,
                JobChatMessage.content,
                JobChatMessage.is_deleted,
                JobChatMessage.created_at,
                Job.title,
                User.name,
            )
            .outerjoin(Job, Job.id == JobChatMessage.job_id)
            .outerjoin(User, User.id == JobChatMessage.author_id)
            .order_by(JobChatMessage.created_at.desc())
            .limit(limit + 1)
        )
        if search:
            from sqlalchemy import func as _func

            q = q.where(
                JobChatMessage.search_vector.op("@@")(
                    _func.plainto_tsquery("simple", search)
                )
            )
        for mid, jid, aid, content, is_del, ts, jtitle, aname in (
            await db.execute(q)
        ).all():
            items.append(
                GlobalChatItem(
                    chat_type="job",
                    message_id=mid,
                    parent_id=jid,
                    parent_label=jtitle or f"Job #{jid}",
                    author_id=aid,
                    author_name=aname,
                    content=("[wiadomość usunięta]" if is_del else content),
                    is_deleted=is_del,
                    created_at=ts,
                )
            )

    if chat_type in (None, "candidate"):
        q = (
            select(
                CandidateChatMessage.id,
                CandidateChatMessage.candidate_id,
                CandidateChatMessage.author_id,
                CandidateChatMessage.content,
                CandidateChatMessage.is_deleted,
                CandidateChatMessage.created_at,
                Candidate.name,
                Candidate.lastname,
                User.name,
            )
            .outerjoin(Candidate, Candidate.id == CandidateChatMessage.candidate_id)
            .outerjoin(User, User.id == CandidateChatMessage.author_id)
            .order_by(CandidateChatMessage.created_at.desc())
            .limit(limit + 1)
        )
        if search:
            from sqlalchemy import func as _func

            q = q.where(
                CandidateChatMessage.search_vector.op("@@")(
                    _func.plainto_tsquery("simple", search)
                )
            )
        for mid, cid, aid, content, is_del, ts, fn, ln, aname in (
            await db.execute(q)
        ).all():
            full_name = " ".join(filter(None, [fn, ln])) or f"Candidate #{cid}"
            items.append(
                GlobalChatItem(
                    chat_type="candidate",
                    message_id=mid,
                    parent_id=cid,
                    parent_label=full_name,
                    author_id=aid,
                    author_name=aname,
                    content=("[wiadomość usunięta]" if is_del else content),
                    is_deleted=is_del,
                    created_at=ts,
                )
            )

    # Merge by created_at desc, take limit, mark has_more
    items.sort(key=lambda x: x.created_at, reverse=True)
    has_more = len(items) > limit
    return GlobalChatList(items=items[:limit], has_more=has_more)
