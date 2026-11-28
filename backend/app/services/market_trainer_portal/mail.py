"""Jedyna droga maila do trenera z rynku.

Wyłączony włącznik (``switch``) = nic nie wychodzi. Nadawca jak w panelu konsultanta
(``portal_mail.default_mailer``: ``CONSULTANT_PORTAL_MAILBOX``, tryb ``HR_M365_MODE``).
Log niesie wyłącznie wynik, bez adresu i treści. Tekst dla osoby spoza firmy bez
myślników „—”.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.care.announcement_mail import MailOutcome
from app.services.consultant_portal import portal_mail
from app.services.market_trainer_portal import switch

logger = logging.getLogger(__name__)


async def send(
    db: AsyncSession, *, to: str, subject: str, text: str
) -> Optional[MailOutcome]:
    if not await switch.is_enabled(db):
        logger.info("market_trainer_mail: blocked (switch off)")
        return None
    mailer = portal_mail.default_mailer()
    if mailer is None:
        logger.warning("market_trainer_mail: no transport")
        return None
    outcome = await mailer.send(to=to, subject=subject, text=text)
    logger.info("market_trainer_mail: status=%s", outcome.status)
    return outcome


def login_url(raw_token: str) -> str:
    """Link logowania: ten sam ekran wejścia co konsultant, token trenera we fragmencie."""
    return portal_mail.portal_url(f"/wejscie#trener={raw_token}")
