from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.models.activity import Activity
from app.models.deleted_note_source import DeletedNoteSource
from app.models.note import SYSTEM_NOTE_SOURCE, Note, NoteType
from app.models.notification import NotificationType
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
from app.api.body_validation import validated_body
from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateWriteAccess,
    note_content_hidden,
)
from app.api.deps import DeliveryLeadPlus
from app.api.recruitment_access import ensure_delivery_lead_job_visible
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.services import candidate_claim, note_kinds, recommendation_card_import
from app.services.recommendation_cards import CARD_KINDS
from app.services.ai_quota import AIQuotaExceeded
from app.services.mention_dispatch import (
    build_note_context_label,
    build_note_deep_link,
    enqueue_mention_notifications,
    refresh_note_mention_snippets,
    retract_note_mention_notifications,
    send_mention_side_effects,
    trim_snippet,
)
from app.services.mention_parser import parse_mentions, parse_mentions_global

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


async def _resolve_mentions(db: AsyncSession, content: str, note: Note) -> list[int]:
    """Wybiera scope w zależności od note.job_id (najwęższy → najszerszy).

    job_id present → tylko members projektu (parse_mentions).
    inaczej → aktywni użytkownicy candidate-domain (parse_mentions_global).
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


def _mention_snippet(note: Note) -> str:
    """Fragment notatki do dzwonka o wzmiance — bez stawki do klienta.

    „Wyślijmy za 161 zł/h @osoba” trafiało w całości do powiadomienia osoby
    oznaczonej, także rekrutera, który tej stawki nie widzi.
    """
    kind = note_kinds.classify(
        note.content,
        note_type=getattr(note.note_type, "value", note.note_type),
        external_source=note.external_source,
    )
    if note_kinds.hides_client_rate(kind):
        return note_kinds.CLIENT_RATE_SNIPPET
    return trim_snippet(note.content or "")


def _plain(note: Note, viewer: User) -> NoteResponse:
    """Odpowiedź bez pól listy — z zakrytą treścią, gdy rola jej nie widzi."""
    response = NoteResponse.model_validate(note)
    if note_content_hidden(viewer, kind=note.kind, author_id=note.author_id):
        response.content = note_kinds.CLIENT_RATE_PLACEHOLDER
        response.content_hidden = True
    return response


def _enriched(
    note: Note,
    *,
    viewer: User,
    author_name: Optional[str],
    job_title: Optional[str],
    pinned_by_name: Optional[str],
    mention_label_map: dict,
) -> EnrichedNoteResponse:
    hidden = note_content_hidden(viewer, kind=note.kind, author_id=note.author_id)
    content = note_kinds.CLIENT_RATE_PLACEHOLDER if hidden else note.content
    return EnrichedNoteResponse(
        id=note.id,
        content=content,
        kind=note.kind,
        content_hidden=hidden,
        note_type=note.note_type,
        candidate_id=note.candidate_id,
        job_id=note.job_id,
        author_id=note.author_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        parent_note_id=note.parent_note_id,
        pinned_at=note.pinned_at,
        author_name=author_name,
        author_email=None,  # P0.6 — do not leak author email to note readers
        content_rendered=render_traffit_mentions(content, mention_label_map),
        job_title=job_title,
        external_source=note.external_source,
        is_system=note.external_source == SYSTEM_NOTE_SOURCE,
        group=note_kinds.group_of(note.kind, note.external_source),
        pinned_by_name=pinned_by_name,
    )


def _enriched_select():
    pinner = aliased(User)
    return (
        select(
            Note,
            User.name.label("author_name"),
            Job.title.label("job_title"),
            pinner.name.label("pinned_by_name"),
        )
        .outerjoin(User, Note.author_id == User.id)
        .outerjoin(Job, Note.job_id == Job.id)
        .outerjoin(pinner, Note.pinned_by == pinner.id)
    )


@router.get("", response_model=EnrichedNoteList)
async def list_notes(
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    # Runda 10 (R10-N6-7): `0` przechodziło sprawdzenie P0.6 (`is None`), ale
    # filtr `if candidate_id:` go pomijał — lista całej firmy. R10-N6-6: typ
    # spoza enuma dawał 500 z Postgresa zamiast 422.
    candidate_id: Optional[int] = Query(None, ge=1),
    job_id: Optional[int] = Query(None, ge=1),
    note_type: Optional[NoteType] = None,
    unattached: bool = False,
    pinned_only: bool = False,
    limit: int = Query(1000, ge=1, le=2000),
):
    """Notatki jednego kandydata/oferty (albo jednej kategorii `note_type`).

    Dedykowane źródło dla zakładki Notatki: feed `/timeline` miesza notatki z
    etapami/aktywnościami i ucina, przez co przy bogatej historii (import
    Traffit) starsze notatki wypadały z widoku. Tu zwracamy komplet dla danego
    zakresu, wzbogacony o `author_name` i `content_rendered`.

    0399 (29.09.2026): lista zwraca wyłącznie notatki GŁÓWNE, przypięte
    pierwsze; odpowiedzi jadą zagnieżdżone w `replies` i nie liczą się do
    `total`. `pinned_only` = same przypięte (dok osoby w rekrutacji pokazuje
    przypięte notatki kandydata niezależnie od rekrutacji).

    P0.6: wcześniej brak filtra zwracał WSZYSTKIE notatki firmy (globalna
    enumeracja treści PII) bez limitu, a odpowiedź ujawniała e-mail autora.
    Teraz wymagany jest zawężający filtr (subject albo `note_type`), zakres jest
    ograniczony, a e-mail autora nie jest zwracany (bezpieczna tożsamość =
    `author_name`). Rola i tak jest gated przez `CandidatePIIAccess`
    (viewer wykluczony).
    """
    if candidate_id is None and job_id is None and note_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wymagany filtr: candidate_id, job_id albo note_type",
        )

    filters = [Note.parent_note_id.is_(None)]
    if candidate_id is not None:
        filters.append(Note.candidate_id == candidate_id)
    if job_id is not None:
        filters.append(Note.job_id == job_id)
    if note_type is not None:
        filters.append(Note.note_type == note_type)
    if pinned_only:
        filters.append(Note.pinned_at.is_not(None))
    if unattached:
        # Panel „Meetingi bez powiązania” w Źródłach AI Championa: wyłącznie
        # notatki bez rekrutacji I bez kandydata (spotkania z klientem/DL
        # z Fireflies). Bez tego filtra lista niosła notatki spotkań
        # kandydatów innych klientów (import Traffita, surowy HTML) z przyciskiem
        # „Powiąż + AI” na cudzej rekrutacji — UAT M03-B13 / M04-B04.
        filters.extend([Note.job_id.is_(None), Note.candidate_id.is_(None)])
    query = (
        _enriched_select()
        .where(*filters)
        .order_by(
            Note.pinned_at.is_(None),
            Note.pinned_at.desc(),
            Note.created_at.desc(),
            Note.id.desc(),
        )
        .limit(limit)
    )
    rows = (await db.execute(query)).all()

    # Liczniki zakładek Historii: cały zakres zapytania, nie tylko `limit`.
    group_counts = {group: 0 for group in note_kinds.NOTE_GROUPS}
    for kind, source, count in (
        await db.execute(
            select(Note.kind, Note.external_source, func.count())
            .where(*filters)
            .group_by(Note.kind, Note.external_source)
        )
    ).all():
        group_counts[note_kinds.group_of(kind, source)] += count

    reply_rows: list = []
    parent_ids = [note.id for note, *_ in rows]
    if parent_ids:
        reply_rows = (
            await db.execute(
                _enriched_select()
                .where(Note.parent_note_id.in_(parent_ids))
                .order_by(Note.created_at.asc(), Note.id.asc())
            )
        ).all()

    mention_label_map = await build_traffit_user_label_map(
        db,
        collect_traffit_user_ids(note.content for note, *_ in [*rows, *reply_rows]),
    )
    replies_by_parent: dict[int, list[EnrichedNoteResponse]] = {}
    for note, author_name, job_title, pinned_by_name in reply_rows:
        replies_by_parent.setdefault(note.parent_note_id, []).append(
            _enriched(
                note,
                viewer=current_user,
                author_name=author_name,
                job_title=job_title,
                pinned_by_name=pinned_by_name,
                mention_label_map=mention_label_map,
            )
        )
    items = []
    for note, author_name, job_title, pinned_by_name in rows:
        item = _enriched(
            note,
            viewer=current_user,
            author_name=author_name,
            job_title=job_title,
            pinned_by_name=pinned_by_name,
            mention_label_map=mention_label_map,
        )
        item.replies = replies_by_parent.get(note.id, [])
        items.append(item)
    return EnrichedNoteList(items=items, total=len(items), group_counts=group_counts)


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreate,
    current_user: CandidateWriteAccess,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Runda 10 (R10-N6-8): nieistniejący kandydat albo rekrutacja kończyły się
    # IntegrityError (FK) przy flush, czyli 500.
    if (
        data.candidate_id is not None
        and await db.get(Candidate, data.candidate_id) is None
    ):
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    parent: Optional[Note] = None
    if data.parent_note_id is not None:
        parent = await db.get(Note, data.parent_note_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Notatka nie istnieje.")
        if parent.parent_note_id is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Na odpowiedź nie można odpowiedzieć — odpowiedz na notatkę główną."
                ),
            )
    elif data.job_id is not None and await db.get(Job, data.job_id) is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")

    values = data.model_dump()
    if parent is not None:
        # Odpowiedź należy do wątku notatki głównej — kandydata i rekrutację
        # bierze z niej serwer; klient ich nie zmieni. Kontraktu NIGDY nie
        # dziedziczy: notatki kontraktu pisze Delivery Lead w zakresie klienta
        # (`POST /api/contracts/{id}/notes`, F03), a ta trasa wymaga tylko
        # zapisu kandydata — odpowiedź zostaje na poziomie kandydata.
        values["candidate_id"] = parent.candidate_id
        values["job_id"] = parent.job_id
        values["contract_id"] = None
        # Odpowiedź nie ma własnego rodzaju podanego wprost.
        values["kind"] = None
    if candidate_claim.is_integration_request(request):
        # 0412: notatka zapisana tokenem integracji (scraper ogłoszeń) jest
        # wpisem automatu — do 03.10.2026 scraper dopisywał ~250 takich
        # dziennie jako zwykłe notatki.
        values["external_source"] = SYSTEM_NOTE_SOURCE
        values["kind"] = None
    note = Note(**values, author_id=current_user.id)
    db.add(note)
    await db.flush()  # need note.id

    # @mentions — wybiera scope, filtruje self, insert NoteMention rows.
    mentioned_ids = await _resolve_mentions(db, note.content, note)
    mentioned_ids = [uid for uid in mentioned_ids if uid != current_user.id]
    for uid in mentioned_ids:
        db.add(NoteMention(note_id=note.id, user_id=uid))

    # Enqueue Notifications (in-transaction). Side-effects (email/WS) po commit.
    snippet = _mention_snippet(note)
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

    # 0399: autor notatki głównej dowiaduje się o odpowiedzi (chyba że to on
    # sam odpowiada albo już dostał wzmiankę w tej odpowiedzi).
    reply_pairs: list = []
    reply_title = ""
    reply_link = ""
    if (
        parent is not None
        and parent.author_id is not None
        and parent.author_id != current_user.id
        and parent.author_id not in mentioned_ids
    ):
        reply_title = (
            f"{current_user.name or current_user.email} odpowiedział(a) "
            "na Twoją notatkę"
        )
        reply_link = build_note_deep_link(parent)
        reply_pairs = await enqueue_mention_notifications(
            db,
            mentioned_user_ids=[parent.author_id],
            author=current_user,
            deep_link_path=reply_link,
            snippet=snippet,
            notification_title=reply_title,
            related_entity_type="note",
            related_entity_id=note.id,
            notification_type=NotificationType.note_reply,
        )

    # Update candidate notes_count — odpowiedź nie jest osobną notatką.
    if note.candidate_id and parent is None:
        result = await db.execute(
            select(Candidate).where(Candidate.id == note.candidate_id)
        )
        candidate = result.scalar_one_or_none()
        if candidate:
            candidate.notes_count = (candidate.notes_count or 0) + 1

    # Track activity for leaderboard
    entity_id = note.candidate_id or note.job_id or note.id
    entity_type = (
        "candidate" if note.candidate_id else ("job" if note.job_id else "note")
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
                "reply_to": parent.id if parent is not None else None,
            },
        )
    )

    # 0413: notatka-karta zapisana w NEXUSIE wypełnia kartę rekomendacji od
    # razu (import w tle łapie resztę). Nigdy nie cofa notatki.
    if note.kind in CARD_KINDS and note.parent_note_id is None:
        await recommendation_card_import.refresh_candidate_safely(
            db, candidate_id=note.candidate_id, job_id=note.job_id
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
    if reply_pairs:
        await send_mention_side_effects(
            reply_pairs,
            author_name=current_user.name or current_user.email,
            snippet=snippet,
            deep_link_path=reply_link,
            context_label=context_label,
            notification_title=reply_title,
            notification_type=NotificationType.note_reply,
            send_email=False,
        )

    await db.refresh(note)
    return note


async def _set_pinned(
    db: AsyncSession, note_id: int, current_user: User, *, pinned: bool
) -> NoteResponse:
    note = await db.scalar(select(Note).where(Note.id == note_id).with_for_update())
    if note is None:
        raise HTTPException(status_code=404, detail="Notatka nie istnieje.")
    if note.parent_note_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Odpowiedzi nie da się przypiąć — przypnij notatkę główną.",
        )
    if (note.pinned_at is not None) == pinned:
        return _plain(note, current_user)
    note.pinned_at = datetime.now(timezone.utc) if pinned else None
    note.pinned_by = current_user.id if pinned else None
    db.add(
        Activity(
            entity_type="note",
            entity_id=note.id,
            action="note_pinned" if pinned else "note_unpinned",
            details={"candidate_id": note.candidate_id, "job_id": note.job_id},
            user_id=current_user.id,
        )
    )
    await db.commit()
    await db.refresh(note)
    return _plain(note, current_user)


@router.post("/{note_id}/pin", response_model=NoteResponse)
async def pin_note(
    note_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Przypnij notatkę — wspólnie dla całego zespołu (0399).

    Ta sama bramka co dodanie notatki: kto może pisać notatki o kandydacie,
    może też przypiąć ważną (np. „nie dzwonić przed 10”). Idempotentne.
    """
    return await _set_pinned(db, note_id, current_user, pinned=True)


