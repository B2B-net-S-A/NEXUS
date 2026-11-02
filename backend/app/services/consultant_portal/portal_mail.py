"""Jedyna droga maila z portalu do konsultanta.

Każda wysyłka do osoby spoza firmy przechodzi przez ``send``, a ``send`` sprawdza
wyłącznik: bez ``consultant_portal`` w stanie pilot albo all (dla tego kontraktu)
nic nie wychodzi. Nadawca to ``CONSULTANT_PORTAL_MAILBOX`` (wsparcie@) przez kanał
komunikatów do konsultantów: ``HR_M365_MODE`` ``off`` = brak nadawcy, ``simulate`` =
nic nie wychodzi, ``live`` = Graph. Log niesie wyłącznie wynik, bez adresu i treści.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.care import announcement_mail
from app.services.care.announcement_mail import AnnouncementMailer, MailOutcome
from app.services.consultant_portal import portal_settings

logger = logging.getLogger(__name__)


def mailbox() -> Optional[str]:
    return (settings.CONSULTANT_PORTAL_MAILBOX or "").strip() or None


def default_mailer() -> Optional[AnnouncementMailer]:
    mode = announcement_mail.transport_mode()
    if mode == "simulate":
        return announcement_mail.SimulatedMailer()
    if mode != "live":
        return None
    from app.services.hr.m365.auth import credentials_configured

    address = mailbox()
    if address is None or not credentials_configured():
        return None
    return announcement_mail.GraphMailer(address)


async def send(
    db: AsyncSession, *, contract_id: int, to: str, subject: str, text: str
) -> Optional[MailOutcome]:
    """Wynik wysyłki albo ``None``: portal zamknięty lub brak nadawcy."""

    state = await portal_settings.load(db)
    if not state.open_for(contract_id):
        logger.info("consultant_portal_mail: blocked state=%s", state.state)
        return None
    mailer = default_mailer()
    if mailer is None:
        logger.warning("consultant_portal_mail: no transport")
        return None
    outcome = await mailer.send(to=to, subject=subject, text=text)
    logger.info("consultant_portal_mail: status=%s", outcome.status)
    return outcome


def portal_url(path: str = "") -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/konsultant{path}"
