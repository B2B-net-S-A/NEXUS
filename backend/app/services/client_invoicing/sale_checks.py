"""Kontrola formalna faktury sprzedaży przed wysyłką i faktur spoza NEXUSA (25.11.2026).

Audyt fakturowania IV–X 2026 znalazł błędy, które klient odsyła do korekty,
a których żadna kontrola NEXUSA nie widziała:

* **data sprzedaży poza okresem usługi** — faktura za maj z datą sprzedaży
  14.06 (``P_6`` w innym miesiącu niż okres pozycji),
* **Nordea**: w polu „ID” pozycji imię zamiast numeru osoby albo osoba klienta
  („Nordea Contact”) wpisana jako „Contractor”,
* **więcej MD (godzin) niż dni roboczych** miesiąca,
* **osoba w pozycji bez kontraktu** u tego klienta.

Wynik to ostrzeżenia, nie blokada: szkic z NEXUSA idzie do KSeF dopiero
z powodem („Wyślij mimo uwag”), a faktury z KSeF wystawione poza NEXUSEM
(eBI24) pokazuje raport „Kontrola faktur z KSeF” w Fakturach do klientów.

Kontrola kodu osoby (``cl.contractor_person_id``) to reguła klienta, nie
warunek na nazwę klienta w kodzie. Pozostałe trzy działają u każdego klienta.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import is_business_day
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.client_time_report import ClientExternalId
from app.models.contract import Contract
from app.services.client_invoicing import clients, matching, requirements
from app.services.client_invoicing import unknown_refs as refs
from app.services.client_settlements.invoice_fields import MONTH_NAMES, months_in

#: Kod osoby u klienta po „ID:” (Nordea: litera i 5–7 cyfr).
PERSON_CODE = re.compile(r"[A-Z]\d{5,7}")
#: „ID: M1”, „ID:M1”, „ID M1” (bez dwukropka) — nie „NIDS:”.
_ID_FIELD = re.compile(r"\bID\b\s*:?\s*([^,;]*)", re.IGNORECASE)
HOURS_PER_DAY = 8
_DAY_UNITS = frozenset({"md", "dzień", "dzien", "dni", "d", "osobodzień", "mandays"})
_HOUR_UNITS = frozenset({"h", "godz", "godzin", "godziny", "godzina", "hours"})
RAW_MAX = 40


@dataclass(frozen=True)
class Line:
    name: str
    consultant: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    contract_id: Optional[int] = None


@dataclass(frozen=True)
class Owner:
    contract_id: int
    person: str


def _day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _month(year: Optional[int], month: int) -> str:
    name = MONTH_NAMES[month - 1]
    return f"{name} {year}" if year else name


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def working_days(year: int, month: int) -> int:
    last = calendar.monthrange(year, month)[1]
    return sum(
        1
        for day in range(1, last + 1)
        if is_business_day(datetime.combine(date(year, month, day), time(12)))
    )


def sale_date_problems(
    sale: date, period: Optional[tuple[int, int]], lines: Sequence[Line]
) -> list[str]:
    """Data sprzedaży a okres usługi (miesiąc faktury i miesiące w nazwach pozycji).

    ``period`` — miesiąc usługi zapisany osobno od daty sprzedaży (szkic z „Do
    faktury”); faktura z KSeF ma okres z samej daty sprzedaży, więc dla niej
    liczą się miesiące z nazw pozycji.
    """

    out: list[str] = []
    if period is not None and (sale.year, sale.month) != period:
        out.append(
            f"Data sprzedaży {_day(sale)} poza okresem usługi "
            f"({_month(*period)}) — data sprzedaży to dzień z okresu usługi, "
            "zwykle ostatni dzień miesiąca."
        )
        return out
    for index, line in enumerate(lines, start=1):
        for year, month in sorted(
            months_in(line.name), key=lambda m: (m[0] or 0, m[1])
        ):
            if month != sale.month or (year is not None and year != sale.year):
                out.append(
                    f"Data sprzedaży {_day(sale)}, a pozycja {index} mówi "
                    f"„{_month(year, month)}” — data sprzedaży i okres usługi "
                    "powinny być w tym samym miesiącu."
                )
                return out
    return out


def _unit_kind(unit: Optional[str]) -> Optional[str]:
    folded = re.sub(r"[.,\s]", "", (unit or "").lower())
    if folded in _DAY_UNITS:
        return "days"
    if folded in _HOUR_UNITS:
        return "hours"
    return None


def quantity_problems(lines: Sequence[Line], period: tuple[int, int]) -> list[str]:
    """Pozycja z liczbą MD (godzin) większą niż dni robocze (× 8 h) miesiąca."""

    days = working_days(*period)
    out: list[str] = []
    for index, line in enumerate(lines, start=1):
        kind = _unit_kind(line.unit)
        if kind is None or line.quantity is None:
            continue
        limit = days if kind == "days" else days * HOURS_PER_DAY
        if line.quantity > limit:
            what = "MD" if kind == "days" else "h"
            cap = (
                f"{days} dni roboczych"
                if kind == "days"
                else f"{limit} h ({days} dni roboczych × {HOURS_PER_DAY} h)"
            )
            out.append(
                f"Pozycja {index}: {_plain(line.quantity)} {what} — więcej niż "
                f"{cap} w miesiącu {_month(*period)}."
            )
    return out


def _fold(name: str) -> str:
    return matching._fold(name).lower()


def person_id_problems(
    lines: Sequence[Line],
    owners: dict[str, tuple[Owner, ...]],
    known: Any = None,
) -> list[str]:
    """``cl.contractor_person_id``: „Contractor <osoba> ID: <kod>” z kodem tej osoby.

    ``known`` (``unknown_refs.known_for_client``) odróżnia nieznany kod osoby
    z kontraktem (NEXUS nie ma jej numeru — faktura może być dobra) od kodu,
    którego nie ma nikt.
    """

    out: list[str] = []
    for index, line in enumerate(lines, start=1):
        people, contacts = refs.contractor_and_contacts(line.name)
        if not people:
            continue
        folded_contacts = {_fold(name) for name in contacts}
        for person in people:
            if _fold(person) in folded_contacts:
                out.append(
                    f"Pozycja {index}: jako „Contractor” wpisano osobę klienta "
                    f"z „Contact” ({person}) — wpisz konsultanta."
                )
        person = people[0]
        found = _ID_FIELD.search(line.name)
        if found is None:
            out.append(f"Pozycja {index}: brak „ID: <kod osoby>” przy {person}.")
            continue
        raw = found.group(1).strip()
        token = raw.split()[0] if raw.split() else ""
        if not PERSON_CODE.fullmatch(token):
            shown = raw[:RAW_MAX] or "puste"
            out.append(
                f"Pozycja {index}: w polu ID jest „{shown}” zamiast kodu osoby "
                "(litera i 5–7 cyfr)."
            )
            continue
        mine = owners.get(token, ())
        if not mine:
            has_contract = line.contract_id is not None or (
                known is not None
                and any(refs.same_person(" ".join(p), person) for p in known.people)
            )
            out.append(
                f"Pozycja {index}: NEXUS nie zna kodu {token} — jeśli to numer "
                f"{person}, dopisz go w numerach osób klienta."
                if has_contract
                else f"Pozycja {index}: kod {token} nie jest w NEXUSIE numerem "
                "żadnej osoby klienta — popraw fakturę albo dopisz numer osobie."
            )
            continue
        if line.contract_id is not None:
            ok = any(owner.contract_id == line.contract_id for owner in mine)
        else:
            ok = any(refs.same_person(owner.person, person) for owner in mine)
        if not ok:
            names = ", ".join(sorted({owner.person for owner in mine}))
            out.append(
                f"Pozycja {index}: kod {token} należy w NEXUSIE do {names}, "
                f"a pozycja dotyczy {person}."
            )
    return out


def without_contract_problems(lines: Sequence[Line], known: Any) -> list[str]:
    """Osoba w pozycji (pole osoby albo „Contractor …”) bez kontraktu u klienta.

    ``known`` — ``unknown_refs.known_for_client``. Pozycja z kontraktem
    (szkic z „Do faktury”) przechodzi.
    """

    out: list[str] = []
    for index, line in enumerate(lines, start=1):
        if line.contract_id is not None:
            continue
        missing = list(refs.people_without_contract(line.name, known))
        consultant = (line.consultant or "").strip()
        if consultant and not any(
            refs.same_person(" ".join(person), consultant) for person in known.people
        ):
            if not any(refs.same_person(consultant, name) for name in missing):
                missing.insert(0, consultant)
        for name in missing:
            out.append(f"Pozycja {index}: {name} nie ma kontraktu u tego klienta.")
    return out


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


async def person_owners(
    db: AsyncSession, client_id: int
) -> dict[str, tuple[Owner, ...]]:
    """Kod osoby → kontrakty z tym kodem (klient ze scalonymi duplikatami)."""

    family = await clients.family(db, [client_id])
    rows = await db.execute(
        select(
            ClientExternalId.value,
            ClientExternalId.contract_id,
            Candidate.name,
            Candidate.lastname,
        )
        .join(Contract, Contract.id == ClientExternalId.contract_id)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(
            ClientExternalId.client_id.in_(family),
            ClientExternalId.kind == refs.PERSON_NO_KIND,
            # Kod odrzucony przez Finanse nie należy do osoby (podpowiedź
            # z faktury, którą ktoś uznał za błędną).
            ClientExternalId.state != "rejected",
        )
    )
    out: dict[str, list[Owner]] = defaultdict(list)
    for value, contract_id, name, lastname in rows.all():
        person = " ".join(part for part in (name, lastname) if part)
        out[str(value).upper()].append(Owner(int(contract_id), person))
    return {code: tuple(found) for code, found in out.items()}


def _decimal(raw: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(raw)) if raw not in (None, "") else None
    except (ArithmeticError, ValueError):
        return None


def issued_lines(raw: Iterable[dict[str, Any]]) -> list[Line]:
    return [
        Line(
            name=str(line.get("name") or ""),
            consultant=line.get("consultant") or None,
            quantity=_decimal(line.get("quantity")),
            unit=line.get("unit"),
            contract_id=int(line["contract_id"]) if line.get("contract_id") else None,
        )
        for line in raw
        if isinstance(line, dict)
    ]


def sales_lines(raw: Iterable[dict[str, Any]]) -> list[Line]:
    return [
        Line(
            name=str(item.get("name") or ""),
            quantity=_decimal(item.get("quantity")),
            unit=item.get("unit"),
        )
        for item in raw
        if isinstance(item, dict) and not item.get("before_correction")
    ]


async def _client_checks(
    db: AsyncSession,
    client_id: int,
    lines: Sequence[Line],
    found: requirements.Requirements,
    cache: dict[int, tuple[Any, dict[str, tuple[Owner, ...]]]],
) -> list[str]:
    if client_id not in cache:
        cache[client_id] = (
            await refs.known_for_client(db, client_id),
            await person_owners(db, client_id),
        )
    known, owners = cache[client_id]
    out: list[str] = []
    if found.contractor_person_id:
        out += person_id_problems(lines, owners, known)
    out += without_contract_problems(lines, known)
    return out


async def issued_checks(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    found: requirements.Requirements,
) -> list[str]:
    """Uwagi przed wysyłką szkicu faktury VAT z NEXUSA (puste = bez uwag)."""

    if invoice.invoice_type != "VAT":
        return []
    lines = issued_lines(invoice.lines or [])
    period = (
        (int(invoice.period_year), int(invoice.period_month))
        if invoice.period_year and invoice.period_month
        else None
    )
    sale = invoice.sale_date or invoice.issue_date
    out = sale_date_problems(sale, period, lines)
    out += quantity_problems(lines, period or (sale.year, sale.month))
    if invoice.client_id is not None:
        out += await _client_checks(db, int(invoice.client_id), lines, found, {})
    return out


async def ksef_report(db: AsyncSession, *, year: int, month: int) -> dict[str, Any]:
    """Faktury VAT z KSeF za miesiąc usługi, wystawione poza NEXUSEM, z uwagami."""

    issued = select(ClientIssuedInvoice.sales_invoice_id).where(
        ClientIssuedInvoice.sales_invoice_id.is_not(None)
    )
    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.period_year == year,
                ClientSalesInvoice.period_month == month,
                ClientSalesInvoice.invoice_kind == "original",
                ClientSalesInvoice.invoice_type == "VAT",
                ClientSalesInvoice.id.not_in(issued),
            )
            .order_by(ClientSalesInvoice.issue_date, ClientSalesInvoice.id)
        )
    )
    period = f"{year:04d}-{month:02d}"
    names = dict(
        (
            await db.execute(
                select(Client.id, Client.name).where(
                    Client.id.in_({i.client_id for i in invoices if i.client_id} or {0})
                )
            )
        ).all()
    )
    rules: dict[int, requirements.Requirements] = {}
    cache: dict[int, tuple[Any, dict[str, tuple[Owner, ...]]]] = {}
    rows: list[dict[str, Any]] = []
    for invoice in invoices:
        lines = sales_lines(invoice.items or [])
        sale = invoice.sale_date or invoice.issue_date
        problems = sale_date_problems(sale, None, lines)
        problems += quantity_problems(lines, (year, month))
        if invoice.client_id is not None:
            client_id = int(invoice.client_id)
            if client_id not in rules:
                rules[client_id] = await requirements.load(db, client_id, period)
            problems += await _client_checks(
                db, client_id, lines, rules[client_id], cache
            )
        if problems:
            rows.append(
                {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "ksef_number": invoice.ksef_number,
                    "client_id": invoice.client_id,
                    "client_name": names.get(invoice.client_id) or invoice.buyer_name,
                    "issue_date": invoice.issue_date.isoformat(),
                    "sale_date": sale.isoformat(),
                    "problems": problems,
                }
            )
    return {"period": period, "checked": len(invoices), "invoices": rows}


__all__ = [
    "Line",
    "Owner",
    "PERSON_CODE",
    "issued_checks",
    "issued_lines",
    "ksef_report",
    "person_id_problems",
    "person_owners",
    "quantity_problems",
    "sale_date_problems",
    "sales_lines",
    "without_contract_problems",
    "working_days",
]
