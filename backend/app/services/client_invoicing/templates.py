"""Faktura z ręki, szablony „co miesiąc” i refaktury benefitów (E6, 15.11.2026).

eBI24 wystawiał co miesiąc ok. 210 faktur bez zamówienia w NEXUSIE (X 2026:
155 refaktur pakietów sportowych i opieki medycznej do kontraktorów, reszta to
usługi do firm bez zamówienia). „Wystaw za miesiąc” bierze tylko zamówienia,
więc tu są trzy drogi do zwykłego szkicu E4:

* ``create_manual`` — pusty szkic do klienta z kartoteki albo do dowolnego
  nabywcy (jednorazowa faktura),
* szablon (``ClientInvoiceTemplate``) — nabywca, pozycje, waluta; ``run``
  tworzy z zaznaczonych szablonów szkice za miesiąc (jeden szkic szablonu na
  miesiąc — unikalny indeks), ``due`` mówi, co za ten miesiąc już jest,
* ``suggestions`` / ``import_from_ksef`` — szablony z faktur z KSeF bez
  zamówienia z wybranego miesiąca (to, co wystawił eBI24), ``from_invoice`` —
  „Zapisz jako szablon” z karty faktury.

Szkic idzie dalej drogą E4 (numer przy wysyłce, KSeF, PDF). Nazwa pozycji może
mieć ``{okres}`` („październik 2026”), ``{okresu}`` („października 2026”),
``{mm}`` i ``{rrrr}`` — przy imporcie miesiąc z nazwy zamienia się na znacznik.
Adres nabywcy bez adresu w szablonie bierze się z kartoteki kontrahentów
(import z eBI24) albo z klienta po NIP-ie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_issued_invoice import ClientInvoiceTemplate, ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.finance_ledger import FinanceCounterparty
from app.services.client_invoice_issue_schema import NOTES_MAX
from app.services.client_invoice_templates_schema import (
    BENEFITS,
    KINDS,
    NAME_MAX,
    TEMPLATE_SERIES,
)
from app.services.client_invoicing import (
    client_defaults,
    fa3_build,
    issue,
    issue_settings,
)
from app.services.client_invoicing.export import MONTHS_PL
from app.services.client_invoicing.issue import IssueError
from app.services.client_sales_invoices_schema import CURRENCIES
from app.services.hr.calendar import month_range

MAX_TEMPLATES_PER_RUN = 500
MAX_IMPORT = 500
BENEFIT_LABELS = {
    "sport": "pakiet sportowy",
    "medical": "opieka medyczna",
    "other": "inny",
}
KIND_LABELS = {"service": "usługi", "benefit": "refaktura benefitu"}

#: Dopełniacz do ``{okresu}`` („za usługi października 2026”).
MONTHS_GEN = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)

_REINVOICE = re.compile(r"refaktur", re.IGNORECASE)
_SPORT = re.compile(r"sport|multisport|fitness|karnet", re.IGNORECASE)
_MEDICAL = re.compile(r"medycz|opiek|zdrow|luxmed|lux med|medicover", re.IGNORECASE)


# ── Nazwy pozycji i miesiąc ─────────────────────────────────────────────────


def render_name(name: str, year: int, month: int) -> str:
    return (
        name.replace("{okresu}", f"{MONTHS_GEN[month - 1]} {year}")
        .replace("{okres}", f"{MONTHS_PL[month - 1]} {year}")
        .replace("{mm}", f"{month:02d}")
        .replace("{rrrr}", str(year))
    )


def templatize_name(name: str, year: int, month: int) -> str:
    """Miesiąc faktury źródłowej w nazwie → znacznik (szablon działa co miesiąc)."""

    out = re.sub(
        rf"\b{MONTHS_GEN[month - 1]}\s+{year}\b", "{okresu}", name, flags=re.IGNORECASE
    )
    out = re.sub(
        rf"\b{MONTHS_PL[month - 1]}\s+{year}\b", "{okres}", out, flags=re.IGNORECASE
    )
    return re.sub(rf"\b{month:02d}([./-]){year}\b", r"{mm}\g<1>{rrrr}", out)


def benefit_of(names: Iterable[str]) -> Optional[str]:
    """Refaktura benefitu po nazwie pozycji: sport, medyczne, inny; ``None`` = usługa."""

    text_ = " ".join(names)
    if not _REINVOICE.search(text_):
        return None
    if _SPORT.search(text_):
        return "sport"
    if _MEDICAL.search(text_):
        return "medical"
    return "other"


# ── Nabywca ─────────────────────────────────────────────────────────────────


def _digits(value: Optional[str]) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _key(number: Optional[str]) -> str:
    """Klucz porównania NIP-u: bez prefiksu PL, bez separatorów."""

    value = _digits(number)
    return value[2:] if value.startswith("PL") and value[2:].isdigit() else value


@dataclass(frozen=True)
class BuyerBook:
    """Adresy i klienci po NIP-ie — kartoteka kontrahentów (eBI24) i klienci."""

    counterparties: dict[str, FinanceCounterparty]
    clients: dict[str, Client]

    def client_for(self, number: Optional[str]) -> Optional[Client]:
        return self.clients.get(_key(number)) if _key(number) else None

    def fill(self, buyer: dict[str, Any]) -> dict[str, Any]:
        """Uzupełnia puste pola nabywcy (nic nie nadpisuje)."""

        key = _key(buyer.get("number"))
        out = dict(buyer)
        party = self.counterparties.get(key) if key else None
        if party is not None:
            if not out.get("name"):
                out["name"] = party.name[:255]
            if not out.get("address_l1") and party.street:
                out["address_l1"] = party.street[:255]
                place = " ".join(
                    part for part in (party.postal_code, party.city) if part
                )
                out["address_l2"] = out.get("address_l2") or place[:255]
            if party.country and not buyer.get("country"):
                out["country"] = party.country
        client = self.client_for(buyer.get("number"))
        if client is not None:
            if not out.get("name"):
                out["name"] = (client.legal_name or client.name or "")[:255]
            if not out.get("address_l1") and client.address:
                out["address_l1"] = client.address[:255]
        return issue.clean_buyer(out, {})


async def buyer_book(db: AsyncSession, numbers: Iterable[Optional[str]]) -> BuyerBook:
    keys = {_key(number) for number in numbers if _key(number)}
    if not keys:
        return BuyerBook({}, {})
    parties = {
        _key(party.id_value): party
        for party in await db.scalars(
            select(FinanceCounterparty).where(
                FinanceCounterparty.id_value.in_(
                    sorted(keys | {f"PL{key}" for key in keys})
                )
            )
        )
    }
    clients = {
        _key(client.nip): client
        for client in await db.scalars(
            select(Client).where(Client.nip.is_not(None), Client.deleted_at.is_(None))
        )
        if _key(client.nip) in keys
    }
    return BuyerBook(parties, clients)


def _series_for(buyer: dict[str, Any], wanted: Optional[str] = None) -> str:
    if wanted in TEMPLATE_SERIES:
        return str(wanted)
    return "UE" if fa3_build.buyer_id(buyer.get("number")).kind == "eu" else "PL"


# ── Faktura z ręki ──────────────────────────────────────────────────────────


async def create_manual(
    db: AsyncSession,
    *,
    client_id: Optional[int],
    buyer: Optional[dict[str, Any]],
    currency: str,
    actor_id: int,
    today: date,
) -> ClientIssuedInvoice:
    """Pusty szkic: klient z kartoteki albo nabywca wpisany ręcznie (bez commita)."""

    if currency not in CURRENCIES:
        raise IssueError("Waluta spoza PLN, EUR i USD.", 422)
    settings = await issue_settings.load(db)
    if client_id is not None:
        client = await db.get(Client, client_id)
        if client is None or client.deleted_at is not None:
            raise IssueError("Nie ma takiego klienta.", 404)
        defaults = issue._defaults(  # noqa: SLF001
            client,
            settings,
            today,
            history=await client_defaults.for_client(db, client, today=today),
        )
        snapshot, series, vat = defaults.buyer, defaults.series, defaults.vat_rate
        due = defaults.due_date
    else:
        raw = issue.clean_buyer(buyer or {}, {})
        if not raw["name"] and not raw["number"]:
            raise IssueError("Podaj nabywcę: klienta albo nazwę lub NIP.", 422)
        snapshot = (await buyer_book(db, [raw["number"]])).fill(raw)
        series = _series_for(snapshot)
        vat = "np II" if series == "UE" else settings["default_vat"]
        due = today + timedelta(days=settings["payment_days"])
    invoice = ClientIssuedInvoice(
        client_id=client_id,
        invoice_type="VAT",
        series_code=series,
        status="draft",
        currency=currency,
        issue_date=today,
        sale_date=today,
        due_date=due,
        buyer=snapshot,
        lines=[
            issue.clean_line(
                {
                    "name": settings["service_name"],
                    "quantity": "1",
                    "unit": "usł.",
                    "vat_rate": vat,
                }
            )
        ],
        lines_before=[],
        history=[],
        created_by=actor_id,
    )
    issue.recompute(invoice)
    await issue._refresh_fx(db, invoice)  # noqa: SLF001
    issue._note(invoice, "created", actor_id, source="manual")  # noqa: SLF001
    db.add(invoice)
    await db.flush()
    return invoice


# ── Szablony: zapis ─────────────────────────────────────────────────────────


def _template_line(raw: dict[str, Any]) -> dict[str, Any]:
    line = issue.clean_line({**raw, "order_id": None})
    line["consultant"] = None
    # Zamówienie i kontrakt pozycji (faktura z kilku zamówień) nie idą do szablonu:
    # faktura z szablonu zablokowałaby te zamówienia w „Wystaw za miesiąc”.
    for key in ("order_key", "order_number", "contract_id"):
        line.pop(key, None)
    return line


def _date(raw: Any, label: str) -> Optional[date]:
    return issue._date(raw, label)  # noqa: SLF001


async def save(
    db: AsyncSession,
    template: Optional[ClientInvoiceTemplate],
    payload: dict[str, Any],
    *,
    actor_id: int,
) -> ClientInvoiceTemplate:
    """Nowy szablon (``template=None``) albo zmiana; brak pola = bez zmian (bez commita)."""

    item = template or ClientInvoiceTemplate(
        kind="service", source="manual", buyer={}, lines=[], created_by=actor_id
    )
    if "kind" in payload:
        if payload["kind"] not in KINDS:
            raise IssueError("Rodzaj szablonu: usługi albo refaktura benefitu.", 422)
        item.kind = payload["kind"]
    if "benefit" in payload or "kind" in payload:
        benefit = payload.get("benefit", item.benefit)
        if item.kind == "benefit":
            if benefit not in BENEFITS:
                raise IssueError(
                    "Wybierz benefit: sport, opieka medyczna albo inny.", 422
                )
            item.benefit = benefit
        else:
            item.benefit = None
    if "client_id" in payload:
        client_id = payload["client_id"]
        if client_id is not None:
            client = await db.get(Client, int(client_id))
            if client is None or client.deleted_at is not None:
                raise IssueError("Nie ma takiego klienta.", 404)
            if "buyer" not in payload:
                item.buyer = issue._buyer_snapshot(client)  # noqa: SLF001
        item.client_id = client_id
    if isinstance(payload.get("buyer"), dict):
        item.buyer = issue.clean_buyer(payload["buyer"], item.buyer or {})
    if "name" in payload:
        item.name = " ".join(str(payload["name"] or "").split())[:NAME_MAX]
    if not item.name:
        item.name = (item.buyer or {}).get("name") or ""
    if not item.name:
        raise IssueError("Podaj nazwę szablonu albo nabywcę.", 422)
    if "currency" in payload:
        if payload["currency"] not in CURRENCIES:
            raise IssueError("Waluta spoza PLN, EUR i USD.", 422)
        item.currency = payload["currency"]
    if "series_code" in payload or template is None:
        item.series_code = _series_for(item.buyer or {}, payload.get("series_code"))
    if "lines" in payload:
        lines = payload["lines"]
        if not isinstance(lines, list) or len(lines) > issue.MAX_LINES:
            raise IssueError("Pozycje: lista do 200 wierszy.", 422)
        item.lines = [_template_line(line) for line in lines if isinstance(line, dict)]
    if "payment_days" in payload:
        days = payload["payment_days"]
        if days is not None and not 0 <= int(days) <= 180:
            raise IssueError("Termin płatności: od 0 do 180 dni.", 422)
        item.payment_days = days
    if "notes" in payload:
        item.notes = str(payload["notes"] or "").strip()[:NOTES_MAX] or None
    if "active" in payload:
        item.active = bool(payload["active"])
    if "valid_from" in payload:
        item.valid_from = _date(payload["valid_from"], "Od")
    if "valid_to" in payload:
        item.valid_to = _date(payload["valid_to"], "Do")
    if item.valid_from and item.valid_to and item.valid_from > item.valid_to:
        raise IssueError("Ważność szablonu: data „od” jest po dacie „do”.", 422)
    item.updated_by = actor_id
    if template is None:
        db.add(item)
    await db.flush()
    return item


async def from_invoice(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, actor_id: int
) -> ClientInvoiceTemplate:
    """„Zapisz jako szablon” z faktury VAT (nabywca, pozycje, waluta, seria)."""

    if invoice.invoice_type != "VAT":
        raise IssueError("Szablon robi się z faktury VAT (nie z korekty ani zaliczki).")
    if issue.order_keys(invoice):
        # Szablon obok „Wystaw za miesiąc” zafakturowałby tę samą usługę drugi raz.
        raise IssueError(
            "Faktura z zamówienia powstaje co miesiąc w „Wystaw za miesiąc” — "
            "szablon robi się z faktury bez zamówienia."
        )
    year, month = invoice.period_year, invoice.period_month
    lines = [
        {
            **line,
            "name": templatize_name(str(line.get("name") or ""), year, month)
            if year and month
            else line.get("name"),
        }
        for line in invoice.lines or []
    ]
    names = [str(line.get("name") or "") for line in lines]
    benefit = benefit_of(names)
    template = await save(
        db,
        None,
        {
            "kind": "benefit" if benefit else "service",
            "benefit": benefit,
            "client_id": invoice.client_id,
            "buyer": dict(invoice.buyer or {}),
            "name": (invoice.buyer or {}).get("name") or "",
            "currency": invoice.currency,
            "series_code": invoice.series_code,
            "lines": lines,
            "notes": invoice.notes,
        },
        actor_id=actor_id,
    )
    template.source = "invoice"
    template.source_ref = invoice.invoice_number
    await db.flush()
    return template


# ── Szablony z faktur z KSeF (to, co wystawił eBI24) ────────────────────────


def _signature(
    number: Optional[str], names: Sequence[str]
) -> tuple[str, tuple[str, ...]]:
    return _key(number), tuple(sorted(" ".join(name.split()).lower() for name in names))


async def _signatures(
    db: AsyncSession,
) -> tuple[set[tuple[str, tuple[str, ...]]], set[str]]:
    rows = list(await db.scalars(select(ClientInvoiceTemplate)))
    signatures = {
        _signature(
            (row.buyer or {}).get("number"),
            [str(line.get("name") or "") for line in row.lines or []],
        )
        for row in rows
    }
    return signatures, {row.source_ref for row in rows if row.source_ref}


def _source_lines(invoice: ClientSalesInvoice) -> list[dict[str, Any]]:
    year, month = invoice.period_year, invoice.period_month
    out = []
    for item in invoice.items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        out.append(
            _template_line(
                {
                    "name": templatize_name(name, year, month)
                    if year and month
                    else name,
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                    "unit_price": item.get("unit_price"),
                    "vat_rate": item.get("vat_rate"),
                }
            )
        )
    return out


async def _unlinked(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    ksef_numbers: Optional[Sequence[str]] = None,
) -> list[ClientSalesInvoice]:
    linked = exists().where(ClientSalesInvoiceLink.invoice_id == ClientSalesInvoice.id)
    issued = exists().where(
        ClientIssuedInvoice.sales_invoice_id == ClientSalesInvoice.id
    )
    query = select(ClientSalesInvoice).where(
        ClientSalesInvoice.period_year == year,
        ClientSalesInvoice.period_month == month,
        ClientSalesInvoice.invoice_type == "VAT",
        ClientSalesInvoice.ignore_reason.is_(None),
        ~linked,
        ~issued,
    )
    if ksef_numbers is not None:
        query = query.where(ClientSalesInvoice.ksef_number.in_(list(ksef_numbers)))
    return list(
        await db.scalars(
            query.order_by(ClientSalesInvoice.buyer_name, ClientSalesInvoice.id)
        )
    )


#: Powody braku dopasowania, przy których faktura do klienta NIE jest z zamówienia.
_NOT_ORDER_REASONS = frozenset({None, "no_orders", "unknown_buyer"})


def _from_order(invoice: ClientSalesInvoice) -> bool:
    """Faktura do klienta, której automat nie dopasował do zamówienia (np. inna kwota).

    To faktura z zamówienia — w NEXUSIE powstaje w „Wystaw za miesiąc”, więc
    szablon z niej zafakturowałby usługę drugi raz (przeklikanie 15.11.2026:
    faktury banku „Usługi informatyczne — konsultant” wśród propozycji).
    """

    return (
        invoice.client_id is not None and invoice.match_reason not in _NOT_ORDER_REASONS
    )


def _buyer_from_sales(invoice: ClientSalesInvoice) -> dict[str, Any]:
    number = invoice.buyer_nip or invoice.buyer_foreign_id or ""
    ident = fa3_build.buyer_id(number)
    country = ident.country if ident.kind == "eu" and ident.country else "PL"
    return issue.clean_buyer(
        {"name": invoice.buyer_name or "", "number": number, "country": country}, {}
    )


async def suggestions(db: AsyncSession, *, year: int, month: int) -> dict[str, Any]:
    """Faktury z KSeF bez zamówienia z miesiąca → propozycje szablonów."""

    invoices = await _unlinked(db, year=year, month=month)
    book = await buyer_book(db, [_buyer_from_sales(inv)["number"] for inv in invoices])
    signatures, refs = await _signatures(db)
    rows = []
    for invoice in invoices:
        lines = _source_lines(invoice)
        names = [line["name"] for line in lines]
        buyer = book.fill(_buyer_from_sales(invoice))
        client = book.client_for(buyer["number"])
        benefit = benefit_of(names)
        rows.append(
            {
                "ksef_number": invoice.ksef_number,
                "invoice_number": invoice.invoice_number,
                "buyer_name": buyer["name"] or invoice.buyer_name,
                "buyer_number": buyer["number"],
                "client_id": client.id if client is not None else None,
                "kind": "benefit" if benefit else "service",
                "benefit": benefit,
                "lines": [issue._line_payload(line) for line in lines],  # noqa: SLF001
                "net": issue._amount(invoice.net_amount),  # noqa: SLF001
                "currency": invoice.currency,
                "address_missing": not buyer["address_l1"],
                "from_order": _from_order(invoice),
                "has_template": invoice.ksef_number in refs
                or _signature(buyer["number"], names) in signatures,
            }
        )
    return {
        "year": year,
        "month": month,
        "rows": rows,
        "counts": {
            "all": len(rows),
            "benefit": sum(1 for row in rows if row["kind"] == "benefit"),
            "has_template": sum(1 for row in rows if row["has_template"]),
            "from_order": sum(1 for row in rows if row["from_order"]),
        },
    }


async def import_from_ksef(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    ksef_numbers: Sequence[str],
    actor_id: int,
) -> list[ClientInvoiceTemplate]:
    """Szablony z zaznaczonych faktur (bez commita); faktura z szablonem — pomijana."""

    wanted = list(dict.fromkeys(ksef_numbers))
    if not wanted:
        raise IssueError("Zaznacz co najmniej jedną fakturę.", 422)
    if len(wanted) > MAX_IMPORT:
        raise IssueError(f"Najwyżej {MAX_IMPORT} faktur naraz.", 422)
    invoices = await _unlinked(db, year=year, month=month, ksef_numbers=wanted)
    book = await buyer_book(db, [_buyer_from_sales(inv)["number"] for inv in invoices])
    signatures, refs = await _signatures(db)
    created = []
    for invoice in invoices:
        lines = _source_lines(invoice)
        names = [line["name"] for line in lines]
        buyer = book.fill(_buyer_from_sales(invoice))
        signature = _signature(buyer["number"], names)
        if (
            _from_order(invoice)
            or invoice.ksef_number in refs
            or signature in signatures
        ):
            continue
        client = book.client_for(buyer["number"])
        benefit = benefit_of(names)
        template = ClientInvoiceTemplate(
            kind="benefit" if benefit else "service",
            benefit=benefit,
            name=(buyer["name"] or invoice.buyer_name or "")[:NAME_MAX],
            active=True,
            client_id=client.id if client is not None else None,
            buyer=buyer,
            currency=invoice.currency if invoice.currency in CURRENCIES else "PLN",
            series_code=_series_for(buyer),
            lines=lines,
            source="ksef",
            source_ref=invoice.ksef_number,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(template)
        created.append(template)
        signatures.add(signature)
    await db.flush()
    return created


# ── Szkice za miesiąc ───────────────────────────────────────────────────────


def _valid_in(template: ClientInvoiceTemplate, first: date, last: date) -> bool:
    return (template.valid_from is None or template.valid_from <= last) and (
        template.valid_to is None or template.valid_to >= first
    )


async def _issued_for(
    db: AsyncSession, year: int, month: int, template_ids: Sequence[int]
) -> dict[int, ClientIssuedInvoice]:
    if not template_ids:
        return {}
    rows = await db.scalars(
        select(ClientIssuedInvoice).where(
            ClientIssuedInvoice.template_id.in_(list(template_ids)),
            ClientIssuedInvoice.period_year == year,
            ClientIssuedInvoice.period_month == month,
            ClientIssuedInvoice.status != "cancelled",
        )
    )
    return {row.template_id: row for row in rows if row.template_id is not None}


def _buyer_match_key(buyer: dict[str, Any]) -> str:
    key = _key(buyer.get("number"))
    if key:
        return key
    name = " ".join(str(buyer.get("name") or "").split()).lower()
    return f"name:{name}" if name else ""


async def _in_ksef(db: AsyncSession, year: int, month: int) -> dict[str, list[str]]:
    """Faktury z KSeF spoza NEXUSA (np. z eBI24) bez zamówienia za miesiąc → nabywca.

    Miesiąc przejściowy (przegląd 15.11.2026): eBI24 wystawia te same faktury
    z własnych szablonów, więc szablon NEXUSA do nabywcy, który ma już taką
    fakturę za ten miesiąc, nie robi szkicu. Porównanie po nabywcy, nie po
    pozycjach — inna nazwa pozycji nie może przepuścić duplikatu; brakującą
    fakturę (np. drugi benefit tej samej osoby) wystawia się „Nową fakturą”.
    """

    out: dict[str, list[str]] = {}
    for invoice in await _unlinked(db, year=year, month=month):
        key = _buyer_match_key(_buyer_from_sales(invoice))
        if key:
            out.setdefault(key, []).append(
                invoice.invoice_number or invoice.ksef_number
            )
    return out


def template_net(template: ClientInvoiceTemplate) -> Optional[Decimal]:
    priced = issue._priced(template.lines or [])  # noqa: SLF001
    if not priced:
        return None
    return fa3_build.totals(priced, []).net


def _problem(template: ClientInvoiceTemplate) -> Optional[str]:
    lines = template.lines or []
    if not lines:
        return "szablon nie ma pozycji"
    if issue.line_problems(lines):
        return "pozycja bez ilości, ceny albo stawki"
    return None


async def listing(
    db: AsyncSession,
    *,
    kind: Optional[str],
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    """Szablony z tym, co za wybrany miesiąc już z nich powstało."""

    query = select(ClientInvoiceTemplate)
    if kind is not None:
        query = query.where(ClientInvoiceTemplate.kind == kind)
    templates = list(
        await db.scalars(
            query.order_by(
                ClientInvoiceTemplate.active.desc(),
                ClientInvoiceTemplate.name,
                ClientInvoiceTemplate.id,
            )
        )
    )
    first, last = month_range(year, month)
    issued = await _issued_for(db, year, month, [t.id for t in templates])
    in_ksef = await _in_ksef(db, year, month)
    book = await buyer_book(db, [(t.buyer or {}).get("number") for t in templates])
    return [
        payload(
            template,
            issued=issued.get(template.id),
            invoiced_in_ksef=in_ksef.get(_buyer_match_key(template.buyer or {}), []),
            in_month=_valid_in(template, first, last),
            address_missing=not book.fill(template.buyer or {})["address_l1"],
        )
        for template in templates
    ]


def payload(
    template: ClientInvoiceTemplate,
    *,
    issued: Optional[ClientIssuedInvoice] = None,
    invoiced_in_ksef: Sequence[str] = (),
    in_month: bool = True,
    address_missing: bool = False,
) -> dict[str, Any]:
    problem = _problem(template)
    return {
        "id": template.id,
        "kind": template.kind,
        "kind_label": KIND_LABELS[template.kind],
        "benefit": template.benefit,
        "benefit_label": BENEFIT_LABELS.get(template.benefit or ""),
        "name": template.name,
        "active": template.active,
        "client_id": template.client_id,
        "buyer": template.buyer or {},
        "currency": template.currency,
        "series_code": template.series_code,
        "lines": [issue._line_payload(line) for line in template.lines or []],  # noqa: SLF001
        "net": issue._amount(template_net(template)),  # noqa: SLF001
        "payment_days": template.payment_days,
        "notes": template.notes,
        "valid_from": issue._iso(template.valid_from),  # noqa: SLF001
        "valid_to": issue._iso(template.valid_to),  # noqa: SLF001
        "source": template.source,
        "source_ref": template.source_ref,
        "in_month": in_month,
        "problem": problem,
        "address_missing": address_missing,
        "issued": (
            {
                "id": issued.id,
                "invoice_number": issued.invoice_number,
                "status": issued.status,
                "status_label": issue.STATUS_LABELS[issued.status],
            }
            if issued is not None
            else None
        ),
        #: Numery faktur z KSeF spoza NEXUSA do tego nabywcy za ten miesiąc (eBI24).
        "invoiced_in_ksef": list(invoiced_in_ksef),
        "selectable": template.active
        and in_month
        and problem is None
        and issued is None
        and not invoiced_in_ksef,
    }


async def run(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    template_ids: Sequence[int],
    actor_id: int,
    today: date,
) -> list[ClientIssuedInvoice]:
    """Szkice z zaznaczonych szablonów za miesiąc (bez commita)."""

    wanted = list(dict.fromkeys(int(tid) for tid in template_ids))
    if not wanted:
        raise IssueError("Zaznacz co najmniej jeden szablon.", 422)
    if len(wanted) > MAX_TEMPLATES_PER_RUN:
        raise IssueError(f"Najwyżej {MAX_TEMPLATES_PER_RUN} szablonów naraz.", 422)
    templates = {
        row.id: row
        for row in await db.scalars(
            select(ClientInvoiceTemplate)
            .where(ClientInvoiceTemplate.id.in_(wanted))
            .with_for_update()
        )
    }
    first, last = month_range(year, month)
    issued = await _issued_for(db, year, month, wanted)
    in_ksef = await _in_ksef(db, year, month)
    problems = []
    for tid in wanted:
        template = templates.get(tid)
        if template is None:
            problems.append(f"Nie ma szablonu {tid}.")
            continue
        if not template.active:
            problems.append(f"{template.name}: szablon wyłączony.")
        elif not _valid_in(template, first, last):
            problems.append(f"{template.name}: szablon nie obowiązuje w tym miesiącu.")
        elif issued.get(tid) is not None:
            problems.append(f"{template.name}: ma już fakturę za ten miesiąc.")
        elif in_ksef.get(_buyer_match_key(template.buyer or {})):
            numbers = ", ".join(in_ksef[_buyer_match_key(template.buyer or {})])
            problems.append(
                f"{template.name}: nabywca ma już w KSeF fakturę za ten miesiąc "
                f"({numbers}) — brakującą wystaw „Nową fakturą”."
            )
        elif _problem(template):
            problems.append(f"{template.name}: {_problem(template)}.")
    if problems:
        raise IssueError(" ".join(problems[:20]))

    settings = await issue_settings.load(db)
    book = await buyer_book(
        db, [(t.buyer or {}).get("number") for t in templates.values()]
    )
    created = []
    for tid in wanted:
        template = templates[tid]
        days = (
            template.payment_days
            if template.payment_days is not None
            else issue_settings.client_payment_days(settings, template.client_id)
        )
        invoice = ClientIssuedInvoice(
            client_id=template.client_id,
            template_id=template.id,
            invoice_type="VAT",
            # Refaktura benefitu idzie własną serią bez rachunku (kompensata),
            # jak w eBI24 „N/M/RRRR/Benefit” — decyzja Artura 16.11.2026.
            series_code="BEN"
            if template.kind == "benefit" and template.series_code == "PL"
            else template.series_code,
            status="draft",
            period_year=year,
            period_month=month,
            currency=template.currency,
            issue_date=today,
            sale_date=last,
            period_from=first,
            period_to=last,
            due_date=today + timedelta(days=days),
            notes=template.notes,
            buyer=book.fill(template.buyer or {}),
            lines=[
                {**line, "name": render_name(str(line.get("name") or ""), year, month)}
                for line in template.lines or []
            ],
            lines_before=[],
            history=[],
            created_by=actor_id,
        )
        issue.recompute(invoice)
        await issue._refresh_fx(db, invoice)  # noqa: SLF001
        issue._note(invoice, "created", actor_id, source=f"template:{template.id}")  # noqa: SLF001
        db.add(invoice)
        created.append(invoice)
    await db.flush()
    return created


__all__ = [
    "BENEFIT_LABELS",
    "BuyerBook",
    "benefit_of",
    "buyer_book",
    "create_manual",
    "from_invoice",
    "import_from_ksef",
    "listing",
    "payload",
    "render_name",
    "run",
    "save",
    "suggestions",
    "templatize_name",
]
