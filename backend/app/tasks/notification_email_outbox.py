"""Maile natychmiast dla kilku powiadomień z dzwonka (07.10.2026).

Dzwonek ma za dużo wpisów, żeby był kanałem dla spraw, na które ktoś czeka
(pomiar 30.09–07.10.2026: czytane 0–8%). Mailem idzie od razu tylko to, co
blokuje cudzą pracę — rodzaje `IMMEDIATE_KINDS` z
`notification_delivery` (CV czeka na przegląd DL, CV wróciło do poprawy, nowa
rekrutacja, prośba o potwierdzenie podpisu, awaria automatu, od 17.10.2026
sprawy „Czas i ludzie” — treść składa `services/hr/hr_mail.py`, bez rodzaju
nieobecności i kwot, od 22.10.2026 rodzaje z `BELL_MAIL_TYPES`: rozmowy
u klienta, prepy, akceptacja klienta, umowa przedwstępna, zadania od zespołu,
zatrudniony bez dokumentów). Resztę zbiera poranny skrót
(`tasks/daily_digest_email.py`).

Pętla co minutę bierze wiersze `Notification` tych typów bez `email_sent_at`
i wysyła je wzorcem `job_deadline_alerts`: rezerwacja `email_send_started_at`
przed wysyłką, stempel po potwierdzeniu, wynik niepewny = bez ponowienia.
Wysyłka szanuje politykę z Ustawień (rodzaj włączony i próg
`send_not_before` — po włączeniu nie wychodzą zaległości) oraz wyciszenia
kategorii osoby (`user_can_receive_notification`) i jej własne wyłączniki
maili (`email_opted_out`). Powiadomienie starsze niż
`MAX_AGE` nie idzie mailem — po dniu przerwy w wysyłce mail byłby już tylko
przypomnieniem o rzeczy załatwionej.

Wiersz, którego odbiorca nie dostaje (wyciszona kategoria, typ tylko dla
admina, brak sekcji, grupa wyłączona dla roli), zostaje bez rezerwacji do
`MAX_AGE`. Przebieg idzie wtedy dalej kolejnymi
stronami (kursor po `created_at`, `id`), aż spróbuje `BATCH` wysyłek —
inaczej 50 takich wierszy zatrzymywało maile wszystkich na dobę (17.10.2026).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, not_, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services import loop_heartbeat
from app.services.email import email_channel_enabled, render_card_email
from app.services.hr.approvals import mail as approval_mail
from app.services.hr.approvals import mail_reply as approval_mail_reply
from app.services.hr.hr_mail import mail_text
from app.services.m365.system_mail import DELIVERY_UNCERTAIN, app_mail_send_outcome
from app.services.notification_access import (
    user_can_receive_notification,
    user_can_receive_required_mail,
)
from app.services.notification_mail_card import MailFacts, build_card, load_facts
from app.services.notification_delivery import (
    BELL_MAIL_TYPES,
    HR_MAIL_KIND,
    HR_MAIL_TYPES,
    IMMEDIATE_KINDS,
    REQUIRED_KINDS,
    email_queue_clause,
    email_wanted,
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
# Ile stron po `BATCH` przejrzeć w jednym przebiegu, zanim spróbuje się
# `BATCH` wysyłek — górna granica pracy przy wielu wierszach bez odbiorcy.
MAX_PAGES = 20
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
        return ntype.in_(
            [
                NotificationType.automation_failing,
                NotificationType.teams_prep_scope_missing,
            ]
        )
    if kind == "data_access_alert":
        return ntype == NotificationType.candidate_data_access_alert
    if kind == HR_MAIL_KIND:
        return ntype.in_([NotificationType(value) for value in HR_MAIL_TYPES])
    if kind in BELL_MAIL_TYPES:
        return ntype.in_([NotificationType(value) for value in BELL_MAIL_TYPES[kind]])
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


def _can_receive(user: User, notif: Notification, kind: str) -> bool:
    # Mail obowiązkowy (26.10.2026): wyciszona kategoria w dzwonku go nie
    # zatrzymuje. Grupa wyłączona dla roli przez admina i sekcje — tak.
    reach = (
        user_can_receive_required_mail
        if kind in REQUIRED_KINDS
        else user_can_receive_notification
    )
    return bool(
        user.is_active
        and user.email
        # Własny wyłącznik maila („Maile do Ciebie”); dzwonek zostaje.
        and email_wanted(user, kind, notif.created_at)
        and reach(
            user,
            notif.notification_type,
            related_entity_type=notif.related_entity_type,
            link=notif.link,
        )
    )


async def _due(
    db: AsyncSession,
    kinds: list[str],
    cutoffs: dict,
    after: tuple[datetime, int] | None = None,
) -> list:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=_CLAIM_STALE_MIN)
    per_kind = [
        and_(
            kind_clause(kind),
            Notification.created_at >= max(cutoffs[kind], now - MAX_AGE),
            # Własny wyłącznik maila — w zapytaniu, żeby nie zajmował paczki.
            email_queue_clause(kind, Notification.created_at),
        )
        for kind in kinds
    ]
    query = (
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
        .order_by(Notification.created_at.asc(), Notification.id.asc())
        .limit(BATCH)
    )
    if after is not None:
        query = query.where(
            tuple_(Notification.created_at, Notification.id) > tuple_(*after)
        )
    return (await db.execute(query)).all()


async def dispatch(db: AsyncSession) -> int:
    """Jeden przebieg kolejki. Zwraca liczbę wysłanych maili."""
    policy = await load_policy(db)
    kinds = [k for k in IMMEDIATE_KINDS if policy.kind_enabled(k)]
    if not kinds or not email_channel_enabled():
        return 0
    cutoffs = {k: policy.cutoff_for(k) for k in kinds}

    sent = attempted = 0
    after: tuple[datetime, int] | None = None
    for _ in range(MAX_PAGES):
        pairs = await _due(db, kinds, cutoffs, after)
        if not pairs:
            break
        last = pairs[-1][0]
        after = (last.created_at, last.id)
        await resolve_effective_section_access_for_users(db, [u for _, u in pairs])
        for notif, user in pairs:
            outcome = await _deliver(db, notif, user, kinds)
            if outcome is None:
                continue
            attempted += 1
            sent += int(outcome)
            if attempted >= BATCH:
                return sent
        if len(pairs) < BATCH:
            break
    return sent


async def _facts(db: AsyncSession, notif: Notification) -> MailFacts:
    # Fakty są dodatkiem: bez nich mail wychodzi z tytułem i opisem dzwonka.
    # Savepoint, bo pełny rollback wygasiłby `notif` i `user` przed wysyłką.
    notif_id = notif.id
    try:
        async with db.begin_nested():
            return await load_facts(db, notif)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notification_email_outbox: fakty notif=%d: %s",
            notif_id,
            type(exc).__name__,
        )
        return MailFacts()


async def _deliver(
    db: AsyncSession, notif: Notification, user: User, kinds: list[str]
) -> bool | None:
    """``True`` wysłany, ``False`` próba bez wysyłki, ``None`` bez próby."""

    kind = immediate_email_kind(
        notif.notification_type,
        title=notif.title,
        related_entity_type=notif.related_entity_type,
    )
    if kind not in kinds or not _can_receive(user, notif, kind):
        # Bez rezerwacji: wiersz wypadnie z kolejki po `MAX_AGE`, a przebieg
        # idzie dalej kursorem, więc nie zajmuje miejsca innym.
        return None
    if not await _claim(db, notif.id):
        return None
    # Rola, sekcje i wyciszenia mogły się zmienić między odczytem a rezerwacją.
    await db.refresh(
        user,
        attribute_names=[
            "role",
            "roles",
            "is_active",
            "muted_notification_categories",
            "email_opt_outs",
        ],
    )
    await resolve_effective_section_access(db, user)
    if not _can_receive(user, notif, kind):
        await _set(db, notif.id, email_send_started_at=None)
        return None

    extra: dict[str, str] = {}
    if notif.notification_type == NotificationType.hr_approval_requested:
        # Zgoda do decyzji: kwota i „po co” tylko decydującemu (20.10.2026).
        # Zgoda już rozpatrzona albo u kogoś innego — bez maila.
        rendered = await approval_mail.render(db, notif, user)
        if rendered is None:
            await _set(db, notif.id, email_send_started_at=None)
            return None
        subject, text_body, html_body = rendered
        # Etap 2: odpowiedź „approved” idzie do skrzynki, którą czyta NEXUS.
        reply_to = approval_mail_reply.reply_mailbox()
        if reply_to and notif.related_entity_type == "approval_request":
            extra["reply_to"] = reply_to
    else:
        title, message = notif.title, notif.message
        if kind == HR_MAIL_KIND:
            # Mail wychodzi poza aplikację: bez rodzaju nieobecności i kwot (D6).
            title, message = mail_text(notif.notification_type, title, message)
        subject, text_body, html_body = render_card_email(
            build_card(
                notification_type=notif.notification_type.value,
                kind=kind,
                title=title,
                message=message,
                link=notif.link,
                required=kind in REQUIRED_KINDS,
                facts=await _facts(db, notif),
                entity_ref=(
                    str(notif.related_entity_id) if notif.related_entity_id else None
                ),
            )
        )
    to_addr = user.email
    created_at = notif.created_at

    def _send(kind=kind, to_addr=to_addr, created_at=created_at) -> bool | None:
        # Flagi wyniku nadawcy żyją w wątku wysyłki — liczymy je tutaj.
        from app.services.email import send_email

        return app_mail_send_outcome(
            guarded_send(
                kind,
                created_at,
                send_email,
                to_addr,
                subject,
                text_body,
                html_body,
                **extra,
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
        return False
    if ok:
        await _set(db, notif.id, email_sent_at=func.now())
        return True
    await _set(db, notif.id, email_send_started_at=None)
    return False


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
