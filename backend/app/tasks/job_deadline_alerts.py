"""Daily scanner — alert o zbliżającym się deadline rekrutacji (``Job.deadline``).

Emituje notyfikacje 7/3/1 dni przed ``Job.deadline`` dla otwartych (status=
``published``) rekrutacji do **przypisanych/delegowanych** osób projektu:

    - ``Job.recruiter_id``     — owner/rekruter prowadzący
    - ``Job.delivery_lead_id`` — Delivery Lead projektu
    - ``Job.tac_id``           — TAC projektu
    - aktywni ``job_collaborators`` (``removed_from_auto_cc=False``)

Świadomie NIE fan-outujemy do wszystkich adminów (inaczej niż globalne alerty
umów w ``dl_portal_expiry_scanner``) — deadline procesu dotyczy zespołu, który
go prowadzi, więc odbiorcy = osoby przypisane. Każdy odbiorca przechodzi przez
te same bramki co Job Chat: konto aktywne + dostęp do domeny kandydatów.

Dwa przebiegi w ``run_once``:

1. **creation** — dla każdego progu wybiera joby z ``deadline == today+N`` i
   ``status=published``, tworzy ``Notification`` (in-app + WS w UI przez
   polling/WS invalidation). Dedup przez ``related_entity=(job, id)`` +
   ``notification_type`` — jeden alert per (user, job, próg) na zawsze
   (deadline to stała data; próg odpala się raz).
2. **email dispatch** — drenuje notyfikacje deadline z ``email_sent_at IS NULL``
   przez atomowy claim/mark (wzorzec z ``chat_email_fallback``): rezerwacja
   ``email_send_started_at`` PRZED SMTP, stempel ``email_sent_at`` dopiero po
   potwierdzonej wysyłce. Crash w oknie zostawia odzyskiwalną rezerwację, nie
   gubi maila. Email bramkowany przez ``SMTP_ENABLED`` (off → retry w kolejnym
   przebiegu). Kill-switch całości: ``JOB_DEADLINE_ALERTS_ENABLED``.

Wzorzec: ``app/tasks/dl_portal_expiry_scanner.py`` (daily 24h loop, dedup przez
``related_entity``) + ``app/tasks/chat_email_fallback.py`` (email outbox claim).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.email import email_channel_enabled, send_email
from app.services.m365.system_mail import (
    get_system_sender_connection,
    send_system_email,
)

logger = logging.getLogger(__name__)

_INTERVAL_HOURS = 24.0

# Próg (dni) → typ notyfikacji. Iterujemy po tym mapowaniu przecinając je z
# konfigurowalnym ``JOB_DEADLINE_ALERT_THRESHOLDS_DAYS`` — nowy próg wymaga
# dołożenia wariantu enuma, więc mapa jest źródłem prawdy o dostępnych progach.
_NTYPE_BY_DAY = {
    7: NotificationType.job_deadline_7d,
    3: NotificationType.job_deadline_3d,
    1: NotificationType.job_deadline_1d,
}

_DEADLINE_NTYPES = tuple(_NTYPE_BY_DAY.values())

_ENTITY_TYPE = "job"

# Rezerwacja starsza niż to (crash w trakcie wysyłki) może być przejęta ponownie.
_CLAIM_STALE_MIN = 15
# Maks. maili na jeden przebieg email (ochrona przed N+1 / długim cyklem).
_EMAIL_BATCH = 200


def _active_thresholds() -> list[int]:
    """Progi (dni) do przeskanowania — przecięcie configu i dostępnych enumów."""
    return [
        d for d in settings.JOB_DEADLINE_ALERT_THRESHOLDS_DAYS if d in _NTYPE_BY_DAY
    ]


async def _assigned_user_ids(db: AsyncSession, job: Job) -> list[int]:
    """user_id przypisanych/delegowanych do joba (bez globalnych adminów).

    owner recruiter + DL + TAC + aktywni collaboratorzy, przefiltrowani do
    kont aktywnych z dostępem do domeny kandydatów (ten sam kontrakt co Job Chat).
    """
    candidate_ids: set[int] = set()
    for uid in (job.recruiter_id, job.delivery_lead_id, job.tac_id):
        if uid:
            candidate_ids.add(uid)

    rows = await db.execute(
        select(JobCollaborator.user_id)
        .where(JobCollaborator.job_id == job.id)
        .where(JobCollaborator.removed_from_auto_cc.is_(False))
    )
    for (uid,) in rows.all():
        if uid:
            candidate_ids.add(uid)

    if not candidate_ids:
        return []

    eligible = await db.execute(
        select(User).where(User.id.in_(candidate_ids)).where(User.is_active.is_(True))
    )
    return sorted(
        u.id for u in eligible.scalars().all() if user_can_access_candidate_domain(u)
    )


async def _existing_pairs(
    db: AsyncSession, job_ids: list[int], ntype: NotificationType
) -> set[tuple[int, int]]:
    """Zbiór (user_id, job_id) już powiadomionych dla danego typu — jednym SELECT-em.

    Zastępuje per-odbiorcę ``_already_notified`` (N+1) jednym zapytaniem na
    (próg × partia jobów), więc liczba roundtripów nie rośnie z liczbą
    odbiorców ani jobów w danym progu.
    """
    if not job_ids:
        return set()
    rows = await db.execute(
        select(Notification.user_id, Notification.related_entity_id).where(
            Notification.related_entity_type == _ENTITY_TYPE,
            Notification.related_entity_id.in_(job_ids),
            Notification.notification_type == ntype,
        )
    )
    return {(r.user_id, r.related_entity_id) for r in rows.all()}


async def _scan_and_create(db: AsyncSession) -> int:
    """Utwórz in-app notyfikacje dla nadchodzących deadline'ów. Zwraca # nowych."""
    # UTC-anchored (host bywa nie-UTC) — zgodnie z resztą kodu.
    today = datetime.now(timezone.utc).date()
    created = 0
    for days in _active_thresholds():
        target = today + timedelta(days=days)
        ntype = _NTYPE_BY_DAY[days]
        jobs = list(
            (
                await db.execute(
                    select(Job).where(
                        Job.status == JobStatus.published,
                        Job.deadline == target,
                    )
                )
            ).scalars()
        )
        already = await _existing_pairs(db, [j.id for j in jobs], ntype)
        for job in jobs:
            recipients = await _assigned_user_ids(db, job)
            for user_id in recipients:
                if (user_id, job.id) in already:
                    continue
                # Guard przeciw ewentualnym duplikatom w obrębie jednego przebiegu.
                already.add((user_id, job.id))
                day_word = "dzień" if days == 1 else "dni"
                db.add(
                    Notification(
                        user_id=user_id,
                        title=f"Deadline rekrutacji za {days} {day_word}",
                        message=(
                            f"Rekrutacja „{job.title}” ma deadline "
                            f"{job.deadline.isoformat()} (za {days} {day_word}). "
                            "Sprawdź status procesu i kandydatów."
                        ),
                        notification_type=ntype,
                        related_entity_type=_ENTITY_TYPE,
                        related_entity_id=job.id,
                        link=f"/jobs/{job.id}",
                    )
                )
                created += 1
    return created


