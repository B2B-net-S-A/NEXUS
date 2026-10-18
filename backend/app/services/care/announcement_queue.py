"""Kolejka komunikatów do konsultantów — 30 maili na minutę (O12).

``run_once`` wpina koordynator w pętlę ``app/tasks/hr_loops.py`` (co 60 s).
Każdy przebieg:

* nic nie robi przy wyłączonym module opieki, wyłączonym przełączniku wysyłki
  (``app_settings['care_announcements']``, domyślnie brak = wyłączona), bez
  nadawcy administracja@ albo bez niczego do wysłania (wtedy nie zakłada też
  wiersza w ``hr_job_runs``) — kolejka stoi, nikt nic nie dostaje,
* rezerwuje MINUTĘ w ``hr_job_runs`` (``job_runs.claim``): drugi proces albo
  restart w tej samej minucie nie wyśle drugiej trzydziestki,
* bierze najwyżej ``RATE_PER_MINUTE`` osób (najstarszy komunikat pierwszy),
  oznacza je „w wysyłce” i commituje PRZED wysłaniem. ``claimed_at`` stempluje
  dopiero chwila wysyłki do danej osoby: przerwany przebieg zostawia osobę
  ze stemplem jako „niepewną” (mail mógł wyjść, bez ponowienia), a bez stempla
  — wraca do kolejki (mail na pewno nie wyszedł),
* każda osoba jest osobno: brak wiersza (usunięty kandydat) = pominięcie,
  błąd przygotowania maila liczy jej próbę, przebieg idzie dalej,
* token wypisu (informacyjne) trafia do bazy jako SHA-256 przed wysyłką, więc
  link z maila zawsze działa,
* awaria całego połączenia (brak tokenu, 401, 403, brak połączenia z Graph)
  kończy przebieg od razu: osoba w toku i reszta paczki wracają do kolejki BEZ
  liczenia próby, wynik mówi ``deferred`` / ``transport``,
* odłożona wysyłka jednej osoby (408, 429, 5xx) wraca do kolejki do
  ``MAX_ATTEMPTS`` prób; odrzucona (np. 400 — zły adres) to „błąd”, który
  autor może wysłać ponownie (``announcements.retry_failed``).

Jeden adresat na mail. Logi niosą tylko liczby, identyfikatory i kody.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import case, exists, func, or_, select, update
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


async def _has_work(db: AsyncSession) -> bool:
    """Komunikat w kolejce albo osoba „w wysyłce” (do wygaszenia)."""

    queued = exists().where(_A.status == "queued")
    sending = exists().where(_R.status == "sending")
    return bool(await db.scalar(select(or_(queued, sending))))


def _unstarted_status():
    """Niewysłany wraca do kolejki; przy anulowanym komunikacie — „anulowany”."""

    queued = exists().where(_A.id == _R.announcement_id, _A.status == "queued")
    return case((queued, "pending"), else_="cancelled")


async def _expire_stuck(db: AsyncSession) -> int:
    """Osoby „w wysyłce” po przerwanym przebiegu: bez stempla wracają do
    kolejki, ze stemplem (wysyłka ruszyła) — „niepewny”."""

    stale = func.now() - STUCK_AFTER
    await db.execute(
        update(_R)
        .where(_R.status == "sending", _R.claimed_at.is_(None), _R.updated_at < stale)
        .values(status=_unstarted_status(), updated_at=func.now())
    )
    result = await db.execute(
        update(_R)
        .where(_R.status == "sending", _R.claimed_at < stale)
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
            .values(status="sending", claimed_at=None, updated_at=func.now())
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


async def _release_unstarted(db: AsyncSession, ids: list[int]) -> int:
    """Zarezerwowani, do których wysyłka nie ruszyła — z powrotem do kolejki."""

    if not ids:
        return 0
    result = await db.execute(
        update(_R)
        .where(_R.id.in_(ids), _R.status == "sending", _R.claimed_at.is_(None))
        .values(status=_unstarted_status(), updated_at=func.now())
    )
    await db.commit()
    return result.rowcount or 0


async def _owner_label(db: AsyncSession, owner_id: Optional[int]) -> str:
    owner = await db.get(User, owner_id) if owner_id else None
    if owner is None or not owner.is_active:
        return mail.owner_label(None, None)
    return mail.owner_label(owner.name, owner.email)


@dataclass(frozen=True)
class _Prepared:
    to: str
    subject: str
    body: str


async def _prepare(
    db: AsyncSession, recipient_id: int, counts: Counter[str]
) -> Optional[_Prepared]:
    """Mail jednej osoby albo ``None`` (pominięta: brak wiersza, anulowany
    komunikat, wypis). Stempel wysyłki i hash tokenu idą do bazy przed
    wysłaniem — link z maila zawsze trafi na wiersz."""

    recipient = await db.get(_R, recipient_id, populate_existing=True)
    if recipient is None or recipient.status != "sending":
        counts["missing"] += 1
        return None
    announcement = await db.get(_A, recipient.announcement_id, populate_existing=True)
    if announcement is None or announcement.status != "queued":
        recipient.status = "cancelled"
        counts["cancelled"] += 1
        await db.commit()
        return None
    informational = announcement.kind == "informational"
    if informational and await db.get(CareAnnouncementOptOut, recipient.candidate_id):
        # Wypis po zamrożeniu listy — informacyjny już nie idzie.
        recipient.status = "excluded_opted_out"
        counts["opted_out"] += 1
        await db.commit()
        return None
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
    prepared = _Prepared(to=recipient.email, subject=subject, body=body)
    recipient.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    return prepared


async def _prepare_failed(
    db: AsyncSession, recipient_id: int, counts: Counter[str]
) -> None:
    """Błąd przed wysyłką: mail nie wyszedł — próba się liczy, reszta idzie."""

    await db.rollback()
    recipient = await db.get(_R, recipient_id, populate_existing=True)
    if recipient is None or recipient.status != "sending":
        return
    recipient.attempts += 1
    recipient.claimed_at = None
    recipient.error_code = "prepare"
    if recipient.attempts < MAX_ATTEMPTS:
        recipient.status = "pending"
        counts["deferred"] += 1
    else:
        recipient.status = "failed"
        counts["failed"] += 1
    await db.commit()


async def _record(
    db: AsyncSession,
    recipient_id: int,
    outcome: mail.MailOutcome,
    counts: Counter[str],
) -> None:
    recipient = await db.get(_R, recipient_id, populate_existing=True)
    if recipient is None:
        counts["missing"] += 1
        return
    if outcome.status == "unavailable":
        # Połączenie nie działa — mail nie wyszedł, próba się nie liczy.
        recipient.status = "pending"
        recipient.claimed_at = None
        recipient.error_code = outcome.code
        await db.commit()
        return
    recipient.attempts += 1
    recipient.error_code = outcome.code
    if outcome.status == "accepted":
        recipient.status = "sent"
        recipient.sent_at = datetime.now(timezone.utc)
        recipient.simulated = outcome.simulated
        recipient.error_code = None
        counts["sent"] += 1
    elif outcome.status == "deferred" and recipient.attempts < MAX_ATTEMPTS:
        recipient.status = "pending"
        recipient.claimed_at = None
        counts["deferred"] += 1
    elif outcome.status == "uncertain":
        recipient.status = "uncertain"
        counts["uncertain"] += 1
    else:
        recipient.status = "failed"
        counts["failed"] += 1
    await db.commit()


async def _send_one(
    db: AsyncSession,
    sender: mail.AnnouncementMailer,
    recipient_id: int,
    counts: Counter[str],
) -> Optional[mail.MailOutcome]:
    """Wysyłka do jednej osoby; ``None`` = bez wysyłki (pominięta albo błąd
    przygotowania). Błąd tej osoby nie przerywa paczki."""

    try:
        prepared = await _prepare(db, recipient_id, counts)
    except Exception:  # noqa: BLE001 — jedna osoba nie psuje paczki
        logger.exception(
            "[care_announcements] przygotowanie recipient=%s padło", recipient_id
        )
        await _prepare_failed(db, recipient_id, counts)
        return None
    if prepared is None:
        return None
    try:
        outcome = await sender.send(
            to=prepared.to, subject=prepared.subject, text=prepared.body
        )
    except Exception:  # noqa: BLE001 — wynik nieznany, bez ponowienia
        logger.exception(
            "[care_announcements] wysyłka recipient=%s padła", recipient_id
        )
        outcome = mail.MailOutcome("uncertain", "exception")
    try:
        await _record(db, recipient_id, outcome, counts)
    except Exception:  # noqa: BLE001 — osoba zostaje „w wysyłce” ze stemplem
        # i po ``STUCK_AFTER`` dostaje „niepewny”: mail mógł wyjść.
        logger.exception(
            "[care_announcements] zapis wyniku recipient=%s padł", recipient_id
        )
        await db.rollback()
    return outcome


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
    if not await _has_work(db):
        return {"status": "idle"}
    moment = now or datetime.now(timezone.utc)
    minute = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    run_id = await job_runs.claim(db, JOB_KIND, minute, moment)
    if run_id is None:
        return {"status": "skipped", "reason": "minute_taken"}

    counts: Counter[str] = Counter()
    status = "done"
    error: Optional[str] = None
    transport: Optional[str] = None
    claimed: list[int] = []
    try:
        counts["interrupted"] += await _expire_stuck(db)
        claimed = await _claim_batch(db)
        for recipient_id in claimed:
            outcome = await _send_one(db, sender, recipient_id, counts)
            if outcome is not None and outcome.status == "unavailable":
                transport = outcome.code or "transport"
                counts["returned"] += 1
                break
        counts["returned"] += await _release_unstarted(db, claimed)
        counts["finished"] += await _finish_announcements(db)
    except Exception as exc:  # noqa: BLE001 — przebieg nie wywraca pętli
        logger.exception("[care_announcements] przebieg kolejki padł")
        await db.rollback()
        status = "failed"
        error = type(exc).__name__
        try:
            counts["returned"] += await _release_unstarted(db, claimed)
        except Exception:  # noqa: BLE001 — wróci przez ``_expire_stuck``
            logger.exception("[care_announcements] nie oddano rezerwacji")
            await db.rollback()
    summary: dict[str, Any] = dict(counts)
    if transport is not None:
        summary["transport"] = transport
        logger.warning(
            "[care_announcements] połączenie z administracja@ nie działa: %s",
            transport,
        )
    try:
        await job_runs.finish(db, run_id, status=status, counts=summary, error=error)
    except Exception:  # noqa: BLE001 — rezerwacja i tak wygaśnie
        logger.exception("[care_announcements] nie zapisano wyniku przebiegu")
        await db.rollback()
    logger.info("[care_announcements] kolejka: %s %s", status, summary)
    if status != "done":
        return {"status": "error", **counts}
    if transport is not None:
        return {
            "status": "deferred",
            "reason": "transport",
            "code": transport,
            **counts,
        }
    return {"status": "ok", **counts}
