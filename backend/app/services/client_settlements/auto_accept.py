"""Automat „Przyjmuj RCP bez uwag automatycznie” (reguła ``order.auto_accept_clean``).

Decyzja Artura z 23.11.2026 (makiety panelu Finansów, rekomendacja 1): w październiku
93 z 200 osób miało RCP „Bez uwag”, a każde Finanse przyjmowały ręcznie. Przy
włączonej regule klienta automat co rano w dzień roboczy przyjmuje takie RCP tą
samą ścieżką co „Przyjmij RCP bez uwag” (``service.accept_batch``): MD schodzą
z zamówienia według ``order.charge_on_accept``, a konsultant dostaje to samo co przy
ręcznym przyjęciu (``portal_documents.accept``, przez wyłącznik panelu).

Termin: miesiąc ``M`` automat bierze od N-tego dnia roboczego miesiąca po nim
(parametr reguły, domyślnie 3), czyli rozliczany miesiąc po kilku dniach na
poprawki, a starsze, zamknięte miesiące od razu. Bieżący miesiąc kalendarzowy
nigdy, bo się nie skończył. Przegląda trzy ostatnie miesiące.

Nie bierze: reguła wyłączona w miesiącu rozliczenia, status inny niż ``ok`` po
przeliczeniu, rozliczenie, które Finanse odesłały „Do poprawy” (znacznik
``service.AUTO_ACCEPT_OFF`` zostaje na zawsze), moduł rozliczeń zamknięty.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, is_business_day
from app.models.client_settlement import ClientSettlement
from app.services.client_settlements import settings as module_settings
from app.services.hr.payroll_periods import add_months

logger = logging.getLogger(__name__)

RULE = "order.auto_accept_clean"
DEFAULT_WORKDAY = 3
MAX_WORKDAY = 15
#: Rozliczany miesiąc i dwa wcześniejsze.
LOOKBACK_MONTHS = 3
#: Poranny bieg: od 7:00 do południa (restart po wieczornym wdrożeniu czeka do rana).
FIRST_HOUR = 7
LAST_HOUR = 12


def enabled(rules: Mapping[str, Mapping[str, Any]]) -> bool:
    return rules[RULE]["level"] != "off"


def workday(rules: Mapping[str, Mapping[str, Any]]) -> int:
    raw = str(rules[RULE]["params"].get("workday", "")).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WORKDAY
    return max(1, min(MAX_WORKDAY, value))


def _month_of(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def due_from(month: str, n: int) -> date:
    """N-ty dzień roboczy (kalendarz firmy) miesiąca po ``month``."""

    year, mon = (int(x) for x in month.split("-"))
    year, mon = add_months(year, mon, 1)
    day = date(year, mon, 1)
    count = 0
    while True:
        if is_business_day(datetime(day.year, day.month, day.day, 12)):
            count += 1
            if count >= n:
                return day
        day += timedelta(days=1)


def is_due(month: str, today: date, n: int) -> bool:
    if month >= _month_of(today):
        return False
    return today >= due_from(month, n)


def months_to_check(today: date) -> list[str]:
    out = []
    year, mon = today.year, today.month
    for _ in range(LOOKBACK_MONTHS):
        year, mon = add_months(year, mon, -1)
        out.append(f"{year}-{mon:02d}")
    return out


def morning(now: datetime) -> bool:
    return is_business_day(now) and FIRST_HOUR <= now.hour < LAST_HOUR


def info(
    rules: Mapping[str, Mapping[str, Any]], month: str, count: int
) -> dict[str, Any] | None:
    """Pasek nad tabelą miesiąca: ile „Bez uwag” przyjmie się samo i od kiedy."""

    if not enabled(rules):
        return None
    n = workday(rules)
    return {"count": count, "workday": n, "from": due_from(month, n).isoformat()}


async def run(db: AsyncSession, *, now: datetime) -> int:
    """Przyjmij dziś RCP „Bez uwag” klientów z włączoną regułą; zwraca liczbę.

    Każdy klient i miesiąc w osobnym punkcie zapisu: awaria jednego nie cofa
    pozostałych. Commit robi wołający."""

    from app.services.client_settlements import service

    if not await module_settings.is_enabled(db):
        return 0
    today = business_date(now)
    months = months_to_check(today)
    pairs = (
        await db.execute(
            select(ClientSettlement.client_id, ClientSettlement.period_month)
            .where(
                ClientSettlement.period_month.in_(months),
                ClientSettlement.kind == service.ACTUAL,
                ClientSettlement.status == "ok",
            )
            .distinct()
            .order_by(ClientSettlement.period_month, ClientSettlement.client_id)
        )
    ).all()
    accepted = 0
    for client_id, month in pairs:
        rules = await service.rules_for(db, client_id, month)
        if not enabled(rules) or not is_due(month, today, workday(rules)):
            continue
        try:
            async with db.begin_nested():
                done = await service.accept_batch(
                    db, client_id, month, actor=None, now=now, auto=True
                )
        except Exception:  # noqa: BLE001 — jeden klient nie zatrzymuje reszty
            logger.exception(
                "auto_accept: klient %s, miesiąc %s nie przeszedł", client_id, month
            )
            continue
        if done:
            logger.info(
                "auto_accept: klient %s, %s — przyjęto %s RCP", client_id, month, done
            )
        accepted += done
    return accepted
