"""„Przygotuj monit”: szkic maila do klienta o fakturach po terminie i wysyłka po kliknięciu.

Monit idzie wyłącznie po kliknięciu człowieka w Finanse → Faktury do klientów →
„Po terminie”, przez zwykłą ścieżkę maili NEXUSA (``services.email.send_email``,
skrzynka serwisowa Graph albo SMTP), z odpowiedzią do osoby, która wysyła.
Automatu nie ma: wysyłka do ludzi spoza firmy, włączenie = decyzja Artura.
Reguła: ``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``.

* Faktury: tylko „po terminie” z dowodem z wyciągów (``views.late_chains``),
  w tym faktury walutowe z nieopłaconym VAT w PLN. Bez dowodu monitu nie ma.
* Poziom: najwyższy z faktur (7 / 14 / 30 dni po terminie, ``receivables``);
  przed 7. dniem szkic jest, ale monit nie jest proponowany.
* Adresaci: kontakty klienta (i scalonych duplikatów) z działem albo stanowiskiem
  od finansów i rozliczeń, potem adres paczki i akceptacji z reguł rozliczeń
  klienta (``cl.send_to``, ``cl.client_acceptance``). Wysłać można tylko na adres
  z tej listy — serwer liczy ją od nowa przy wysyłce.
* Ślad: Historia zdarzeń (``client.payment_reminder_sent``) z poziomem, numerami
  faktur i liczbą adresatów; z niej „ostatni monit”.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.client import Client
from app.models.contact import Contact
from app.models.critical_event import CriticalEvent
from app.models.user import User
from app.services import critical_events
from app.services.client_identity import client_display_name
from app.services.client_invoicing import (
    clients,
    issue_settings,
    ledger,
    payment_proof,
    receivables,
    views,
)
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import ZERO
from app.services.client_invoicing.views import Late

logger = logging.getLogger(__name__)

EVENT_TYPE = "client.payment_reminder_sent"
SUBJECT_MAX = 200
TEXT_MAX = 20_000
Language = Literal["pl", "en"]

#: Dział albo stanowisko kontaktu, który dostaje monity (bez wielkości liter).
_FINANCE_WORDS = re.compile(
    r"finans|księgow|ksiegow|rozlicz|płatn|platn|faktur|należn|naleznos|"
    r"financ|account|invoice|billing|payable|receivable|treasury|controlling",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ReminderError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class Recipient:
    email: str
    name: Optional[str]
    #: ``contact`` — kontakt klienta z działu finansów; ``send_to`` / ``acceptance``
    #: — adres z reguł rozliczeń klienta.
    source: str


SOURCE_LABELS = {
    "contact": "kontakt klienta (finanse)",
    "send_to": "adres paczki do klienta (reguły rozliczeń)",
    "acceptance": "adres akceptacji klienta (reguły rozliczeń)",
}


def _norm_email(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    return text if _EMAIL.match(text) else None


def finance_contact(contact: Contact) -> bool:
    return bool(
        _FINANCE_WORDS.search(contact.department or "")
        or _FINANCE_WORDS.search(contact.position or "")
    )


def merge_recipients(groups: Iterable[Iterable[Recipient]]) -> list[Recipient]:
    """Adresaci bez powtórek, w kolejności źródeł (pierwsze źródło wygrywa)."""

    seen: set[str] = set()
    out = []
    for group in groups:
        for item in group:
            if item.email in seen:
                continue
            seen.add(item.email)
            out.append(item)
    return out


async def recipients(
    db: AsyncSession, client_id: int, members: Collection[int], today: date
) -> list[Recipient]:
    from app.services.client_settlements import client_documents, service

    contacts = [
        Recipient(email, contact.name, "contact")
        for contact in await db.scalars(
            select(Contact)
            .where(Contact.client_id.in_(sorted(members) or [-1]))
            .order_by(Contact.id)
        )
        if finance_contact(contact) and (email := _norm_email(contact.email))
    ]
    rules = await service.rules_for(db, client_id, f"{today.year}-{today.month:02d}")
    ruled = []
    send_to = _norm_email(client_documents.send_to(rules))
    if send_to:
        ruled.append(Recipient(send_to, None, "send_to"))
    acceptance = rules.get("cl.client_acceptance") or {}
    if acceptance.get("level") != "off":
        email = _norm_email((acceptance.get("params") or {}).get("email"))
        if email:
            ruled.append(Recipient(email, None, "acceptance"))
    return merge_recipients([contacts, ruled])


# ── Treść ────────────────────────────────────────────────────────────────────


def _day(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _amount_text(value: Decimal, currency: str, language: Language) -> str:
    text = f"{money(value):,.2f}"
    if language == "pl":
        text = text.replace(",", "\u00a0").replace(".", ",")
    return f"{text} {currency}"


_INTRO: dict[Language, dict[str, str]] = {
    "pl": {
        "first": "uprzejmie przypominamy, że według naszych zapisów poniższe faktury "
        "pozostają nieopłacone po terminie płatności:",
        "second": "ponownie prosimy o zapłatę poniższych faktur, które według naszych "
        "zapisów pozostają nieopłacone po terminie:",
        "final": "mimo wcześniejszych przypomnień poniższe faktury pozostają nieopłacone "
        "ponad 30 dni po terminie. Prosimy o pilną zapłatę:",
    },
    "en": {
        "first": "this is a friendly reminder that, according to our records, the "
        "following invoices remain unpaid past their due date:",
        "second": "we kindly ask again for payment of the following invoices, which "
        "according to our records remain unpaid past their due date:",
        "final": "despite our previous reminders, the following invoices remain unpaid "
        "more than 30 days past their due date. We ask for prompt payment:",
    },
}
_SUBJECT: dict[Language, dict[str, str]] = {
    "pl": receivables.LEVEL_LABELS,
    "en": {
        "first": "Payment reminder",
        "second": "Second payment reminder",
        "final": "Final payment reminder",
    },
}


@dataclass(frozen=True)
class DraftInvoice:
    invoice_id: int
    number: str
    ksef_number: Optional[str]
    issue_date: date
    due_date: Optional[date]
    currency: str
    to_pay: Decimal
    overdue_days: int
    statements_until: Optional[date]
    #: VAT faktury walutowej płatny w PLN (``None`` — zwykła należność).
    vat: Optional[Decimal] = None
    vat_pln: Optional[Decimal] = None

    @property
    def pay_currency(self) -> str:
        return "PLN" if self.vat is not None else self.currency

    @property
    def pay_amount(self) -> Optional[Decimal]:
        return self.vat_pln if self.vat is not None else self.to_pay


def draft_invoice(item: Late) -> DraftInvoice:
    head = item.chain.head
    return DraftInvoice(
        invoice_id=head.id,
        number=head.invoice_number,
        ksef_number=head.ksef_number,
        issue_date=head.issue_date,
        due_date=head.due_date,
        currency=head.currency,
        to_pay=item.chain.to_pay,
        overdue_days=item.verdict.overdue_days,
        statements_until=item.verdict.until,
        vat=item.vat,
        vat_pln=item.vat_pln,
    )


def level_for(invoices: Sequence[DraftInvoice]) -> Optional[str]:
    return receivables.escalation(max((i.overdue_days for i in invoices), default=0))


def _line(invoice: DraftInvoice, language: Language) -> str:
    ksef = f" (KSeF {invoice.ksef_number})" if invoice.ksef_number else ""
    if language == "en":
        head = (
            f"- {invoice.number}{ksef} of {_day(invoice.issue_date)}, "
            f"due {_day(invoice.due_date)}"
        )
        days = f"{invoice.overdue_days} days overdue"
        if invoice.vat is not None:
            amount = (
                _amount_text(invoice.vat_pln, "PLN", language)
                if invoice.vat_pln is not None
                else f"VAT {_amount_text(invoice.vat, invoice.currency, language)} "
                "converted to PLN at the invoice rate"
            )
            return f"{head}: net amount paid, VAT outstanding {amount} — {days}"
        return f"{head}: outstanding {_amount_text(invoice.to_pay, invoice.currency, language)} — {days}"
    head = (
        f"- {invoice.number}{ksef} z {_day(invoice.issue_date)}, "
        f"termin {_day(invoice.due_date)}"
    )
    days = f"{invoice.overdue_days} dni po terminie"
    if invoice.vat is not None:
        amount = (
            _amount_text(invoice.vat_pln, "PLN", language)
            if invoice.vat_pln is not None
            else f"VAT {_amount_text(invoice.vat, invoice.currency, language)} "
            "przeliczony na PLN po kursie z faktury"
        )
        return f"{head}: netto zapłacone, do zapłaty VAT {amount} — {days}"
    return f"{head}: do zapłaty {_amount_text(invoice.to_pay, invoice.currency, language)} — {days}"


def totals(invoices: Iterable[DraftInvoice]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for invoice in invoices:
        if invoice.pay_amount is not None:
            out[invoice.pay_currency] = money(
                out[invoice.pay_currency] + invoice.pay_amount
            )
    return dict(sorted(out.items()))


def compose(
    invoices: Sequence[DraftInvoice],
    *,
    level: str,
    language: Language,
    accounts: dict[str, str],
    signature: Sequence[str],
) -> tuple[str, str]:
    """Temat i treść monitu (bez kwot spoza listy faktur)."""

    count = len(invoices)
    if language == "en":
        subject = f"{_SUBJECT['en'][level]} — {count} overdue invoice{'s' if count != 1 else ''}"
        greeting, total_word = "Dear Sir or Madam,", "Total outstanding"
    else:
        noun = (
            "faktura"
            if count == 1
            else "faktury"
            if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14
            else "faktur"
        )
        subject = f"{_SUBJECT['pl'][level]} — {count} {noun} po terminie"
        greeting, total_word = "Dzień dobry,", "Razem do zapłaty"
    until = min(
        (i.statements_until for i in invoices if i.statements_until), default=None
    )
    lines = [greeting, "", _INTRO[language][level], ""]
    lines += [_line(invoice, language) for invoice in invoices]
    sums = totals(invoices)
    if sums:
        lines += [
            "",
            f"{total_word}: "
            + ", ".join(_amount_text(v, c, language) for c, v in sums.items()),
        ]
    if until:
        lines.append(
            f"Payments recorded up to {_day(until)}."
            if language == "en"
            else f"Stan wpłat na {_day(until)}."
        )
    used = [c for c in sums if accounts.get(c)]
    if used:
        lines.append("")
        if language == "en":
            lines.append("Please pay to the account below, quoting the invoice number:")
        else:
            lines.append("Prosimy o wpłatę na rachunek, w tytule numer faktury:")
        lines += [f"{currency}: {accounts[currency]}" for currency in used]
    lines.append("")
    if language == "en":
        lines.append(
            "If the payment has already been made, please reply with the transfer "
            "confirmation and disregard this message."
        )
        if level == "final":
            lines.append(
                "We reserve the right to charge statutory interest for late payment "
                "in commercial transactions."
            )
        lines += ["", "Kind regards,"]
    else:
        lines.append(
            "Jeśli zapłata została już wysłana, prosimy o potwierdzenie przelewu "
            "w odpowiedzi na tę wiadomość — wtedy monit jest nieaktualny."
        )
        if level == "final":
            lines.append(
                "Zastrzegamy prawo do naliczenia odsetek ustawowych za opóźnienie "
                "w transakcjach handlowych."
            )
        lines += ["", "Z poważaniem"]
    lines += [part for part in signature if part]
    return subject, "\n".join(lines)


def language_for(late: Iterable[Late]) -> Language:
    """Angielski, gdy wszyscy nabywcy faktur mają kraj spoza Polski."""

    countries = {(item.chain.head.buyer_country or "").upper() for item in late}
    return "en" if countries and "" not in countries and "PL" not in countries else "pl"


# ── Szkic i wysyłka ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Draft:
    client_id: int
    client_name: Optional[str]
    level: Optional[str]
    language: Language
    subject: str
    text: str
    invoices: list[DraftInvoice]
    recipients: list[Recipient]
    last_sent_at: Optional[datetime]
    last_level: Optional[str]


async def _late_for(
    db: AsyncSession, members: Collection[int], today: date
) -> list[Late]:
    proof = await payment_proof.load(db)
    items = await views.late_chains(
        db, await ledger.open_chains(db, client_ids=members), day=today, proof=proof
    )
    return sorted(
        (item for item in items if item.proven),
        key=lambda i: (-i.verdict.overdue_days, i.chain.head.id),
    )


async def last_sent(
    db: AsyncSession, members: Collection[int]
) -> dict[int, tuple[datetime, Optional[str]]]:
    """Ostatni monit per klient (z Historii zdarzeń)."""

    out: dict[int, tuple[datetime, Optional[str]]] = {}
    for client_id, at, details in await db.execute(
        select(
            CriticalEvent.client_id, CriticalEvent.occurred_at, CriticalEvent.details
        )
        .where(
            CriticalEvent.event_type == EVENT_TYPE,
            CriticalEvent.outcome == "executed",
            CriticalEvent.client_id.in_(sorted(members) or [-1]),
        )
        .order_by(CriticalEvent.occurred_at)
    ):
        out[int(client_id)] = (at, (details or {}).get("level"))
    return out


async def build(
    db: AsyncSession,
    *,
    client_id: int,
    today: date,
    actor: User,
    language: Optional[Language] = None,
) -> Draft:
    client = await db.get(Client, client_id)
    if client is None:
        raise ReminderError("Nie ma takiego klienta.", 404)
    members = await clients.family(db, [client_id])
    late = await _late_for(db, members, today)
    invoices = [draft_invoice(item) for item in late]
    level = level_for(invoices)
    chosen: Language = language or language_for(late)
    issue = await issue_settings.load(db)
    accounts = {
        currency: account
        for currency in {invoice.pay_currency for invoice in invoices}
        if (account := payment_proof.receiving_account(issue, client_id, currency))
    }
    seller = (issue.get("seller") or {}).get("name")
    subject, text = ("", "")
    if invoices:
        subject, text = compose(
            invoices,
            level=level or "first",
            language=chosen,
            accounts=accounts,
            signature=[actor.name or "", seller or ""],
        )
    history = await last_sent(db, members)
    latest = max(history.values(), default=None, key=lambda item: item[0])
    return Draft(
        client_id=client_id,
        client_name=client_display_name(client),
        level=level,
        language=chosen,
        subject=subject,
        text=text,
        invoices=invoices,
        recipients=await recipients(db, client_id, members, today),
        last_sent_at=latest[0] if latest else None,
        last_level=latest[1] if latest else None,
    )


def draft_payload(draft: Draft) -> dict[str, Any]:
    return {
        "client_id": draft.client_id,
        "client_name": draft.client_name,
        "level": draft.level,
        "level_label": receivables.LEVEL_LABELS.get(draft.level or ""),
        "first_day": receivables.FIRST_DAY,
        "language": draft.language,
        "subject": draft.subject,
        "text": draft.text,
        "invoices": [
            {
                "invoice_id": i.invoice_id,
                "invoice_number": i.number,
                "ksef_number": i.ksef_number,
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "currency": i.currency,
                "to_pay": str(i.to_pay),
                "overdue_days": i.overdue_days,
                "escalation": receivables.escalation(i.overdue_days),
                "vat": str(i.vat) if i.vat is not None else None,
                "vat_pln": str(i.vat_pln) if i.vat_pln is not None else None,
            }
            for i in draft.invoices
        ],
        "totals": [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in totals(draft.invoices).items()
        ],
        "recipients": [
            {
                "email": r.email,
                "name": r.name,
                "source": r.source,
                "source_label": SOURCE_LABELS[r.source],
            }
            for r in draft.recipients
        ],
        "last_sent_at": draft.last_sent_at.isoformat() if draft.last_sent_at else None,
        "last_level": draft.last_level,
    }


def _clean_text(value: str, limit: int, what: str) -> str:
    text = (value or "").replace("\r\n", "\n").strip()
    if len(text) < 3:
        raise ReminderError(f"Uzupełnij {what}.")
    if len(text) > limit:
        raise ReminderError(
            f"{what.capitalize()} jest za długi (najwyżej {limit} znaków)."
        )
    return text


async def send(
    db: AsyncSession,
    *,
    client_id: int,
    to: Sequence[str],
    subject: str,
    text: str,
    today: date,
    actor: User,
) -> dict[str, Any]:
    """Wysyłka monitu po kliknięciu (adresaci tylko z listy szkicu)."""

    from app.services.email import send_email

    clean_subject = " ".join(_clean_text(subject, SUBJECT_MAX, "temat").split())
    clean_text = _clean_text(text, TEXT_MAX, "treść")
    draft = await build(db, client_id=client_id, today=today, actor=actor)
    if not draft.invoices:
        raise ReminderError(
            "Klient nie ma faktur po terminie z dowodem z wyciągów.", 409
        )
    if draft.level is None:
        raise ReminderError(
            f"Monit wysyłamy od {receivables.FIRST_DAY}. dnia po terminie.", 409
        )
    allowed = {r.email for r in draft.recipients}
    wanted = []
    for raw in to:
        email = _norm_email(raw)
        if email is None or email not in allowed:
            raise ReminderError(
                "Adresat spoza kontaktów rozliczeniowych klienta. Dodaj kontakt "
                "z działem Finanse w profilu klienta."
            )
        if email not in wanted:
            wanted.append(email)
    if not wanted:
        raise ReminderError("Wybierz co najmniej jednego adresata.")
    sent, failed = [], []
    for email in wanted:
        try:
            ok = await run_in_threadpool(
                send_email,
                email,
                clean_subject,
                clean_text,
                None,
                reply_to=actor.email or None,
            )
        except Exception:  # send_email nie rzuca, ale monit nie może wywrócić trasy.
            logger.exception("payment_reminder: client=%s", client_id)
            ok = False
        (sent if ok else failed).append(email)
    if sent:
        await critical_events.record_executed(
            db,
            actor=actor,
            event_type=EVENT_TYPE,
            entity_type="client",
            entity_id=client_id,
            client_id=client_id,
            reason=f"{receivables.LEVEL_LABELS[draft.level]}: "
            + ", ".join(i.number for i in draft.invoices),
            details={
                "level": draft.level,
                "invoice_ids": [i.invoice_id for i in draft.invoices],
                "recipients": len(sent),
                "failed": len(failed),
            },
        )
    else:
        logger.warning(
            "payment_reminder: no channel confirmed client=%s recipients=%s",
            client_id,
            len(wanted),
        )
    return {"sent": len(sent), "failed": len(failed), "level": draft.level}


__all__ = [
    "Draft",
    "DraftInvoice",
    "EVENT_TYPE",
    "Recipient",
    "ReminderError",
    "build",
    "compose",
    "draft_invoice",
    "draft_payload",
    "finance_contact",
    "language_for",
    "last_sent",
    "level_for",
    "merge_recipients",
    "recipients",
    "send",
    "totals",
]
