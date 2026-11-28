"""Faktury sprzedaży wystawiane w NEXUSIE: szkice z „Do faktury”, edycja, wysyłka do KSeF (E4).

* ``to_issue`` — „Wystaw za miesiąc”: wiersze ``billing.billing_rows`` wszystkich
  klientów z tym, co już wystawiono dla zamówienia w tym miesiącu,
* ``create_drafts`` — szkice z zaznaczonych zamówień: domyślnie jedna faktura
  na zamówienie (pozycja na osobę: usługa + konsultant, ilość × cena),
  opcjonalnie faktura na osobę. Pozycja bez kwoty (brak zużycia MD) blokuje
  szkic z komunikatem; zamówienie kosztowe daje pozycję bez ceny do
  uzupełnienia (kwotę ustalają Finanse),
* ``update`` / ``delete`` — edycja szkicu; usunięcie szkicu nie zostawia śladu
  w numeracji (szkic nie ma numeru),
* ``create_correction`` (do faktury przyjętej w KSeF) i ``create_advance``
  (zaliczkowa — minimalnie: pełna wartość zamówienia),
* ``prepare_send`` → commit → ``apply_result``: numer z serii pod blokadą,
  XML FA(3), wysyłka (``ksef_send``), wynik; przyjęta faktura trafia do
  ``client_sales_invoices`` z tym samym numerem KSeF i wiąże się z zamówieniem.

Kwoty w JSON-ie jako tekst dziesiętny z kropką.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today, is_business_day
from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoiceLink,
    ClientSalesInvoicePayment,
)
from app.services import fx_service
from app.services.client_invoicing import (
    billing,
    client_defaults,
    clients,
    fa3_build,
    fa_sales,
    issue_settings,
    ksef_send,
    matching,
    numbering,
    period_checks,
    rebate,
    requirements,
    sale_checks,
)
from app.services.client_invoicing import sync as sales_sync
from app.services.client_invoicing.export import month_label
from app.services.client_invoicing.fa3_build import VAT_RATES, decimal_or_none
from app.services.client_invoice_issue_schema import (
    NOTES_MAX,
    ORDER_NUMBER_MAX,
    REASON_MAX,
)
from app.services.client_sales_invoices_schema import CURRENCIES
from app.services.order_client_identity import nip_checksum_valid
from app.services.hr.calendar import month_range

logger = logging.getLogger(__name__)
_ZONE = ZoneInfo(DEFAULT_TZ)

ZERO = Decimal("0.00")
EDITABLE = frozenset({"draft", "rejected", "failed"})
SENDABLE = EDITABLE
CHECKABLE = frozenset({"sending", "sent"})
#: Wysyłka bez otwartej sesji KSeF starsza niż tyle = przerwana, zanim plik
#: mógł dotrzeć (sesja zapisuje się w bazie zaraz po otwarciu) — da się ją
#: wysłać ponownie albo wycofać.
STALE_UNSENT_AFTER = timedelta(minutes=5)
LINE_NAME_MAX = 512
ORDER_KEY = re.compile(r"[go]\d{1,12}")
MAX_LINES = 200
HISTORY_MAX = 50
STATUS_LABELS = {
    "draft": "Szkic",
    "sending": "Wysyłanie do KSeF",
    "sent": "W KSeF — czeka na wynik",
    "accepted": "Przyjęta w KSeF",
    "rejected": "Odrzucona przez KSeF",
    "failed": "Nie wysłano",
    "cancelled": "Wycofana — numer niewykorzystany",
}
TYPE_LABELS = {"VAT": "Faktura", "KOR": "Korekta", "ZAL": "Zaliczkowa"}
UNIT_FOR_BASIS = {
    "md": "MD",
    "hours": "h",
    "days": "dni",
    "month": "mies.",
    "cost": "usł.",
}


class IssueError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


def _amount(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(fa3_build.money(value), "f")


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _note(
    invoice: ClientIssuedInvoice, event: str, actor_id: Optional[int], **extra: Any
) -> None:
    entry = {"at": _now().isoformat(timespec="seconds"), "event": event, "by": actor_id}
    entry.update({key: value for key, value in extra.items() if value is not None})
    invoice.history = [*(invoice.history or []), entry][-HISTORY_MAX:]


def stale_unsent(invoice: ClientIssuedInvoice, now: Optional[datetime] = None) -> bool:
    """``sending`` bez sesji KSeF dłużej niż kilka minut: wysyłka przerwana
    (padnięcie procesu) przed otwarciem sesji — plik nie dotarł do KSeF."""

    if invoice.status != "sending" or invoice.ksef_session_ref:
        return False
    started = invoice.sent_at
    return started is None or (now or _now()) - started > STALE_UNSENT_AFTER


def editable(invoice: ClientIssuedInvoice) -> bool:
    return invoice.status in EDITABLE or stale_unsent(invoice)


# ── Pozycje i kwoty ─────────────────────────────────────────────────────────


def clean_line(raw: dict[str, Any]) -> dict[str, Any]:
    """Pozycja z formularza albo z „Do faktury” w kształcie zapisu (kwoty tekstem)."""

    quantity = decimal_or_none(raw.get("quantity"))
    price = decimal_or_none(raw.get("unit_price"))
    rate = str(raw.get("vat_rate") or "")
    line = {
        "name": " ".join(str(raw.get("name") or "").split())[:LINE_NAME_MAX],
        "consultant": " ".join(str(raw.get("consultant") or "").split())[:200] or None,
        "quantity": fa3_build.plain(quantity) if quantity is not None else None,
        "unit": " ".join(str(raw.get("unit") or "").split())[:32] or None,
        "unit_price": fa3_build.plain(price) if price is not None else None,
        "vat_rate": rate if rate in VAT_RATES else None,
        "order_id": int(raw["order_id"])
        if str(raw.get("order_id") or "").isdigit()
        else None,
    }
    # Zamówienie pozycji (faktura z kilku zamówień, ``cl.orders_together``) i kontrakt
    # osoby (nabywca per kontrakt) — z „Do faktury”, front odsyła je bez zmian.
    key = str(raw.get("order_key") or "")
    if ORDER_KEY.fullmatch(key):
        line["order_key"] = key
        number = " ".join(str(raw.get("order_number") or "").split())
        if number:
            line["order_number"] = number[:ORDER_NUMBER_MAX]
    if str(raw.get("contract_id") or "").isdigit():
        line["contract_id"] = int(raw["contract_id"])
    discount = fa3_build.line_discount_pct(
        {"discount_pct": decimal_or_none(raw.get("discount_pct"))}
    )
    if discount is not None:
        line["discount_pct"] = fa3_build.plain(money_pct(discount))
    net = fa3_build.line_net(line)
    line["net"] = _amount(net)
    return line


def money_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def line_problems(lines: Sequence[dict[str, Any]]) -> list[str]:
    problems = []
    for index, line in enumerate(lines, start=1):
        if not line.get("name"):
            problems.append(f"Pozycja {index}: brak nazwy usługi.")
        if line.get("quantity") is None or line.get("unit_price") is None:
            problems.append(f"Pozycja {index}: uzupełnij ilość i cenę netto.")
        elif (decimal_or_none(line.get("quantity")) or ZERO) <= 0:
            problems.append(f"Pozycja {index}: ilość musi być większa od zera.")
        if not line.get("vat_rate"):
            problems.append(f"Pozycja {index}: wybierz stawkę VAT.")
    return problems


def _priced(lines: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        line
        for line in lines
        if fa3_build.line_net(line) is not None and line.get("vat_rate")
    ]


def recompute(invoice: ClientIssuedInvoice) -> fa3_build.Totals:
    result = fa3_build.totals(
        _priced(invoice.lines or []), _priced(invoice.lines_before or [])
    )
    invoice.net_amount = result.net
    invoice.vat_amount = result.vat
    invoice.gross_amount = result.gross
    return result


def rate_day(delivery: date) -> date:
    """Ostatni dzień roboczy przed datą dostawy (pon–pt bez świąt ustawowych)."""

    day = delivery - timedelta(days=1)
    while not is_business_day(datetime.combine(day, time(12), tzinfo=_ZONE)):
        day -= timedelta(days=1)
    return day


async def fx_for(
    db: AsyncSession, currency: str, delivery: Optional[date]
) -> tuple[Optional[Decimal], Optional[date]]:
    """Kurs średni NBP z DOKŁADNIE ostatniego dnia roboczego przed datą dostawy.

    Brak tabeli z tego dnia w ``fx_rates`` (dziura w pobieraniu) to brak kursu,
    nie kurs z wcześniejszego dnia — ten byłby niezgodny z art. 31a ustawy o VAT.
    """

    if currency == "PLN" or delivery is None:
        return None, None
    target = rate_day(delivery)
    snapshot = await fx_service.get_rate_snapshot_to_pln(db, currency, on=target)
    if (
        snapshot is None
        or snapshot.source != "NBP"
        or snapshot.effective_date != target
    ):
        return None, None
    return snapshot.rate_to_pln, snapshot.effective_date


async def _refresh_fx(db: AsyncSession, invoice: ClientIssuedInvoice) -> None:
    if invoice.invoice_type == "KOR" and invoice.corrects_id:
        original = await db.get(ClientIssuedInvoice, invoice.corrects_id)
        if original is not None:
            invoice.fx_rate, invoice.fx_date = original.fx_rate, original.fx_date
            return
    delivery = invoice.period_to or invoice.sale_date or invoice.issue_date
    invoice.fx_rate, invoice.fx_date = await fx_for(db, invoice.currency, delivery)


# ── Nabywca ─────────────────────────────────────────────────────────────────


def _buyer_snapshot(
    client: Client, history: Optional[client_defaults.ClientDefaults] = None
) -> dict[str, Any]:
    number = client.nip or ""
    ident = fa3_build.buyer_id(number)
    country = "PL" if ident.kind in ("nip", "none") else (ident.country or "PL")
    address_l1, address_l2 = (client.address or ""), ""
    if not address_l1.strip() and history is not None and history.address_l1:
        # Karta bez adresu: adres z kartoteki eBI24 albo z faktur klienta w KSeF
        # (``client_defaults``), bo bez niego XML FA(3) nie powstaje.
        address_l1, address_l2 = history.address_l1, history.address_l2
    return {
        "name": (client.legal_name or client.name or "")[:255],
        "number": number[:32],
        "address_l1": address_l1[:255],
        "address_l2": address_l2[:255],
        "country": "EL" if country == "GR" else country,
    }


def _buyer_kind(buyer: dict[str, Any]) -> str:
    return fa3_build.buyer_id(buyer.get("number")).kind


def _country(raw: Any, default: str = "PL") -> str:
    return "".join(ch for ch in str(raw or default).upper() if ch.isalpha())[:2]


def clean_buyer(raw: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Nabywca szkicu; ``code`` = nabywca z listy klienta, ``delivery_*`` = adres doręczenia."""

    merged = {**current, **{k: v for k, v in raw.items() if v is not None}}
    out = {
        "name": " ".join(str(merged.get("name") or "").split())[:255],
        "number": "".join(
            ch for ch in str(merged.get("number") or "").upper() if ch.isalnum()
        )[:32],
        "address_l1": " ".join(str(merged.get("address_l1") or "").split())[:255],
        "address_l2": " ".join(str(merged.get("address_l2") or "").split())[:255],
        "country": _country(merged.get("country")) or "PL",
    }
    code = str(merged.get("code") or "")
    if issue_settings.BUYER_CODE.fullmatch(code):
        out["code"] = code
    delivery = " ".join(str(merged.get("delivery_l1") or "").split())[:255]
    if delivery:
        out["delivery_l1"] = delivery
        out["delivery_l2"] = " ".join(str(merged.get("delivery_l2") or "").split())[
            :255
        ]
        out["delivery_country"] = _country(merged.get("delivery_country")) or "PL"
    return out


