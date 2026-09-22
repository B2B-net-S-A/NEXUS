"""Send emails from the user's mailbox via Graph.

Flow for a NEW message:
    POST /me/messages         (create draft → returns id + internetMessageId)
    POST /me/messages/{id}/send   (send; 202 Accepted)

We use the draft+send flow (not /me/sendMail) because:
- It returns the message id pre-send, so we can persist a local row without
  polling SentItems.
- It lets us attach files before sending without a second round trip.

Flow for a REPLY:
    POST /me/messages/{id}/createReply → PATCH body → POST /send

Jednorazowość wysyłki (INT-04/05/07, 09.2026)
---------------------------------------------
Wiersz ``Email`` jest REZERWOWANY przed pierwszym wywołaniem Graph
(``send_state='pending'``, zastępczy ``m365_message_id`` ``pending:<uuid>``),
z unikalnym ``idempotency_key``:

* ``client_request_id`` z formularza (UUID nadany przy otwarciu okna i
  powtarzany przy ponowieniach) → klucz = użytkownik + UUID;
* bez niego (automaty, stare klienty) → odcisk użytkownik + odbiorcy + temat +
  minuta + skrót TREŚCI + kandydat (wcześniej bez treści: korekta wysłana
  w tej samej minucie była po cichu gubiona — INT-05).

Drugie żądanie z tym samym kluczem nie woła Graph: wysłany wiersz wraca jako
wynik, wysyłka w toku albo o niepewnym wyniku daje ``EmailSendConflict``.
Po utworzeniu szkicu wiersz dostaje prawdziwe identyfikatory; awaria po tym
momencie zostawia wiersz w stanie ``uncertain`` (mail mógł wyjść), awaria
przed nim zwalnia rezerwację (mail na pewno nie wyszedł).

``commit_reservation=True`` (endpointy API) commituje rezerwację, więc
równoległe żądanie widzi ją od razu. Automaty trzymające własną transakcję
(harmonogram maili odrzucenia z blokadą wiersza) zostają przy domyślnym
``False`` — wtedy wzajemne wykluczenie daje sam UNIQUE (drugi INSERT czeka na
koniec pierwszej transakcji).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.m365 import (
    Email,
    EmailDirection,
    EmailMatchMethod,
    M365Connection,
)
from app.services.m365.actionable_messages import (
    build_interview_confirmation_card,
)
from app.services.m365.access import require_eligible_connection_owner
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.m365.html_sanitize import html_to_text, sanitize_html
from app.services.m365.signature_cache import get_outlook_signature

logger = logging.getLogger(__name__)

# Phase 7.7 — visible divider between body and pulled signature so it's
# obvious in the rendered mail where the user's signature begins. The
# class hook lets the frontend (and our future inline editor) collapse
# the block if needed.
_SIGNATURE_DIVIDER = '<br><br><div class="nexus-signature">--</div>'

# Outlook treats this header as the "this message has Actionable Messages"
# signal — without it the JSON-LD `OpenAction` block is ignored and the user
# only sees the fallback link.
_ACTIONABLE_MESSAGE_HEADER = "X-MS-Actionable-Message"

SEND_STATE_PENDING = "pending"
SEND_STATE_SENT = "sent"
SEND_STATE_UNCERTAIN = "uncertain"

# Prefiks zastępczych identyfikatorów Graph wiersza zarezerwowanego przed
# utworzeniem szkicu (kolumny są NOT NULL, a m365_message_id — UNIQUE).
PENDING_ID_PREFIX = "pending:"

# Rezerwacja „w toku" starsza niż to okno oznacza proces, który padł w trakcie
# (deploy) — wynik jest nieznany, więc raportujemy ją jak niepewną.
_STALE_PENDING_AFTER = timedelta(minutes=10)


class EmailSendConflict(RuntimeError):
    """Wysyłka z tym kluczem jest w toku albo jej wynik jest nieznany.

    ``state`` — ``pending`` albo ``uncertain``. ``first_attempt=True`` znaczy,
    że to TO żądanie straciło odpowiedź Graph (nie ponowienie).
    """

    def __init__(
        self, state: str, email_id: Optional[int], *, first_attempt: bool = False
    ) -> None:
        self.state = state
        self.email_id = email_id
        self.first_attempt = first_attempt
        if state == SEND_STATE_PENDING:
            message = "Ta wiadomość jest już wysyłana."
        else:
            message = (
                "Nie wiadomo, czy wiadomość została wysłana — sprawdź folder "
                "Wysłane w Outlooku, zanim spróbujesz ponownie."
            )
        super().__init__(message)


def _append_signature(body_html: str, signature_html: str) -> str:
    """Concat signature onto a body separated by a visible divider."""
    return body_html + _SIGNATURE_DIVIDER + signature_html


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_key(*, user_id: int, client_request_id: str) -> str:
    """Klucz intencji nadanej przez formularz (użytkownik + UUID)."""
    return _sha(f"request|{user_id}|{client_request_id.strip()}")


def _build_idempotency_key(
    *,
    user_id: int,
    to: list[str],
    cc: list[str],
    subject: str,
    now: Optional[datetime] = None,
    body_html: Optional[str] = None,
    candidate_id: Optional[int] = None,
) -> str:
    """Odcisk intencji, gdy wołający nie podał ``client_request_id``.

    W tej samej minucie ten sam (użytkownik, odbiorcy, temat, treść, kandydat)
    daje ten sam klucz — podwójne kliknięcie nie wysyła drugi raz. Treść
    i kandydat są w odcisku od 09.2026 (INT-05): korekta o innej treści
    w tej samej minucie jest osobną wiadomością.
    """
    now = now or datetime.now(timezone.utc)
    minute_bucket = now.strftime("%Y-%m-%dT%H:%M")
    parts = [
        str(user_id),
        ",".join(sorted({a.strip().lower() for a in to if a})),
        ",".join(sorted({a.strip().lower() for a in cc if a})),
        (subject or "").strip(),
        minute_bucket,
    ]
    if body_html is not None or candidate_id is not None:
        parts.append(_sha(body_html or ""))
        parts.append(str(candidate_id or ""))
    return _sha("|".join(parts))


def _build_reply_idempotency_key(
    *, user_id: int, email_id: int, body_html: str, now: datetime
) -> str:
    return _sha(
        "|".join(
            [
                "reply",
                str(user_id),
                str(email_id),
                _sha(body_html or ""),
                now.strftime("%Y-%m-%dT%H:%M"),
            ]
        )
    )


def _placeholder_id() -> str:
    return f"{PENDING_ID_PREFIX}{uuid.uuid4().hex}"


def _resolve_existing(existing: Email) -> Email:
    """Wynik ponowienia: wysłany wiersz albo konflikt (nigdy druga wysyłka)."""
    state = existing.send_state
    if state in (None, SEND_STATE_SENT):
        return existing
    if state == SEND_STATE_PENDING:
        created = existing.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is not None and (
            datetime.now(timezone.utc) - created > _STALE_PENDING_AFTER
        ):
            raise EmailSendConflict(SEND_STATE_UNCERTAIN, existing.id)
        raise EmailSendConflict(SEND_STATE_PENDING, existing.id)
    raise EmailSendConflict(SEND_STATE_UNCERTAIN, existing.id)


async def _find_by_key(db: AsyncSession, key: str) -> Optional[Email]:
    return await db.scalar(select(Email).where(Email.idempotency_key == key))


async def _reserve(db: AsyncSession, row: Email, *, commit: bool) -> Optional[Email]:
    """Zarezerwuj wiersz przed Graphem. Zwraca istniejący wynik ponowienia.

    ``None`` = rezerwacja założona (ten wywołujący wysyła). Istniejący wiersz
    z tym kluczem = wynik wcześniejszej wysyłki albo ``EmailSendConflict``.
    """
    existing = await _find_by_key(db, row.idempotency_key)
    if existing is not None:
        return _resolve_existing(existing)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Równoległe żądanie wstawiło ten sam klucz między SELECT a INSERT
        # (UNIQUE na idempotency_key). To ono wysyła — my nie.
        existing = await _find_by_key(db, row.idempotency_key)
        if existing is None:
            raise
        return _resolve_existing(existing)
    if commit:
        await db.commit()
    return None


async def _release(db: AsyncSession, row: Email, *, commit: bool) -> None:
    """Mail na pewno nie wyszedł — zwolnij rezerwację (ponowienie wolno)."""
    try:
        await db.delete(row)
        await db.flush()
        if commit:
            await db.commit()
    except Exception:  # noqa: BLE001 — nie maskuj pierwotnego błędu
        logger.exception("m365 sender: failed to release reservation %s", row.id)


async def _mark_uncertain(db: AsyncSession, row: Email, *, commit: bool) -> None:
    try:
        row.send_state = SEND_STATE_UNCERTAIN
        await db.flush()
        if commit:
            await db.commit()
    except Exception:  # noqa: BLE001 — nie maskuj pierwotnego błędu
        logger.exception("m365 sender: failed to mark email %s uncertain", row.id)


def _definitely_not_sent(exc: BaseException) -> bool:
    """Graph odrzucił ``/send`` jednoznacznie (4xx) — mail nie wyszedł."""
    return isinstance(exc, GraphRequestError) and 400 <= exc.status < 500


async def _signature_body(
    gc: GraphClient, connection: M365Connection, body: str
) -> str:
    # Phase 7.7 — append the user's Outlook signature so NEXUS-sent mail
    # matches what they'd get from Outlook itself. Memoized for 24h per
    # mailbox; failures are silent (no signature is better than no send).
    if not settings.M365_SIGNATURE_INJECTION_ENABLED:
        return body
    signature_html = await get_outlook_signature(
        gc,
        user_id=connection.user_id,
        mailbox_upn=connection.mailbox_upn,
    )
    if signature_html:
        return _append_signature(body, sanitize_html(signature_html))
    return body


DraftBuilder = Callable[[GraphClient], Awaitable[dict[str, Any]]]


async def _deliver(
    db: AsyncSession,
    connection: M365Connection,
    row: Email,
    *,
    create_draft: DraftBuilder,
    commit: bool,
) -> Email:
    """Utwórz szkic, zapisz jego identyfikatory, wyślij, oznacz wynik."""
    draft: Optional[dict[str, Any]] = None
    try:
        async with GraphClient(connection, db) as gc:
            draft = await create_draft(gc)
            message_id = draft["id"]
            row.m365_message_id = message_id
            if draft.get("internetMessageId"):
                row.m365_internet_message_id = draft["internetMessageId"]
            if draft.get("conversationId"):
                row.m365_conversation_id = draft["conversationId"]
            elif row.m365_conversation_id.startswith(PENDING_ID_PREFIX):
                row.m365_conversation_id = message_id
            await db.flush()
            if commit:
                await db.commit()
            await gc.post(f"/me/messages/{message_id}/send", json={})
    except Exception as exc:
        if draft is None or _definitely_not_sent(exc):
            await _release(db, row, commit=commit)
            raise
        logger.warning(
            "m365 sender: send outcome unknown for email %s (%s)",
            row.id,
            type(exc).__name__,
        )
        await _mark_uncertain(db, row, commit=commit)
        raise EmailSendConflict(
            SEND_STATE_UNCERTAIN, row.id, first_attempt=True
        ) from exc

    row.send_state = SEND_STATE_SENT
    await db.flush()
    return row


def _new_outbound_row(
    *,
    connection: M365Connection,
    candidate_id: Optional[int],
    subject: str,
    to: list[str],
    cc: list[str],
    body_html: str,
    now: datetime,
    idempotency_key: str,
    conversation_id: Optional[str] = None,
) -> Email:
    body_text = html_to_text(body_html)
    placeholder = _placeholder_id()
    return Email(
        user_id=connection.user_id,
        candidate_id=candidate_id,
        m365_message_id=placeholder,
        m365_internet_message_id=None,
        m365_conversation_id=conversation_id or placeholder,
        subject=subject[:998] if subject else None,
        from_address=connection.mailbox_upn,
        from_name=None,
        to_addresses=[{"address": a} for a in to],
        cc_addresses=[{"address": a} for a in cc],
        body_html=body_html,
        body_text=body_text,
        body_preview=body_text[:255] if body_text else None,
        sent_at=now,
        received_at=now,
        direction=EmailDirection.sent,
        has_attachments=False,
        is_read=True,
        match_method=(
            EmailMatchMethod.manual
            if candidate_id is not None
            else EmailMatchMethod.unmatched
        ),
        matched_at=now if candidate_id is not None else None,
        match_confidence=1.0 if candidate_id is not None else None,
        idempotency_key=idempotency_key,
        send_state=SEND_STATE_PENDING,
    )


def _set_body(row: Email, body_html: str) -> None:
    body_text = html_to_text(body_html)
    row.body_html = body_html
    row.body_text = body_text
    row.body_preview = body_text[:255] if body_text else None


async def send_new(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    subject: str,
    body_html: str,
    candidate_id: Optional[int] = None,
    client_request_id: Optional[str] = None,
    commit_reservation: bool = False,
) -> Email:
    """Send a brand-new message from the connected mailbox.

    Returns the persisted local Email row (direction=sent). Ponowienie z tym
    samym kluczem zwraca wcześniejszy wiersz bez drugiego wywołania Graph albo
    rzuca ``EmailSendConflict`` (wysyłka w toku / wynik nieznany).
    """
    await require_eligible_connection_owner(db, connection)
    cc = cc or []
    body_html = sanitize_html(body_html)

    now = datetime.now(timezone.utc)
    if client_request_id:
        idempotency_key = request_key(
            user_id=connection.user_id, client_request_id=client_request_id
        )
    else:
        idempotency_key = _build_idempotency_key(
            user_id=connection.user_id,
            to=to,
            cc=cc,
            subject=subject,
            now=now,
            body_html=body_html,
            candidate_id=candidate_id,
        )
    row = _new_outbound_row(
        connection=connection,
        candidate_id=candidate_id,
        subject=subject,
        to=to,
        cc=cc,
        body_html=body_html,
        now=now,
        idempotency_key=idempotency_key,
    )
    replay = await _reserve(db, row, commit=commit_reservation)
    if replay is not None:
        logger.info(
            "send_new: idempotent hit for user_id=%s — returning row %d",
            connection.user_id,
            replay.id,
        )
        return replay

    async def _create(gc: GraphClient) -> dict[str, Any]:
        full_body = await _signature_body(gc, connection, body_html)
        if full_body != body_html:
            _set_body(row, full_body)
        payload = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": full_body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        }
        return await gc.post("/me/messages", json=payload)

    return await _deliver(
        db, connection, row, create_draft=_create, commit=commit_reservation
    )


async def send_interview_invitation(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    subject: str,
    body_html: str,
    candidate_id: int,
    event_id: int,
    button_label: str = "Potwierdzam interview",
    client_request_id: Optional[str] = None,
    commit_reservation: bool = False,
) -> Email:
    """Send an interview invite enriched with an Outlook Actionable Messages
    "Confirm" button (Phase 7.5).

    The `body_html` is rendered as the recruiter wrote it (signature, agenda,
    etc.) and the JSON-LD action block plus a fallback link are injected
    immediately before send. The `X-MS-Actionable-Message` internet header is
    set on the Graph payload so Outlook recognises the message as actionable.

    Jednorazowość jak w ``send_new`` (rezerwacja przed Graphem).
    """
    await require_eligible_connection_owner(db, connection)
    cc = cc or []

    # Sanitize the recruiter-authored body first (XSS hardening for whatever
    # the user pasted into the editor). Then concatenate our trusted
    # actionable block — it includes the JSON-LD `<script type="application/
    # ld+json">` that bleach would otherwise strip. The block is built from
    # internal-only inputs (event_id/candidate_id/JWT we just signed) so
    # bypassing sanitize on it is safe.
    safe_body_html = sanitize_html(body_html)

    now = datetime.now(timezone.utc)
    if client_request_id:
        idempotency_key = request_key(
            user_id=connection.user_id, client_request_id=client_request_id
        )
    else:
        idempotency_key = _build_idempotency_key(
            user_id=connection.user_id,
            to=to,
            cc=cc,
            subject=subject,
            now=now,
            body_html=safe_body_html,
            candidate_id=candidate_id,
        )
    existing = await _find_by_key(db, idempotency_key)
    if existing is not None:
        logger.info(
            "send_interview_invitation: idempotent hit for user_id=%s — row %d",
            connection.user_id,
            existing.id,
        )
        return _resolve_existing(existing)

    actionable_html, _payload = build_interview_confirmation_card(
        event_id=event_id,
        candidate_id=candidate_id,
        button_label=button_label,
    )
    enriched_html = f"{safe_body_html}\n{actionable_html}"

    row = _new_outbound_row(
        connection=connection,
        candidate_id=candidate_id,
        subject=subject,
        to=to,
        cc=cc,
        body_html=enriched_html,
        now=now,
        idempotency_key=idempotency_key,
    )
    replay = await _reserve(db, row, commit=commit_reservation)
    if replay is not None:
        return replay

    payload: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": enriched_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        "internetMessageHeaders": [
            {"name": _ACTIONABLE_MESSAGE_HEADER, "value": "true"},
        ],
    }

    async def _create(gc: GraphClient) -> dict[str, Any]:
        return await gc.post("/me/messages", json=payload)

    return await _deliver(
        db, connection, row, create_draft=_create, commit=commit_reservation
    )


async def reply(
    db: AsyncSession,
    connection: M365Connection,
    *,
    email_row: Email,
    body_html: str,
    client_request_id: Optional[str] = None,
    commit_reservation: bool = False,
) -> Email:
    """Reply to an existing message; Graph auto-quotes thread history.

    Returns the persisted local Email row for the sent reply (createReply →
    PATCH body → send). Rezerwacja i ponowienia jak w ``send_new``.
    """
    await require_eligible_connection_owner(db, connection)
    body_html = sanitize_html(body_html)

    now = datetime.now(timezone.utc)
    if client_request_id:
        idempotency_key = request_key(
            user_id=connection.user_id, client_request_id=client_request_id
        )
    else:
        idempotency_key = _build_reply_idempotency_key(
            user_id=connection.user_id,
            email_id=email_row.id,
            body_html=body_html,
            now=now,
        )
    # Odczyt pól oryginału PRZED rezerwacją — commit rezerwacji nie może
    # zależeć od tego, czy obiekt oryginału jest jeszcze świeży.
    original_graph_id = email_row.m365_message_id
    subject = (
        f"Re: {email_row.subject}"
        if email_row.subject and not email_row.subject.lower().startswith("re:")
        else email_row.subject or "Re:"
    )[:998]
    row = _new_outbound_row(
        connection=connection,
        candidate_id=email_row.candidate_id,
        subject=subject,
        to=[email_row.from_address] if email_row.from_address else [],
        cc=[],
        body_html=body_html,
        now=now,
        idempotency_key=idempotency_key,
        conversation_id=email_row.m365_conversation_id,
    )
    replay = await _reserve(db, row, commit=commit_reservation)
    if replay is not None:
        return replay

    async def _create(gc: GraphClient) -> dict[str, Any]:
        # Phase 7.7 — createReply auto-quotes the thread but does NOT include
        # the user's signature, so we still need to append it.
        full_body = await _signature_body(gc, connection, body_html)
        if full_body != body_html:
            _set_body(row, full_body)
        # 1) Create reply draft (Graph fills in recipients, subject, history).
        draft = await gc.post(f"/me/messages/{original_graph_id}/createReply", json={})
        # 2) Patch the body.
        await gc.patch(
            f"/me/messages/{draft['id']}",
            json={"body": {"contentType": "HTML", "content": full_body}},
        )
        return draft

    return await _deliver(
        db, connection, row, create_draft=_create, commit=commit_reservation
    )