async def _claim_email(db: AsyncSession, notif_id: int) -> bool:
    """Atomowo zarezerwuj wiersz do wysyłki emaila (bez stempla „wysłane").

    UPDATE ``email_send_started_at=now()`` pod warunkiem ``email_sent_at IS NULL``
    i (rezerwacja NULL lub starsza niż ``_CLAIM_STALE_MIN``). Zwraca True tylko
    dla zwycięzcy wyścigu; commit natychmiast zwalnia lock i uwidacznia rezerwację
    innym workerom (brak leader-election → możliwy overlap; to jest gwarancja
    exactly-once dla emaila).
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=_CLAIM_STALE_MIN)
    res = await db.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.email_sent_at.is_(None),
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


async def _mark_email_sent(db: AsyncSession, notif_id: int) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_sent_at=func.now())
    )
    await db.commit()


async def _release_email_claim(db: AsyncSession, notif_id: int) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id)
        .values(email_send_started_at=None)
    )
    await db.commit()


async def _dispatch_emails(db: AsyncSession) -> int:
    """Wyślij email dla deadline-notyfikacji bez ``email_sent_at``. Zwraca # wysłanych.

    Priorytet kanału: **delegated** (skrzynka serwisowa podłączona w Nexusie przez
    „Połącz Microsoft 365") → inaczej ``send_email`` (Graph app-only / SMTP).
    Delegated nie wymaga admin-consentu w Azure — działa gdy ktoś podłączył
    ``M365_MAIL_SENDER_UPN`` w UI.
    """
    connection = await get_system_sender_connection(db)
    if connection is None and not email_channel_enabled():
        # Żaden kanał (delegated, Graph app-only, SMTP) — nie rezerwuj, retry później.
        return 0

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=_CLAIM_STALE_MIN)
    rows = await db.execute(
        select(Notification, User)
        .join(User, User.id == Notification.user_id)
        .where(Notification.notification_type.in_(_DEADLINE_NTYPES))
        .where(User.is_active.is_(True))
        .where(Notification.email_sent_at.is_(None))
        .where(
            or_(
                Notification.email_send_started_at.is_(None),
                Notification.email_send_started_at <= stale_cutoff,
            )
        )
        .order_by(Notification.created_at.asc())
        .limit(_EMAIL_BATCH)
    )
    pairs = rows.all()
    if not pairs:
        return 0

    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    sent = 0
    for notif, user in pairs:
        # Re-check bieżących uprawnień do domeny kandydatów zanim poleci PII.
        if not user.email or not user_can_access_candidate_domain(user):
            continue
        if not await _claim_email(db, notif.id):
            continue
        # Stan roli/konta mógł się zmienić między SELECT-em a claimem.
        await db.refresh(user, attribute_names=["role", "roles", "is_active"])
        if not user.is_active or not user_can_access_candidate_domain(user):
            await _release_email_claim(db, notif.id)
            continue

        link = f"{base}{notif.link}" if base and notif.link else (notif.link or "/")
        subject = f"[Nexus] {notif.title}"
        text_body = (
            f"Cześć {user.name or user.email},\n\n"
            f"{notif.title}\n\n"
            f"{notif.message}\n\n"
            f"Otwórz w Nexusie: {link}\n\n"
            "— Nexus ATS"
        )
        ok = False
        try:
            if connection is not None:
                # Delegated Graph — async, wprost (ma sesję db).
                ok = await send_system_email(
                    db, connection, to=user.email, subject=subject, text_body=text_body
                )
            else:
                # Blocking smtplib/app-only — offload z event loopa.
                ok = await asyncio.to_thread(
                    send_email, user.email, subject, text_body, None
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "job_deadline_alerts email failed notif=%d: %s",
                notif.id,
                type(exc).__name__,
            )
        if ok:
            await _mark_email_sent(db, notif.id)
            sent += 1
        else:
            await _release_email_claim(db, notif.id)
    return sent


async def run_once() -> dict:
    """Jeden przebieg: creation + email dispatch. Zwraca summary dict."""
    if not settings.JOB_DEADLINE_ALERTS_ENABLED:
        return {"enabled": False, "created": 0, "emails_sent": 0}

    async with AsyncSessionLocal() as db:
        try:
            created = await _scan_and_create(db)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            raise

    async with AsyncSessionLocal() as db:
        emails_sent = await _dispatch_emails(db)

    summary = {"enabled": True, "created": created, "emails_sent": emails_sent}
    logger.info("job_deadline_alerts scan: %s", summary)
    return summary


async def job_deadline_alerts_loop() -> None:
    """Daily loop — pierwszy przebieg na starcie, potem co 24h."""
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("job_deadline_alerts_loop iteration failed")
        try:
            await asyncio.sleep(_INTERVAL_HOURS * 3600)
        except asyncio.CancelledError:
            raise