def configured_buyer(entry: dict[str, Any]) -> dict[str, Any]:
    """Migawka nabywcy z listy klienta w ustawieniach (Nordea: nabywca per kontrakt)."""

    return clean_buyer(dict(entry), {})


# ── „Wystaw za miesiąc” ─────────────────────────────────────────────────────


async def _existing_by_key(
    db: AsyncSession, year: int, month: int
) -> dict[str, list[ClientIssuedInvoice]]:
    rows = await db.scalars(
        select(ClientIssuedInvoice).where(
            ClientIssuedInvoice.period_year == year,
            ClientIssuedInvoice.period_month == month,
            ClientIssuedInvoice.invoice_type == "VAT",
            ClientIssuedInvoice.status != "cancelled",
        )
    )
    out: dict[str, list[ClientIssuedInvoice]] = {}
    for invoice in rows:
        for key in order_keys(invoice):
            out.setdefault(key, []).append(invoice)
    return out


def order_keys(invoice: ClientIssuedInvoice) -> list[str]:
    """Wiersze „Do faktury” faktury: jej zamówienie albo zamówienia pozycji.

    Faktura z kilku zamówień (``cl.orders_together``) nie ma własnego zamówienia —
    każda pozycja niesie ``order_key`` swojego.
    """

    if invoice.order_group_id is not None:
        return [f"g{invoice.order_group_id}"]
    if invoice.order_id is not None:
        return [f"o{invoice.order_id}"]
    keys: list[str] = []
    for line in invoice.lines or []:
        key = line.get("order_key")
        if key and key not in keys:
            keys.append(key)
    return keys


def order_numbers(invoice: ClientIssuedInvoice) -> list[str]:
    """Numery zamówień do KSeF (``NrZamowienia``): z pozycji, gdy faktura ma kilka."""

    if invoice.order_group_id is None and invoice.order_id is None:
        numbers: list[str] = []
        for line in invoice.lines or []:
            number = line.get("order_number")
            if line.get("order_key") and number and number not in numbers:
                numbers.append(number)
        if len(numbers) > 1:
            return numbers
    return [invoice.client_order_number] if invoice.client_order_number else []


async def _ksef_by_key(
    db: AsyncSession, year: int, month: int, rows: Sequence[billing.BillingRow]
) -> dict[str, list[str]]:
    """Numery faktur z KSeF wystawionych poza NEXUSEM (np. w eBI24) i powiązanych
    z zamówieniem za ten miesiąc.

    Bez tego „Wystaw za miesiąc” pokazywało zamówienie zafakturowane w eBI24 jako
    „do wystawienia” — w miesiącu przejściowym prosta droga do drugiej faktury
    (przeklikanie na stagingu 14.11.2026). Faktury wystawione w NEXUSIE liczy
    ``_existing_by_key``.
    """

    by_order: dict[int, str] = {}
    for row in rows:
        if row.order_id is not None:
            by_order[row.order_id] = row.key
        for line in row.lines:
            if line.order_id is not None:
                by_order.setdefault(line.order_id, row.key)
    links = await db.execute(
        select(
            ClientSalesInvoiceLink.order_group_id,
            ClientSalesInvoiceLink.order_id,
            ClientSalesInvoice.invoice_number,
        )
        .join(
            ClientSalesInvoice,
            ClientSalesInvoice.id == ClientSalesInvoiceLink.invoice_id,
        )
        .where(
            ClientSalesInvoiceLink.period_year == year,
            ClientSalesInvoiceLink.period_month == month,
            or_(
                ClientSalesInvoice.match_method.is_(None),
                ClientSalesInvoice.match_method != "issued",
            ),
        )
    )
    out: dict[str, list[str]] = {}
    for group_id, order_id, number in links.all():
        if group_id is not None:
            key = f"g{group_id}"
        elif order_id is not None and order_id in by_order:
            key = by_order[order_id]
        else:
            continue
        if number not in out.setdefault(key, []):
            out[key].append(number)
    return out


def _row_block(row: billing.BillingRow) -> Optional[str]:
    if row.missing:
        people = ", ".join(
            line.consultant
            for line in row.lines
            if line.net is None and line.basis != "cost"
        )
        return f"Brak kwoty pozycji (czeka na zużycie MD albo stawkę): {people}."
    # Osoba z rozliczeniem w NEXUSIE bez przyjętego RCP (albo z godzinami
    # niezatwierdzonymi w T4T): kwota z zamówienia to tylko podgląd, faktura
    # z niej rozjechałaby się z raportem (pomiar 27.11.2026: 93/624 zgodnych).
    waiting = [line for line in row.lines if line.awaiting]
    if waiting:
        people = ", ".join(f"{line.consultant} ({line.awaiting})" for line in waiting)
        return f"Pozycje czekają na rozliczenie: {people}."
    return None


async def to_issue(db: AsyncSession, *, year: int, month: int) -> dict[str, Any]:
    rows = await billing.billing_rows(db, year=year, month=month)
    existing = await _existing_by_key(db, year, month)
    in_ksef = await _ksef_by_key(db, year, month, rows)
    names = await clients.names(db, {row.client_id for row in rows})
    period = billing.month_key(year, month)
    infos = await _orders_info(db, rows)
    reqs: dict[int, requirements.Requirements] = {}
    by_client: dict[int, dict[str, Any]] = {}
    for row in sorted(
        rows, key=lambda r: (names.get(r.client_id) or "", r.order_number)
    ):
        found = await _requirements(db, reqs, row.client_id, period)
        entry = by_client.setdefault(
            row.client_id,
            {
                "client_id": row.client_id,
                "client_name": names.get(row.client_id),
                "orders_together": found.orders_together,
                "rows": [],
            },
        )
        issued = existing.get(row.key, [])
        entry["rows"].append(
            {
                "key": row.key,
                "kind": row.kind,
                "order_number": row.order_number,
                "currency": row.currency,
                "expected_net": _amount(row.expected_net),
                "people": len(row.lines),
                "blocked": _row_block(row)
                or await _signature_block(db, row, found, infos, period)
                or await _bzone_block(db, row, found, infos, period),
                "needs_amount": row.kind == "cost",
                "invoiced_in_ksef": in_ksef.get(row.key, []),
                "issued": [
                    {
                        "id": invoice.id,
                        "status": invoice.status,
                        "status_label": STATUS_LABELS[invoice.status],
                        "invoice_number": invoice.invoice_number,
                    }
                    for invoice in issued
                ],
            }
        )
    return {
        "period": billing.month_key(year, month),
        "clients": list(by_client.values()),
    }


def _line_name(service: str, order_number: str, consultant: str, period: str) -> str:
    return (
        f"{service} — {consultant} — {month_label(period)} (zamówienie {order_number})"
    )


@dataclass(frozen=True)
class OrderInfo:
    """Kontrakt osoby i tytuł pozycji zamówienia (rola) — do nabywcy i opisu pozycji."""

    contract_id: Optional[int]
    role: Optional[str]


async def _orders_info(
    db: AsyncSession, rows: Sequence[billing.BillingRow]
) -> dict[int, OrderInfo]:
    ids = {
        line.order_id for row in rows for line in row.lines if line.order_id is not None
    }
    if not ids:
        return {}
    result = await db.execute(
        select(ClientOrder.id, ClientOrder.contract_id, ClientOrder.title).where(
            ClientOrder.id.in_(ids)
        )
    )
    return {
        order_id: OrderInfo(contract_id, " ".join((title or "").split()) or None)
        for order_id, contract_id, title in result.all()
    }


