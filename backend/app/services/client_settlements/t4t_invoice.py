"""Faktura do klienta z raportu T4T (Nordea, korespondencja Finansów z 23.11.2026).

Od września Nordea przyjmuje na fakturze sprzedaży tylko godziny zatwierdzone
w Time for Teams (status 2). Za wrzesień 18 faktur miało więcej godzin niż
zatwierdzone (zwykle o 32 h z ostatniego tygodnia), a Nordea zapowiada
odrzucanie takich faktur i noty kredytowe. Dla klienta z regułą
``report.time_for_teams`` „Do faktury dla klienta” liczy więc pozycję osoby
z godzin zatwierdzonych w ostatniej wersji raportu, a nie z RCP:

* godziny niezatwierdzone (status 0 albo 1) w tej wersji wstrzymują pozycję
  z powodem „Godziny niezatwierdzone w T4T (wersja z DD.MM)”;
* wyjątek: mailowa akceptacja managera klienta z liczbą godzin za miesiąc, gdy
  osoba odeszła z projektu i nie poprawi T4T (Cost Control przyjął ją 4 razy
  w VIII–X). Mail leży przy osobie jak każdy dokument rozliczenia;
* termin faktury (art. 106i ust. 1 VAT): 15. dzień następnego miesiąca.
  Na N dni przed nim (parametr reguły) ekran ostrzega, ile osób nie ma
  zatwierdzonych godzin.

Godzin przeniesionych z poprzedniego miesiąca automat nie wydziela: raport
ich nie odróżnia, a praktyka jest decyzją Finansów
(``docs/claude/finanse-insights/rozliczenia-praktyka-z-korespondencji.md``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_time_report import ClientTimeReportRow
from app.models.consultant_portal import CpDocument
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus
from app.services.client_order_lines import month_bounds
from app.services.client_settlements import acceptance_mail, mail_text, service
from app.services.client_settlements import time_report_engine as engine
from app.services.client_settlements import time_reports
from app.services.consultant_portal import documents as portal_documents
from app.services.hr.payroll_periods import add_months
from app.services.order_revenue_steps import priced_for_month

logger = logging.getLogger(__name__)

RULE_KEY = time_reports.RULE_KEY
#: 0 Not submitted, 1 Submitted — godziny jeszcze bez akceptacji managera.
PENDING = (0, engine.SUBMITTED)
DEADLINE_DAY = 15
DEFAULT_WARN_DAYS = 5
MAX_WARN_DAYS = 31
MAIL_MIMES = (mail_text.MSG, mail_text.EML)
ZERO = Decimal("0")


def is_on(rules: dict[str, dict[str, Any]]) -> bool:
    rule = rules.get(RULE_KEY)
    return bool(rule) and rule["level"] != "off"


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


# ── Godziny z ostatniej wersji raportu ───────────────────────────────────────


@dataclass(frozen=True)
class Hours:
    approved: Decimal
    pending: Decimal


@dataclass(frozen=True)
class Basis:
    version_id: Optional[int]
    received_on: Optional[date]
    hours: dict[int, Hours]
    contracts: dict[int, Contract]

    @property
    def version_label(self) -> str:
        return (
            f"wersja z {self.received_on:%d.%m}" if self.received_on else "brak raportu"
        )


async def basis(db: AsyncSession, client_id: int, month: str) -> Basis:
    """Godziny per kontrakt z ostatniej wersji raportu za miesiąc.

    Wersje się nie sumują: każda wersja to pełny raport miesiąca, więc liczy
    się tylko najnowsza (``received_on``, potem numer wersji). Numer osoby bez
    potwierdzenia w kartotece nie przypisuje godzin nikomu."""

    reports = await time_reports._reports(db, client_id, month)
    contracts = await time_reports._contracts(db, client_id)
    plain = {cid: c.contract for cid, c in contracts.items()}
    if not reports:
        return Basis(None, None, {}, plain)
    latest = reports[-1]
    person_contract, _, _ = time_reports.person_contracts(
        await time_reports._ids(db, client_id), contracts, month
    )
    sums: dict[int, list[Decimal]] = {}
    for person_no, status, total in (
        await db.execute(
            select(
                ClientTimeReportRow.person_no,
                ClientTimeReportRow.status,
                func.sum(ClientTimeReportRow.hours),
            )
            .where(ClientTimeReportRow.report_id == latest.id)
            .group_by(ClientTimeReportRow.person_no, ClientTimeReportRow.status)
        )
    ).all():
        contract_id = person_contract.get(person_no)
        if contract_id is None:
            continue
        slot = sums.setdefault(contract_id, [ZERO, ZERO])
        if status == engine.APPROVED:
            slot[0] += Decimal(total)
        elif status in PENDING:
            slot[1] += Decimal(total)
    return Basis(
        latest.id,
        latest.received_on,
        {cid: Hours(a, p) for cid, (a, p) in sums.items()},
        plain,
    )


async def orders_for(
    db: AsyncSession, contract_ids: Iterable[int], month: str
) -> dict[int, Any]:
    """Linia zamówienia osoby na miesiąc, jak ``service._order_for``, dla wielu
    kontraktów jednym zapytaniem (Nordea: ok. 300 osób)."""

    ids = list(contract_ids)
    if not ids:
        return {}
    first, last = month_bounds(month)
    found = (
        await db.scalars(
            select(ClientOrder)
            .where(
                ClientOrder.contract_id.in_(ids),
                ClientOrder.status.in_(service.ORDER_STATUSES),
                or_(ClientOrder.start_date.is_(None), ClientOrder.start_date <= last),
                or_(ClientOrder.end_date.is_(None), ClientOrder.end_date >= first),
            )
            .order_by(
                (ClientOrder.status == ClientOrderStatus.active).desc(),
                ClientOrder.start_date.desc().nullslast(),
                ClientOrder.id.desc(),
            )
        )
    ).all()
    best: dict[int, ClientOrder] = {}
    for order in found:
        best.setdefault(order.contract_id, order)
    priced = await priced_for_month(db, list(best.values()), first)
    return {order.contract_id: order for order in priced}


# ── Wyjątek: mailowa akceptacja managera ─────────────────────────────────────


@dataclass(frozen=True)
class MailAcceptance:
    ok: bool
    hours: Optional[Decimal]
    note: str


def judge_mail(
    mail: mail_text.Mail,
    messages: list[acceptance_mail.MailMessage],
    *,
    month: str,
    domains: tuple[str, ...],
) -> MailAcceptance:
    """Czy mail to akceptacja managera klienta z jedną liczbą godzin za miesiąc.

    Nasza prośba („please approve the 102 hours”) sama nie wystarcza: w wątku
    musi być wiadomość z domeny klienta (z kontaktów klienta)."""

    found = mail_text.read_acceptance(mail.text, month, english=True)
    label = mail_text.month_label(month)
    if not acceptance_mail.from_domain(messages, domains):
        return MailAcceptance(
            False, None, "Mail z akceptacją nie pochodzi od managera klienta."
        )
    if not found.approved:
        return MailAcceptance(False, None, "W mailu nie ma akceptacji managera.")
    if month not in found.months:
        return MailAcceptance(False, None, f"Akceptacja mailowa nie za {label}.")
    values = sorted(set(found.hours))
    if len(values) != 1:
        listed = ", ".join(f"{_fmt(v)} h" for v in values) or "brak"
        return MailAcceptance(
            False,
            None,
            f"Akceptacja mailowa bez jednej liczby godzin ({listed}): sprawdź mail.",
        )
    return MailAcceptance(
        True,
        values[0],
        f"Akceptacja mailowa managera: {_fmt(values[0])} h za {label}.",
    )


def _read(content: bytes, mime: str) -> tuple[Optional[mail_text.Mail], list[Any]]:
    return mail_text.read(content, mime), acceptance_mail.read(content, mime)


async def client_domains(db: AsyncSession, client_id: int) -> tuple[str, ...]:
    emails = await db.scalars(
        select(func.lower(func.btrim(Contact.email))).where(
            Contact.client_id == client_id, Contact.email.like("%@%")
        )
    )
    return tuple(sorted({e.rpartition("@")[2] for e in emails if e}))


async def mail_acceptances(
    db: AsyncSession, client_id: int, month: str, contract_ids: list[int]
) -> dict[int, MailAcceptance]:
    """Najlepsza akceptacja mailowa per kontrakt z maili miesiąca i następnego.

    Akceptacja za wrzesień przychodzi zwykle w październiku, a mail bez miesiąca
    w temacie dostaje okres z daty, więc czytamy oba miesiące; o miesiącu
    rozstrzyga treść."""

    if not contract_ids:
        return {}
    year, mon = (int(x) for x in month.split("-"))
    next_year, next_mon = add_months(year, mon, 1)
    docs = (
        await db.scalars(
            select(CpDocument)
            .where(
                CpDocument.contract_id.in_(contract_ids),
                CpDocument.kind == "report",
                CpDocument.status != "rejected",
                CpDocument.mime.in_(MAIL_MIMES),
                or_(
                    (CpDocument.period_year == year) & (CpDocument.period_month == mon),
                    (CpDocument.period_year == next_year)
                    & (CpDocument.period_month == next_mon),
                ),
            )
            .order_by(CpDocument.created_at.desc(), CpDocument.id.desc())
        )
    ).all()
    if not docs:
        return {}
    domains = await client_domains(db, client_id)
    out: dict[int, MailAcceptance] = {}
    for doc in docs:
        if doc.contract_id is None or (
            doc.contract_id in out and out[doc.contract_id].ok
        ):
            continue
        try:
            content = portal_documents.path_for(doc.file_path).read_bytes()
        except OSError:
            continue
        mail, messages = await asyncio.to_thread(_read, content, doc.mime)
        if mail is None:
            continue
        verdict = judge_mail(mail, messages, month=month, domains=domains)
        if verdict.ok or doc.contract_id not in out:
            out[doc.contract_id] = verdict
    return out


# ── Termin faktury (art. 106i) ───────────────────────────────────────────────


def deadline(month: str) -> date:
    """15. dzień miesiąca po miesiącu usługi."""

    year, mon = (int(x) for x in month.split("-"))
    year, mon = add_months(year, mon, 1)
    return date(year, mon, DEADLINE_DAY)


def warn_days(rules: dict[str, dict[str, Any]]) -> int:
    raw = str(rules.get(RULE_KEY, {}).get("params", {}).get("warn_days") or "")
    try:
        days = int(raw.strip())
    except ValueError:
        return DEFAULT_WARN_DAYS
    return max(0, min(days, MAX_WARN_DAYS))


def left_project(contract: Optional[Contract], month: str) -> bool:
    """Osoba odeszła z projektu: kontrakt zakończony najpóźniej w terminie faktury."""

    if contract is None:
        return False
    if contract.status == ContractStatus.ended:
        return True
    return contract.end_date is not None and contract.end_date <= deadline(month)


def deadline_warning(
    month: str,
    today: Optional[date],
    rules: dict[str, dict[str, Any]],
    missing: list[str],
) -> Optional[dict[str, Any]]:
    """Ostrzeżenie przed terminem faktury: osoby bez zatwierdzonych godzin."""

    if today is None or not missing:
        return None
    due = deadline(month)
    days_left = (due - today).days
    if days_left > warn_days(rules):
        return None
    return {
        "date": due.isoformat(),
        "days_left": days_left,
        "overdue": days_left < 0,
        "missing": len(missing),
        "people": sorted(missing, key=str.lower),
    }
