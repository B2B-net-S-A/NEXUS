from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.note import Note
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note_mention import NoteMention
from app.models.user import User, UserRole
from app.models.user_activity import UserActivity, UserActionType
from app.schemas.note import (
    EnrichedNoteList,
    EnrichedNoteResponse,
    NoteCreate,
    NoteResponse,
    NoteUpdate,
)
from app.services.note_mention_render import (
    build_traffit_user_label_map,
    collect_traffit_user_ids,
    render_traffit_mentions,
)
from app.api.deps import CurrentUser, DeliveryLeadPlus
from app.services.mention_dispatch import (
    build_note_context_label,
    build_note_deep_link,
    enqueue_mention_notifications,
    send_mention_side_effects,
    trim_snippet,
)
from app.services.mention_parser import parse_mentions, parse_mentions_global

router = APIRouter()


async def _resolve_mentions(db: AsyncSession, content: str, note: Note) -> list[int]:
    """Wybiera scope w zależności od note.job_id (najwęższy → najszerszy).

    job_id present → tylko members projektu (parse_mentions).
    inaczej → każdy aktywny user firmy (parse_mentions_global).
    """
    if not content:
        return []
    if note.job_id:
        return await parse_mentions(db, content, note.job_id)
    return await parse_mentions_global(db, content)


def _can_modify_note(user: User, note: Note) -> bool:
    """Kto może edytować/usuwać notatkę: jej autor albo admin (moderacja).

    Świadomie wąsko — notatki to ślad odpowiedzialności w ATS, więc cudzych
    domyślnie nie ruszamy. Admin ma override do porządkowania (np. usunięcie
    notatek testowych). Zgodne z UI w CandidateDetailV2 (canModifyNote).
    """
    return note.author_id == user.id or user.has_any_role(UserRole.admin)