def _info(infos: dict[int, OrderInfo], line: billing.BillingLine) -> OrderInfo:
    return infos.get(line.order_id or 0) or OrderInfo(None, None)


async def _requirements(
    db: AsyncSession,
    cache: dict[int, requirements.Requirements],
    client_id: int,
    period: str,
) -> requirements.Requirements:
    if client_id not in cache:
        cache[client_id] = await requirements.load(db, client_id, period)
    return cache[client_id]


async def _signature_block(
    db: AsyncSession,
    row: billing.BillingRow,
    found: requirements.Requirements,
    infos: dict[int, OrderInfo],
    period: str,
) -> Optional[str]:
    """Klient z ``cl.after_signed_document``: faktura dopiero po podpisanym dokumencie."""

    if found.signed_document is None:
        return None
    by_contract = {
        _info(infos, line).contract_id: line.consultant
        for line in row.lines
        if _info(infos, line).contract_id is not None
    }
    # Pozycja bez kontraktu (np. pula zamówienia bez podziału na osoby): podpisu
    # nie da się sprawdzić, więc też czeka — inaczej faktura wyszłaby bez protokołu.
    unknown = [
        line.consultant for line in row.lines if _info(infos, line).contract_id is None
    ]
    missing = await requirements.unsigned_people(
        db, found, contract_ids=by_contract, period=period
    )
    if not missing and not unknown:
        return None
    kind = "protokołu" if found.signed_document == "protocol" else "arkusza"
    people = ", ".join(sorted([*(by_contract[cid] for cid in missing), *unknown]))
    return (
        f"Klient wymaga podpisanego obustronnie {kind} przed fakturą — brak podpisu: "
        f"{people}."
    )


async def _bzone_block(
    db: AsyncSession,
    row: billing.BillingRow,
    found: requirements.Requirements,
    infos: dict[int, OrderInfo],
    period: str,
) -> Optional[str]:
    """Klient z ``cl.bzone_order``: każda osoba wiersza ma zlecenie B-ZONE na swoje dni."""

    if not found.bzone_order:
        return None
    people = [(line.consultant, _info(infos, line).contract_id) for line in row.lines]
    return await _bzone_problem(db, row.client_id, people, period)


async def _bzone_problem(
    db: AsyncSession,
    client_id: int,
    people: Sequence[tuple[str, Optional[int]]],
    period: str,
) -> Optional[str]:
    # Pozycja bez kontraktu (pula bez podziału na osoby): zlecenia nie da się
    # sprawdzić, więc też czeka — jak przy podpisanym protokole.
    gaps: dict[str, list[date]] = {
        person or "pozycja bez osoby": [] for person, cid in people if cid is None
    }
    by_contract = {cid: person for person, cid in people if cid is not None}
    missing = await period_checks.bzone_gaps(
        db, client_id=client_id, contract_ids=by_contract, period=period
    )
    for cid, days in missing.items():
        gaps[by_contract[cid] or f"kontrakt {cid}"] = days
    return period_checks.bzone_message(gaps)


def _lines_for(
    row: billing.BillingRow,
    lines: Sequence[billing.BillingLine],
    *,
    service: str,
    period: str,
    vat_rate: str,
    found: requirements.Requirements = requirements.Requirements(),
    infos: Optional[dict[int, OrderInfo]] = None,
) -> list[dict[str, Any]]:
    out = []
    for line in lines:
        cost = line.basis == "cost"
        info = _info(infos or {}, line)
        name = found.item_name(
            service=service,
            order_number=row.order_number,
            person=line.consultant,
            role=info.role,
            period=period,
        ) or _line_name(service, row.order_number, line.consultant, period)
        if line.suffix:
            name = f"{name} — {line.suffix}"
        out.append(
            clean_line(
                {
                    "name": name,
                    "consultant": line.consultant,
                    "quantity": "1" if cost else line.quantity,
                    "unit": UNIT_FOR_BASIS.get(line.basis, line.unit),
                    "unit_price": None if cost else line.unit_price,
                    "vat_rate": vat_rate,
                    "order_id": line.order_id,
                    "order_key": row.key,
                    "order_number": row.order_number,
                    "contract_id": info.contract_id,
                }
            )
        )
    return out


@dataclass(frozen=True)
class DraftDefaults:
    issue_date: date
    due_date: date
    vat_rate: str
    series: str
    buyer: dict[str, Any]


def _defaults(
    client: Client,
    settings: dict[str, Any],
    today: date,
    buyer: Optional[dict[str, Any]] = None,
    history: Optional[client_defaults.ClientDefaults] = None,
) -> DraftDefaults:
    snapshot = configured_buyer(buyer) if buyer else _buyer_snapshot(client, history)
    eu = _buyer_kind(snapshot) == "eu"
    days = issue_settings.client_payment_days_override(settings, client.id)
    if days is None and not buyer and history is not None:
        # Termin z faktur klienta w KSeF tylko dla nabywcy z karty klienta:
        # nabywca z listy (Nordea per kontrakt, Bosch DE) ma własne warunki.
        days = history.payment_days
    if days is None:
        days = settings["payment_days"]
    return DraftDefaults(
        issue_date=today,
        due_date=today + timedelta(days=days),
        vat_rate=issue_settings.client_vat(settings, client.id, eu_buyer=eu),
        series="UE" if eu else "PL",
        buyer=snapshot,
    )


@dataclass
class _Unit:
    """Jedna przyszła faktura: części wierszy „Do faktury” z tym samym nabywcą."""

    client_id: int
    currency: str
    buyer: Optional[dict[str, Any]]
    parts: list[tuple[billing.BillingRow, list[billing.BillingLine]]]

    @property
    def rows(self) -> list[billing.BillingRow]:
        out: list[billing.BillingRow] = []
        for row, _ in self.parts:
            if row not in out:
                out.append(row)
        return out


def _units(
    wanted: Sequence[str],
    rows: dict[str, billing.BillingRow],
    *,
    split: str,
    settings: dict[str, Any],
    reqs: dict[int, requirements.Requirements],
    infos: dict[int, OrderInfo],
    period: str,
) -> list[_Unit]:
    """Podział zaznaczonych wierszy na faktury.

    Domyślnie faktura na zamówienie (albo na osobę). Nabywca per kontrakt
    (lista nabywców klienta w ustawieniach) dzieli zamówienie na faktury
    nabywców; ``cl.orders_together`` łączy zamówienia klienta w tej samej
    walucie i z tym samym nabywcą w jedną fakturę.
    """

    units: list[_Unit] = []
    together: dict[tuple[int, str, Optional[str]], _Unit] = {}
    for key in wanted:
        row = rows[key]
        currency = row.currency if row.currency in CURRENCIES else "PLN"
        groups = (
            [[line] for line in row.lines] if split == "person" else [list(row.lines)]
        )
        for lines in groups:
            by_buyer: dict[Optional[str], list[billing.BillingLine]] = {}
            buyers: dict[Optional[str], Optional[dict[str, Any]]] = {}
            for line in lines:
                buyer = issue_settings.buyer_for_contract(
                    settings, row.client_id, _info(infos, line).contract_id, period
                )
                code = buyer["code"] if buyer else None
                by_buyer.setdefault(code, []).append(line)
                buyers[code] = buyer
            for code, part in by_buyer.items():
                merge = split != "person" and reqs[row.client_id].orders_together
                slot = (row.client_id, currency, code)
                if merge and slot in together:
                    together[slot].parts.append((row, part))
                    continue
                unit = _Unit(row.client_id, currency, buyers[code], [(row, part)])
                units.append(unit)
                if merge:
                    together[slot] = unit
    return units


