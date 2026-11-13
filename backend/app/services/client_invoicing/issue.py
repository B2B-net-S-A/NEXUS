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
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.services import fx_service
from app.services.client_invoicing import (
    billing,
    clients,
    fa3_build,
    fa_sales,
    issue_settings,
    ksef_send,
    matching,
    numbering,
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
from app.services.hr.calendar import month_range

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")
EDITABLE = frozenset({"draft", "rejected", "failed"})
SENDABLE = EDITABLE
CHECKABLE = frozenset({"sending", "sent"})
#: Kurs NBP starszy o tyle dni od dnia przed datą dostawy to brak kursu w cache.
FX_MAX_GAP_DAYS = 7
LINE_NAME_MAX = 512
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
    net = fa3_build.line_net(line)
    line["net"] = _amount(net)
    return line


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


async def fx_for(
    db: AsyncSession, currency: str, delivery: Optional[date]
) -> tuple[Optional[Decimal], Optional[date]]:
    """Kurs średni NBP z ostatniego dnia roboczego przed datą dostawy."""

    if currency == "PLN" or delivery is None:
        return None, None
    snapshot = await fx_service.get_rate_snapshot_to_pln(
        db, currency, on=delivery - timedelta(days=1)
    )
    if (
        snapshot is None
        or snapshot.source != "NBP"
        or (delivery - snapshot.effective_date).days > FX_MAX_GAP_DAYS
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


def _buyer_snapshot(client: Client) -> dict[str, Any]:
    number = client.nip or ""
    ident = fa3_build.buyer_id(number)
    country = "PL" if ident.kind in ("nip", "none") else (ident.country or "PL")
    return {
        "name": (client.legal_name or client.name or "")[:255],
        "number": number[:32],
        "address_l1": (client.address or "")[:255],
        "address_l2": "",
        "country": "EL" if country == "GR" else country,
    }


def _buyer_kind(buyer: dict[str, Any]) -> str:
    return fa3_build.buyer_id(buyer.get("number")).kind


def clean_buyer(raw: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = {**current, **{k: v for k, v in raw.items() if v is not None}}
    country = "".join(
        ch for ch in str(merged.get("country") or "PL").upper() if ch.isalpha()
    )[:2]
    return {
        "name": " ".join(str(merged.get("name") or "").split())[:255],
        "number": "".join(
            ch for ch in str(merged.get("number") or "").upper() if ch.isalnum()
        )[:32],
        "address_l1": " ".join(str(merged.get("address_l1") or "").split())[:255],
        "address_l2": " ".join(str(merged.get("address_l2") or "").split())[:255],
        "country": country or "PL",
    }


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
        key = (
            f"g{invoice.order_group_id}"
            if invoice.order_group_id is not None
            else f"o{invoice.order_id}"
        )
        out.setdefault(key, []).append(invoice)
    return out


def _row_block(row: billing.BillingRow) -> Optional[str]:
    if row.missing:
        people = ", ".join(
            line.consultant
            for line in row.lines
            if line.net is None and line.basis != "cost"
        )
        return f"Brak kwoty pozycji (czeka na zużycie MD albo stawkę): {people}."
    return None


async def to_issue(db: AsyncSession, *, year: int, month: int) -> dict[str, Any]:
    rows = await billing.billing_rows(db, year=year, month=month)
    existing = await _existing_by_key(db, year, month)
    names = await clients.names(db, {row.client_id for row in rows})
    by_client: dict[int, dict[str, Any]] = {}
    for row in sorted(
        rows, key=lambda r: (names.get(r.client_id) or "", r.order_number)
    ):
        entry = by_client.setdefault(
            row.client_id,
            {
                "client_id": row.client_id,
                "client_name": names.get(row.client_id),
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
                "blocked": _row_block(row),
                "needs_amount": row.kind == "cost",
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


def _lines_for(
    row: billing.BillingRow,
    lines: Sequence[billing.BillingLine],
    *,
    service: str,
    period: str,
    vat_rate: str,
) -> list[dict[str, Any]]:
    out = []
    for line in lines:
        cost = line.basis == "cost"
        out.append(
            clean_line(
                {
                    "name": _line_name(
                        service, row.order_number, line.consultant, period
                    ),
                    "consultant": line.consultant,
                    "quantity": "1" if cost else line.quantity,
                    "unit": UNIT_FOR_BASIS.get(line.basis, line.unit),
                    "unit_price": None if cost else line.unit_price,
                    "vat_rate": vat_rate,
                    "order_id": line.order_id,
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


def _defaults(client: Client, settings: dict[str, Any], today: date) -> DraftDefaults:
    buyer = _buyer_snapshot(client)
    eu = _buyer_kind(buyer) == "eu"
    return DraftDefaults(
        issue_date=today,
        due_date=today
        + timedelta(days=issue_settings.client_payment_days(settings, client.id)),
        vat_rate=issue_settings.client_vat(settings, client.id, eu_buyer=eu),
        series="UE" if eu else "PL",
        buyer=buyer,
    )


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
    existing = await _existing_by_key(db, year, month)
    problems = []
    for key in wanted:
        row = rows.get(key)
        if row is None:
            problems.append(
                f"Zamówienie {key} nie ma pozycji do faktury w tym miesiącu."
            )
            continue
        block = _row_block(row)
        if block:
            problems.append(f"{row.order_number}: {block}")
        if existing.get(key):
            problems.append(
                f"{row.order_number}: ma już fakturę za ten miesiąc "
                f"({STATUS_LABELS[existing[key][0].status].lower()})."
            )
    if problems:
        raise IssueError(" ".join(problems))

    settings = await issue_settings.load(db)
    period = billing.month_key(year, month)
    first, last = month_range(year, month)
    created: list[ClientIssuedInvoice] = []
    for key in wanted:
        row = rows[key]
        client = await db.get(Client, row.client_id)
        if client is None:
            raise IssueError("Nie ma klienta zamówienia.", 404)
        defaults = _defaults(client, settings, today)
        groups = (
            [[line] for line in row.lines] if split == "person" else [list(row.lines)]
        )
        for lines in groups:
            invoice = ClientIssuedInvoice(
                client_id=row.client_id,
                invoice_type="VAT",
                series_code=defaults.series,
                status="draft",
                order_group_id=row.group_id,
                order_id=row.order_id
                if row.group_id is None
                else (lines[0].order_id if split == "person" else None),
                period_year=year,
                period_month=month,
                currency=row.currency if row.currency in CURRENCIES else "PLN",
                issue_date=defaults.issue_date,
                sale_date=last,
                period_from=first,
                period_to=last,
                due_date=defaults.due_date,
                client_order_number=row.order_number[:ORDER_NUMBER_MAX],
                buyer=defaults.buyer,
                lines=_lines_for(
                    row,
                    lines,
                    service=settings["service_name"],
                    period=period,
                    vat_rate=defaults.vat_rate,
                ),
                lines_before=[],
                history=[],
                created_by=actor_id,
            )
            recompute(invoice)
            await _refresh_fx(db, invoice)
            _note(invoice, "created", actor_id, source=key)
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

    if invoice.status not in EDITABLE:
        raise IssueError("Tę fakturę można już tylko skorygować.")
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
        if code not in ("PL", "UE"):
            raise IssueError("Faktura VAT idzie serią krajową albo UE.", 422)
        if invoice.number_seq is not None and code != invoice.series_code:
            raise IssueError("Faktura ma już numer z tej serii.", 422)
        invoice.series_code = code
    if isinstance(payload.get("buyer"), dict):
        invoice.buyer = clean_buyer(payload["buyer"], invoice.buyer or {})
    if "lines" in payload:
        lines = payload["lines"]
        if not isinstance(lines, list) or len(lines) > MAX_LINES:
            raise IssueError("Pozycje: lista do 200 wierszy.", 422)
        invoice.lines = [clean_line(line) for line in lines if isinstance(line, dict)]
    recompute(invoice)
    await _refresh_fx(db, invoice)
    _note(invoice, "edited", actor_id)
    await db.flush()
    return invoice


async def delete(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, actor_id: int
) -> str:
    """Szkic znika bez śladu; faktura z numerem spoza obrotu — patrz ``numbering.release``.

    Zwraca ``deleted`` albo ``cancelled``.
    """

    if invoice.status not in EDITABLE:
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
    note = " ".join((reason or "").split())
    if len(note) < 3:
        raise IssueError("Podaj przyczynę korekty (co najmniej 3 znaki).", 422)
    settings = await issue_settings.load(db)
    lines = [clean_line(line) for line in original.lines or []]
    invoice = ClientIssuedInvoice(
        client_id=original.client_id,
        invoice_type="KOR",
        series_code="KOR",
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
    defaults = _defaults(client, settings, today)
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
    if not invoice.lines:
        out.append("Faktura nie ma pozycji.")
    out.extend(line_problems(invoice.lines or []))
    if invoice.invoice_type == "KOR":
        if not invoice.correction_reason:
            out.append("Podaj przyczynę korekty.")
        if invoice.lines == invoice.lines_before:
            out.append("Korekta nie zmienia żadnej pozycji.")
    if invoice.currency != "PLN" and invoice.fx_rate is None:
        out.append(
            f"Brak kursu NBP {invoice.currency} z dnia roboczego przed datą dostawy "
            "— kursy pobiera NEXUS codziennie, sprawdź datę dostawy."
        )
    codes = {line.get("vat_rate") for line in invoice.lines or []}
    if "zw" in codes and not settings["exemption_basis"]:
        out.append("Pozycja „zw.” wymaga podstawy zwolnienia w ustawieniach.")
    if (
        invoice.currency != "PLN"
        and not settings["accounts"][invoice.currency]["number"]
    ):
        out.append(f"Brak rachunku {invoice.currency} w ustawieniach wystawiania.")
    if invoice.currency == "PLN" and not settings["accounts"]["PLN"]["number"]:
        out.append("Brak rachunku PLN w ustawieniach wystawiania.")
    return out


async def document(
    db: AsyncSession, invoice: ClientIssuedInvoice, settings: dict[str, Any]
) -> fa3_build.InvoiceDocument:
    seller = settings["seller"]
    account = settings["accounts"].get(invoice.currency) or {}
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
    buyer = invoice.buyer or {}
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
        client_order_number=invoice.client_order_number,
        notes=invoice.notes,
        exemption_basis=settings["exemption_basis"] or None,
        corrected=corrected,
        created_at=_now(),
    )


async def prepare_send(
    db: AsyncSession,
    invoice: ClientIssuedInvoice,
    *,
    config: ksef_send.IssueConfig,
    actor_id: int,
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
    if invoice.status not in SENDABLE:
        raise IssueError("Ta faktura jest już w KSeF albo w drodze do niego.")
    settings = await issue_settings.load(db)
    await _refresh_fx(db, invoice)
    recompute(invoice)
    blocking = await problems(db, invoice, settings, config)
    if blocking:
        raise IssueError(" ".join(blocking), 422)
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
    """Zapis wyniku wysyłki albo „Sprawdź status” (bez commita)."""

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
        invoice.ksef_status_text = None
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
    if status is not None and not status.pending and status.code is not None:
        invoice.status = "rejected"
        invoice.ksef_status_code = status.code
        invoice.ksef_status_text = status.text
        _note(invoice, "rejected", actor_id, code=status.code)
    elif result.error is not None and result.stage in ("open", "send"):
        # Plik nie dotarł do KSeF albo KSeF go nie przyjął do przetwarzania —
        # faktura nie istnieje w obrocie, numer zostaje przy niej do ponownej wysyłki.
        invoice.status = "failed"
        invoice.ksef_status_code = result.error.code or result.error.status
        invoice.ksef_status_text = result.error.message[:500]
        _note(invoice, "failed", actor_id, reason=result.error.category)
    else:
        invoice.status = (
            "sent" if result.invoice_ref or invoice.ksef_invoice_ref else "sending"
        )
        if status is not None:
            invoice.ksef_status_code = status.code
            invoice.ksef_status_text = status.text
        elif result.error is not None:
            invoice.ksef_status_text = (
                f"Wynik nieznany: {result.error.message} Sprawdź status za chwilę."
            )[:500]
        _note(invoice, "pending", actor_id)
    await db.flush()


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
    targets: list[matching.Target] = []
    if invoice.order_id is not None:
        targets.append(matching.Target(order_id=invoice.order_id))
    elif invoice.order_group_id is not None:
        targets.append(matching.Target(group_id=invoice.order_group_id))
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
        "client_name": client_name,
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
        await problems(db, invoice, settings, config)
        if invoice.status in SENDABLE
        else []
    )
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
            "ksef_status_code": invoice.ksef_status_code,
            "ksef_environment": invoice.ksef_environment,
            "has_upo": bool(invoice.upo_xml),
            "has_xml": bool(invoice.xml),
            "sales_invoice_id": invoice.sales_invoice_id,
            "problems": blocking,
            "editable": invoice.status in EDITABLE,
            "can_send": invoice.status in SENDABLE and not blocking and config.enabled,
            "can_check": invoice.status in CHECKABLE and config.enabled,
            "can_correct": invoice.status == "accepted"
            and invoice.invoice_type != "KOR",
            "history": list(invoice.history or [])[-20:],
        }
    )
    return data


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
    names = await clients.names(db, {invoice.client_id for invoice in invoices})
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