@router.delete("/{note_id}/pin", response_model=NoteResponse)
async def unpin_note(
    note_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Odepnij notatkę (każdy z prawem zapisu notatek; idempotentne)."""
    return await _set_pinned(db, note_id, current_user, pinned=False)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return _plain(note, current_user)


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int,
    data: NoteUpdate,
    current_user: CandidateWriteAccess,
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
    snippet = _mention_snippet(note)
    deep_link = build_note_deep_link(note)
    context_label = await build_note_context_label(db, note)
    notification_title = (
        f"{current_user.name or current_user.email} oznaczył(a) Cię w notatce"
    )
    if "content" in data.model_fields_set:
        # Runda 10 (R10-N6-3): wzmianka w dzwonku niosła pierwotny fragment.
        await refresh_note_mention_snippets(db, note.id, snippet)
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

    # 0413: zmiana treści przelicza karty rekomendacji kandydata (notatka
    # mogła przestać być kartą albo zmienić wartości pól).
    await db.flush()
    await recommendation_card_import.refresh_candidate_safely(
        db, candidate_id=note.candidate_id, job_id=note.job_id
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
    note_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if not _can_modify_note(current_user, note):
        raise HTTPException(
            status_code=403, detail="Brak uprawnień do usunięcia tej notatki"
        )
    await _tombstone_traffit_source(db, note)
    # 0399: odpowiedzi znikają razem z notatką główną (CASCADE), więc ich
    # dzwonki (`note_reply`, wzmianki) też nie mogą dalej nieść treści.
    reply_ids = (
        await db.scalars(select(Note.id).where(Note.parent_note_id == note.id))
    ).all()
    for retracted_id in (note.id, *reply_ids):
        await retract_note_mention_notifications(db, retracted_id)
    candidate_id = note.candidate_id
    await db.delete(note)
    await db.flush()
    if candidate_id is not None:
        await _forget_note_facts(db, candidate_id, actor_id=current_user.id)
        # 0413: pola karty rekomendacji z usuniętej notatki znikają razem z nią.
        await recommendation_card_import.refresh_candidate_safely(
            db, candidate_id=candidate_id
        )


_TRAFFIT_NOTE_ACTIONS = (
    "traffit:Notatka",
    "traffit:Email",
    "traffit:Reply",
    "traffit:Rozmowa telefoniczna",
    "traffit:Spotkanie",
)


async def _tombstone_traffit_source(db: AsyncSession, note: Note) -> None:
    """Runda 10 (R10-N6-1): usunięta notatka z Traffita nie wraca z syncem.

    Promocja aktywności (``_PROMOTE_NOTES_SQL``) deduplikowała wyłącznie po
    ISTNIEJĄCEJ notatce, więc pełny bieg zakładał usuniętą od nowa. Notatki
    z migracji 0077 nie mają ``source_ref`` — promocja dopasowuje je po
    (kandydat, ``created_at``), więc nagrobek dostaje każda aktywność z tym
    samym znacznikiem czasu (żadna z nich nie była promowana obok 0077).
    """
    refs: set[str] = set()
    source_ref = note.source_ref or ""
    if source_ref.startswith("traffit:activity:"):
        refs.add(source_ref)
    elif not source_ref and note.candidate_id is not None and note.created_at:
        rows = await db.execute(
            text(
                "SELECT 'traffit:activity:' || external_id FROM activities "
                "WHERE external_source = 'traffit' AND entity_type = 'candidate' "
                "AND entity_id = :cid AND created_at = :at "
                "AND external_id IS NOT NULL "
                "AND action = ANY(CAST(:actions AS text[]))"
            ),
            {
                "cid": note.candidate_id,
                "at": note.created_at,
                "actions": list(_TRAFFIT_NOTE_ACTIONS),
            },
        )
        refs.update(ref for (ref,) in rows.all())
    for ref in sorted(refs):
        await db.execute(
            pg_insert(DeletedNoteSource)
            .values(source_ref=ref)
            .on_conflict_do_nothing(index_elements=["source_ref"])
        )


async def _forget_note_facts(
    db: AsyncSession, candidate_id: int, *, actor_id: int
) -> None:
    """Runda 10 (R10-N6-2): fakty z usuniętej notatki nie zostają na profilu.

    Są jeszcze notatki → znacznik zmiany, nocna ekstrakcja policzy fakty od
    nowa. Nie ma żadnej → fakty z notatek i stawka wpisana przez notatki
    znikają od razu (kandydat bez notatek nie trafia już do selekcji).
    """
    from app.services.candidate_notes_facts import (
        clear_notes_facts,
        mark_notes_changed,
    )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return
    remaining = await db.scalar(
        select(func.count(Note.id)).where(Note.candidate_id == candidate_id)
    )
    if remaining:
        mark_notes_changed(candidate, now_iso=datetime.now(timezone.utc).isoformat())
        return
    rate_audit = clear_notes_facts(candidate)
    if rate_audit is None:
        return
    from app.services import candidate_audit
    from app.services.match_score_cache import mark_stale_for_candidate

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.PROFILE_RATE_CHANGED,
        user_id=actor_id,
        entity_id=candidate_id,
        details=rate_audit,
    )
    await mark_stale_for_candidate(db, candidate_id)


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

    body = validated_body(LinkNoteJobPayload, payload or {})

    note = await db.scalar(select(Note).where(Note.id == note_id))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    job = await db.scalar(select(Job).where(Job.id == body.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # `job_id` arrives in the BODY, not the path — which is why a route-level
    # scope guard was never applied here, and why an audit that walks path
    # parameters would not have found it either. Without this, a Delivery Lead
    # could attach a note to ANY client's job and, worse, trigger a paid LLM
    # enrichment that writes a Champion draft onto it.
    await ensure_delivery_lead_job_visible(job, current_user, db)

    from app.services.note_job_link import ensure_note_linkable_to_job

    await ensure_note_linkable_to_job(db, note, body.job_id)

    # Kwota jest obciążana WYŁĄCZNIE w `enrich_from_meeting` (`async with
    # ai_feature(...)`), który pokrywa każdy punkt wejścia. Wcześniejsze
    # obciążenie na poziomie trasy pochodziło sprzed tamtej bramki i nigdy nie
    # zostało zdjęte: gołe `check_and_increment` nie ustawia kontekstu wywołania,
    # więc serwis nie widział go jako zagnieżdżonego i naliczał `champion_draft`
    # DRUGI raz na jedno kliknięcie.
    note.job_id = body.job_id
    await db.commit()
    await db.refresh(note)

    # Enrichment uses the full note.content — which already contains the
    # summary and transcript as formatted by fireflies_sync.py.
    title_line = (
        note.content.split("\n", 1)[0].lstrip("# ").strip() if note.content else ""
    )
    # Powiązanie notatki z rekrutacją jest już zapisane i AI do niego nie jest
    # potrzebne — wyłączenie AI nie może cofać operacji na danych. Blokada kwoty
    # dotyczy wyłącznie wzbogacenia i wychodzi jako 503 z tym samym słownikiem
    # `detail`, co bliźniacze handlery (front ma na to gotową gałąź). Bez tego
    # `AIQuotaExceeded` uciekało tędy jako 500: to jedyne miejsce wywołania kwoty
    # w `app/api` bez własnego `except`, a aplikacja nie rejestruje dla niego
    # handlera globalnego.
    try:
        suggestion = await enrich_from_meeting(
            db,
            job_id=body.job_id,
            meeting_title=title_line or f"Meeting #{note.id}",
            meeting_summary="",
            meeting_transcript=note.content or "",
            source_ref=f"note:{note.id}",
            user_id=current_user.id,
        )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc
    out = ChampionProfileSuggestionOut.model_validate(suggestion)
    out.patches = patches_from_payload(suggestion.payload or {})
    return {"note_id": note.id, "job_id": body.job_id, "suggestion": out}
