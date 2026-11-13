"""Cztery boty Sprzedaży (decyzja Artura z 13.11.2026), bez bazy."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.services.sales import bots, signals


@pytest.fixture
def webhooks(monkeypatch):
    for prefix in (
        "GROK_BOT_WEBHOOK",
        "GROK_BOT_LEADS_WEBHOOK",
        "GROK_BOT_RESEARCH_WEBHOOK",
        "GROK_BOT_COMPANY_WEBHOOK",
        "GROK_BOT_CONTACTS_WEBHOOK",
        "GROK_BOT_PEOPLE_WEBHOOK",
    ):
        monkeypatch.setattr(settings, f"{prefix}_URL", "")
        monkeypatch.setattr(settings, f"{prefix}_KEY", "")
    return monkeypatch


def test_every_registered_kind_belongs_to_one_bot() -> None:
    from app.services.sales import bot_tasks

    assert set(bot_tasks.REGISTRY) <= set(bots.KIND_BOT)
    assert bots.bot_for("signals") == bots.LEADS
    assert bots.bot_for("winback") == bots.LEADS
    assert bots.bot_for("briefing") == bots.RESEARCH
    assert bots.bot_for("question") == bots.RESEARCH
    assert bots.bot_for("enrich") == bots.COMPANY
    assert bots.bot_for("people", {"source": "public"}) == bots.CONTACTS
    assert bots.bot_for("people", {"source": "cognism"}) == bots.COGNISM
    assert bots.bot_for("unknown") is None


def test_bot_without_its_own_routine_uses_the_shared_webhook(webhooks) -> None:
    webhooks.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/shared")
    webhooks.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "shared-key")
    webhooks.setattr(settings, "GROK_BOT_COMPANY_WEBHOOK_URL", "https://bot.example/c")
    webhooks.setattr(settings, "GROK_BOT_COMPANY_WEBHOOK_KEY", "company-key")
    assert bots.webhook(bots.COMPANY) == ("https://bot.example/c", "company-key")
    assert bots.webhook(bots.LEADS) == ("https://bot.example/shared", "shared-key")
    # Cognism nigdy nie idzie na wspólny webhook.
    assert bots.webhook(bots.COGNISM) == ("", "")
    # Połowa pary własnego webhooka to brak własnego.
    webhooks.setattr(settings, "GROK_BOT_LEADS_WEBHOOK_URL", "https://bot.example/l")
    assert bots.webhook(bots.LEADS) == ("https://bot.example/shared", "shared-key")


def test_configured_follows_the_bot_of_the_kind(webhooks) -> None:
    assert not signals.configured()
    webhooks.setattr(settings, "GROK_BOT_CONTACTS_WEBHOOK_URL", "https://bot.example/p")
    webhooks.setattr(settings, "GROK_BOT_CONTACTS_WEBHOOK_KEY", "people-key")
    assert signals.configured()
    assert signals.configured("people")
    assert not signals.configured("enrich")


class _Db:
    def __init__(self, row: Optional[AppSetting] = None) -> None:
        self.row = row
        self.added: list[Any] = []

    async def get(self, model, key, **kw):  # noqa: ANN001
        return self.row

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.row = obj


@pytest.mark.asyncio
async def test_pause_and_resume_keep_one_settings_row() -> None:
    db = _Db()
    assert await bots.paused_refusal(db, "enrich") is None
    assert await bots.set_paused(db, bots.COMPANY, True, user_id=5) == {bots.COMPANY}
    assert len(db.added) == 1 and db.row.value == {"paused": ["company"]}
    assert await bots.is_paused(db, bots.COMPANY)
    assert await bots.paused_refusal(db, "enrich") == (
        "Bot Dane firm: wstrzymany w Sprzedaż → Leady → Boty."
    )
    await bots.set_paused(db, bots.LEADS, True, user_id=5)
    assert await bots.set_paused(db, bots.COMPANY, False, user_id=5) == {bots.LEADS}
    assert len(db.added) == 1 and db.row.value == {"paused": ["leads"]}
    with pytest.raises(ValueError):
        await bots.set_paused(db, "inny", True, user_id=5)


@pytest.mark.asyncio
async def test_unknown_values_in_the_setting_are_ignored() -> None:
    db = _Db(AppSetting(key=bots.SALES_BOTS_KEY, value={"paused": ["company", "x"]}))
    assert await bots.paused_bots(db) == {bots.COMPANY}
