"""Email thread endpoints used by the candidate-detail UI.

GET  /api/candidates/{id}/emails          → list conversations (grouped)
GET  /api/candidates/{id}/emails/thread/{conv_id} → all messages in a thread
GET  /api/emails/{id}                     → full email w/ attachments
GET  /api/emails/{id}/attachments/{aid}/download → binary
POST /api/candidates/{id}/emails/compose  → new email in candidate context
POST /api/candidates/{id}/emails/reply    → reply to an existing email
POST /api/microsoft365/emails/bulk        → bulk action on selected emails (Phase 5.1)
"""

# NOTE: keep annotations eager in this module. ``search_emails`` is wrapped by
# slowapi's limiter and FastAPI resolves the wrapper signature from slowapi's
# globals. With postponed annotations, ``CandidatePIIAccess`` remains an
# unresolved ForwardRef there, is misclassified as a query parameter and both
# ``/openapi.json`` and authenticated email search fail. Python 3.12 supports
# every annotation used below without the future import.

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess, CandidateWriteAccess
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.m365 import (
    Email,
    EmailAttachment,
    EmailDirection,
    EmailMatchMethod,
    M365Connection,
)
from app.services.m365 import sender as m365_sender
from app.services.m365.attachment_handler import STORAGE_ROOT
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    is_inline: bool

    model_config = ConfigDict(from_attributes=True)


class EmailOut(BaseModel):
    id: int
    m365_message_id: str
    m365_conversation_id: str
    subject: Optional[str]
    from_address: str
    from_name: Optional[str]
    to_addresses: list[dict] = []
    cc_addresses: list[dict] = []
    body_html: Optional[str]
    body_text: Optional[str]
    body_preview: Optional[str]
    sent_at: Optional[datetime]
    received_at: datetime
    direction: str
    has_attachments: bool
    is_read: bool
    is_archived: bool
    is_private_filtered: bool
    match_method: str
    match_confidence: Optional[float]
    candidate_id: Optional[int] = None
    # INT-04: stan wysyłki z NEXUSA (pending/sent/uncertain; None = wiersz
    # z synchronizacji albo sprzed zmiany).
    send_state: Optional[str] = None
    attachments: list[AttachmentOut] = []

    model_config = ConfigDict(from_attributes=True)


class ThreadPreview(BaseModel):
    conversation_id: str
    subject: Optional[str]
    latest: EmailOut
    message_count: int
    unread_count: int


class ThreadListResponse(BaseModel):
    """Strona wątków kandydata. ``total`` = wszystkie widoczne wątki, żeby UI
    mogło napisać „Pokazano X z Y" i zaproponować „Pokaż więcej" zamiast
    urywać historię na pierwszej stronie."""

    items: list[ThreadPreview]
    total: int
    limit: int
    offset: int


class EmailSearchHit(BaseModel):
    """Single hit on the FTS endpoint.

    Slimmer than ``EmailOut`` — body_html is excluded (caller fetches it via
    GET /emails/{id} when opening the thread) and ``snippet`` is added with
    ``<mark>...</mark>`` highlighted around match terms.
    """

    id: int
    m365_conversation_id: str
    candidate_id: Optional[int]
    subject: Optional[str]
    from_address: str
    from_name: Optional[str]
    received_at: datetime
    has_attachments: bool
    is_read: bool
    snippet: Optional[str]


class EmailSearchResponse(BaseModel):
    items: list[EmailSearchHit]
    total: int
    limit: int
    offset: int


# INT-04/05: identyfikator operacji nadany przez formularz przy otwarciu okna
# (crypto.randomUUID) i powtarzany przy ponowieniach. Opcjonalny — bez niego
# serwer bierze odcisk treści.
_CLIENT_REQUEST_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


class ComposeRequest(BaseModel):
    to: list[EmailStr]
    cc: list[EmailStr] = []
    subject: str = Field(min_length=1, max_length=998)
    body_html: str = Field(min_length=1)
    client_request_id: Optional[str] = Field(
        default=None, pattern=_CLIENT_REQUEST_ID_PATTERN
    )


class ReplyRequest(BaseModel):
    email_id: int
    body_html: str = Field(min_length=1)
    client_request_id: Optional[str] = Field(
        default=None, pattern=_CLIENT_REQUEST_ID_PATTERN
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _require_active_connection(db: AsyncSession, user_id: int) -> M365Connection:
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail="No active Microsoft 365 connection",
        )
    return conn


