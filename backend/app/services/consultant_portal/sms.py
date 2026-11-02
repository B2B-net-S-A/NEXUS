"""Wysyłka kodów SMS: interfejs bez konkretnego dostawcy.

Dostawcy SMS jeszcze nie wybrano i w NEXUSIE go nie ma. Domyślny ``disabled`` mówi
„niedostępne”, a finanse w portalu pokazują wtedy zdanie po polsku; reszta portalu
działa. ``log`` zapisuje kod do logu i wolno go wyłącznie na stagingu i w testach:
na produkcji kod w logu otwierałby finanse każdemu, kto czyta logi.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class SmsSender(Protocol):
    @property
    def available(self) -> bool: ...

    async def send(self, *, to: str, text: str) -> bool: ...


class DisabledSmsSender:
    available = False

    async def send(self, *, to: str, text: str) -> bool:
        return False


class LogSmsSender:
    """Staging i testy: treść w logu, numer tylko końcówką."""

    available = True

    async def send(self, *, to: str, text: str) -> bool:
        logger.info("consultant_portal_sms to=***%s text=%s", to[-3:], text)
        return True


def log_allowed() -> bool:
    return settings.NEXUS_ENV == "staging" or "PYTEST_CURRENT_TEST" in os.environ


def default_sender() -> SmsSender:
    provider = (settings.CONSULTANT_PORTAL_SMS_PROVIDER or "").strip().lower()
    if provider == "log" and log_allowed():
        return LogSmsSender()
    return DisabledSmsSender()


_override: Optional[SmsSender] = None


def current_sender() -> SmsSender:
    return _override or default_sender()


def set_sender_for_tests(sender: Optional[SmsSender]) -> None:
    global _override
    _override = sender
