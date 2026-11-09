"""Rekrutacja własna: dostęp, odczyty i decyzje właściciela."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.candidate import Candidate
from app.models.m365 import M365Connection
from app.models.notification import NotificationType
from app.models.own_hiring import (
    OwnHiringApplication,
    OwnHiringBooking,
    OwnHiringEvent,
    OwnHiringProcess,
)
from app.models.user import User
from app.services import notification_triggers
from app.services.m365 import sender as m365_sender
from app.services.own_hiring import mail as mail_text
from app.services.own_hiring.slots import DEFAULT_SETTINGS, response_deadline

logger = logging.getLogger(__name__)

Role = Literal["owner", "assistant"]

TOKEN_LENGTH = 16
TOKEN_VALID_DAYS = 45
MAX_CALL_ATTEMPTS = 3
#: Karta wraca do tych etapów z ręcznego „Przenieś”.
MOVABLE_STAGES = frozenset(
    {"new", "no_response", "assistant", "teams", "office", "contract", "signed"}
)
ENTITY_APPLICATION = "own_hiring_application"
ENTITY_PROCESS = "own_hiring_process"


class OwnHiringError(Exception):
    """Błąd biznesowy z kodem HTTP i komunikatem dla człowieka."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Context:
    process: OwnHiringProcess
    role: Role
    user: User


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def merged_settings(process: OwnHiringProcess) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(process.settings or {})}


async def context_for(db: AsyncSession, user: User) -> Optional[Context]:
    """Proces, do którego należy ta osoba. Rola konta nie ma tu znaczenia."""
    process = await db.scalar(
        select(OwnHiringProcess)
        .where(
            OwnHiringProcess.is_active.is_(True),
            (OwnHiringProcess.owner_user_id == user.id)
            | (OwnHiringProcess.assistant_user_id == user.id),
        )
        .order_by(OwnHiringProcess.id.desc())
        .limit(1)
    )
    if process is None:
        return None
    role: Role = "owner" if process.owner_user_id == user.id else "assistant"
    return Context(process=process, role=role, user=user)


