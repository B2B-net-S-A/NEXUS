"""Kolejka maili „Dziękujemy za zgłoszenie” z prośbą o warunki.

Zgłoszenie (portal, strona kariery) tylko dopisuje wiersz ``queued``. Decyzję,
co wysłać, podejmuje wysyłka (``process_queue``), bo między aplikacją a 8:00
rekruter mógł już uzupełnić profil. Reguły w ``services/candidate_terms.py``.

Nic tutaj nie może cofnąć zgłoszenia: ``enqueue`` działa w punkcie zapisu
(SAVEPOINT) i nigdy nie rzuca. Logi bez adresów i imion.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_terms_request import CandidateTermsRequest
from app.services import candidate_terms as rules

logger = logging.getLogger(__name__)

#: Najwyżej tyle maili w jednym przebiegu pętli (co 5 min) — rozkłada wysyłkę.
BATCH = 25


async def enqueue(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: Optional[int],
    source: str,
    applied_at: Optional[datetime] = None,
    ad_title: Optional[str] = None,
) -> bool:
    """Dopisz zgłoszenie do kolejki. Nie rzuca.

    Jedno na osobę w ciągu doby (import i trasa portalu zapisują tę samą
    aplikację dwiema drogami, z rekrutacją i bez), a na (osobę, rekrutację)
    jedno w 30 dniach. Czekający wpis bez rekrutacji dostaje ją od drugiej drogi.
    """
    try:
        async with db.begin_nested():
            recent = await db.scalar(
                select(CandidateTermsRequest)
                .where(
                    CandidateTermsRequest.candidate_id == candidate_id,
                    CandidateTermsRequest.queued_at > func.now() - timedelta(days=1),
                )
                .order_by(CandidateTermsRequest.queued_at.desc())
                .limit(1)
            )
            if recent is not None:
                if recent.status == "queued" and recent.job_id is None and job_id:
                    recent.job_id = job_id
                if recent.status == "queued" and not recent.ad_title and ad_title:
                    recent.ad_title = ad_title[:200]
                return False
            if job_id is not None:
                same_job = await db.scalar(
                    select(CandidateTermsRequest.id).where(
                        CandidateTermsRequest.candidate_id == candidate_id,
                        CandidateTermsRequest.job_id == job_id,
                        CandidateTermsRequest.queued_at
                        > func.now() - timedelta(days=rules.RESEND_AFTER_DAYS),
                    )
                )
                if same_job is not None:
                    return False
            db.add(
                CandidateTermsRequest(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    source=source[:40],
                    ad_title=(ad_title or "").strip()[:200] or None,
                    applied_at=applied_at or datetime.now(timezone.utc),
                )
            )
        return True
    except Exception as exc:  # noqa: BLE001 — mail nie cofa zgłoszenia
        logger.warning("[candidate-terms] enqueue failed: %s", type(exc).__name__)
        return False


async def _snapshot(candidate: Candidate) -> rules.TermsSnapshot:
    from app.services.candidate_notes_facts import profile_work_mode
    from app.services.candidate_rate_from import effective_rate

    mode = profile_work_mode(candidate)
    prefs = candidate.preferences if isinstance(candidate.preferences, dict) else {}
    cities = prefs.get("office_cities") or []
    return rules.TermsSnapshot(
        rate=effective_rate(candidate)[0],
        modes=tuple(mode["modes"]),
        onsite_days=mode["max_onsite_days"],
        office_cities=tuple(c for c in cities if isinstance(c, str) and c.strip()),
        availability_date=candidate.availability_date,
        notice_period=candidate.notice_period,
    )


async def _facts(db: AsyncSession, candidate_id: int, now: datetime):
    last_link = await db.scalar(
        select(func.max(CandidateTermsRequest.sent_at)).where(
            CandidateTermsRequest.candidate_id == candidate_id,
            CandidateTermsRequest.action == "link",
        )
    )
    opted_out = await db.scalar(
        select(func.count()).where(
            CandidateTermsRequest.candidate_id == candidate_id,
            CandidateTermsRequest.opted_out_at.is_not(None),
        )
    )
    from app.services.current_employment import current_employment_client_ids

    today = now.astimezone(ZoneInfo(DEFAULT_TZ)).date()
    live = await current_employment_client_ids(db, [candidate_id], today=today)
    return last_link, bool(opted_out), bool(live.get(candidate_id))


def _base() -> str:
    return (settings.PUBLIC_BASE_URL or "").rstrip("/")


def candidate_sender_ready() -> bool:
    """Graph bez skrzynki kandydatów = nie wysyłamy (zespołowa nie pisze do kandydatów)."""
    if settings.M365_APP_MAIL_ENABLED:
        return bool(settings.CANDIDATE_MAIL_SENDER_UPN)
    return bool(settings.SMTP_ENABLED and settings.SMTP_HOST)


async def _sent_today(db: AsyncSession, now: datetime) -> int:
    tz = ZoneInfo(DEFAULT_TZ)
    start = datetime.combine(now.astimezone(tz).date(), datetime.min.time(), tz)
    return int(
        await db.scalar(
            select(func.count()).where(
                CandidateTermsRequest.status == "sent",
                CandidateTermsRequest.sent_at >= start,
            )
        )
        or 0
    )


async def expire_stale(db: AsyncSession, now: datetime) -> int:
    """Zgłoszenia starsze niż 3 dni odpadają (także poza oknem wysyłki)."""
    result = await db.execute(
        update(CandidateTermsRequest)
        .where(
            CandidateTermsRequest.status == "queued",
            CandidateTermsRequest.applied_at
            < now - timedelta(days=rules.MAX_APPLICATION_AGE_DAYS),
        )
        .values(status="skipped", skip_reason="stale_application")
    )
    return int(result.rowcount or 0)


def _deliver(
    message: rules.TermsEmail, *, to: str, event_at, unsubscribe=None
) -> tuple[bool, bool]:
    """Wątek wysyłki: polityka sprawdzana jeszcze raz tuż przed nadawcą.

    ``unsubscribe`` = wypis jednym kliknięciem w nagłówku (Gmail/Yahoo dla
    nadawców masowych); w Graph przełącza wysyłkę na MIME z częścią tekstową.

    Zwraca ``(ok, uncertain)``. „Nie wiadomo” (502/504 po POST do Graphu) żyje
    we fladze wątku wysyłki, więc czytamy ją tutaj — w pętli zdarzeń po
    ``asyncio.to_thread`` flaga jest zawsze pusta (audyt r4, 24.11.2026).
    """
    from app.services.email import send_email
    from app.services.m365.app_mail import last_delivery_uncertain
    from app.services.notification_delivery import (
        guarded_send,
        last_send_policy_blocked,
    )

    ok = guarded_send(
        rules.KIND,
        event_at,
        send_email,
        to,
        message.subject,
        message.text_body,
        message.html_body,
        None,  # bez Reply-To: kandydat wypełnia formularz, nie odpisuje (17.11.2026)
        settings.CANDIDATE_MAIL_SENDER_UPN or None,
        list_unsubscribe=unsubscribe,
    )
    uncertain = bool(
        not ok
        and settings.M365_APP_MAIL_ENABLED
        and not last_send_policy_blocked()
        and last_delivery_uncertain()
    )
    return bool(ok), uncertain


async def send_one(
    db: AsyncSession, row: CandidateTermsRequest, *, now: datetime
) -> str:
    """Wyślij jeden wiersz. Zwraca nowy status. Commit robi wołający."""
    candidate = await db.get(Candidate, row.candidate_id)
    if candidate is None:
        row.status, row.skip_reason = "skipped", "no_candidate"
        return row.status
    last_link, opted_out, works_here = await _facts(db, candidate.id, now)
    decision = rules.eligibility(
        email=candidate.email,
        snapshot=await _snapshot(candidate),
        applied_at=row.applied_at,
        now=now,
        last_link_sent_at=last_link,
        opted_out=opted_out,
        blacklisted=candidate.status == CandidateStatus.blacklisted,
        works_here=works_here,
    )
    row.missing = list(decision.missing)
    if decision.action == rules.NONE:
        row.status, row.skip_reason = "skipped", decision.reason
        return row.status

    from app.services.application_confirmation_email import public_job_title, rodo_url

    raw = None
    if decision.action == rules.LINK:
        raw, row.token_sha256 = rules.new_token()
        row.expires_at = now + timedelta(days=rules.LINK_TTL_DAYS)
    base = _base()
    message = rules.render_terms_email(
        job_title=await public_job_title(db, row.job_id) or row.ad_title,
        link=f"{base}/warunki/{raw}" if raw else None,
        optout_link=f"{base}/warunki/{raw}?wypis=1" if raw else None,
        rodo_url=rodo_url(),
        logo_url=f"{base}/brand/mail/b2bnetwork-264.png",
        logo_light_url=f"{base}/brand/mail/b2bnetwork-light-240.png",
    )
    row.action = decision.action
    # Przy samym podziękowaniu powód (wypis, link w 30 dniach, komplet) do liczenia.
    row.skip_reason = decision.reason if decision.action == rules.THANKS else None
    # Rezerwacja przed wysyłką: drugi worker nie weźmie tego wiersza, a restart
    # w trakcie nie wyśle drugiego maila (niepewny wynik zostaje „sent”).
    row.status, row.sent_at = "sent", now
    await db.commit()
    uncertain = False
    try:
        ok, uncertain = await asyncio.to_thread(
            _deliver,
            message,
            to=candidate.email,
            event_at=row.queued_at,
            unsubscribe=rules.one_click_unsubscribe_url(
                settings.PUBLIC_API_BASE_URL, raw
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[candidate-terms] send failed: %s", type(exc).__name__)
        ok = False
    if not ok and not uncertain:
        row.status, row.sent_at, row.token_sha256 = "failed", None, None
        row.expires_at = None
    return row.status


async def process_queue(db: AsyncSession, *, now: Optional[datetime] = None) -> dict:
    """Jeden przebieg pętli. Zwraca liczniki (bez danych osobowych)."""
    now = now or datetime.now(timezone.utc)
    stats = {
        "expired": await expire_stale(db, now),
        "sent": 0,
        "skipped": 0,
        "failed": 0,
    }
    await db.commit()
    if not rules.in_send_window(now.astimezone(ZoneInfo(DEFAULT_TZ))):
        return stats
    if not candidate_sender_ready():
        return stats
    from app.services.notification_delivery import load_policy

    policy = await load_policy(db)
    if not policy.allows(rules.KIND, now):
        return stats
    cutoff = policy.cutoff_for(rules.KIND)
    if cutoff is not None:
        # Włączenie maila nie wysyła zaległości (jak każdy rodzaj w Ustawieniach).
        await db.execute(
            update(CandidateTermsRequest)
            .where(
                CandidateTermsRequest.status == "queued",
                CandidateTermsRequest.queued_at < cutoff,
            )
            .values(status="skipped", skip_reason="before_enabled")
        )
        await db.commit()
    room = max(0, settings.CANDIDATE_TERMS_DAILY_LIMIT - await _sent_today(db, now))
    if room == 0:
        return stats
    # Po jednym wierszu: ``send_one`` commituje rezerwację przed wysyłką, więc
    # blokada wielu wierszy naraz i tak by się zwolniła po pierwszym.
    for _ in range(min(room, BATCH)):
        row = await db.scalar(
            select(CandidateTermsRequest)
            .where(CandidateTermsRequest.status == "queued")
            # Najnowsze najpierw: przy limicie 20 i ~270 zgłoszeniach dziennie
            # najstarsze najpierw dawało mail 2–3 dni po aplikacji (22.11.2026).
            # Starsze czekają i po 3 dniach odpadają w ``expire_stale``.
            .order_by(
                CandidateTermsRequest.queued_at.desc(),
                CandidateTermsRequest.id.desc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            break
        status = await send_one(db, row, now=now)
        await db.commit()
        stats[status if status in stats else "skipped"] += 1
    return stats


#: Kanały źródła, które oznaczają aplikację kandydata (portal, strona kariery).
APPLICATION_CHANNELS = frozenset({"posting", "career_link_job", "career_link_general"})


_AD_TITLE = re.compile(r"(?:oferta|ogłoszenie):\s*(.+)$", re.IGNORECASE)


def ad_title_from_note(note: Optional[str]) -> Optional[str]:
    """„Źródło: Pracuj.pl — oferta: Data Engineer” → „Data Engineer”."""
    match = _AD_TITLE.search((note or "").strip())
    return match.group(1).strip()[:200] if match else None


def source_label(channel: str, utm_source: Optional[str]) -> str:
    if channel == "posting":
        return (utm_source or "portal").strip().lower()[:40] or "portal"
    return "career"


async def enqueue_from_source(
    db: AsyncSession,
    *,
    candidate_id: int,
    channel: object,
    job_id: Optional[int],
    utm_source: Optional[str],
    captured_at: Optional[datetime],
    note: Optional[str] = None,
) -> bool:
    """Wpis źródła = aplikacja? To dopisz do kolejki. Wołane przy każdym zapisie źródła."""
    value = getattr(channel, "value", channel)
    if value not in APPLICATION_CHANNELS:
        return False
    return await enqueue(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        source=source_label(str(value), utm_source),
        applied_at=captured_at,
        ad_title=ad_title_from_note(note),
    )
