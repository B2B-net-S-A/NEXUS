"""Rozliczenie widziane przez konsultanta (roadmapa E3, styl A „Do zrobienia”).

Lista dozwolonych pól, jak reszta panelu (``consultant_portal/panel.py``):
konsultant widzi stan swojego RCP, wynik sprawdzenia, MD i — po przyjęciu — kwotę
do własnej faktury. Nigdy stawki klienta, przychodu, marży ani mnożnika nadgodzin
(decyzja z uwag rozliczeń BNP, 09.11.2026). Bez paska kroków miesiąca: decyzja
Artura z 04.11.2026 (styl A).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_settlements import contractor_invoices, service
from app.services.multi_consultant_orders import format_md
from app.services.client_settlements import settings as module_settings

#: Termin zapłaty z umowy B2B (dni od nadania numeru KSeF), gdy klient nie ma
#: reguły ``ci.payment_days``.
DEFAULT_PAYMENT_DAYS = 14
#: Grupy kontroli, które konsultant może zobaczyć; „Zamówienie”, „Stawki”
#: i „MD wdrożeniowe” zostają u Finansów.
VISIBLE_GROUPS = ("RCP", "Time Sheet", "Pola i sumy", "Nadgodziny")

STATUS_LABELS = {
    "checking": "Sprawdzamy RCP",
    "warnings": "Sprawdzamy RCP",
    "ok": "RCP bez uwag, czeka na akceptację Finansów",
    "no_md": "RCP u Finansów: sprawą zajmują się Finanse i Twój opiekun",
    "needs_fix": "RCP do poprawy",
    "accepted": "RCP przyjęte: wystaw fakturę",
}
MONTHS = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
#: Plan miesiąca (estymacja, E5.3): RCP z planowanymi dniami przed końcem miesiąca.
ESTIMATE_LABELS = {
    "checking": "Plan: sprawdzamy",
    "warnings": "Plan: sprawdzamy",
    "ok": "Plan bez uwag, czeka na akceptację Finansów",
    "no_md": "Plan u Finansów: sprawą zajmują się Finanse i Twój opiekun",
    "needs_fix": "Plan do poprawy",
    "accepted": "Plan przyjęty. RCP za ten miesiąc wyślij po jego końcu",
}
#: Uwagi, które konsultant sam może naprawić, i zadanie w „Do zrobienia”.
FIXABLE = {
    "Brak maila z akceptacją pracy dodatkowej": "Dołącz mail z akceptacją pracy dodatkowej",
    "Excel bez maila akceptującego usługi": "Dołącz mail z akceptacją usług",
    "PDF bez podpisu elektronicznego": "Wyślij RCP z podpisem elektronicznym",
    "RCP za inny miesiąc": "Wyślij RCP za właściwy miesiąc",
}


def _dec(value: Optional[Decimal], places: int) -> Optional[str]:
    return None if value is None else f"{Decimal(value):.{places}f}"


async def payment_days(db: AsyncSession, client_id: Optional[int], month: str) -> int:
    if client_id is None:
        return DEFAULT_PAYMENT_DAYS
    rule = (await service.rules_for(db, client_id, month))["ci.payment_days"]
    if rule["level"] == "off":
        return DEFAULT_PAYMENT_DAYS
    try:
        days = int(str(rule["params"].get("days", "")).strip())
    except ValueError:
        return DEFAULT_PAYMENT_DAYS
    return days if 0 < days <= 120 else DEFAULT_PAYMENT_DAYS


def _visible_checks(checks: list[Any]) -> list[dict[str, Optional[str]]]:
    out: list[dict[str, Optional[str]]] = []
    for group in checks:
        if not isinstance(group, dict) or group.get("title") not in VISIBLE_GROUPS:
            continue
        for check in group.get("checks") or []:
            title = str(check.get("title") or "")
            if "×" in title:  # mnożnik nadgodzin
                continue
            out.append({"state": check.get("state"), "title": title})
    return out


async def view(
    db: AsyncSession, contract_id: int, client_id: Optional[int], year: int, month: int
) -> Optional[dict[str, Any]]:
    """Blok „rozliczenie” w wierszu miesiąca; ``None`` przy wyłączonym module
    albo bez rozliczenia (wtedy panel pokazuje dzisiejszy stan dokumentów)."""

    if not await module_settings.is_enabled(db):
        return None
    period = f"{year}-{month:02d}"
    s = await service._settlement(db, contract_id, period)
    if s is None:
        s = await service._settlement(db, contract_id, period, kind=service.ESTIMATE)
        if s is None:
            return None
        return {
            "status": s.status,
            "kind": service.ESTIMATE,
            "label": ESTIMATE_LABELS.get(s.status, "Plan: sprawdzamy"),
            "fix_reason": s.fix_reason if s.status == "needs_fix" else None,
            "checks": _visible_checks(s.checks or []),
            "todo": [],
            "md_regular": _dec(s.md_regular, 3),
            "md_extra": None,
            "md_remaining_after": None,
            "invoice": None,
        }
    checks = _visible_checks(s.checks or [])
    todo = [
        FIXABLE[c["title"]]
        for c in checks
        if c["state"] in ("fail", "warn") and c["title"] in FIXABLE
    ]
    result: dict[str, Any] = {
        "status": s.status,
        "kind": service.ACTUAL,
        "label": STATUS_LABELS.get(s.status, "Sprawdzamy RCP"),
        "fix_reason": s.fix_reason if s.status == "needs_fix" else None,
        "checks": checks,
        "todo": todo if s.status != "accepted" else [],
        "md_regular": _dec(s.md_regular, 3),
        "md_extra": _dec(s.md_extra, 3) if s.md_extra else None,
        "md_remaining_after": None,
        "invoice": None,
    }
    if client_id is not None:
        rules = await service.rules_for(db, client_id, period)
        if rules["order.md_visible"]["level"] != "off":
            result["md_remaining_after"] = next(
                (
                    c.get("remaining_after")
                    for c in (s.checks or [])
                    if isinstance(c, dict) and "remaining_after" in c
                ),
                None,
            )
    if s.status == "accepted":
        from app.services.consultant_portal.panel import BUYER  # noqa: PLC0415

        last = date(year, month, calendar.monthrange(year, month)[1])
        days = await payment_days(db, client_id, period)
        amount = _dec(s.amount_cost, 2)
        result["invoice"] = {
            "amount_net": amount,
            "sale_date": last.isoformat(),
            "payment_days": days,
            # E3.2: pola do przepisania w programie do faktur (kopiowanie, nie
            # wystawianie). Jedna pozycja: podział na pracę dodatkową zdradzałby
            # mnożnik, którego konsultant nie widzi.
            "buyer": BUYER,
            "item": {
                "description": f"Usługi zgodnie z umową za {MONTHS[month - 1]} {year}",
                "quantity": "1",
                "net": amount,
            },
            "ksef": await _ksef(db, s, client_id, period, days),
        }
        over = service.md_over(s)
        if over:
            # Rozliczenia 10.11: „zafakturować możesz X MD”, bez obietnicy zamówienia.
            billable = Decimal(s.md_charged or 0) + Decimal(s.md_onboarding or 0)
            result["label"] = (
                f"RCP przyjęte: wystaw fakturę na {format_md(billable)} MD, "
                "tyle zostało na zamówieniu"
            )
        ksef = result["invoice"]["ksef"]
        if ksef is not None:
            result["label"] = ksef["label"]
            if ksef["state"] == contractor_invoices.DIFFERS:
                result["todo"] = ["Wystaw korektę faktury"]
    return result


async def _ksef(
    db: AsyncSession,
    s: Any,
    client_id: Optional[int],
    period: str,
    days: int,
) -> Optional[dict[str, Any]]:
    """Faktura konsultanta, która już jest w KSeF (E4): stan i termin zapłaty."""

    invoices = [
        i
        for i in (await contractor_invoices.for_month(db, [s.contract_id], period)).get(
            s.contract_id, []
        )
        if i.nip_state in contractor_invoices.BOUND
    ]
    if not invoices or client_id is None:
        return None
    rules = await service.rules_for(db, client_id, period)
    state = contractor_invoices.state(s, invoices, rules)
    first = invoices[0]
    due = first.acquired_at.date() + timedelta(days=days) if first.acquired_at else None
    net = sum((i.net_amount or 0) for i in invoices)
    label = (
        "Faktura w KSeF: inna kwota niż rozliczenie"
        if state == contractor_invoices.DIFFERS
        else "Faktura w KSeF"
        + (f": płatność do {due.strftime('%d.%m.%Y')}" if due else "")
    )
    return {
        "state": state,
        "label": label,
        "invoice_number": first.invoice_number,
        "ksef_number": first.ksef_number,
        "net_amount": f"{net:.2f}",
        "due_date": due.isoformat() if due else None,
    }


async def estimate_todo(
    db: AsyncSession, contract_id: int, client_id: Optional[int], today: date
) -> Optional[dict[str, str]]:
    """Zadanie „Wyślij RCP z planem” w miesiącu z estymacją (E5.4), dopóki planu
    nie ma albo wrócił do poprawy."""

    if client_id is None or not await module_settings.is_enabled(db):
        return None
    period = f"{today.year}-{today.month:02d}"
    if not await service.estimate_allowed(db, client_id, period):
        return None
    plan = await service._settlement(db, contract_id, period, kind=service.ESTIMATE)
    if plan is not None and plan.status != "needs_fix":
        return None
    if plan is None and await service._month_reports(
        db, contract_id, period, kind=service.ESTIMATE
    ):
        return None
    rule = (await service.rules_for(db, client_id, period))["cl.estimate"]
    deadline = str(rule["params"].get("deadline") or "").strip()
    return {
        "key": f"estimate-{period}",
        "title": f"Wyślij RCP z planem na {MONTHS[today.month - 1]}"
        + (f" do {deadline}" if deadline else ""),
        "detail": "Planowane dni do końca miesiąca, podpisane przez akceptanta"
        + (f". Co poprawić: {plan.fix_reason}" if plan and plan.fix_reason else ""),
        "href": "/konsultant/faktury",
    }