def _send_conflict_http(exc: m365_sender.EmailSendConflict) -> HTTPException:
    """Wysyłka w toku albo o nieznanym wyniku — nigdy druga wysyłka.

    Zawsze 409 (także gdy to żądanie straciło odpowiedź Graph): 502 zostałby
    ponowiony przez interceptor frontu, a wynik i tak byłby ten sam.
    """
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


def _graph_refusal_http(exc: GraphRequestError) -> HTTPException:
    """Odmowa Graph 4xx przed wysyłką → 4xx z polskim komunikatem (runda 6 audytu).

    Do 26.09 każda odmowa (np. oryginał usunięty ze skrzynki, zły adres)
    kończyła się nieobsłużonym 500. Treści odpowiedzi Graph nie oddajemy —
    bywa w niej adres i identyfikator wiadomości.
    """
    if exc.status in (401, 403):
        return HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Microsoft 365 odmówił dostępu do skrzynki — połącz konto ponownie.",
        )
    if exc.status == 429:
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Microsoft 365 ogranicza liczbę wysyłek — spróbuj za chwilę.",
        )
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Microsoft 365 odrzucił wiadomość (np. oryginał usunięto ze skrzynki "
        "albo adres jest nieprawidłowy). Nic nie zostało wysłane.",
    )


def _can_access_email(email: Email, user, privileged_role: bool) -> bool:
    if email.user_id == user.id:
        return True
    return privileged_role