async def create_drafts(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    keys: Sequence[str],
    split: str,
    actor_id: int,
    today: date,
) -> list[ClientIssuedInvoice]:
    """Szkice z zaznaczonych wierszy „Do faktury” (bez commita)."""

    wanted = list(dict.fromkeys(keys))
    if not wanted:
        raise IssueError("Zaznacz co najmniej jedno zamówienie.", 422)
    rows = {
        row.key: row for row in await billing.billing_rows(db, year=year, month=month)
    }
    period = billing.month_key(year, month)
    # Dwa równoległe „Wystaw za miesiąc” czytały istniejące faktury, zanim
    # pierwsze wstawiło szkic, i za to samo zamówienie powstawały dwie FV VAT
    # (audyt 24.11.2026). Indeks unikalny odpada (``split='person'`` daje kilka
    # faktur na zamówienie), więc blokada na zamówienia miesiąca do commita;
    # kolejność posortowana, żeby dwa wybory z częścią wspólną się nie zakleszczyły.
    for key in sorted(wanted):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"client-invoice-draft:{period}:{key}"},
        )
    existing = await _existing_by_key(db, year, month)
    in_ksef = await _ksef_by_key(db, year, month, list(rows.values()))
    infos = await _orders_info(db, [rows[key] for key in wanted if key in rows])
    reqs: dict[int, requirements.Requirements] = {}
    problems = []
    for key in wanted:
        row = rows.get(key)
        if row is None:
            problems.append(
                f"Zamówienie {key} nie ma pozycji do faktury w tym miesiącu."
            )
            continue
        found = await _requirements(db, reqs, row.client_id, period)
        block = (
            _row_block(row)
            or await _signature_block(db, row, found, infos, period)
            or await _bzone_block(db, row, found, infos, period)
        )
        if block:
            problems.append(f"{row.order_number}: {block}")
        if existing.get(key):
            problems.append(
                f"{row.order_number}: ma już fakturę za ten miesiąc "
                f"({STATUS_LABELS[existing[key][0].status].lower()})."
            )
        elif in_ksef.get(key):
            problems.append(
                f"{row.order_number}: ma już fakturę w KSeF za ten miesiąc "
                f"({', '.join(in_ksef[key])}) — popraw ją korektą albo odepnij "
                "w „Do faktury”."
            )
    if problems:
        raise IssueError(" ".join(problems))

    settings = await issue_settings.load(db)
    first, last = month_range(year, month)
    created: list[ClientIssuedInvoice] = []
    rebate_cache: dict[tuple[int, int], Optional[rebate.YearRebate]] = {}
    histories: dict[int, client_defaults.ClientDefaults] = {}
    for unit in _units(
        wanted,
        rows,
        split=split,
        settings=settings,
        reqs=reqs,
        infos=infos,
        period=period,
    ):
        client = await db.get(Client, unit.client_id)
        if client is None:
            raise IssueError("Nie ma klienta zamówienia.", 404)
        if client.id not in histories:
            histories[client.id] = await client_defaults.for_client(
                db, client, today=today
            )
        defaults = _defaults(client, settings, today, unit.buyer, histories[client.id])
        unit_rows = unit.rows
        single = unit_rows[0] if len(unit_rows) == 1 else None
        if single is not None:
            group_id = single.group_id
            order_id = (
                single.order_id
                if single.group_id is None
                else (unit.parts[0][1][0].order_id if split == "person" else None)
            )
            order_number = single.order_number
        else:
            # Faktura z kilku zamówień: zamówienia niesie każda pozycja (``order_key``).
            group_id = order_id = None
            order_number = ", ".join(row.order_number for row in unit_rows)
        lines: list[dict[str, Any]] = []
        for row, part in unit.parts:
            lines.extend(
                _lines_for(
                    row,
                    part,
                    service=settings["service_name"],
                    period=period,
                    vat_rate=defaults.vat_rate,
                    found=reqs[unit.client_id],
                    infos=infos,
                )
            )
        invoice = ClientIssuedInvoice(
            client_id=unit.client_id,
            invoice_type="VAT",
            series_code=defaults.series,
            status="draft",
            order_group_id=group_id,
            order_id=order_id,
            period_year=year,
            period_month=month,
            currency=unit.currency,
            issue_date=defaults.issue_date,
            sale_date=last,
            period_from=first,
            period_to=last,
            due_date=defaults.due_date,
            client_order_number=order_number[:ORDER_NUMBER_MAX],
            buyer=defaults.buyer,
            lines=lines,
            lines_before=[],
            history=[],
            created_by=actor_id,
        )
        await apply_rebate(db, invoice, settings, cache=rebate_cache)
        recompute(invoice)
        await _refresh_fx(db, invoice)
        _note(
            invoice,
            "created",
            actor_id,
            source=",".join(row.key for row in unit_rows),
        )
        db.add(invoice)
        created.append(invoice)
    await db.flush()
    return created


# ── Edycja, usunięcie ───────────────────────────────────────────────────────


def _date(raw: Any, label: str) -> Optional[date]:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise IssueError(f"{label}: zła data.", 422) from None


async def update(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    payload: dict[str, Any],
    *,
    actor_id: int,
) -> ClientIssuedInvoice:
    """Edycja szkicu albo faktury odrzuconej/niewysłanej (bez commita)."""

    if not editable(invoice):
        raise IssueError(
            "Faktura jest w KSeF albo w drodze do niego — można ją tylko sprawdzić "
            "albo skorygować."
        )
    if "issue_date" in payload:
        issue_date = _date(payload["issue_date"], "Data wystawienia")
        if issue_date is None:
            raise IssueError("Podaj datę wystawienia.", 422)
        if invoice.number_seq is not None and (
            (issue_date.year, issue_date.month)
            != (invoice.number_year, invoice.number_month)
        ):
            raise IssueError(
                "Faktura ma już numer z tego miesiąca — data wystawienia musi zostać "
                "w tym samym miesiącu. Inny miesiąc = wycofaj fakturę i wystaw nową.",
                422,
            )
        invoice.issue_date = issue_date
    for name, label in (
        ("sale_date", "Data dostawy"),
        ("period_from", "Okres od"),
        ("period_to", "Okres do"),
        ("due_date", "Termin płatności"),
    ):
        if name in payload:
            setattr(invoice, name, _date(payload[name], label))
    if (invoice.period_from is None) != (invoice.period_to is None):
        raise IssueError("Okres usługi wymaga obu dat albo żadnej.", 422)
    if (
        invoice.period_from
        and invoice.period_to
        and invoice.period_from > invoice.period_to
    ):
        raise IssueError("Okres usługi: data „od” jest po dacie „do”.", 422)
    if "client_order_number" in payload:
        value = " ".join(str(payload["client_order_number"] or "").split())
        invoice.client_order_number = value[:ORDER_NUMBER_MAX] or None
    if "notes" in payload:
        value = str(payload["notes"] or "").strip()
        invoice.notes = value[:NOTES_MAX] or None
    if "correction_reason" in payload and invoice.invoice_type == "KOR":
        value = " ".join(str(payload["correction_reason"] or "").split())
        invoice.correction_reason = value[:REASON_MAX] or None
    if "currency" in payload:
        currency = str(payload["currency"] or "").upper()
        if currency not in CURRENCIES:
            raise IssueError("Waluta spoza PLN, EUR i USD.", 422)
        if invoice.invoice_type == "KOR" and currency != invoice.currency:
            raise IssueError("Korekta ma walutę faktury korygowanej.", 422)
        invoice.currency = currency
    if "series_code" in payload and invoice.invoice_type == "VAT":
        code = str(payload["series_code"] or "")
        if code not in ("PL", "UE", "BEN"):
            raise IssueError(
                "Faktura VAT idzie serią krajową, UE albo refaktur benefitów.", 422
            )
        if invoice.number_seq is not None and code != invoice.series_code:
            raise IssueError("Faktura ma już numer z tej serii.", 422)
        invoice.series_code = code
    if isinstance(payload.get("buyer"), dict):
        invoice.buyer = clean_buyer(payload["buyer"], invoice.buyer or {})
    if payload.get("buyer_code"):
        await _choose_buyer(db, invoice, str(payload["buyer_code"]), actor_id=actor_id)
    if "lines" in payload:
        lines = payload["lines"]
        if not isinstance(lines, list) or len(lines) > MAX_LINES:
            raise IssueError("Pozycje: lista do 200 wierszy.", 422)
        cleaned = [clean_line(line) for line in lines if isinstance(line, dict)]
        if invoice.collective_correction is not None and not all(
            rebate.is_rebate_line(line) for line in cleaned
        ):
            # Po nazwie obrót rozpoznaje opust: inna nazwa = przyjęta korekta
            # zaniżyłaby obrót do progu (``rebate.service_base``).
            raise IssueError(
                "Pozycja korekty rabatu musi zaczynać się od "
                f"„{rebate.REBATE_LINE_PREFIX}”.",
                422,
            )
        invoice.lines = cleaned
    recompute(invoice)
    await _refresh_fx(db, invoice)
    _note(invoice, "edited", actor_id)
    await db.flush()
    return invoice


async def _choose_buyer(
    db: AsyncSession, invoice: ClientIssuedInvoice, code: str, *, actor_id: int
) -> None:
    """Nabywca z listy klienta; zapamiętany dla kontraktów pozycji (następne szkice).

    Seria i stawka VAT idą za nabywcą (VAT UE = seria UE i odwrotne obciążenie),
    jak przy tworzeniu szkicu. Faktura z numerem zostaje w swojej serii.
    """

    if invoice.invoice_type != "VAT":
        raise IssueError(
            "Nabywcę z listy wybiera się w fakturze VAT; korekta ma nabywcę "
            "faktury korygowanej.",
            422,
        )
    # Blokada wiersza: zapis niżej podmienia całe ustawienia, a między odczytem
    # a zapisem mail CPro mógł dopisać nabywcę innego kontraktu (przegląd 24.11.2026).
    settings = await issue_settings.load(db, lock=True)
    buyer = next(
        (
            item
            for item in issue_settings.client_buyers(settings, invoice.client_id)
            if item["code"] == code
        ),
        None,
    )
    if buyer is None:
        raise IssueError("Nie ma takiego nabywcy na liście klienta.", 422)
    invoice.buyer = configured_buyer(buyer)
    if invoice.invoice_type == "VAT" and invoice.number_seq is None:
        eu = _buyer_kind(invoice.buyer) == "eu"
        invoice.series_code = "UE" if eu else "PL"
        if invoice.client_id is not None:
            rate = issue_settings.client_vat(settings, invoice.client_id, eu_buyer=eu)
            invoice.lines = [
                clean_line({**line, "vat_rate": rate}) for line in invoice.lines or []
            ]
    contracts = {
        int(line["contract_id"])
        for line in invoice.lines or []
        if str(line.get("contract_id") or "").isdigit()
    }
    if (
        invoice.client_id is not None
        and contracts
        and issue_settings.remember_buyer(
            settings, invoice.client_id, contracts, code, invoice_period(invoice)
        )
    ):
        await issue_settings.save(db, settings, actor_id=actor_id)
    _note(invoice, "buyer", actor_id, buyer=code)


async def delete(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, actor_id: int
) -> str:
    """Szkic znika bez śladu; faktura z numerem spoza obrotu — patrz ``numbering.release``.

    Zwraca ``deleted`` albo ``cancelled``.
    """

    if not editable(invoice):
        raise IssueError(
            "Faktura jest w KSeF albo w drodze do niego — nie da się jej usunąć."
        )
    if await db.scalar(
        select(ClientIssuedInvoice.id).where(
            ClientIssuedInvoice.corrects_id == invoice.id
        )
    ):
        raise IssueError("Faktura ma korektę — usuń najpierw korektę.")
    if invoice.number_seq is None or await numbering.release(db, invoice):
        await db.delete(invoice)
        await db.flush()
        return "deleted"
    invoice.status = "cancelled"
    invoice.ksef_status_text = (
        f"Numer {invoice.invoice_number} niewykorzystany: faktura nie weszła do obrotu "
        "(odrzucona przez KSeF albo niewysłana) i została wycofana."
    )[:500]
    _note(invoice, "cancelled", actor_id)
    await db.flush()
    return "cancelled"


