"""Wysyłka raportu kompetencji (N4): rezerwacja, mail i wynik na wierszu.

Snapshot składa ``competence_report_engine``; tu raport wychodzi do kandydata.
``send_report`` rezerwuje wiersz (``sent``) i commituje przed wysyłką, jak
``candidate_terms_queue.send_one``: restart w trakcie nie wyśle drugiego maila.
Wysyłka zostawia jeden wpis ``competence_report_sent`` na kandydacie:
``user_id`` = rekruter przy „Wyślij teraz”, ``None`` przy wysyłce automatycznej.
Nazwy ``send_report``, ``send_report_now`` i ``ReportNotSendable`` to kontrakt
z pętlą (``tasks/competence_report_sender``) i kolejką rekrutera.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport
from app.models.user import User
from app.services.competence_report_email import (
    KIND,
    RenderedMail,
    ReportLinks,
    recipient_allowed,
    render_report_email,
)
from app.services.competence_report_schema import ReportSnapshot
from app.services.competence_report_tokens import new_token, report_urls, token_expiry

logger = logging.getLogger(__name__)

#: Po tylu nieudanych wysyłkach raport przechodzi w ``failed``.
MAX_ATTEMPTS = 5
ACTIVITY_ACTION = "competence_report_sent"


class ReportNotSendable(Exception):
    """Raport nie może teraz wyjść; ``reason`` to krótki kod bez danych osobowych."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _first_name(candidate: Optional[Candidate]) -> Optional[str]:
    from app.services.public_apply import PLACEHOLDER_NAME

    name = (candidate.name if candidate is not None else "") or ""
    return None if not name.strip() or name.strip() == PLACEHOLDER_NAME else name


def _deliver(
    mail: RenderedMail, *, to: str, event_at: datetime, reply_to: Optional[str]
) -> tuple[bool, bool]:
    """Wątek wysyłki; polityka sprawdzana jeszcze raz tuż przed nadawcą. ``(ok, niepewne)``."""
    from app.services.email import send_email
    from app.services.m365.app_mail import last_delivery_uncertain
    from app.services.notification_delivery import (
        guarded_send,
        last_send_policy_blocked,
    )

    ok = guarded_send(
        KIND,
        event_at,
        send_email,
        to,
        mail.subject,
        mail.text,
        mail.html,
        reply_to,
        settings.CANDIDATE_MAIL_SENDER_UPN or None,
        list_unsubscribe=mail.list_unsubscribe,
    )
    uncertain = bool(
        not ok
        and settings.M365_APP_MAIL_ENABLED
        and not last_send_policy_blocked()
        and last_delivery_uncertain()
    )
    return bool(ok), uncertain


async def _candidate_opted_out(db: AsyncSession, candidate_id: int) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    CompetenceReport.candidate_id == candidate_id,
                    CompetenceReport.opted_out_at.is_not(None),
                )
            )
        )
    )


async def _blocker(
    db: AsyncSession, row: CompetenceReport, *, manual: bool
) -> Optional[tuple[str, Optional[str]]]:
    """``(powód, nowy status albo None)`` gdy raport nie może wyjść."""
    from app.services.candidate_terms_queue import candidate_sender_ready
    from app.services.notification_delivery import load_policy

    if row.status != "ready" and not (manual and row.status == "failed"):
        return "not_ready", None
    if row.opted_out_at is not None or await _candidate_opted_out(db, row.candidate_id):
        return "opted_out", "opted_out"
    if row.held_at is not None and not manual:
        return "held", None
    if not row.snapshot:
        return "no_snapshot", None
    if not recipient_allowed(row.email):
        return "recipient_not_allowed", None if manual else "skipped"
    if not candidate_sender_ready():
        return "sender_not_ready", None
    policy = await load_policy(db)
    if not policy.allows(KIND, row.created_at):
        if not policy.kind_enabled(KIND):
            return "mail_disabled", None
        # Raport sprzed włączenia rodzaju maila: automat go pomija na stałe,
        # a rekruter dostaje właściwy powód zamiast „mail wyłączony”.
        return "before_enabled", None if manual else "skipped"
    return None