def _to_email_out(email: Email) -> EmailOut:
    return EmailOut(
        id=email.id,
        m365_message_id=email.m365_message_id,
        m365_conversation_id=email.m365_conversation_id,
        subject=email.subject,
        from_address=email.from_address,
        from_name=email.from_name,
        to_addresses=list(email.to_addresses or []),
        cc_addresses=list(email.cc_addresses or []),
        body_html=email.body_html,
        body_text=email.body_text,
        body_preview=email.body_preview,
        sent_at=email.sent_at,
        received_at=email.received_at,
        direction=email.direction.value if email.direction else "received",
        has_attachments=email.has_attachments,
        is_read=email.is_read,
        is_archived=email.is_archived,
        is_private_filtered=email.is_private_filtered,
        match_method=email.match_method.value if email.match_method else "unmatched",
        match_confidence=email.match_confidence,
        candidate_id=email.candidate_id,
        send_state=email.send_state,
        attachments=[],  # filled by callers that eager-load
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/candidates/{candidate_id}/emails", response_model=ThreadListResponse)
async def list_candidate_emails(
    candidate_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_archived: bool = Query(False),
) -> ThreadListResponse:
    """Return conversation previews for a candidate, most-recent first.

    Groups by `m365_conversation_id`. Each preview carries the latest message
    plus aggregate counts (total + unread). Archived emails (Phase 5.1) are
    hidden unless `include_archived=true`.
    """
    # Fetch all candidate emails the user can see, latest first.
    base_stmt = select(Email).where(Email.candidate_id == candidate_id)
    if not include_archived:
        base_stmt = base_stmt.where(Email.is_archived.is_(False))
    base_stmt = (
        base_stmt.order_by(Email.received_at.desc()).limit(
            1000
        )  # cap for safety — UI paginates by thread count
    )
    result = await db.execute(base_stmt)
    rows = result.scalars().all()

    privileged = current_user.role.value in {"admin", "delivery_lead"}
    visible = [e for e in rows if _can_access_email(e, current_user, privileged)]

    threads: dict[str, dict] = {}
    for e in visible:
        conv = e.m365_conversation_id
        slot = threads.get(conv)
        if slot is None:
            threads[conv] = {"latest": e, "count": 1, "unread": 0 if e.is_read else 1}
        else:
            slot["count"] += 1
            if not e.is_read:
                slot["unread"] += 1
            if e.received_at > slot["latest"].received_at:
                slot["latest"] = e

    ordered = sorted(
        threads.values(), key=lambda t: t["latest"].received_at, reverse=True
    )
    page = ordered[offset : offset + limit]

    return ThreadListResponse(
        items=[
            ThreadPreview(
                conversation_id=t["latest"].m365_conversation_id,
                subject=t["latest"].subject,
                latest=_to_email_out(t["latest"]),
                message_count=t["count"],
                unread_count=t["unread"],
            )
            for t in page
        ],
        total=len(ordered),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/candidates/{candidate_id}/emails/thread/{conversation_id:path}",
    response_model=list[EmailOut],
)
async def list_thread_messages(
    candidate_id: int,
    conversation_id: str,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[EmailOut]:
    """Return every message in a candidate's conversation, oldest first.

    Powers the thread-tree visualization (Phase 5.3): the frontend needs the
    full conversation to render parent/child indentation. Sort is ASC by
    sent_at (Graph timestamp on the sender's clock) with a fallback to
    received_at so we still get a deterministic order for sent-from-ATS
    messages that lack a Graph sent_at until the next delta pass.
    """
    stmt = (
        select(Email)
        .where(
            Email.candidate_id == candidate_id,
            Email.m365_conversation_id == conversation_id,
        )
        .order_by(Email.sent_at.asc().nulls_last(), Email.received_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    privileged = current_user.role.value in {"admin", "delivery_lead"}
    visible = [e for e in rows if _can_access_email(e, current_user, privileged)]
    return [_to_email_out(e) for e in visible]


@router.get("/emails/{email_id}", response_model=EmailOut)
async def get_email(
    email_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    email = await db.get(Email, email_id)
    if email is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "email not found")
    privileged = current_user.role.value in {"admin", "delivery_lead"}
    if not _can_access_email(email, current_user, privileged):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    # Separate attachment query — avoid assigning into the SA relationship
    # collection, which could trip cascade behavior.
    atts_result = await db.scalars(
        select(EmailAttachment).where(EmailAttachment.email_id == email_id)
    )
    attachments = [AttachmentOut.model_validate(a) for a in atts_result.all()]
    out = _to_email_out(email)
    out.attachments = attachments
    return out


@router.get("/emails/{email_id}/attachments/{attachment_id}/download")
async def download_attachment(
    email_id: int,
    attachment_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    email = await db.get(Email, email_id)
    att = await db.get(EmailAttachment, attachment_id)
    if email is None or att is None or att.email_id != email.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attachment not found")
    privileged = current_user.role.value in {"admin", "delivery_lead"}
    if not _can_access_email(email, current_user, privileged):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if not att.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not persisted")
    abs_path = (STORAGE_ROOT / att.storage_path).resolve()
    # Path-traversal guard — same as storage_service.get_contract_document_path.
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    if not abs_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file missing on disk")
    return FileResponse(abs_path, media_type=att.content_type, filename=att.filename)


@router.post("/candidates/{candidate_id}/emails/compose", response_model=EmailOut)
async def compose_email(
    candidate_id: int,
    payload: ComposeRequest,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    # P0.9: sending real M365 mail requires an internal operational role
    # (CandidatePIIAccess excludes the read-only viewer).
    conn = await _require_active_connection(db, current_user.id)
    # INT-07: kandydat MUSI istnieć, zanim cokolwiek pójdzie do Graph —
    # inaczej mail wychodził, a zapis śladu padał na kluczu obcym.
    if await db.get(Candidate, candidate_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono kandydata")
    try:
        row = await m365_sender.send_new(
            db,
            conn,
            to=[str(x) for x in payload.to],
            cc=[str(x) for x in payload.cc],
            subject=payload.subject,
            body_html=payload.body_html,
            candidate_id=candidate_id,
            client_request_id=payload.client_request_id,
            commit_reservation=True,
        )
    except m365_sender.EmailSendConflict as exc:
        raise _send_conflict_http(exc) from exc
    except GraphRequestError as exc:
        if 400 <= exc.status < 500:
            raise _graph_refusal_http(exc) from exc
        raise
    await db.commit()
    return _to_email_out(row)


@router.get(
    "/microsoft365/emails/search",
    response_model=EmailSearchResponse,
)
@limiter.limit("60/minute")
async def search_emails(
    request: Request,
    current_user: CandidatePIIAccess,
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    candidate_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> EmailSearchResponse:
    """Full-text search over the caller's own emails (Phase 4.4).

    Multi-tenant: rows filtered to ``Email.user_id == current_user.id`` — no
    privileged-role bypass, mailbox content is per-user PII.

    Uses ``plainto_tsquery('simple', :q)`` so the caller can pass natural
    language; ``simple`` config matches the generated column (no stemming,
    mixed PL/EN/DE in production mailboxes).

    Ranking: ``ts_rank`` desc with ``received_at`` desc as tiebreaker — when
    two emails match equally, newest wins.

    ``candidate_id`` zawęża trafienia do maili przypisanych temu kandydatowi —
    wyszukiwarka w profilu kandydata inaczej pokazywała maile innych osób,
    a kliknięcie takiego wyniku otwierało pusty wątek (para kandydat A +
    rozmowa kandydata B nie ma wiadomości).
    """
    # Single CTE-style query to share the same `:q` binding for filter,
    # ranking and snippet. asyncpg's prepared-statement cache handles repeats.
    sql = text(
        """
        WITH matches AS (
            SELECT e.*,
                   ts_rank(e.search_vector,
                           plainto_tsquery('simple', :q)) AS rank,
                   ts_headline(
                       'simple',
                       coalesce(e.body_text, ''),
                       plainto_tsquery('simple', :q),
                       'StartSel=<mark>,StopSel=</mark>,'
                       'MaxFragments=2,MaxWords=15,MinWords=5,'
                       'ShortWord=2,HighlightAll=false'
                   ) AS snippet
            FROM emails e
            WHERE e.user_id = :user_id
              AND e.search_vector @@ plainto_tsquery('simple', :q)
              AND (
                  CAST(:candidate_id AS integer) IS NULL
                  OR e.candidate_id = CAST(:candidate_id AS integer)
              )
        )
        SELECT id, m365_conversation_id, candidate_id, subject,
               from_address, from_name, received_at,
               has_attachments, is_read, snippet,
               COUNT(*) OVER () AS total
        FROM matches
        ORDER BY rank DESC, received_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    result = await db.execute(
        sql,
        {
            "q": q,
            "user_id": current_user.id,
            "candidate_id": candidate_id,
            "limit": limit,
            "offset": offset,
        },
    )
    rows = result.mappings().all()

    total = int(rows[0]["total"]) if rows else 0
    items = [
        EmailSearchHit(
            id=row["id"],
            m365_conversation_id=row["m365_conversation_id"],
            candidate_id=row["candidate_id"],
            subject=row["subject"],
            from_address=row["from_address"],
            from_name=row["from_name"],
            received_at=row["received_at"],
            has_attachments=row["has_attachments"],
            is_read=row["is_read"],
            snippet=row["snippet"],
        )
        for row in rows
    ]
    return EmailSearchResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/candidates/{candidate_id}/emails/reply", response_model=EmailOut)
async def reply_email(
    candidate_id: int,
    payload: ReplyRequest,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    # P0.9: viewer excluded from sending (reply is also owner+candidate scoped).
    conn = await _require_active_connection(db, current_user.id)
    original = await db.get(Email, payload.email_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "original email not found")
    if original.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if original.candidate_id not in (None, candidate_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "original email belongs to a different candidate",
        )
    if original.direction == EmailDirection.sent:
        # Runda 6 audytu: odpowiedź na własny wysłany mail trafiała do nas
        # samych (Graph bierze nadawcę oryginału). Odpowiadamy na ostatnią
        # wiadomość PRZYCHODZĄCĄ OD KANDYDATA; bez niej — prośba o nowy mail.
        # Runda 7 (R7-V1-2): sama „ostatnia przychodząca” trafiała też w maila
        # HM-a klienta albo kolegi z kopii w tym samym wątku, a Graph wysyłał
        # wtedy treść dla kandydata do nich.
        candidate_email = (
            select(func.lower(func.trim(Candidate.email)))
            .where(Candidate.id == candidate_id)
            .scalar_subquery()
        )
        inbound = await db.scalar(
            select(Email)
            .where(
                Email.user_id == current_user.id,
                Email.m365_conversation_id == original.m365_conversation_id,
                Email.direction == EmailDirection.received,
                or_(Email.candidate_id == candidate_id, Email.candidate_id.is_(None)),
                func.lower(func.trim(Email.from_address)) == candidate_email,
            )
            .order_by(Email.received_at.desc(), Email.id.desc())
            .limit(1)
        )
        if inbound is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Kandydat jeszcze nie odpowiedział w tym wątku — napisz nowy mail.",
            )
        original = inbound
    if (original.m365_message_id or "").startswith(m365_sender.PENDING_ID_PREFIX):
        # Wiersz zarezerwowany, którego szkic jeszcze nie powstał — Graph nie
        # zna tego identyfikatora, odpowiedź skończyłaby się 404.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ta wiadomość jest jeszcze wysyłana — spróbuj za chwilę.",
        )
    try:
        row = await m365_sender.reply(
            db,
            conn,
            email_row=original,
            body_html=payload.body_html,
            client_request_id=payload.client_request_id,
            commit_reservation=True,
        )
    except m365_sender.EmailSendConflict as exc:
        raise _send_conflict_http(exc) from exc
    except GraphRequestError as exc:
        if 400 <= exc.status < 500:
            raise _graph_refusal_http(exc) from exc
        raise
    if row.candidate_id is None:
        row.candidate_id = candidate_id
        row.match_method = EmailMatchMethod.manual
    await db.commit()
    return _to_email_out(row)


# ── Bulk actions (Phase 5.1) ────────────────────────────────────────────────


BulkEmailAction = Literal[
    "archive",
    "mark_read",
    "mark_unread",
    "link_to_candidate",
    "unlink",
]


class BulkEmailActionRequest(BaseModel):
    """Request shape for POST /api/microsoft365/emails/bulk.

    `candidate_id` is required only for `link_to_candidate` — validated below.
    """

    email_ids: list[int] = Field(..., min_length=1, max_length=200)
    action: BulkEmailAction
    candidate_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_candidate_for_link(self) -> "BulkEmailActionRequest":
        if self.action == "link_to_candidate" and self.candidate_id is None:
            raise ValueError("candidate_id is required for action='link_to_candidate'")
        return self


class BulkEmailActionItemError(BaseModel):
    id: int
    reason: str


class BulkEmailActionResponse(BaseModel):
    action: BulkEmailAction
    updated_count: int
    skipped_count: int
    errors: list[BulkEmailActionItemError]


def _apply_bulk_action(
    email: Email,
    action: BulkEmailAction,
    candidate_id: Optional[int],
    user_id: int,
    now: datetime,
) -> None:
    if action == "archive":
        email.is_archived = True
    elif action == "mark_read":
        email.is_read = True
    elif action == "mark_unread":
        email.is_read = False
    elif action == "link_to_candidate":
        # candidate_id presence validated in request model.
        assert candidate_id is not None
        email.candidate_id = candidate_id
        email.match_method = EmailMatchMethod.manual
        email.match_confidence = 1.0
        email.matched_at = now
        email.matched_by_user_id = user_id
    elif action == "unlink":
        # Runda 6 audytu: ręczne odpięcie jest DECYZJĄ — ``unmatched`` z
        # ``matched_by_user_id`` (kto i kiedy odpiął). Czytają to sync
        # (``_upsert_message``), rematch i zakładanie kandydata z CV, które do
        # 26.09 przypinały mail z powrotem przy najbliższym przebiegu. Czyści
        # to ręczne podpięcie (``link_to_candidate``).
        email.candidate_id = None
        email.match_method = EmailMatchMethod.unmatched
        email.match_confidence = None
        email.matched_at = now
        email.matched_by_user_id = user_id
    # `updated_at` mixin column refreshes via TimestampMixin.


@router.post("/microsoft365/emails/bulk", response_model=BulkEmailActionResponse)
async def bulk_email_action(
    payload: BulkEmailActionRequest,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> BulkEmailActionResponse:
    """Apply a single action to many emails owned by the current user.

    Multi-tenant scope: `Email.user_id == current_user.id`. Emails belonging to
    other users are reported as `forbidden` skips, never silently mutated.

    Actions:
      - archive          → set is_archived=true
      - mark_read        → set is_read=true
      - mark_unread      → set is_read=false
      - link_to_candidate → set candidate_id (+ match_method=manual)
      - unlink           → clear candidate_id (+ match_method=unmatched)
    """
    requested_ids = sorted(set(payload.email_ids))

    # Validate candidate for link_to_candidate (must exist).
    if payload.action == "link_to_candidate":
        candidate = await db.get(Candidate, payload.candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"candidate {payload.candidate_id} not found",
            )

    rows = await db.execute(select(Email).where(Email.id.in_(requested_ids)))
    emails = list(rows.scalars().all())
    found_by_id = {e.id: e for e in emails}

    errors: list[BulkEmailActionItemError] = []
    updated = 0
    now = datetime.now(timezone.utc)

    for email_id in requested_ids:
        email = found_by_id.get(email_id)
        if email is None:
            errors.append(BulkEmailActionItemError(id=email_id, reason="not_found"))
            continue
        if email.user_id != current_user.id:
            errors.append(BulkEmailActionItemError(id=email_id, reason="forbidden"))
            continue
        _apply_bulk_action(
            email,
            payload.action,
            payload.candidate_id,
            current_user.id,
            now,
        )
        updated += 1

    await db.commit()

    return BulkEmailActionResponse(
        action=payload.action,
        updated_count=updated,
        skipped_count=len(errors),
        errors=errors,
    )