# ── Korekta, zaliczkowa ─────────────────────────────────────────────────────


async def create_correction(
    db: AsyncSession,
    original: ClientIssuedInvoice,
    *,
    reason: str,
    actor_id: int,
    today: date,
) -> ClientIssuedInvoice:
    if original.status != "accepted" or original.invoice_type == "KOR":
        raise IssueError("Korektę wystawia się do faktury przyjętej w KSeF.")
    if original.invoice_type == "ZAL":
        raise IssueError(
            "Korekty faktury zaliczkowej (KOR_ZAL) NEXUS jeszcze nie wystawia."
        )
    corrections = list(
        await db.scalars(
            select(ClientIssuedInvoice)
            .where(
                ClientIssuedInvoice.corrects_id == original.id,
                ClientIssuedInvoice.status != "cancelled",
            )
            .order_by(ClientIssuedInvoice.accepted_at, ClientIssuedInvoice.id)
        )
    )
    if any(item.status != "accepted" for item in corrections):
        raise IssueError(
            "Ta faktura ma już korektę w toku — wyślij albo wycofaj ją najpierw."
        )
    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise IssueError("Podaj przyczynę korekty (co najmniej 3 znaki).", 422)
    settings = await issue_settings.load(db)
    # Stan przed = stan po ostatniej przyjętej korekcie (inaczej druga korekta
    # liczyłaby różnicę od faktury pierwotnej).
    latest = corrections[-1] if corrections else original
    lines = [clean_line(line) for line in latest.lines or []]
    invoice = ClientIssuedInvoice(
        client_id=original.client_id,
        invoice_type="KOR",
        # Korekta faktury UE ma własną serię (jak w eBI24: „1/10/2026/KORUE”).
        series_code="KORUE" if original.series_code == "UE" else "KOR",
        status="draft",
        order_group_id=original.order_group_id,
        order_id=original.order_id,
        period_year=original.period_year,
        period_month=original.period_month,
        corrects_id=original.id,
        correction_reason=note[:REASON_MAX],
        currency=original.currency,
        issue_date=today,
        sale_date=original.sale_date,
        period_from=original.period_from,
        period_to=original.period_to,
        due_date=today
        + timedelta(
            days=issue_settings.client_payment_days(settings, original.client_id)
        ),
        client_order_number=original.client_order_number,
        buyer=dict(original.buyer or {}),
        lines=lines,
        lines_before=[dict(line) for line in lines],
        fx_rate=original.fx_rate,
        fx_date=original.fx_date,
        history=[],
        created_by=actor_id,
    )
    recompute(invoice)
    _note(invoice, "created", actor_id, corrects=original.invoice_number)
    db.add(invoice)
    await db.flush()
    return invoice


async def create_advance(
    db: AsyncSession,
    *,
    client_id: int,
    currency: str,
    received_on: date,
    actor_id: int,
    today: date,
) -> ClientIssuedInvoice:
    client = await db.get(Client, client_id)
    if client is None or client.deleted_at is not None:
        raise IssueError("Nie ma takiego klienta.", 404)
    if currency not in CURRENCIES:
        raise IssueError("Waluta spoza PLN, EUR i USD.", 422)
    settings = await issue_settings.load(db)
    defaults = _defaults(
        client,
        settings,
        today,
        history=await client_defaults.for_client(db, client, today=today),
    )
    invoice = ClientIssuedInvoice(
        client_id=client_id,
        invoice_type="ZAL",
        series_code="ZAL",
        status="draft",
        currency=currency,
        issue_date=today,
        sale_date=received_on,
        due_date=None,
        buyer=defaults.buyer,
        lines=[
            clean_line(
                {
                    "name": settings["service_name"],
                    "quantity": "1",
                    "unit": "usł.",
                    "vat_rate": defaults.vat_rate,
                }
            )
        ],
        lines_before=[],
        history=[],
        created_by=actor_id,
    )
    recompute(invoice)
    await _refresh_fx(db, invoice)
    _note(invoice, "created", actor_id)
    db.add(invoice)
    await db.flush()
    return invoice


# ── Wysyłka ─────────────────────────────────────────────────────────────────


async def problems(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    settings: dict[str, Any],
    config: Optional[ksef_send.IssueConfig] = None,
) -> list[str]:
    """Co blokuje wysyłkę (puste = gotowa)."""

    out: list[str] = []
    missing = issue_settings.seller_missing(settings)
    if missing:
        out.append("Ustawienia wystawiania: brak " + ", ".join(missing) + ".")
    if (
        config is not None
        and config.context_nip
        and settings["seller"]["nip"]
        and (settings["seller"]["nip"] != config.context_nip)
    ):
        out.append("NIP sprzedawcy w ustawieniach różni się od NIP-u spółki w KSeF.")
    buyer = invoice.buyer or {}
    if not buyer.get("name") or not buyer.get("address_l1"):
        out.append("Uzupełnij nazwę i adres nabywcy.")
    ident = fa3_build.buyer_id(buyer.get("number"))
    if ident.kind == "nip" and not nip_checksum_valid(ident.nip or ""):
        # KSeF tego nie sprawdza: na testowym MF (28.11.2026) przyjął fakturę
        # z NIP-em z błędną cyfrą kontrolną, a na produkcji to korekta faktury.
        out.append(
            f"NIP nabywcy {ident.nip} ma błędną cyfrę kontrolną — popraw go "
            "w nabywcy faktury albo na karcie klienta."
        )
    today = business_today()
    if invoice.issue_date is not None and invoice.issue_date > today:
        # KSeF odrzuca taką fakturę kodem 450 dopiero po nadaniu numeru.
        out.append(
            f"Data wystawienia {invoice.issue_date.strftime('%d.%m.%Y')} jest "
            f"w przyszłości — wysłać można najwcześniej tego dnia "
            f"(dziś {today.strftime('%d.%m.%Y')})."
        )
    if not invoice.lines:
        out.append("Faktura nie ma pozycji.")
    out.extend(line_problems(invoice.lines or []))
    if invoice.invoice_type == "KOR":
        if not invoice.correction_reason:
            out.append("Podaj przyczynę korekty.")
        if invoice.lines == invoice.lines_before:
            out.append("Korekta nie zmienia żadnej pozycji.")
        if invoice.collective_correction is not None and not (
            invoice.collective_correction.get("invoices")
        ):
            out.append("Korekta zbiorcza nie wskazuje żadnej faktury korygowanej.")
    if invoice.currency != "PLN" and invoice.fx_rate is None:
        delivery = invoice.period_to or invoice.sale_date or invoice.issue_date
        out.append(
            f"Brak kursu NBP {invoice.currency} z dnia "
            f"{rate_day(delivery).strftime('%d.%m.%Y')} (ostatni dzień roboczy przed "
            "datą dostawy) — NEXUS nie ma tej tabeli kursów; kurs z innego dnia "
            "byłby niezgodny z art. 31a ustawy o VAT."
        )
    codes = {line.get("vat_rate") for line in invoice.lines or []}
    if "zw" in codes and not settings["exemption_basis"]:
        out.append("Pozycja „zw.” wymaga podstawy zwolnienia w ustawieniach.")
    if (
        invoice.series_code not in issue_settings.COMPENSATION_SERIES
        and issue_settings.account_for(
            settings, invoice.client_id, invoice.currency, invoice.series_code
        )
        is None
    ):
        out.append(f"Brak rachunku {invoice.currency} w ustawieniach wystawiania.")
    found = await invoice_requirements(db, invoice)
    blocking, _ = requirements.line_problems(found, invoice.lines or [])
    out.extend(blocking)
    if found.bzone_order and invoice.invoice_type == "VAT" and invoice.client_id:
        bzone = await _bzone_problem(
            db,
            invoice.client_id,
            [(person, cid) for person, cid, _ in await _line_people(db, invoice)],
            invoice_period(invoice),
        )
        if bzone:
            out.append(bzone)
    numbers = order_numbers(invoice)
    if len(numbers) > fa3_build.MAX_TERMS:
        out.append(
            f"Faktura ma {len(numbers)} numerów zamówień, KSeF przyjmuje najwyżej "
            f"{fa3_build.MAX_TERMS} — podziel ją."
        )
    if buyer_choice_needed(invoice, settings):
        out.append(
            "Klient ma kilku nabywców (nabywca zależy od kontraktu): wybierz nabywcę "
            "z listy — NEXUS zapamięta go dla kontraktów tej faktury."
        )
    return out


async def _line_people(
    db: AsyncSession, invoice: ClientIssuedInvoice
) -> list[tuple[str, Optional[int], Optional[int]]]:
    """(osoba, kontrakt, zamówienie) pozycji osób faktury.

    Kontrakt z pozycji („Do faktury” zapisuje ``contract_id``), a bez niego z jej
    zamówienia. Pozycja bez osoby, kontraktu i zamówienia (np. koszty dodatkowe)
    nie jest pozycją osoby i się nie liczy."""

    lines = [
        line
        for line in invoice.lines or []
        if line.get("contract_id") or line.get("order_id") or line.get("consultant")
    ]
    order_ids = {
        int(line["order_id"])
        for line in lines
        if line.get("order_id") and not line.get("contract_id")
    }
    contracts: dict[int, Optional[int]] = {}
    if order_ids:
        contracts = dict(
            (
                await db.execute(
                    select(ClientOrder.id, ClientOrder.contract_id).where(
                        ClientOrder.id.in_(order_ids)
                    )
                )
            ).all()
        )
    out = []
    for line in lines:
        order_id = int(line["order_id"]) if line.get("order_id") else None
        contract_id = line.get("contract_id") or contracts.get(order_id or 0)
        out.append(
            (
                str(line.get("consultant") or line.get("name") or ""),
                int(contract_id) if contract_id else None,
                order_id,
            )
        )
    return out