def compute_token(application_id: int, nonce: str) -> str:
    digest = hmac.new(
        app_settings.SECRET_KEY.encode(),
        f"own-hiring:{application_id}:{nonce}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(digest).decode().lower()[:TOKEN_LENGTH]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_token(application: OwnHiringApplication) -> Optional[str]:
    if not application.token_nonce:
        return None
    return compute_token(application.id, application.token_nonce)


def public_link(token: str) -> str:
    return f"{app_settings.PUBLIC_BASE_URL.rstrip('/')}/t/{token}"


def issue_token(application: OwnHiringApplication, now: datetime) -> str:
    application.token_nonce = secrets.token_hex(16)
    token = compute_token(application.id, application.token_nonce)
    application.token_sha256 = token_digest(token)
    application.token_expires_at = now + timedelta(days=TOKEN_VALID_DAYS)
    return token


def log_event(
    db: AsyncSession,
    application: OwnHiringApplication,
    kind: str,
    *,
    actor_id: Optional[int] = None,
    **payload: Any,
) -> None:
    db.add(
        OwnHiringEvent(
            application_id=application.id,
            kind=kind,
            actor_user_id=actor_id,
            payload=payload,
        )
    )


def set_stage(application: OwnHiringApplication, stage: str, now: datetime) -> None:
    if application.stage != stage:
        application.stage = stage
        application.stage_changed_at = now
    if stage != "closed":
        application.close_reason = None
        application.closed_at = None


def close(application: OwnHiringApplication, reason: str, now: datetime) -> None:
    set_stage(application, "closed", now)
    application.close_reason = reason
    application.closed_at = now


async def notify(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    message: str,
    entity_type: str,
    entity_id: int,
) -> None:
    await notification_triggers.emit(
        db,
        user_id=user_id,
        title=title,
        message=message,
        ntype=NotificationType.own_hiring_update,
        related_entity_type=entity_type,
        related_entity_id=entity_id,
        link="/rekrutacja-wlasna",
    )


async def owner_connection(
    db: AsyncSession, process: OwnHiringProcess
) -> Optional[M365Connection]:
    return await db.scalar(
        select(M365Connection).where(
            M365Connection.user_id == process.owner_user_id,
            M365Connection.is_active.is_(True),
        )
    )


async def _active_bookings(
    db: AsyncSession, application_ids: Sequence[int]
) -> dict[int, OwnHiringBooking]:
    if not application_ids:
        return {}
    rows = await db.scalars(
        select(OwnHiringBooking)
        .where(
            OwnHiringBooking.application_id.in_(application_ids),
            OwnHiringBooking.status == "active",
        )
        .order_by(OwnHiringBooking.start_at)
    )
    return {row.application_id: row for row in rows}


def booking_out(booking: Optional[OwnHiringBooking]) -> Optional[dict[str, Any]]:
    if booking is None:
        return None
    return {
        "kind": booking.kind,
        "start": booking.start_at,
        "end": booking.end_at,
        "via": booking.booked_via,
        "sync_status": booking.sync_status,
        "join_url": booking.join_url,
    }


def _person_name(candidate: Candidate) -> str:
    return " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()


def _card(
    application: OwnHiringApplication,
    candidate: Candidate,
    booking: Optional[OwnHiringBooking],
    now: datetime,
) -> dict[str, Any]:
    evidence = application.evidence or {}
    return {
        "id": application.id,
        "candidate_id": application.candidate_id,
        "name": _person_name(candidate),
        "city": candidate.city,
        "stage": application.stage,
        "bucket": application.bucket,
        "filter_reason": application.filter_reason,
        "role": evidence.get("role"),
        "company": evidence.get("company"),
        "months": evidence.get("months"),
        "until": evidence.get("until"),
        "is_it": bool(evidence.get("is_it")),
        "source": application.source_label,
        "ad_title": application.ad_title,
        "applied_at": application.applied_at,
        "has_email": bool(candidate.email),
        "invited_at": application.invited_at,
        "response_due_at": application.response_due_at,
        "replied_at": application.replied_at,
        "call_attempts": application.call_attempts,
        "callback_at": application.callback_at,
        "booking": booking_out(booking),
        "needs_decision": bool(
            booking is not None
            and booking.end_at <= now
            and application.stage in ("teams", "office")
        ),
        "contract_sent_at": application.contract_sent_at,
        "signed_at": application.signed_at,
        "close_reason": application.close_reason,
    }


async def _load_cards(
    db: AsyncSession, query: Any, *, now: datetime
) -> list[dict[str, Any]]:
    rows = (await db.execute(query)).all()
    bookings = await _active_bookings(db, [row[0].id for row in rows])
    return [_card(app, cand, bookings.get(app.id), now) for app, cand in rows]


def _months_desc() -> Any:
    return OwnHiringApplication.evidence["months"].as_integer().desc().nulls_last()


async def bucket_counts(db: AsyncSession, process_id: int) -> dict[str, int]:
    rows = await db.execute(
        select(OwnHiringApplication.bucket, func.count())
        .where(
            OwnHiringApplication.process_id == process_id,
            OwnHiringApplication.stage == "new",
        )
        .group_by(OwnHiringApplication.bucket)
    )
    counts = {"match": 0, "review": 0, "filtered": 0}
    counts.update({bucket: int(total) for bucket, total in rows})
    return counts


async def board(db: AsyncSession, process: OwnHiringProcess) -> dict[str, Any]:
    now = now_utc()
    base = (
        select(OwnHiringApplication, Candidate)
        .join(Candidate, Candidate.id == OwnHiringApplication.candidate_id)
        .where(OwnHiringApplication.process_id == process.id)
    )
    newest = await _load_cards(
        db,
        base.where(
            OwnHiringApplication.stage == "new", OwnHiringApplication.bucket == "match"
        )
        .order_by(_months_desc(), OwnHiringApplication.id.desc())
        .limit(50),
        now=now,
    )
    active = await _load_cards(
        db,
        base.where(OwnHiringApplication.stage.notin_(("new", "closed"))).order_by(
            OwnHiringApplication.stage_changed_at.desc()
        ),
        now=now,
    )
    closed = await db.execute(
        select(OwnHiringApplication.close_reason, func.count())
        .where(
            OwnHiringApplication.process_id == process.id,
            OwnHiringApplication.stage == "closed",
        )
        .group_by(OwnHiringApplication.close_reason)
    )
    last_import = await db.scalar(
        select(func.max(OwnHiringApplication.created_at)).where(
            OwnHiringApplication.process_id == process.id
        )
    )
    return {
        "cards": [*newest, *active],
        "new_counts": await bucket_counts(db, process.id),
        "closed_counts": {str(k): int(v) for k, v in closed},
        "last_import_at": last_import,
    }


async def new_list(
    db: AsyncSession, process: OwnHiringProcess, *, bucket: str
) -> list[dict[str, Any]]:
    query = (
        select(OwnHiringApplication, Candidate)
        .join(Candidate, Candidate.id == OwnHiringApplication.candidate_id)
        .where(
            OwnHiringApplication.process_id == process.id,
            OwnHiringApplication.stage == "new",
            OwnHiringApplication.bucket == bucket,
        )
        .order_by(_months_desc(), OwnHiringApplication.applied_at.desc())
        .limit(500)
    )
    return await _load_cards(db, query, now=now_utc())


async def _application(
    db: AsyncSession,
    process: OwnHiringProcess,
    application_id: int,
    *,
    lock: bool = False,
) -> OwnHiringApplication:
    query = select(OwnHiringApplication).where(
        OwnHiringApplication.id == application_id,
        OwnHiringApplication.process_id == process.id,
    )
    if lock:
        query = query.with_for_update()
    application = await db.scalar(query)
    if application is None:
        raise OwnHiringError(404, "not_found", "Nie ma takiej osoby w tym procesie.")
    return application


async def detail(
    db: AsyncSession, process: OwnHiringProcess, application_id: int
) -> dict[str, Any]:
    application = await _application(db, process, application_id)
    candidate = await db.get(Candidate, application.candidate_id)
    if candidate is None:
        raise OwnHiringError(404, "not_found", "Nie ma takiej osoby w tym procesie.")
    bookings = await _active_bookings(db, [application.id])
    events = await db.scalars(
        select(OwnHiringEvent)
        .where(OwnHiringEvent.application_id == application.id)
        .order_by(OwnHiringEvent.created_at.desc(), OwnHiringEvent.id.desc())
        .limit(100)
    )
    return {
        **_card(application, candidate, bookings.get(application.id), now_utc()),
        "email": candidate.email,
        "phone": candidate.phone,
        "availability": application.availability,
        "expected_money": application.expected_money,
        "tech_level": application.tech_level,
        "teams_note": application.teams_note,
        "office_note": application.office_note,
        "contract_kind": application.contract_kind,
        "events": [
            {"kind": e.kind, "at": e.created_at, "payload": e.payload} for e in events
        ],
    }


def _plain_text(body_html: str) -> str:
    """Podgląd maila jako tekst: okno nie wstawia HTML-a do strony."""
    with_breaks = re.sub(r"</p>\s*", "\n\n", body_html)
    return html.unescape(re.sub(r"<[^>]+>", "", with_breaks)).strip()


def invitation_preview(process: OwnHiringProcess) -> dict[str, Any]:
    settings = merged_settings(process)
    now = now_utc()
    text = mail_text.invitation(
        role_title=process.title,
        minutes=int(settings["slot_minutes"]),
        link=public_link("przyklad"),
    )
    return {
        "subject": text.subject,
        "body_text": _plain_text(text.body_html),
        "response_due_at": response_deadline(
            now, int(settings["response_business_days"])
        ),
    }


async def invite(
    db: AsyncSession, ctx: Context, application_ids: Sequence[int]
) -> list[dict[str, Any]]:
    """Wysyła zaproszenia po jednym. Awaria jednej osoby nie zatrzymuje reszty."""
    connection = await owner_connection(db, ctx.process)
    if connection is None:
        raise OwnHiringError(
            412,
            "mailbox_missing",
            "Podłącz skrzynkę Microsoft 365 w ustawieniach konta, żeby wysłać zaproszenia.",
        )
    settings = merged_settings(ctx.process)
    results: list[dict[str, Any]] = []
    for application_id in dict.fromkeys(application_ids):
        results.append(await _invite_one(db, ctx, application_id, connection, settings))
    return results


async def _invite_one(
    db: AsyncSession,
    ctx: Context,
    application_id: int,
    connection: M365Connection,
    settings: dict[str, Any],
) -> dict[str, Any]:
    application = await _application(db, ctx.process, application_id, lock=True)
    candidate = await db.get(Candidate, application.candidate_id)
    if application.stage not in ("new", "no_response"):
        await db.rollback()
        return {"id": application_id, "outcome": "wrong_stage"}
    if candidate is None or not candidate.email:
        await db.rollback()
        return {"id": application_id, "outcome": "no_email"}

    now = now_utc()
    # Ponowienie po awarii wysyłki trzyma ten sam klucz, żeby nie wysłać dwa razy.
    if application.token_nonce is None or application.stage != "new":
        token = issue_token(application, now)
    else:
        token = compute_token(application.id, application.token_nonce)
    await db.commit()
    text = mail_text.invitation(
        role_title=ctx.process.title,
        minutes=int(settings["slot_minutes"]),
        link=public_link(token),
    )
    try:
        await m365_sender.send_new(
            db,
            connection,
            to=[candidate.email],
            subject=text.subject,
            body_html=text.body_html,
            client_request_id=f"own-hiring-invite:{application.id}:{application.token_nonce}",
            commit_reservation=True,
        )
    except Exception as exc:  # noqa: BLE001 — wynik per osoba, reszta idzie dalej
        await db.rollback()
        logger.warning(
            "own_hiring.invite_failed application=%s error=%s",
            application_id,
            type(exc).__name__,
        )
        return {"id": application_id, "outcome": "failed"}

    application = await _application(db, ctx.process, application_id, lock=True)
    sent_at = now_utc()
    application.invited_at = sent_at
    application.replied_at = None
    application.response_due_at = response_deadline(
        sent_at, int(settings["response_business_days"])
    )
    set_stage(application, "invited", sent_at)
    log_event(db, application, "invited", actor_id=ctx.user.id)
    await db.commit()
    return {"id": application_id, "outcome": "sent"}


async def reject(db: AsyncSession, ctx: Context, application_ids: Sequence[int]) -> int:
    from app.services.own_hiring import booking as booking_service  # noqa: PLC0415

    now = now_utc()
    rows = await db.scalars(
        select(OwnHiringApplication)
        .where(
            OwnHiringApplication.process_id == ctx.process.id,
            OwnHiringApplication.id.in_(application_ids),
            OwnHiringApplication.stage != "closed",
        )
        .with_for_update()
    )
    closed = list(rows)
    cancelled: list[OwnHiringBooking] = []
    for application in closed:
        cancelled.extend(await booking_service.release_active(db, application, now))
        close(application, "rejected", now)
        log_event(db, application, "rejected", actor_id=ctx.user.id)
    await db.commit()
    await booking_service.cancel_in_calendar(db, ctx.process, cancelled)
    return len(closed)


async def hand_off(
    db: AsyncSession, ctx: Context, application_ids: Sequence[int]
) -> int:
    if ctx.process.assistant_user_id is None:
        raise OwnHiringError(
            409,
            "assistant_missing",
            "Najpierw wskaż asystentkę w ustawieniach procesu.",
        )
    now = now_utc()
    rows = await db.scalars(
        select(OwnHiringApplication)
        .where(
            OwnHiringApplication.process_id == ctx.process.id,
            OwnHiringApplication.id.in_(application_ids),
            OwnHiringApplication.stage.in_(("no_response", "invited")),
        )
        .with_for_update()
    )
    moved = list(rows)
    for application in moved:
        set_stage(application, "assistant", now)
        application.handed_off_at = now
        application.call_attempts = 0
        application.callback_at = None
        log_event(db, application, "handed_off", actor_id=ctx.user.id)
    if moved:
        await notify(
            db,
            user_id=ctx.process.assistant_user_id,
            title="Nowe telefony do umówienia",
            message="Artur przekazał Ci osoby do zadzwonienia.",
            entity_type=ENTITY_PROCESS,
            entity_id=ctx.process.id,
        )
    await db.commit()
    return len(moved)


async def move(
    db: AsyncSession, ctx: Context, application_id: int, stage: str
) -> dict[str, Any]:
    if stage not in MOVABLE_STAGES:
        raise OwnHiringError(
            422, "bad_stage", "Na ten etap nie można przenieść ręcznie."
        )
    application = await _application(db, ctx.process, application_id, lock=True)
    now = now_utc()
    previous = application.stage
    set_stage(application, stage, now)
    if stage == "signed" and application.signed_at is None:
        application.signed_at = now
    if stage == "new":
        application.bucket = "match"
    log_event(
        db, application, "moved", actor_id=ctx.user.id, previous=previous, stage=stage
    )
    await db.commit()
    return await detail(db, ctx.process, application_id)


async def teams_outcome(
    db: AsyncSession,
    ctx: Context,
    application_id: int,
    *,
    availability: Optional[str],
    expected_money: Optional[str],
    tech_level: Optional[str],
    note: Optional[str],
    decision: Literal["office", "reject"],
    office_start: Optional[datetime],
) -> dict[str, Any]:
    from app.services.own_hiring import booking as booking_service  # noqa: PLC0415

    application = await _application(db, ctx.process, application_id, lock=True)
    if application.stage != "teams":
        raise OwnHiringError(
            409, "wrong_stage", "Ta osoba nie jest na etapie rozmowy Teams."
        )
    now = now_utc()
    application.availability = availability
    application.expected_money = expected_money
    application.tech_level = tech_level
    application.teams_note = note
    await booking_service.finish_active(db, application)
    log_event(
        db,
        application,
        "teams_done",
        actor_id=ctx.user.id,
        decision=decision,
        availability=availability,
        tech_level=tech_level,
    )
    created: Optional[OwnHiringBooking] = None
    if decision == "reject":
        close(application, "rejected", now)
    else:
        if office_start is None:
            raise OwnHiringError(
                422, "office_start_required", "Wybierz termin w biurze."
            )
        created = await booking_service.create_office(
            db, ctx, application, office_start, now
        )
    await db.commit()
    if created is not None:
        await booking_service.sync_to_calendar(db, created.id)
    return await detail(db, ctx.process, application_id)


async def office_outcome(
    db: AsyncSession,
    ctx: Context,
    application_id: int,
    *,
    note: Optional[str],
    decision: Literal["contract", "withdraw"],
    contract_kind: Optional[str],
) -> dict[str, Any]:
    from app.services.own_hiring import booking as booking_service  # noqa: PLC0415

    application = await _application(db, ctx.process, application_id, lock=True)
    if application.stage != "office":
        raise OwnHiringError(
            409, "wrong_stage", "Ta osoba nie jest na etapie rozmowy w biurze."
        )
    now = now_utc()
    application.office_note = note
    await booking_service.finish_active(db, application)
    if decision == "contract":
        application.contract_kind = contract_kind
        application.contract_sent_at = now
        set_stage(application, "contract", now)
    else:
        close(application, "withdrawn", now)
    log_event(db, application, "office_done", actor_id=ctx.user.id, decision=decision)
    await db.commit()
    return await detail(db, ctx.process, application_id)


async def contract_outcome(
    db: AsyncSession,
    ctx: Context,
    application_id: int,
    *,
    decision: Literal["signed", "withdrawn"],
) -> dict[str, Any]:
    application = await _application(db, ctx.process, application_id, lock=True)
    if application.stage != "contract":
        raise OwnHiringError(409, "wrong_stage", "Ta osoba nie ma wysłanej umowy.")
    now = now_utc()
    if decision == "signed":
        application.signed_at = now
        set_stage(application, "signed", now)
    else:
        close(application, "withdrawn", now)
    log_event(db, application, "contract_done", actor_id=ctx.user.id, decision=decision)
    await db.commit()
    return await detail(db, ctx.process, application_id)


async def no_show(
    db: AsyncSession, ctx: Context, application_id: int
) -> dict[str, Any]:
    from app.services.own_hiring import booking as booking_service  # noqa: PLC0415

    application = await _application(db, ctx.process, application_id, lock=True)
    if application.stage != "teams":
        raise OwnHiringError(
            409, "wrong_stage", "Ta osoba nie jest na etapie rozmowy Teams."
        )
    now = now_utc()
    await booking_service.finish_active(db, application)
    set_stage(application, "assistant", now)
    application.handed_off_at = now
    application.call_attempts = 0
    application.callback_at = None
    log_event(db, application, "no_show", actor_id=ctx.user.id)
    await db.commit()
    return await detail(db, ctx.process, application_id)


# ── Kolejka asystentki ─────────────────────────────────────────────


async def call_queue(
    db: AsyncSession, process: OwnHiringProcess
) -> list[dict[str, Any]]:
    """Tylko pola potrzebne do telefonu: bez CV, oczekiwań i notatek z rozmów."""
    callback_first = case((OwnHiringApplication.callback_at.is_(None), 1), else_=0)
    rows = (
        await db.execute(
            select(OwnHiringApplication, Candidate)
            .join(Candidate, Candidate.id == OwnHiringApplication.candidate_id)
            .where(
                OwnHiringApplication.process_id == process.id,
                OwnHiringApplication.stage == "assistant",
            )
            .order_by(
                callback_first,
                OwnHiringApplication.callback_at,
                OwnHiringApplication.call_attempts,
                OwnHiringApplication.handed_off_at,
            )
        )
    ).all()
    return [
        {
            "id": app.id,
            "name": _person_name(candidate),
            "phone": candidate.phone,
            "ad_title": app.ad_title,
            "invited_at": app.invited_at,
            "handed_off_at": app.handed_off_at,
            "call_attempts": app.call_attempts,
            "callback_at": app.callback_at,
            "max_attempts": MAX_CALL_ATTEMPTS,
        }
        for app, candidate in rows
    ]


async def call_result(
    db: AsyncSession,
    ctx: Context,
    application_id: int,
    *,
    result: Literal["no_answer", "callback", "withdrawn"],
    callback_at: Optional[datetime],
) -> None:
    application = await _application(db, ctx.process, application_id, lock=True)
    if application.stage != "assistant":
        raise OwnHiringError(409, "wrong_stage", "Tej osoby nie ma już w kolejce.")
    now = now_utc()
    if result == "callback":
        if callback_at is None or callback_at <= now:
            raise OwnHiringError(
                422, "callback_invalid", "Podaj przyszły termin telefonu."
            )
        application.callback_at = callback_at
    elif result == "withdrawn":
        close(application, "withdrawn", now)
    else:
        application.call_attempts += 1
        application.callback_at = None
        if application.call_attempts >= MAX_CALL_ATTEMPTS:
            set_stage(application, "no_response", now)
            log_event(db, application, "attempts_exhausted", actor_id=ctx.user.id)
    log_event(db, application, f"call_{result}", actor_id=ctx.user.id)
    await db.commit()


# ── Proces ─────────────────────────────────────────────────────────


async def create_process(
    db: AsyncSession,
    *,
    owner: User,
    title: str,
    ad_titles: list[str],
    intake_since: datetime,
) -> OwnHiringProcess:
    existing = await context_for(db, owner)
    if existing is not None:
        raise OwnHiringError(
            409, "process_exists", "Masz już proces rekrutacji własnej."
        )
    process = OwnHiringProcess(
        title=title,
        owner_user_id=owner.id,
        ad_titles=ad_titles,
        settings=dict(DEFAULT_SETTINGS),
        intake_since=intake_since,
    )
    db.add(process)
    await db.commit()
    await db.refresh(process)
    return process


async def assistant_options(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(User.id, User.name).where(User.is_active.is_(True)).order_by(User.name)
    )
    return [{"id": user_id, "name": name} for user_id, name in rows]


async def update_settings(
    db: AsyncSession,
    ctx: Context,
    *,
    title: str,
    ad_titles: list[str],
    assistant_user_id: Optional[int],
    settings: dict[str, Any],
) -> OwnHiringProcess:
    process = ctx.process
    if assistant_user_id is not None:
        active = await db.scalar(
            select(User.id).where(
                User.id == assistant_user_id, User.is_active.is_(True)
            )
        )
        if active is None:
            raise OwnHiringError(
                422, "assistant_invalid", "Nie ma takiego aktywnego konta."
            )
        if assistant_user_id == process.owner_user_id:
            raise OwnHiringError(
                422, "assistant_invalid", "Właściciel nie może być asystentem."
            )
    process.title = title
    process.ad_titles = ad_titles
    process.assistant_user_id = assistant_user_id
    process.settings = {**merged_settings(process), **settings}
    await db.commit()
    await db.refresh(process)
    return process


def process_out(process: OwnHiringProcess) -> dict[str, Any]:
    return {
        "id": process.id,
        "title": process.title,
        "ad_titles": process.ad_titles,
        "assistant_user_id": process.assistant_user_id,
        "settings": merged_settings(process),
        "intake_since": process.intake_since,
    }