@router.get("", response_model=EnrichedNoteList)
async def list_notes(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    candidate_id: Optional[int] = None,
    job_id: Optional[int] = None,
):
    """Wszystkie notatki kandydata/oferty — bez obcinania.

    Świadomie dedykowane źródło dla zakładki Notatki: feed `/timeline` miesza
    notatki z etapami/aktywnościami i ucina do `limit`, przez co przy bogatej
    historii (np. import Traffit) starsze notatki wypadały z widoku. Tu zwracamy
    komplet, wzbogacony o `author_name` (User outerjoin) i `content_rendered`
    (rozwinięte `$$user_NN$$` Traffit mention tokeny — jak w `/timeline`).
    """
    query = (
        select(
            Note,
            User.name.label("author_name"),
            User.email.label("author_email"),
            Job.title.label("job_title"),
        )
        .outerjoin(User, Note.author_id == User.id)
        .outerjoin(Job, Note.job_id == Job.id)
    )
    if candidate_id:
        query = query.where(Note.candidate_id == candidate_id)
    if job_id:
        query = query.where(Note.job_id == job_id)
    query = query.order_by(Note.created_at.desc())
    rows = (await db.execute(query)).all()

    mention_label_map = await build_traffit_user_label_map(
        db, collect_traffit_user_ids(note.content for note, *_ in rows)
    )
    items = [
        EnrichedNoteResponse(
            id=note.id,
            content=note.content,
            note_type=note.note_type,
            candidate_id=note.candidate_id,
            job_id=note.job_id,
            author_id=note.author_id,
            created_at=note.created_at,
            updated_at=note.updated_at,
            author_name=author_name,
            author_email=author_email,
            content_rendered=render_traffit_mentions(note.content, mention_label_map),
            job_title=job_title,
        )
        for note, author_name, author_email, job_title in rows
    ]
    return EnrichedNoteList(items=items, total=len(items))


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    note = Note(**data.model_dump(), author_id=current_user.id)
    db.add(note)
    await db.flush()  # need note.id

    # @mentions — wybiera scope, filtruje self, insert NoteMention rows.
    mentioned_ids = await _resolve_mentions(db, note.content, note)
    mentioned_ids = [uid for uid in mentioned_ids if uid != current_user.id]
    for uid in mentioned_ids:
        db.add(NoteMention(note_id=note.id, user_id=uid))

    # Enqueue Notifications (in-transaction). Side-effects (email/WS) po commit.
    snippet = trim_snippet(note.content or "")
    deep_link = build_note_deep_link(note)
    context_label = await build_note_context_label(db, note)
    notification_title = (
        f"{current_user.name or current_user.email} oznaczył(a) Cię w notatce"
    )
    pairs = await enqueue_mention_notifications(
        db,
        mentioned_user_ids=mentioned_ids,
        author=current_user,
        deep_link_path=deep_link,
        snippet=snippet,
        notification_title=notification_title,
        related_entity_type="note",
        related_entity_id=note.id,
    )

    # Update candidate notes_count
    if data.candidate_id:
        result = await db.execute(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        candidate = result.scalar_one_or_none()
        if candidate:
            candidate.notes_count = (candidate.notes_count or 0) + 1

    # Track activity for leaderboard
    entity_id = data.candidate_id or data.job_id or note.id
    entity_type = (
        "candidate" if data.candidate_id else ("job" if data.job_id else "note")
    )
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.note_added,
            entity_type=entity_type,
            entity_id=entity_id,
            details={
                "note_id": note.id,
                "note_type": data.note_type.value if data.note_type else None,
                "mentioned_count": len(mentioned_ids),
            },
        )
    )

    # Explicit commit — Notification rows muszą być trwałe ZANIM odpalimy email/WS.
    await db.commit()

    # Best-effort side-effects po commicie. Nie blokują response gdy SMTP fail.
    if pairs:
        await send_mention_side_effects(
            pairs,
            author_name=current_user.name or current_user.email,
            snippet=snippet,
            deep_link_path=deep_link,
            context_label=context_label,
            notification_title=notification_title,
        )

    await db.refresh(note)
    return note


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int,
    data: NoteUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if not _can_modify_note(current_user, note):
        raise HTTPException(
            status_code=403, detail="Brak uprawnień do edycji tej notatki"
        )

    # Załaduj stare mentions (do diffu).
    old_rows = await db.execute(
        select(NoteMention.user_id).where(NoteMention.note_id == note.id)
    )
    old_ids = {uid for (uid,) in old_rows.all()}

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(note, k, v)

    # Po apply contentu — re-parse mentions na nowej treści.
    new_ids_list = await _resolve_mentions(db, note.content or "", note)
    new_ids = {uid for uid in new_ids_list if uid != current_user.id}

    to_add = sorted(new_ids - old_ids)
    to_remove = old_ids - new_ids

    if to_remove:
        await db.execute(
            NoteMention.__table__.delete().where(
                NoteMention.note_id == note.id,
                NoteMention.user_id.in_(to_remove),
            )
        )
    for uid in to_add:
        db.add(NoteMention(note_id=note.id, user_id=uid))

    pairs: list = []
    snippet = trim_snippet(note.content or "")
    deep_link = build_note_deep_link(note)
    context_label = await build_note_context_label(db, note)
    notification_title = (
        f"{current_user.name or current_user.email} oznaczył(a) Cię w notatce"
    )
    if to_add:
        pairs = await enqueue_mention_notifications(
            db,
            mentioned_user_ids=to_add,
            author=current_user,
            deep_link_path=deep_link,
            snippet=snippet,
            notification_title=notification_title,
            related_entity_type="note",
            related_entity_id=note.id,
        )

    await db.commit()

    if pairs:
        await send_mention_side_effects(
            pairs,
            author_name=current_user.name or current_user.email,
            snippet=snippet,
            deep_link_path=deep_link,
            context_label=context_label,
            notification_title=notification_title,
        )

    await db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if not _can_modify_note(current_user, note):
        raise HTTPException(
            status_code=403, detail="Brak uprawnień do usunięcia tej notatki"
        )
    await db.delete(note)


@router.post("/{note_id}/link-job")
async def link_note_to_job(
    note_id: int,
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Manually attach a Fireflies (or other) meeting Note to a Job and
    trigger LLM enrichment of the Job's Champion Profile.

    Used from the "Sugerowane meetingi" / "Wszystkie meetingi bez powiązania"
    panels on the Job detail view (Phase 14).
    """
    from app.models.job import Job
    from app.schemas.champion_suggestion import (
        ChampionProfileSuggestionOut,
        LinkNoteJobPayload,
        patches_from_payload,
    )
    from app.services.champion_draft_service import enrich_from_meeting

    body = LinkNoteJobPayload.model_validate(payload or {})

    note = await db.scalar(select(Note).where(Note.id == note_id))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    job = await db.scalar(select(Job).where(Job.id == body.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    note.job_id = body.job_id
    await db.commit()
    await db.refresh(note)

    # Enrichment uses the full note.content — which already contains the
    # summary and transcript as formatted by fireflies_sync.py.
    title_line = (
        note.content.split("\n", 1)[0].lstrip("# ").strip() if note.content else ""
    )
    suggestion = await enrich_from_meeting(
        db,
        job_id=body.job_id,
        meeting_title=title_line or f"Meeting #{note.id}",
        meeting_summary="",
        meeting_transcript=note.content or "",
        source_ref=f"note:{note.id}",
        user_id=current_user.id,
    )
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return {"note_id": note.id, "job_id": body.job_id, "suggestion": out}