async def protocol_warnings(
    db: AsyncSession, invoice: ClientIssuedInvoice, found: requirements.Requirements
) -> list[str]:
    """``cl.client_protocol``: osoby faktury bez protokołu odbioru od klienta."""

    if not found.client_protocol or invoice.invoice_type != "VAT":
        return []
    if invoice.client_id is None:
        return []
    people = await _line_people(db, invoice)
    executive = await period_checks.executive_numbers(
        db, [order_id for _, _, order_id in people if order_id]
    )
    numbers = {
        line.get("order_id"): line.get("order_number")
        for line in invoice.lines or []
        if line.get("order_id")
    }
    needs = [
        period_checks.ProtocolNeed(
            contract_id=cid,
            person=person,
            contract_number=executive.get(order_id or 0) or numbers.get(order_id),
        )
        for person, cid, order_id in people
        if cid is not None
    ]
    missing = await period_checks.without_protocol(
        db, client_id=invoice.client_id, needs=needs, period=invoice_period(invoice)
    )
    missing += [person for person, cid, _ in people if cid is None]
    message = period_checks.protocol_message(missing)
    return [message] if message else []


async def invoice_requirements(
    db: AsyncSession, invoice: ClientIssuedInvoice
) -> requirements.Requirements:
    """Wymagania klienta na miesiąc usługi faktury (reguły ``cl.*``)."""

    if invoice.client_id is None:
        return requirements.Requirements()
    return await requirements.load(db, invoice.client_id, invoice_period(invoice))


def invoice_period(invoice: ClientIssuedInvoice) -> str:
    """Miesiąc usługi faktury (``RRRR-MM``); bez okresu — z daty sprzedaży/wystawienia."""

    if invoice.period_year and invoice.period_month:
        return billing.month_key(int(invoice.period_year), int(invoice.period_month))
    day = invoice.sale_date or invoice.issue_date
    return billing.month_key(day.year, day.month)


def buyer_choice_needed(invoice: ClientIssuedInvoice, settings: dict[str, Any]) -> bool:
    """Faktura z zamówienia klienta z listą nabywców, bez nabywcy z tej listy."""

    if invoice.invoice_type != "VAT":
        # Korekta ma nabywcę faktury korygowanej — wybór z listy zmieniłby podmiot.
        return False
    buyers = issue_settings.client_buyers(settings, invoice.client_id)
    if not buyers or not order_keys(invoice):
        return False
    code = (invoice.buyer or {}).get("code")
    return code not in {buyer["code"] for buyer in buyers}


async def document(
    db: AsyncSession, invoice: ClientIssuedInvoice, settings: dict[str, Any]
) -> fa3_build.InvoiceDocument:
    seller = settings["seller"]
    account = (
        issue_settings.account_for(
            settings, invoice.client_id, invoice.currency, invoice.series_code
        )
        or {}
    )
    compensation = invoice.series_code in issue_settings.COMPENSATION_SERIES
    corrected = None
    if invoice.invoice_type == "KOR" and invoice.corrects_id:
        original = await db.get(ClientIssuedInvoice, invoice.corrects_id)
        if original is None or not original.invoice_number:
            raise IssueError("Nie ma faktury korygowanej.", 404)
        corrected = fa3_build.CorrectedInvoice(
            number=original.invoice_number,
            issue_date=original.issue_date,
            ksef_number=original.ksef_number,
            reason=invoice.correction_reason,
        )
    collective = (
        invoice.collective_correction if invoice.invoice_type == "KOR" else None
    )
    buyer = invoice.buyer or {}
    found = await invoice_requirements(db, invoice)
    numbers = order_numbers(invoice)
    return fa3_build.InvoiceDocument(
        invoice_type=invoice.invoice_type,
        number=invoice.invoice_number or "SZKIC",
        issue_date=invoice.issue_date,
        currency=invoice.currency,
        seller_nip=seller["nip"],
        seller=fa3_build.Party(
            name=seller["name"],
            address_l1=seller["address_l1"],
            address_l2=seller["address_l2"] or None,
        ),
        buyer=fa3_build.Party(
            name=buyer.get("name") or "",
            address_l1=buyer.get("address_l1") or "",
            address_l2=buyer.get("address_l2") or None,
            country=buyer.get("country") or "PL",
        ),
        buyer_ident=fa3_build.buyer_id(buyer.get("number")),
        buyer_delivery=fa3_build.Party(
            name="",
            address_l1=buyer["delivery_l1"],
            address_l2=buyer.get("delivery_l2") or None,
            country=buyer.get("delivery_country") or "PL",
        )
        if buyer.get("delivery_l1")
        else None,
        lines=list(invoice.lines or []),
        lines_before=list(invoice.lines_before or []),
        sale_date=invoice.sale_date,
        period_from=invoice.period_from,
        period_to=invoice.period_to,
        issue_place=seller["issue_place"] or None,
        fx_rate=invoice.fx_rate,
        due_date=invoice.due_date,
        account=fa3_build.BankAccount(
            number=account.get("number") or "",
            bank=account.get("bank") or None,
            swift=account.get("swift") or None,
        )
        if account.get("number")
        else None,
        payment_other=issue_settings.COMPENSATION_LABEL if compensation else None,
        client_order_number=invoice.client_order_number,
        order_numbers=tuple(numbers),
        contract_number=found.contract_number,
        contract_date=found.contract_date,
        notes=invoice.notes,
        extra_fields=requirements.ksef_fields(found, numbers),
        exemption_basis=settings["exemption_basis"] or None,
        corrected=corrected,
        corrected_list=collective_refs(collective),
        correction_reason=invoice.correction_reason if collective else None,
        correction_type=(collective or {}).get("correction_type") or None,
        corrected_period=(collective or {}).get("period") or None,
        created_at=_now(),
    )


def collective_refs(
    collective: Optional[dict[str, Any]],
) -> tuple[fa3_build.CorrectedInvoice, ...]:
    """Faktury korygowane korekty zbiorczej (``collective_correction.invoices``)."""

    return tuple(
        fa3_build.CorrectedInvoice(
            number=str(item["number"]),
            issue_date=date.fromisoformat(str(item["issue_date"])[:10]),
            ksef_number=item.get("ksef_number") or None,
            reason=None,
        )
        for item in (collective or {}).get("invoices") or ()
    )


#: Najkrótszy powód wysyłki mimo uwag kontroli formalnej.
CHECKS_REASON_MIN = 5


async def prepare_send(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    *,
    config: ksef_send.IssueConfig,
    actor_id: int,
    checks_reason: Optional[str] = None,
) -> bytes:
    """Numer z serii (blokada wiersza serii) + XML FA(3); stan ``sending`` (bez commita).

    Commit po tej funkcji, przed rozmową z KSeF: numer i XML są zapisane, nawet
    gdy proces padnie w trakcie wysyłki („Sprawdź status” dokończy sprawę).
    """

    if not config.enabled:
        raise IssueError(
            ksef_send.DISABLED_REASONS.get(
                config.disabled_reason or "", "Wysyłka wyłączona."
            )
        )
    if not editable(invoice):
        raise IssueError("Ta faktura jest już w KSeF albo w drodze do niego.")
    settings = await issue_settings.load(db)
    await _refresh_fx(db, invoice)
    recompute(invoice)
    blocking = await problems(db, invoice, settings, config)
    if blocking:
        raise IssueError(" ".join(blocking), 422)
    # Kontrola formalna (data sprzedaży, kod osoby, MD, osoba bez kontraktu):
    # ostrzega, więc faktura idzie dalej tylko z powodem, który zostaje w historii.
    checks = await sale_checks.issued_checks(
        db, invoice, await invoice_requirements(db, invoice)
    )
    reason = " ".join((checks_reason or "").split())[:REASON_MAX]
    if checks and len(reason) < CHECKS_REASON_MIN:
        raise IssueError(
            "Kontrola przed wysyłką ma uwagi: "
            + " ".join(checks)
            + " Popraw szkic albo wyślij mimo uwag z powodem."
        )
    if checks:
        _note(invoice, "checks_overridden", actor_id, reason=reason, checks=checks)
    # Stan przed numerem: CHECK bazy nie zna szkicu z numerem.
    invoice.status = "sending"
    await numbering.assign(db, invoice, pattern=settings["series"][invoice.series_code])
    try:
        xml = fa3_build.build_xml(await document(db, invoice, settings))
    except fa3_build.InvoiceBuildError as exc:
        raise IssueError(str(exc), 422) from exc
    invoice.xml = xml.decode("utf-8")
    invoice.xml_sha256 = hashlib.sha256(xml).hexdigest()
    invoice.status = "sending"
    invoice.ksef_environment = config.mode
    invoice.ksef_session_ref = None
    invoice.ksef_invoice_ref = None
    invoice.ksef_status_code = None
    invoice.ksef_status_text = None
    invoice.sent_by = actor_id
    invoice.sent_at = _now()
    _note(invoice, "sending", actor_id, number=invoice.invoice_number)
    await db.flush()
    return xml


