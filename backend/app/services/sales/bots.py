"""Cztery boty Sprzedaży zamiast jednej rutyny (decyzja Artura z 13.11.2026).

Każdy rodzaj zadania należy do jednego bota, a każdy bot ma własną rutynę
w Grok Bocie (własny webhook i krótkie polecenie):

- **Leady** (``signals``, ``winback``, ``discovery``): szuka okazji.
- **Research** (``briefing`` z trybami haczyka i teczki, ``question``):
  przygotowuje do rozmowy.
- **Dane firm** (``enrich``): uzupełnia kartę firmy.
- **Kontakty** (``people`` ze źródeł publicznych): ludzie na karcie.
- **Cognism** (``people`` z ``request.source = "cognism"``): osobna rutyna
  z panelem Cognism, jak dotąd (``GROK_BOT_PEOPLE_WEBHOOK_*``).

Bot bez własnego webhooka idzie na wspólny (``GROK_BOT_WEBHOOK_*``), więc
podział działa od wdrożenia, zanim powstaną nowe rutyny. Pauza bota
(ekran Leady → Boty) leży w ``app_settings`` pod ``SALES_BOTS_KEY`` i zatrzymuje
nowe biegi w ``signals.start_run``; flagi środowiskowe zostają głównym
włącznikiem. Reguły: ``docs/claude/sprzedaz/cztery-boty-sprzedazy.md``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting

LEADS = "leads"
RESEARCH = "research"
COMPANY = "company"
CONTACTS = "contacts"
COGNISM = "cognism"
#: Bot Listy (13.11.2026): listy do dzwonienia z briefu kampanii (``bot_lists.py``).
LISTS = "lists"

#: Kolejność na ekranie.
BOTS: tuple[str, ...] = (LISTS, LEADS, RESEARCH, COMPANY, CONTACTS, COGNISM)
NAMES: dict[str, str] = {
    LEADS: "Bot Leady",
    RESEARCH: "Bot Research",
    COMPANY: "Bot Dane firm",
    CONTACTS: "Bot Kontakty",
    COGNISM: "Rutyna Cognism",
    LISTS: "Bot Listy",
}
KIND_BOT: dict[str, str] = {
    "signals": LEADS,
    "winback": LEADS,
    "discovery": LEADS,
    "briefing": RESEARCH,
    "question": RESEARCH,
    "enrich": COMPANY,
    "people": CONTACTS,
}
#: Prefiks zmiennych webhooka bota; Cognism ma dotychczasowe nazwy.
_WEBHOOK_PREFIX: dict[str, str] = {
    LEADS: "GROK_BOT_LEADS_WEBHOOK",
    RESEARCH: "GROK_BOT_RESEARCH_WEBHOOK",
    COMPANY: "GROK_BOT_COMPANY_WEBHOOK",
    CONTACTS: "GROK_BOT_CONTACTS_WEBHOOK",
    COGNISM: "GROK_BOT_PEOPLE_WEBHOOK",
    LISTS: "GROK_BOT_LISTS_WEBHOOK",
}

SALES_BOTS_KEY = "sales_bots"
PAUSED_DETAIL = "{name}: wstrzymany w Sprzedaż → Leady → Boty."


async def paused_refusal(
    db: AsyncSession, kind: str, request: Optional[dict[str, Any]] = None
) -> Optional[str]:
    """Polski komunikat 409 dla trasy startu, gdy bot rodzaju jest wstrzymany."""

    bot = bot_for(kind, request)
    if bot is not None and await is_paused(db, bot):
        return PAUSED_DETAIL.format(name=NAMES[bot])
    return None


def bot_for(kind: str, request: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Bot, do którego należy rodzaj biegu; ``None`` dla rodzaju spoza listy."""

    if kind == "people" and (request or {}).get("source") == COGNISM:
        return COGNISM
    return KIND_BOT.get(kind)


def own_webhook(bot: str) -> tuple[str, str]:
    prefix = _WEBHOOK_PREFIX[bot]
    return (
        str(getattr(settings, f"{prefix}_URL", "") or ""),
        str(getattr(settings, f"{prefix}_KEY", "") or ""),
    )


def webhook(bot: str) -> tuple[str, str]:
    """Adres i klucz webhooka bota; bez własnej pary wspólny (poza Cognism)."""

    url, key = own_webhook(bot)
    if url and key:
        return url, key
    if bot == COGNISM:
        return "", ""
    return settings.GROK_BOT_WEBHOOK_URL, settings.GROK_BOT_WEBHOOK_KEY


async def paused_bots(db: AsyncSession) -> set[str]:
    row = await db.get(AppSetting, SALES_BOTS_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {str(bot) for bot in value.get("paused") or [] if bot in BOTS}


async def is_paused(db: AsyncSession, bot: str) -> bool:
    return bot in await paused_bots(db)


async def set_paused(
    db: AsyncSession, bot: str, paused: bool, *, user_id: Optional[int]
) -> set[str]:
    """Wstrzymaj albo wznów bota; commit robi wywołujący."""

    if bot not in BOTS:
        raise ValueError(f"Nieznany bot: {bot}")
    row = await db.get(AppSetting, SALES_BOTS_KEY, with_for_update=True)
    current = await paused_bots(db) if row is not None else set()
    updated = (current | {bot}) if paused else (current - {bot})
    value = {"paused": sorted(updated)}
    if row is None:
        db.add(AppSetting(key=SALES_BOTS_KEY, value=value, updated_by=user_id))
    else:
        row.value = value
        row.updated_by = user_id
    return updated
