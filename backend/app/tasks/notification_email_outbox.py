"""Maile natychmiast dla kilku powiadomień z dzwonka (07.10.2026).

Dzwonek ma za dużo wpisów, żeby był kanałem dla spraw, na które ktoś czeka
(pomiar 30.09–07.10.2026: czytane 0–8%). Mailem idzie od razu tylko to, co
blokuje cudzą pracę — rodzaje `IMMEDIATE_KINDS` z
`notification_delivery` (CV czeka na przegląd DL, CV wróciło do poprawy, nowa
rekrutacja, prośba o potwierdzenie podpisu, awaria automatu). Resztę zbiera
poranny skrót (`tasks/daily_digest_email.py`).

Pętla co minutę bierze wiersze `Notification` tych typów bez `email_sent_at`
i wysyła je wzorcem `job_deadline_alerts`: rezerwacja `email_send_started_at`
przed wysyłką, stempel po potwierdzeniu, wynik niepewny = bez ponowienia.
Wysyłka szanuje politykę z Ustawień (rodzaj włączony i próg
`send_not_before` — po włączeniu nie wychodzą zaległości) oraz wyciszenia
kategorii osoby (`user_can_receive_notification`). Powiadomienie starsze niż
`MAX_AGE` nie idzie mailem — po dniu przerwy w wysyłce mail byłby już tylko
przypomnieniem o rzeczy załatwionej.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services import loop_heartbeat
from app.services.email import email_channel_enabled, render_notification_email
from app.services.m365.system_mail import DELIVERY_UNCERTAIN, app_mail_send_outcome
from app.services.notification_access import user_can_receive_notification
from app.services.notification_delivery import (
    IMMEDIATE_KINDS,
    guarded_send,
    immediate_email_kind,
    load_policy,
)
from app.services.section_permissions import (
    resolve_effective_section_access,
    resolve_effective_section_access_for_users,
)
from app.services.stage_handoff_recipients import RETURNED_TITLE_PREFIXES

logger = logging.getLogger(__name__)

LOOP_SLEEP_SECONDS = 60
MAX_AGE = timedelta(hours=24)
BATCH = 50
_CLAIM_STALE_MIN = 15


def _returned_title():
    return or_(
        *(
            Notification.title.startswith(p, autoescape=True)
            for p in RETURNED_TITLE_PREFIXES
        )
    )


def kind_clause(kind: str):
    """Warunek SQL wierszy danego rodzaju — lustro `immediate_email_kind`."""
    ntype = Notification.notification_type
    if kind == "dl_review":
        return and_(
            ntype == NotificationType.board_task_waiting, not_(_returned_title())
        )
    if kind == "cv_returned":
        return and_(ntype == NotificationType.board_task_waiting, _returned_title())
    if kind == "request_assigned":
        return and_(
            ntype == NotificationType.request_assignment_changed,
            Notification.related_entity_type == "job",
        )
    if kind == "signature_request":
        return ntype == NotificationType.b2b_signature_requested
    if kind == "system_failure":
        return ntype == NotificationType.automation_failing
    raise ValueError(kind)


async def _claim(db: AsyncSession, notif_id: int) -> bool:
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=_CLAIM_STALE_MIN)
    res = await db.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.email_sent_at.is_(None),
            Notification.email_delivery_uncertain.is_(False),
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            ),
        )
        .values(email_send_started_at=func.now())
        .returning(Notification.id)
    )
    claimed = res.scalar_one_or_none() is not None
    await db.commit()
    return claimed


async def _set(db: AsyncSession, notif_id: int, **values) -> None:
    await db.execute(
        update(Notification).where(Notification.id == notif_id).values(**values)
    )
    await db.commit()


def _can_receive(user: User, notif: Notification) -> bool:
    return bool(
        user.is_active
        and user.email
        and user_can_receive_notification(
            user,
            notif.notification_type,
            related_entity_type=notif.related_entity_type,
            link=notif.link,
        )
    )


async def _due(db: AsyncSession, kinds: list[str], cutoffs: dict) -> list:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=_CLAIM_STALE_MIN)
    per_kind = [
        and_(
            kind_clause(kind),
            Notification.created_at >= max(cutoffs[kind], now - MAX_AGE),
        )
        for kind in kinds
    ]
    rows = await db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(or_(*per_kind))
        .where(User.is_active.is_(True))
        .where(Notification.email_sent_at.is_(None))
        .where(Notification.email_delivery_uncertain.is_(False))
        .where(
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            )
        )
        .order_by(Notification.created_at.asc())
        .limit(BATCH)
    )
    return rows.all()


async def dispatch(db: AsyncSession) -> int:
    """Jeden przebieg kolejki. Zwraca liczbę wysłanych maili."""
    policy = await load_policy(db)
    kinds = [k for k in IMMEDIATE_KINDS if policy.kind_enabled(k)]
    if not kinds or not email_channel_enabled():
        return 0
    cutoffs = {k: policy.cutoff_for(k) for k in kinds}
    pairs = await _due(db, kinds, cutoffs)
    if not pairs:
        return 0
    await resolve_effective_section_access_for_users(db, [u for _, u in pairs])

    sent = 0
    for notif, user in pairs:
        kind = immediate_email_kind(
            notif.notification_type,
            title=notif.title,
            related_entity_type=notif.related_entity_type,
        )
        if kind not in kinds or not _can_receive(user, notif):
            # Bez rezerwacji: wiersz wypadnie z kolejki po `MAX_AGE`.
            continue
        if not await _claim(db, notif.id):
            continue
        # Rola, sekcje i wyciszenia mogły się zmienić między odczytem a rezerwacją.
        await db.refresh(
            user,
            attribute_names=[
                "role",
                "roles",
                "is_active",
                "muted_notification_categories",
            ],
        )
        await resolve_effective_section_access(db, user)
        if not _can_receive(user, notif):
            await _set(db, notif.id, email_send_started_at=None)
            continue

        subject, text_body, html_body = render_notification_email(
            recipient_name=user.name or user.email,
            title=notif.title,
            message=notif.message,
            deep_link_path=notif.link or "/dashboard",
        )
        to_addr = user.email
        created_at = notif.created_at

        def _send(kind=kind, to_addr=to_addr, created_at=created_at) -> bool | None:
            # Flagi wyniku nadawcy żyją w wątku wysyłki — liczymy je tutaj.
            from app.services.email import send_email

            return app_mail_send_outcome(
                guarded_send(
                    kind, created_at, send_email, to_addr, subject, text_body, html_body
                )
            )

        ok: bool | None = False
        try:
            ok = await asyncio.to_thread(_send)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "notification_email_outbox: wysyłka %s notif=%d: %s",
                kind,
                notif.id,
                type(exc).__name__,
            )
        if ok is DELIVERY_UNCERTAIN:
            await _set(db, notif.id, email_delivery_uncertain=True)
        elif ok:
            await _set(db, notif.id, email_sent_at=func.now())
            sent += 1
        else:
            await _set(db, notif.id, email_send_started_at=None)
    return sent


async def run_once() -> int:
    async with AsyncSessionLocal() as db:
        sent = await dispatch(db)
    if sent:
        logger.info("notification_email_outbox: wysłano %d", sent)
    return sent


async def notification_email_outbox_loop() -> None:
    if not settings.NOTIFICATION_EMAIL_OUTBOX_ENABLED:
        logger.info("notification_email_outbox disabled")
        return
    beat = loop_heartbeat.register(
        "notification_email_outbox", max_silence_seconds=LOOP_SLEEP_SECONDS + 900
    )
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("notification_email_outbox iteration failed")
        await asyncio.sleep(LOOP_SLEEP_SECONDS)