async def apply_result(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    result: ksef_send.TransmitResult,
    *,
    actor_id: Optional[int],
) -> None:
    """Zapis wyniku wysyłki albo „Sprawdź status” (bez commita).

    Do edycji (i do zwolnienia numeru przy wycofaniu) wraca tylko faktura,
    która na pewno nie weszła do KSeF: sesja nie powstała, KSeF jawnie odmówił
    pliku albo odrzucił fakturę po weryfikacji. Wynik nieznany (zerwane
    połączenie, 5xx, awaria) i duplikat (440 — faktura o tym numerze już jest
    w KSeF) zostają w drodze, do „Sprawdź status”.
    """

    if result.session_ref:
        invoice.ksef_session_ref = result.session_ref[:64]
    if result.invoice_ref:
        invoice.ksef_invoice_ref = result.invoice_ref[:64]
    if result.upo:
        invoice.upo_xml = result.upo.decode("utf-8", errors="replace")
    status = result.status
    if status is not None and status.accepted:
        invoice.status = "accepted"
        invoice.ksef_number = status.ksef_number
        invoice.ksef_status_code = status.code
        invoice.ksef_status_text = (
            "Faktura była już w KSeF (duplikat) — numer KSeF dociągnięty."
            if result.resolved_duplicate
            else None
        )
        invoice.ksef_acquired_at = status.acquired_at
        invoice.accepted_at = invoice.accepted_at or _now()
        _note(invoice, "accepted", actor_id, ksef_number=status.ksef_number)
        await db.flush()
        try:
            async with db.begin_nested():
                await link_sales_invoice(db, invoice, actor_id=actor_id)
        except Exception:  # noqa: BLE001 — numer KSeF musi zostać zapisany mimo to
            # Powiązanie dorobi odczyt z KSeF (ten sam numer) albo Finanse ręcznie.
            logger.exception(
                "[client-invoicing] powiązanie wystawionej faktury %s nieudane",
                invoice.id,
            )
            await db.refresh(invoice)
        return
    if status is not None and status.duplicate:
        invoice.status = "sent"
        invoice.ksef_status_code = status.code
        invoice.ksef_status_text = (
            f"KSeF ma już fakturę o numerze {invoice.invoice_number} — nie wysyłaj "
            "jej ponownie. „Sprawdź status” dociągnie jej numer KSeF."
        )[:500]
        _note(invoice, "duplicate", actor_id, code=status.code)
    elif status is not None and not status.pending and status.code is not None:
        invoice.status = "rejected"
        invoice.ksef_status_code = status.code
        invoice.ksef_status_text = status.text
        _note(invoice, "rejected", actor_id, code=status.code)
    elif result.definitely_not_sent or (
        result.missing_in_session and _older_than(invoice, STALE_UNSENT_AFTER)
    ):
        # Plik nie dotarł do KSeF albo KSeF go nie przyjął do przetwarzania —
        # faktura nie istnieje w obrocie, numer zostaje przy niej do ponownej wysyłki.
        invoice.status = "failed"
        if result.error is not None:
            invoice.ksef_status_code = result.error.code or result.error.status
            invoice.ksef_status_text = result.error.message[:500]
            _note(invoice, "failed", actor_id, reason=result.error.category)
        else:
            invoice.ksef_status_code = None
            invoice.ksef_status_text = (
                "KSeF nie ma tej faktury w sesji — plik nie dotarł. Wyślij ponownie."
            )
            _note(invoice, "failed", actor_id, reason="missing_in_session")
    else:
        invoice.status = (
            "sent" if result.invoice_ref or invoice.ksef_invoice_ref else "sending"
        )
        if status is not None:
            invoice.ksef_status_code = status.code
            invoice.ksef_status_text = status.text
        elif result.error is not None:
            invoice.ksef_status_text = (
                f"Wynik nieznany: {result.error.message} Faktura mogła trafić do "
                "KSeF — nie wysyłaj jej ponownie, użyj „Sprawdź status”."
            )[:500]
        _note(invoice, "pending", actor_id)
    await db.flush()


def _older_than(invoice: ClientIssuedInvoice, age: timedelta) -> bool:
    return invoice.sent_at is None or _now() - invoice.sent_at > age


async def link_sales_invoice(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, actor_id: Optional[int]
) -> Optional[ClientSalesInvoice]:
    """Wpis w ``client_sales_invoices`` z tym samym numerem KSeF i powiązanie z zamówieniem.

    Odczyt z KSeF (``sales_ksef_fetch``) widzi numer jako zapisany i nie robi
    duplikatu; gdy był szybszy, wiążemy jego wpis.
    """

    if not invoice.ksef_number or not invoice.xml:
        return None
    xml = invoice.xml.encode("utf-8")
    sales = await db.scalar(
        select(ClientSalesInvoice).where(
            ClientSalesInvoice.ksef_number == invoice.ksef_number
        )
    )
    if sales is None:
        parsed = fa_sales.parse_sales_invoice(xml)
        sales = await sales_sync.store_invoice(
            db,
            ksef_number=invoice.ksef_number,
            sales=parsed,
            xml_sha256=hashlib.sha256(xml).hexdigest(),
            acquired_at=invoice.ksef_acquired_at,
            now=_now(),
        )
        if sales is None:
            sales = await db.scalar(
                select(ClientSalesInvoice).where(
                    ClientSalesInvoice.ksef_number == invoice.ksef_number
                )
            )
    if sales is None:
        return None
    invoice.sales_invoice_id = sales.id
    if sales.client_id is None:
        sales.client_id = invoice.client_id
    if invoice.collective_correction is not None:
        # Korekta zbiorcza dotyczy całego miesiąca: odczyt XML-a przypiąłby ją do
        # pierwszej faktury z listy, a „Do faktury” pokazałby tam różnicę.
        sales.corrects_invoice_id = None
    targets: list[matching.Target] = [
        matching.Target(group_id=int(key[1:]))
        if key.startswith("g")
        else matching.Target(order_id=int(key[1:]))
        for key in order_keys(invoice)
    ]
    if (
        targets
        and invoice.invoice_type != "KOR"
        and invoice.period_year is not None
        and sales.match_method != "manual"
    ):
        await matching.link_issued(
            db,
            sales,
            targets=targets,
            period=(int(invoice.period_year), int(invoice.period_month)),
            actor_id=actor_id,
        )
    elif (
        not targets
        and sales.match_method != "manual"
        and sales.match_status != "ignored"
    ):
        # Faktura z ręki, z szablonu, zaliczkowa (i korekta takiej) nie ma
        # zamówienia — automat nie może jej przypiąć „po kwocie”.
        await matching.keep_issued_without_order(db, sales, actor_id=actor_id)
    await db.flush()
    return sales


# ── Odczyt ──────────────────────────────────────────────────────────────────


async def _payment(db: AsyncSession, invoice: ClientIssuedInvoice) -> dict[str, Any]:
    if invoice.sales_invoice_id is None:
        return {"status": "none", "paid": None}
    paid = ZERO
    for amount in await db.scalars(
        select(ClientSalesInvoicePayment.amount).where(
            ClientSalesInvoicePayment.invoice_id == invoice.sales_invoice_id,
            ClientSalesInvoicePayment.match_status == "matched",
        )
    ):
        paid += amount
    gross = invoice.gross_amount or ZERO
    if paid <= 0:
        state = "unpaid"
    elif paid < gross:
        state = "partial"
    else:
        state = "paid"
    return {"status": state, "paid": _amount(paid)}


def _line_payload(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": line.get("name") or "",
        "consultant": line.get("consultant"),
        "quantity": line.get("quantity"),
        "unit": line.get("unit"),
        "unit_price": line.get("unit_price"),
        "vat_rate": line.get("vat_rate"),
        "net": line.get("net"),
        "order_id": line.get("order_id"),
        "order_key": line.get("order_key"),
        "order_number": line.get("order_number"),
        "contract_id": line.get("contract_id"),
        "discount_pct": line.get("discount_pct"),
    }