async def send_report(
    db: AsyncSession,
    report: CompetenceReport,
    *,
    by_user_id: Optional[int],
    now: Optional[datetime] = None,
) -> None:
    """Wyślij raport. Commituje (rezerwacja przed wysyłką i wynik po niej).

    Rzuca ``ReportNotSendable`` z kodem, gdy raport nie może wyjść (wypis,
    wstrzymanie przy wysyłce automatycznej, adres spoza próby, mail wyłączony
    w Ustawieniach). Wysyłka rekrutera (``by_user_id``) przechodzi mimo
    „Wstrzymaj” i ponawia raport ``failed``. Nieudana wysyłka: ``attempts`` + 1,
    ``last_error``, po ``MAX_ATTEMPTS`` status ``failed``.
    """
    now = now or datetime.now(timezone.utc)
    row = await db.scalar(
        select(CompetenceReport)
        .where(CompetenceReport.id == report.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ReportNotSendable("busy")
    blocked = await _blocker(db, row, manual=by_user_id is not None)
    if blocked is not None:
        reason, status = blocked
        if status is not None:
            row.status, row.last_error = status, reason
        # Commit, nie rollback: zwalnia blokadę, a nie wygasza obiektów wołającego.
        await db.commit()
        raise ReportNotSendable(reason)

    candidate = await db.get(Candidate, row.candidate_id)
    owner = await db.get(User, row.owner_user_id) if row.owner_user_id else None
    raw, digest = new_token()
    urls = report_urls(raw)
    mail = render_report_email(
        ReportSnapshot.model_validate(row.snapshot),
        first_name=_first_name(candidate),
        links=ReportLinks(
            edit_conditions_url=urls.edit_conditions_url,
            unsubscribe_url=urls.unsubscribe_url,
            one_click_unsubscribe_url=urls.one_click_unsubscribe_url,
        ),
    )
    to, event_at = row.email, row.created_at
    reply_to = owner.email if owner is not None and owner.is_active else None
    # Rezerwacja przed wysyłką: drugi worker go nie weźmie, a restart w trakcie
    # nie wyśle drugiego maila (niepewny wynik zostaje „sent”).
    row.token_hash, row.token_expires_at = digest, token_expiry(now)
    row.status, row.sent_at, row.sent_by_user_id = "sent", now, by_user_id
    row.last_error = None
    await db.commit()

    uncertain = False
    try:
        ok, uncertain = await asyncio.to_thread(
            _deliver, mail, to=to, event_at=event_at, reply_to=reply_to
        )
        error = None if ok else "policy_blocked_or_send_failed"
    except Exception as exc:  # noqa: BLE001 — wynik zapisujemy na wierszu
        logger.warning("[competence-report] send failed: %s", type(exc).__name__)
        ok, error = False, f"send_error:{type(exc).__name__}"[:120]
    if ok or uncertain:
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=row.candidate_id,
                action=ACTIVITY_ACTION,
                user_id=by_user_id,
                external_source="system" if by_user_id is None else "manual",
                details={
                    "summary": "raport kompetencji wysłany",
                    "report_id": row.id,
                    "manual": by_user_id is not None,
                    **({"uncertain": True} if uncertain else {}),
                },
            )
        )
        await db.commit()
        return
    row.attempts = (row.attempts or 0) + 1
    row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "ready"
    row.sent_at = row.sent_by_user_id = None
    row.token_hash = row.token_expires_at = None
    row.last_error = error
    await db.commit()


async def send_report_now(
    db: AsyncSession, report: CompetenceReport, user: User
) -> None:
    """„Wyślij teraz” z kolejki rekrutera: przed terminem, jako ``user``."""
    await send_report(db, report, by_user_id=user.id)
