"""Kolejka komunikatów do konsultantów — 30 maili na minutę (O12).

``run_once`` wpina koordynator w pętlę ``app/tasks/hr_loops.py`` (co 60 s).
Każdy przebieg:

* nic nie robi przy wyłączonym module opieki, wyłączonym przełączniku wysyłki
  (``app_settings['care_announcements']``, domyślnie brak = wyłączona) albo bez
  nadawcy administracja@ — kolejka stoi, nikt nic nie dostaje,
* rezerwuje MINUTĘ w ``hr_job_runs`` (``job_runs.claim``): drugi proces albo
  restart w tej samej minucie nie wyśle drugiej trzydziestki,
* bierze najwyżej ``RATE_PER_MINUTE`` osób (najstarszy komunikat pierwszy),
  oznacza je „w wysyłce” i commituje PRZED wysłaniem — przerwany przebieg nie
  wyśle nikomu drugiego maila: osoba „w wysyłce” dłużej niż ``STUCK_AFTER``
  dostaje stan „niepewny” (bez ponowienia),
* token wypisu (informacyjne) trafia do bazy jako SHA-256 przed wysyłką, więc
  link z maila zawsze działa,
* odłożona wysyłka (429, 5xx, brak tokenu) wraca do kolejki do
  ``MAX_ATTEMPTS`` prób; odrzucona (np. 400 — zły adres) to „błąd”.

Jeden adresat na mail. Logi niosą tylko liczby i identyfikatory.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.care_announcement import (
    CareAnnouncement,
    CareAnnouncementOptOut,
    CareAnnouncementRecipient,
)
from app.models.user import User
from app.services.care import announcement_mail as mail
from app.services.care.announcements import RATE_PER_MINUTE, sending_enabled
from app.services.hr import job_runs
from app.services.hr import modules as hr_modules

logger = logging.getLogger(__name__)

JOB_KIND = "care_announcements_send"
STUCK_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3

_R = CareAnnouncementRecipient
_A = CareAnnouncement


async def _expire_stuck(db: AsyncSession) -> int:
    result = await db.execute(
        update(_R)
        .where(
            _R.status == "sending",
            _R.claimed_at < func.now() - STUCK_AFTER,
        )
        .values(status="uncertain", error_code="interrupted", updated_at=func.now())
    )
    return result.rowcount or 0


async def _claim_batch(db: AsyncSession) -> list[int]:
    ids = list(
        (
            await db.scalars(
                select(_R.id)
                .join(_A, _A.id == _R.announcement_id)
                .where(_A.status == "queued", _R.status == "pending")
                .order_by(_A.queued_at, _A.id, _R.id)
                .limit(RATE_PER_MINUTE)
                .with_for_update(of=_R, skip_locked=True)
            )
        ).all()
    )
    if ids:
        await db.execute(
            update(_R)
            .where(_R.id.in_(ids))
            .values(
                status="sending",
                claimed_at=func.now(),
                attempts=_R.attempts + 1,
                updated_at=func.now(),
            )
        )
        await db.execute(
            update(_A)
            .where(
                _A.id.in_(select(_R.announcement_id).where(_R.id.in_(ids))),
                _A.send_started_at.is_(None),
            )
            .values(send_started_at=func.now())
        )
    await db.commit()
    return ids


async def _owner_label(db: AsyncSession, owner_id: Optional[int]) -> str:
    owner = await db.get(User, owner_id) if owner_id else None
    if owner is None or not owner.is_active:
        return mail.owner_label(None, None)
    return mail.owner_label(owner.name, owner.email)


async def _send_one(
    db: AsyncSession,
    sender: mail.AnnouncementMailer,
    recipient_id: int,
    counts: Counter[str],
) -> None:
    recipient = await db.get(_R, recipient_id, populate_existing=True)
    announcement = await db.get(_A, recipient.announcement_id, populate_existing=True)
    if announcement.status != "queued":
        recipient.status = "cancelled"
        counts["cancelled"] += 1
        await db.commit()
        return
    informational = announcement.kind == "informational"
    if informational and await db.get(CareAnnouncementOptOut, recipient.candidate_id):
        # Wypis po zamrożeniu listy — informacyjny już nie idzie.
        recipient.status = "excluded_opted_out"
        counts["opted_out"] += 1
        await db.commit()
        return
    raw_token: Optional[str] = None
    if informational:
        raw_token, hashed = mail.new_token()
        recipient.unsubscribe_token_sha256 = hashed
    owner = await _owner_label(db, recipient.owner_user_id)
    subject, body = mail.compose(
        announcement_id=announcement.id,
        code=announcement.code,
        kind=announcement.kind,
        subject=announcement.subject,
        body=announcement.body,
        first_name=recipient.first_name,
        owner=owner,
        unsubscribe=mail.unsubscribe_url(raw_token) if raw_token else None,
    )
    to = recipient.email
    attempts = recipient.attempts
    # Hash tokenu w bazie przed wysyłką: link z maila zawsze trafi na wiersz.
    await db.commit()

    try:
        outcome = await sender.send(to=to, subject=subject, text=body)
    except Exception:  # noqa: BLE001 — wynik nieznany, bez ponowienia
        logger.exception(
            "[care_announcements] wysyłka recipient=%s padła", recipient_id
        )
        outcome = mail.MailOutcome("uncertain", "exception")

    recipient = await db.get(_R, recipient_id, populate_existing=True)
    recipient.error_code = outcome.code
    if outcome.status == "accepted":
        recipient.status = "sent"
        recipient.sent_at = datetime.now(timezone.utc)
        recipient.simulated = outcome.simulated
        recipient.error_code = None
        counts["sent"] += 1
    elif outcome.status == "deferred" and attempts < MAX_ATTEMPTS:
        recipient.status = "pending"
        counts["deferred"] += 1
    elif outcome.status == "uncertain":
        recipient.status = "uncertain"
        counts["uncertain"] += 1
    else:
        recipient.status = "failed"
        counts["failed"] += 1
    await db.commit()


async def _finish_announcements(db: AsyncSession) -> int:
    open_rows = exists().where(
        _R.announcement_id == _A.id, _R.status.in_(("pending", "sending"))
    )
    result = await db.execute(
        update(_A)
        .where(_A.status == "queued", ~open_rows)
        .values(status="sent", send_finished_at=func.now(), updated_at=func.now())
    )
    await db.commit()
    return result.rowcount or 0


async def run_once(
    db: AsyncSession,
    *,
    mailer: Optional[mail.AnnouncementMailer] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Jeden przebieg kolejki. Nie rzuca; wynik w ``hr_job_runs``."""

    modules = await hr_modules.load_modules(db)
    if not modules.get(hr_modules.HrModule.care):
        return {"status": "disabled", "reason": "module"}
    if not await sending_enabled(db):
        return {"status": "disabled", "reason": "switch"}
    sender = mailer or mail.default_mailer()
    if sender is None:
        return {"status": "disabled", "reason": "transport"}
    moment = now or datetime.now(timezone.utc)
    minute = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    run_id = await job_runs.claim(db, JOB_KIND, minute, moment)
    if run_id is None:
        return {"status": "skipped", "reason": "minute_taken"}

    counts: Counter[str] = Counter()
    status = "done"
    error: Optional[str] = None
    try:
        counts["interrupted"] += await _expire_stuck(db)
        for recipient_id in await _claim_batch(db):
            await _send_one(db, sender, recipient_id, counts)
        counts["finished"] += await _finish_announcements(db)
    except Exception as exc:  # noqa: BLE001 — przebieg nie wywraca pętli
        logger.exception("[care_announcements] przebieg kolejki padł")
        await db.rollback()
        status = "failed"
        error = type(exc).__name__
    try:
        await job_runs.finish(
            db, run_id, status=status, counts=dict(counts), error=error
        )
    except Exception:  # noqa: BLE001 — rezerwacja i tak wygaśnie
        logger.exception("[care_announcements] nie zapisano wyniku przebiegu")
        await db.rollback()
    logger.info("[care_announcements] kolejka: %s %s", status, dict(counts))
    return {"status": "ok" if status == "done" else "error", **counts}