async def payload(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    *,
    settings: dict[str, Any],
    config: ksef_send.IssueConfig,
    client_name: Optional[str] = None,
    full: bool = True,
) -> dict[str, Any]:
    result = fa3_build.totals(
        _priced(invoice.lines or []), _priced(invoice.lines_before or [])
    )
    data: dict[str, Any] = {
        "id": invoice.id,
        "status": invoice.status,
        "status_label": STATUS_LABELS[invoice.status],
        "invoice_type": invoice.invoice_type,
        "type_label": TYPE_LABELS[invoice.invoice_type],
        "series_code": invoice.series_code,
        "invoice_number": invoice.invoice_number,
        "client_id": invoice.client_id,
        # Faktura z ręki albo z szablonu do nabywcy spoza kartoteki (E6): nazwa nabywcy.
        "client_name": client_name or (invoice.buyer or {}).get("name") or None,
        "template_id": invoice.template_id,
        "buyer": invoice.buyer or {},
        "buyer_kind": _buyer_kind(invoice.buyer or {}),
        "order_group_id": invoice.order_group_id,
        "order_id": invoice.order_id,
        "client_order_number": invoice.client_order_number,
        "period": billing.month_key(int(invoice.period_year), int(invoice.period_month))
        if invoice.period_year
        else None,
        "currency": invoice.currency,
        "issue_date": _iso(invoice.issue_date),
        "sale_date": _iso(invoice.sale_date),
        "period_from": _iso(invoice.period_from),
        "period_to": _iso(invoice.period_to),
        "due_date": _iso(invoice.due_date),
        "net": _amount(invoice.net_amount),
        "vat": _amount(invoice.vat_amount),
        "gross": _amount(invoice.gross_amount),
        "ksef_number": invoice.ksef_number,
        "ksef_status_text": invoice.ksef_status_text,
        "sent_at": _iso(invoice.sent_at),
        "accepted_at": _iso(invoice.accepted_at),
        "payment": await _payment(db, invoice),
    }
    if not full:
        return data
    blocking = (
        await problems(db, invoice, settings, config) if editable(invoice) else []
    )
    found = await invoice_requirements(db, invoice)
    numbers = order_numbers(invoice)
    _, warnings = requirements.line_problems(found, invoice.lines or [])
    checks: list[str] = []
    if editable(invoice):
        warnings = warnings + await protocol_warnings(db, invoice, found)
        checks = await sale_checks.issued_checks(db, invoice, found)
    corrects = (
        await db.get(ClientIssuedInvoice, invoice.corrects_id)
        if invoice.corrects_id
        else None
    )
    data.update(
        {
            "lines": [_line_payload(line) for line in invoice.lines or []],
            "lines_before": [
                _line_payload(line) for line in invoice.lines_before or []
            ],
            "rates": [
                {
                    "code": item.rate.code,
                    "label": item.rate.label,
                    "net": _amount(item.net),
                    "vat": _amount(item.vat),
                }
                for item in result.rates
            ],
            "fx": {
                "rate": fa3_build.plain(invoice.fx_rate),
                "date": _iso(invoice.fx_date),
            }
            if invoice.fx_rate is not None
            else None,
            "notes": invoice.notes,
            "correction_reason": invoice.correction_reason,
            "corrects": {"id": corrects.id, "invoice_number": corrects.invoice_number}
            if corrects is not None
            else None,
            "collective": _collective_payload(invoice.collective_correction),
            "ksef_status_code": invoice.ksef_status_code,
            "ksef_environment": invoice.ksef_environment,
            "has_upo": bool(invoice.upo_xml),
            "has_xml": bool(invoice.xml),
            "sales_invoice_id": invoice.sales_invoice_id,
            "problems": blocking,
            "warnings": warnings if editable(invoice) else [],
            # Uwagi kontroli formalnej: wysyłka tylko z powodem (``checks_reason``).
            "checks": checks,
            "order_numbers": numbers,
            "requirements": requirements.summary(found, numbers),
            "mail": found.mail_for(
                series=invoice.series_code,
                number=invoice.invoice_number,
                ksef_number=invoice.ksef_number,
                period=data["period"],
                order_numbers=numbers,
            ),
            "buyer_options": [
                {"code": item["code"], "name": item["name"], "number": item["number"]}
                for item in issue_settings.client_buyers(settings, invoice.client_id)
            ],
            "editable": editable(invoice),
            "can_send": editable(invoice) and not blocking and config.enabled,
            "can_check": invoice.status in CHECKABLE
            and bool(invoice.ksef_session_ref)
            and config.enabled,
            "can_correct": invoice.status == "accepted"
            and invoice.invoice_type == "VAT"
            and invoice.invoice_type != "KOR",
            "history": list(invoice.history or [])[-20:],
            "rebate": await _rebate(db, invoice, settings),
        }
    )
    return data


def _collective_payload(raw: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    invoices = [
        {
            "number": item.get("number"),
            "issue_date": item.get("issue_date"),
            "ksef_number": item.get("ksef_number"),
        }
        for item in raw.get("invoices") or ()
    ]
    return {
        "year": raw.get("year"),
        "month": raw.get("month"),
        "period": raw.get("period"),
        "correction_type": raw.get("correction_type"),
        "rate_diff": raw.get("rate_diff"),
        "excess": raw.get("excess"),
        "threshold_currency": raw.get("threshold_currency"),
        "invoice_count": len(invoices),
        "invoices": invoices,
    }


def _rebate_period(invoice: ClientIssuedInvoice) -> tuple[int, int]:
    if invoice.period_year and invoice.period_month:
        return int(invoice.period_year), int(invoice.period_month)
    day = invoice.sale_date or invoice.issue_date
    return day.year, day.month


async def apply_rebate(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    settings: dict[str, Any],
    *,
    cache: Optional[dict[tuple[int, int], Optional[rebate.YearRebate]]] = None,
) -> None:
    """Rabat % na pozycjach usług faktury VAT klienta z rabatem od obrotu.

    Tak jak Nordea dostaje go dziś z eBI24 (decyzja Artura 16.11.2026): na każdym
    wierszu cena przed rabatem, rabat % i wartość po rabacie (``P_10`` w XML-u).
    Stawka = próg obrotu roku SPRZED miesiąca faktury. Pozycje wyłączone
    (podróże, refaktury) bez rabatu. Bez warunków przy kliencie nic się nie dzieje.
    """

    terms = issue_settings.client_rebate(settings, invoice.client_id)
    if terms is None or invoice.client_id is None or invoice.invoice_type != "VAT":
        return
    year, month = _rebate_period(invoice)
    key = (invoice.client_id, year)
    if cache is not None and key in cache:
        status = cache[key]
    else:
        status = await rebate.year_rebate(
            db, client_id=invoice.client_id, year=year, terms=terms
        )
        if cache is not None:
            cache[key] = status
    if status is None:
        return
    invoice.lines = [
        clean_line(line)
        for line in rebate.with_discount(
            invoice.lines or [], status.rate_for(month), terms.exclude_words
        )
    ]


async def _rebate(
    db: AsyncSession, invoice: ClientIssuedInvoice, settings: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Stan rabatu od obrotu na karcie faktury: stawka, licznik do progu, korekty.

    Faktura przyjęta w KSeF jest już w ``client_sales_invoices``; szkic (i każda
    nieprzyjęta) dolicza się do obrotu swojego miesiąca.
    """

    terms = issue_settings.client_rebate(settings, invoice.client_id)
    if (
        terms is None
        or invoice.client_id is None
        or invoice.status == "cancelled"
        or invoice.collective_correction is not None
    ):
        return None
    year, month = _rebate_period(invoice)
    lines = list(invoice.lines or [])
    own = None
    if invoice.status != "accepted" and invoice.net_amount is not None:
        net, touched = rebate.service_base(
            Decimal(invoice.net_amount), lines, terms.exclude_words
        )
        own = rebate.Entry(
            (invoice.currency or "PLN").upper(),
            net,
            rebate.rate_boundary(invoice.sale_date, invoice.issue_date),
            month,
            touched,
        )
    status = await rebate.year_rebate(
        db,
        client_id=invoice.client_id,
        year=year,
        terms=terms,
        extra=(own,) if own is not None else (),
    )
    if status is None:
        return None
    discounted = [
        line for line in lines if fa3_build.line_discount_pct(line) is not None
    ]
    on_invoice = sum(
        (
            (fa3_build.line_gross_value(line) or ZERO)
            - (fa3_build.line_net(line) or ZERO)
            for line in discounted
        ),
        Decimal(0),
    )
    data = rebate.payload(
        status,
        month=month,
        on_invoice=on_invoice if discounted else None,
        currency=invoice.currency,
    )
    issued = await collective_issued(db, client_id=invoice.client_id, year=year)
    for item in data["corrections"]:
        item["issued"] = [
            _issued_ref(found)
            for found in issued
            if found.period_month == item["month"]
        ]
    return data


async def collective_issued(
    db: AsyncSession,
    *,
    client_id: int,
    year: int,
    month: Optional[int] = None,
    currency: Optional[str] = None,
) -> list[ClientIssuedInvoice]:
    """Korekty zbiorcze rabatu klienta w roku (bez wycofanych)."""

    query = select(ClientIssuedInvoice).where(
        ClientIssuedInvoice.client_id == client_id,
        ClientIssuedInvoice.period_year == year,
        ClientIssuedInvoice.collective_correction.is_not(None),
        ClientIssuedInvoice.status != "cancelled",
    )
    if month is not None:
        query = query.where(ClientIssuedInvoice.period_month == month)
    if currency is not None:
        query = query.where(ClientIssuedInvoice.currency == currency)
    return list(await db.scalars(query.order_by(ClientIssuedInvoice.id)))


def _issued_ref(invoice: ClientIssuedInvoice) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "currency": invoice.currency,
        "status": invoice.status,
        "status_label": STATUS_LABELS[invoice.status],
        "invoice_number": invoice.invoice_number,
    }


async def listing(
    db: AsyncSession,
    *,
    statuses: Sequence[str],
    settings: dict[str, Any],
    config: ksef_send.IssueConfig,
    year: Optional[int] = None,
    month: Optional[int] = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    query = (
        select(ClientIssuedInvoice)
        .where(ClientIssuedInvoice.status.in_(list(statuses)))
        .order_by(ClientIssuedInvoice.issue_date.desc(), ClientIssuedInvoice.id.desc())
        .limit(limit)
    )
    if year is not None and month is not None:
        # Miesiąc usługi (faktury za październik wystawia się w listopadzie);
        # zaliczkowa bez okresu — miesiąc wystawienia.
        first, last = month_range(year, month)
        query = query.where(
            or_(
                and_(
                    ClientIssuedInvoice.period_year == year,
                    ClientIssuedInvoice.period_month == month,
                ),
                and_(
                    ClientIssuedInvoice.period_year.is_(None),
                    ClientIssuedInvoice.issue_date >= first,
                    ClientIssuedInvoice.issue_date <= last,
                ),
            )
        )
    invoices = list(await db.scalars(query))
    names = await clients.names(
        db, {invoice.client_id for invoice in invoices if invoice.client_id is not None}
    )
    return [
        await payload(
            db,
            invoice,
            settings=settings,
            config=config,
            client_name=names.get(invoice.client_id),
            full=False,
        )
        for invoice in invoices
    ]


__all__ = [
    "EDITABLE",
    "STATUS_LABELS",
    "IssueError",
    "apply_result",
    "clean_line",
    "collective_issued",
    "collective_refs",
    "create_advance",
    "create_correction",
    "create_drafts",
    "delete",
    "document",
    "fx_for",
    "link_sales_invoice",
    "listing",
    "payload",
    "prepare_send",
    "problems",
    "recompute",
    "to_issue",
    "update",
]
