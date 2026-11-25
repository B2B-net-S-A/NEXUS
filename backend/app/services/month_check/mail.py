"""Maile kontroli miesiąca do Finansów (0784, decyzja Artura 25.11.2026).

* **Poniedziałek od 8:00** — nowe sprawy z ostatnich 7 dni (stan ``new``
  albo ``to_correct``) z kwotą, numerami faktur i linkiem do „Przebiegu
  miesiąca”. Pusty tydzień nie wychodzi.
* **12. dzień miesiąca od 8:00** — podsumowanie poprzedniego miesiąca: ile
  osobo-miesięcy się zgadza, ile spraw i na jaką kwotę, co jest otwarte.
  Wychodzi tylko przy włączonej wysyłce do Finansów.

Adresaci: ``app_settings['month_check_mail']``. Domyślnie (``to_finance``
wyłączone) mail tygodniowy idzie wyłącznie do Artura na próbę; do Finansów
dopiero po jego „wysyłaj” (``to_finance: true``). Rodzaj maila
``month_check_report`` jest obowiązkowy (``notification_delivery``), bez
duplikatu po restarcie przez znaczniki ``kpi_email_report_runs``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.models.month_check_case import MonthCheckCase
from app.models.user import User, UserRole
from app.services.month_check import rules, service

logger = logging.getLogger(__name__)

KIND = "month_check_report"
WEEKLY_RUN = "month_check_weekly"
MONTHLY_RUN = "month_check_month"
SETTING_KEY = "month_check_mail"
SEND_HOUR = 8
SUMMARY_DAY = 12
MAX_ROWS = 60


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str


async def to_finance(db: AsyncSession) -> bool:
    stored = await db.get(AppSetting, SETTING_KEY)
    return bool(stored and (stored.value or {}).get("to_finance") is True)


def test_recipients() -> list[str]:
    """Próba z pierwszego tygodnia (decyzja Artura 25.11.2026): ``MONTH_CHECK_TEST_RECIPIENTS``."""

    raw = settings.MONTH_CHECK_TEST_RECIPIENTS or ""
    return [a.strip() for a in raw.split(",") if "@" in a]


async def recipients(db: AsyncSession) -> list[str]:
    if not await to_finance(db):
        return test_recipients()
    from app.services.notification_delivery import email_opted_out

    users = await db.scalars(
        select(User)
        .where(
            User.is_active.is_(True),
            User.email.is_not(None),
            or_(
                User.role == UserRole.finance,
                User.roles.contains([UserRole.finance.value]),
            ),
        )
        .order_by(User.id)
    )
    # Mail obowiązkowy: konto go nie wyłącza, ale nadawca pyta jak każdy.
    return [u.email for u in users.all() if u.email and not email_opted_out(u, KIND)]


def weekly_key(now_local: datetime) -> Optional[str]:
    if now_local.weekday() != 0 or now_local.hour < SEND_HOUR:
        return None
    year, week, _ = now_local.date().isocalendar()
    return f"{year}-W{week:02d}"


def summary_key(now_local: datetime) -> Optional[str]:
    if now_local.day != SUMMARY_DAY or now_local.hour < SEND_HOUR:
        return None
    return rules.shift(rules.month_key(now_local.date()), -1)


def _link(month: str) -> str:
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/finance?view=month-close&mcMonth={month}&mcTab=diff"


def _pln(value: Optional[Decimal], currency: str = "PLN") -> str:
    if value is None:
        return "—"
    whole = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",")
    unit = "zł" if currency == "PLN" else currency
    return f"{'−' if value < 0 else ''}{whole} {unit}"


def _invoices(details: dict[str, Any]) -> str:
    sales = ", ".join(details.get("sales_invoices") or []) or "brak"
    costs = (
        ", ".join(d.get("number", "") for d in details.get("contractor_invoices") or [])
        or "brak"
    )
    return f"faktura do klienta: {sales}; faktura konsultanta: {costs}"


def render_weekly(rows: list[dict[str, Any]], week: str) -> tuple[str, str]:
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_month[r["month"]].append(r)
    # Suma tylko w złotych; kwoty w innej walucie są przy wierszach.
    total = sum(
        (
            abs(Decimal(r["amount"]))
            for r in rows
            if r["amount"] and r["currency"] == "PLN"
        ),
        Decimal(0),
    )
    lines = [
        f"Nowe rozbieżności faktur z ostatniego tygodnia: {len(rows)} (w złotych razem {_pln(total)} do wyjaśnienia).",
        "",
    ]
    for month in sorted(by_month):
        items = by_month[month]
        lines.append(f"{month} — {len(items)} · {_link(month)}")
        for r in items[:MAX_ROWS]:
            amount = _pln(Decimal(r["amount"]), r["currency"]) if r["amount"] else "—"
            lines.append(
                f"  • {r['client'] or 'klient?'} · {r['person']} · {r['kind_label']} · {amount}"
            )
            lines.append(f"    {_invoices(r['details'])}")
        if len(items) > MAX_ROWS:
            lines.append(f"  … i {len(items) - MAX_ROWS} więcej na ekranie.")
        lines.append("")
    lines.append(
        "„Wyjaśnione” (z powodem) albo „Do korekty” zaznaczasz w Finanse → Przebieg miesiąca → Rozbieżności."
    )
    return f"NEXUS: rozbieżności faktur — {week}", "\n".join(lines)


def render_summary(month: str, summary: dict[str, Any]) -> tuple[str, str]:
    lines = [
        f"Kontrola faktur za {month}:",
        f"  • zgodne osobo-miesiące: {summary.get('matched') or 0} z {summary.get('person_months') or 0}",
        f"  • sprawy: {summary['cases']} na {_pln(Decimal(summary['cases_amount'] or 0))}",
        f"  • otwarte: {summary['open']} na {_pln(Decimal(summary['open_amount'] or 0))}",
        f"  • w innej walucie niż zł (poza sumami): {summary.get('foreign_currency') or 0}",
        f"  • wyjaśnione: {summary['by_state'].get(service.EXPLAINED, 0)}, zamknięte same: {summary['by_state'].get(service.CLOSED, 0)}",
        "",
        _link(month),
    ]
    return f"NEXUS: kontrola faktur za {month}", "\n".join(lines)


async def weekly_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.scalars(
                select(MonthCheckCase)
                .where(
                    MonthCheckCase.state.in_(service.OPEN_STATES),
                    MonthCheckCase.first_seen_at >= now - timedelta(days=7),
                )
                .order_by(MonthCheckCase.period_month, MonthCheckCase.id)
            )
        ).all()
    )
    person, client = await service.names(db, rows)
    return [service.case_dict(r, person, client, amounts=True) for r in rows]


def _deliver(mail: Mail, now_utc: datetime) -> bool:
    from app.services.email import send_email
    from app.services.notification_delivery import guarded_send

    return guarded_send(KIND, now_utc, send_email, mail.to, mail.subject, mail.text)


async def _send(
    db: AsyncSession, run_kind: str, period: str, mails: list[Mail], now_utc: datetime
) -> int:
    from app.tasks.kpi_email_reports import _finish, claim_report

    run_id = await claim_report(db, run_kind, period)
    if run_id is None:
        return 0
    if not mails:
        await _finish(db, run_id, status="skipped", recipients=0, sent=0)
        return 0
    sent = 0
    for mail in mails:
        try:
            if await asyncio.to_thread(_deliver, mail, now_utc):
                sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("month_check mail %s: %s", run_kind, type(exc).__name__)
    await _finish(
        db,
        run_id,
        status="sent" if sent else "failed",
        recipients=len(mails),
        sent=sent,
    )
    return sent


async def tick(db: AsyncSession, now_local: datetime) -> dict[str, int]:
    """Wysyłka należnych maili; znacznik ``kpi_email_report_runs`` = raz na okres."""

    now_utc = now_local.astimezone(timezone.utc)
    out: dict[str, int] = {}
    week = weekly_key(now_local)
    if week:
        rows = await weekly_rows(db, now_utc)
        mails: list[Mail] = []
        if rows:
            subject, text = render_weekly(rows, week)
            mails = [Mail(to, subject, text) for to in await recipients(db)]
        out["weekly"] = await _send(db, WEEKLY_RUN, week, mails, now_utc)
    month = summary_key(now_local)
    if month and await to_finance(db):
        view = await service.month_view(db, month, amounts=True, today=now_local.date())
        subject, text = render_summary(month, view["summary"])
        mails = [Mail(to, subject, text) for to in await recipients(db)]
        out["summary"] = await _send(db, MONTHLY_RUN, month, mails, now_utc)
    return out
