"""Nabywca kontraktu Nordei z maila CPro „Invoice address was updated” (24.11.2026).

Przegląd skrzynek DL-ów Nordei: CPro ogłasza zmianę adresu faktury mailem
„Important changes made to contract N” tylko do DL-a przypisanego do kontraktu
(15.09.2026 kontrakt przeszedł z F218 Abp S.A. na F206 Abp Finland i nikt nie
przekazał tego do rozliczeń; w 2025 ten sam błąd dał korekty za dwa miesiące).

Decyzje Artura z 24.11.2026:

* **Zapis sam:** pętla ``cpro_mail`` (nadawca sprawdzony w nagłówkach) dopisuje
  w ``contract_buyers`` nabywcę od miesiąca maila (dzień firmy, Europe/Warsaw):
  mail z 15.09 = nabywca od 2026-09. Późniejsze wpisy zostają (``remember_buyer``).
* **Kod adresu CPro przy nabywcy:** Finanse wpisują w ustawieniach wystawiania
  „Kod w CPro” (F206, F218…). Kodu spoza listy NEXUS nie zgaduje po nazwie.
* **Faktur nie rusza:** dzwonek Finansów wymienia faktury od miesiąca zmiany
  wystawione na innego nabywcę i szkice do poprawy; korekta to decyzja Finansów.
* Numer N to numer Call-Off, czyli tytuł zamówienia Nordei (``client_orders.title``);
  zamówienie daje kontrakt. Brak zamówienia, kilka kontraktów albo nieznany kod =
  „Do ręcznego” i dzwonek.

Reguła: ``docs/claude/integracje/cpro-maile-nordei.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.candidate import Candidate
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_order import ClientOrder
from app.models.contract import Contract
from app.models.notification import NotificationType
from app.services.board_stage_badges import cpro_enabled_for_client
from app.services.client_invoicing import issue_settings

logger = logging.getLogger(__name__)

OUTCOME_DONE = "done"
OUTCOME_ALREADY = "already"
OUTCOME_MANUAL = "manual"
#: Faktury wycofane nie weszły do obrotu; reszta (także odrzucone, które pójdą
#: ponownie z tym samym nabywcą) jest do sprawdzenia.
SKIP_STATUSES = ("cancelled",)
LIST_MAX = 8
SETTINGS_LINK = "/finance?view=sales-invoices&siView=issue-settings"


@dataclass(frozen=True)
class BuyerChange:
    outcome: str
    text: str
    notified: int = 0


def change_month(received_at: datetime) -> str:
    """Miesiąc, od którego obowiązuje nowy nabywca (``RRRR-MM``, dzień firmy)."""

    day = business_date(received_at)
    return f"{day.year:04d}-{day.month:02d}"


def _month_label(period: str) -> str:
    year, month = period.split("-")
    return f"{month}.{year}"


def _invoice_period(invoice: ClientIssuedInvoice) -> str:
    if invoice.period_year and invoice.period_month:
        return f"{int(invoice.period_year):04d}-{int(invoice.period_month):02d}"
    day = invoice.sale_date or invoice.issue_date
    return f"{day.year:04d}-{day.month:02d}"


def _has_contract(invoice: ClientIssuedInvoice, contract_id: int) -> bool:
    return any(
        str((line or {}).get("contract_id") or "") == str(contract_id)
        for line in invoice.lines or []
    )


async def _invoices_to_check(
    db: AsyncSession, client_id: int, contract_id: int, period: str, code: str
) -> tuple[list[str], int]:
    """Numery faktur i liczba szkiców od ``period`` z kontraktem i innym nabywcą."""

    rows = (
        await db.scalars(
            select(ClientIssuedInvoice)
            .where(
                ClientIssuedInvoice.client_id == client_id,
                ClientIssuedInvoice.status.not_in(SKIP_STATUSES),
            )
            .order_by(ClientIssuedInvoice.issue_date, ClientIssuedInvoice.id)
        )
    ).all()
    numbers: list[str] = []
    drafts = 0
    for invoice in rows:
        if _invoice_period(invoice) < period or not _has_contract(invoice, contract_id):
            continue
        if (invoice.buyer or {}).get("code") == code:
            continue
        if invoice.status == "draft":
            drafts += 1
        else:
            numbers.append(invoice.invoice_number or f"#{invoice.id}")
    return numbers, drafts


async def _person(db: AsyncSession, contract_id: int) -> Optional[str]:
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname)
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(Contract.id == contract_id)
        )
    ).first()
    if row is None:
        return None
    return " ".join(part for part in row if part) or None


def buyer_message(
    *,
    number: str,
    person: Optional[str],
    period: str,
    new_buyer: str,
    old_buyer: Optional[str],
    invoices: Sequence[str],
    drafts: int,
) -> str:
    head = f"Kontrakt CPro {number}" + (f" · {person}" if person else "")
    text = (
        f"{head}: od {_month_label(period)} nabywca {new_buyer}"
        + (f" (w NEXUSIE był: {old_buyer})" if old_buyer else "")
        + "."
    )
    if invoices:
        shown = ", ".join(invoices[:LIST_MAX])
        more = len(invoices) - LIST_MAX
        text += f" Faktury od tego miesiąca na innego nabywcę: {shown}" + (
            f" i {more} więcej" if more > 0 else ""
        )
        text += "."
    if drafts:
        text += f" Szkice do poprawy nabywcy: {drafts}."
    if invoices or drafts:
        text += " NEXUS faktur nie zmienia — korekta to decyzja Finansów."
    return text


async def _ring(
    db: AsyncSession, title: str, message: str, event_id: int, link: str
) -> int:
    from app.services.hired_order_status import (  # noqa: PLC0415
        finance_recipient_ids,
    )
    from app.services.notification_triggers import emit  # noqa: PLC0415

    sent = 0
    for user_id in await finance_recipient_ids(db):
        try:
            async with db.begin_nested():
                row = await emit(
                    db,
                    user_id=user_id,
                    title=title,
                    message=message,
                    ntype=NotificationType.cpro_invoice_buyer,
                    related_entity_type="cpro_mail_event",
                    related_entity_id=event_id,
                    link=link,
                )
            sent += int(row is not None)
        except Exception:  # noqa: BLE001 — dzwonek nie cofa zapisu nabywcy
            logger.exception("cpro_invoice_buyer: dzwonek dla %s nie powstał", user_id)
    return sent


async def _manual(db: AsyncSession, text: str, event_id: int) -> BuyerChange:
    sent = await _ring(
        db, "CPro: zmiana nabywcy do przypisania", text, event_id, SETTINGS_LINK
    )
    return BuyerChange(OUTCOME_MANUAL, text, sent)


async def apply_invoice_address(
    db: AsyncSession,
    *,
    number: str,
    cpro_code: str,
    address: Optional[str],
    received_at: datetime,
    event_id: int,
) -> BuyerChange:
    """Nowy nabywca kontraktu ``number`` od miesiąca maila; wołający commituje."""

    period = change_month(received_at)
    what = f"Kontrakt CPro {number}: od {_month_label(period)} adres faktury {address or cpro_code}."
    orders = (
        await db.execute(
            select(ClientOrder.client_id, ClientOrder.contract_id).where(
                func.btrim(ClientOrder.title) == number
            )
        )
    ).all()
    pairs = {
        (client_id, contract_id)
        for client_id, contract_id in orders
        if contract_id is not None and cpro_enabled_for_client(client_id)
    }
    if not pairs:
        return await _manual(
            db,
            f"{what} Nie ma zamówienia Nordei z tym numerem — przypisz nabywcę w szkicu.",
            event_id,
        )
    if len(pairs) > 1:
        return await _manual(
            db,
            f"{what} Numer ma kilka kontraktów w NEXUSIE — przypisz nabywcę w szkicu.",
            event_id,
        )
    ((client_id, contract_id),) = pairs
    settings: dict[str, Any] = await issue_settings.load(db, lock=True)
    buyer = issue_settings.buyer_by_cpro_code(settings, client_id, cpro_code)
    if buyer is None:
        return await _manual(
            db,
            f"{what} Kodu {cpro_code} nie ma przy żadnym nabywcy klienta: wpisz "
            "„Kod w CPro” w Ustawieniach wystawiania.",
            event_id,
        )
    old = issue_settings.buyer_for_contract(settings, client_id, contract_id, period)
    if not issue_settings.remember_buyer(
        settings, client_id, [contract_id], buyer["code"], period
    ):
        return BuyerChange(
            OUTCOME_ALREADY,
            f"Kontrakt {number} ma już od {_month_label(period)} nabywcę {cpro_code}.",
        )
    await issue_settings.save(db, settings, actor_id=None)
    invoices, drafts = await _invoices_to_check(
        db, client_id, contract_id, period, buyer["code"]
    )
    message = buyer_message(
        number=number,
        person=await _person(db, contract_id),
        period=period,
        new_buyer=f"{cpro_code} {buyer['name']}",
        old_buyer=old["name"] if old else None,
        invoices=invoices,
        drafts=drafts,
    )
    sent = await _ring(
        db,
        "CPro: nowy nabywca kontraktu Nordei",
        message,
        event_id,
        f"/finance?view=sales-invoices&siView=issue&siPeriod={period}",
    )
    return BuyerChange(
        OUTCOME_DONE,
        f"Nabywca od {_month_label(period)}: {cpro_code} {buyer['name']}; "
        f"faktury do sprawdzenia: {len(invoices)}, szkice: {drafts}.",
        sent,
    )


__all__ = ["BuyerChange", "apply_invoice_address", "buyer_message", "change_month"]
