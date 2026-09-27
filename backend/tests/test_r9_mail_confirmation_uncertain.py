"""Runda 9 (R9-N10-14): niepewna wysyłka potwierdzenia nie zwalnia rezerwacji."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import application_confirmation_email as confirmation
from app.services import notification_delivery
from app.services.m365 import app_mail


def _message():
    return confirmation.ConfirmationEmail(
        to="kandydat@example.com",
        subject="Potwierdzenie",
        text_body="t",
        html_body="<p>t</p>",
    )


@pytest.fixture
def release(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(confirmation, "release_claim", mock)
    monkeypatch.setattr(settings, "M365_APP_MAIL_ENABLED", True)
    monkeypatch.setattr(
        notification_delivery, "guarded_send", lambda *a, **k: False
    )
    monkeypatch.setattr(notification_delivery, "last_send_policy_blocked", lambda: False)
    return mock


async def test_uncertain_delivery_keeps_the_claim(monkeypatch, release) -> None:
    monkeypatch.setattr(app_mail, "last_delivery_uncertain", lambda: True)

    sent = await confirmation.deliver(
        _message(), event_at=datetime.now(timezone.utc), link_key="job:1"
    )

    assert sent is False
    release.assert_not_awaited()


async def test_certain_failure_still_releases_the_claim(monkeypatch, release) -> None:
    monkeypatch.setattr(app_mail, "last_delivery_uncertain", lambda: False)

    await confirmation.deliver(
        _message(), event_at=datetime.now(timezone.utc), link_key="job:1"
    )

    release.assert_awaited_once()
