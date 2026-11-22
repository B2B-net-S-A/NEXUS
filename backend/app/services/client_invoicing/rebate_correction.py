"""Szkic korekty zbiorczej rabatu od obrotu za miesiąc przekroczenia progu.

Decyzja Artura 16.11.2026 (Nordea): faktury za miesiąc, w którym obrót roku
przekroczył próg, idą jeszcze po niższej stawce; różnicę stawek od części obrotu
tego miesiąca ponad próg rozlicza JEDNA faktura korygująca za cały miesiąc
(art. 106j ust. 3 ustawy o VAT). Kwota pochodzi z ``rebate.YearRebate.corrections``
— tej samej, którą pokazuje karta faktury.

Forma w FA(3) (schemat ``crd.gov.pl/wzor/2025/06/25/13775``):

* ``RodzajFaktury`` = ``KOR``, ``PrzyczynaKorekty``, ``TypKorekty`` = 2
  (obniżka ceny po fakcie — skutek w dacie korekty),
* ``DaneFaKorygowanej`` dla każdej faktury z miesiąca (numer, data, numer
  KSeF; schemat pozwala na 50 000), także faktur z eBI24 — są w KSeF,
* ``OkresFaKorygowanej`` — miesiąc opustu,
* rabat dotyczy części dostaw (usługi bez podróży i refaktur), więc ``FaWiersz``
  podaje rodzaj usług objętych opustem, po jednym wierszu na stawkę VAT; kwota
  dzieli się na stawki według obrotu usług w tych stawkach.

Podgląd (``prepare``) niczego nie zapisuje. „Wystaw korektę” (``create``,
22.11.2026) zapisuje go jako szkic ``ClientIssuedInvoice`` typu ``KOR`` z listą
faktur w ``collective_correction`` (0750): numer z serii ``KOR`` (``KORUE`` dla
nabywcy z UE) dostaje dopiero przy wysyłce, a wysyłka idzie tym samym
przyciskiem Finansów co każda faktura. Jedna korekta na klienta, miesiąc
i walutę (unikalny indeks; wycofana się nie liczy). Do KSeF na produkcji —
dopiero po „tak” Artura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoicing import fa3_build, issue, issue_settings, rebate
from app.services.client_invoicing.export import month_label
from app.services.client_invoicing.fa3_build import VAT_RATES
from app.services.client_invoice_issue_schema import REASON_MAX
from app.services.hr.calendar import month_range

ZERO = Decimal("0.00")
#: Skutek korekty w dacie jej wystawienia (obniżka ceny po dokonaniu sprzedaży).
CORRECTION_TYPE = "2"
DRAFT_NUMBER = "SZKIC"


@dataclass(frozen=True)
class MonthInvoice:
    """Faktura sprzedaży z KSeF za miesiąc korekty (tylko pola potrzebne szkicowi)."""

    number: str
    issue_date: date
    ksef_number: Optional[str]
    kind: str
    net: Decimal
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Draft:
    year: int
    month: int
    currency: str
    threshold_currency: str
    rate_diff: Decimal
    excess: Decimal
    amount: Decimal
    lines: tuple[dict[str, Any], ...]
    corrected: tuple[tuple[MonthInvoice, Decimal], ...]
    other_amounts: tuple[tuple[str, Decimal], ...]
    problems: tuple[str, ...]


def _label(year: int, month: int) -> str:
    return month_label(f"{year}-{month:02d}")


def _rate_text(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def rate_weights(
    invoices: Sequence[MonthInvoice], words: Sequence[str]
) -> dict[str, Decimal]:
    """Obrót usług miesiąca przed rabatem per stawka VAT (jak ``rebate.service_base``)."""

    weights: dict[str, Decimal] = {}
    for invoice in invoices:
        for item in invoice.items:
            if rebate.is_rebate_line(item) or rebate._excluded(item, words):
                continue
            quantity = rebate._num(item.get("quantity"))
            price = rebate._num(item.get("unit_price"))
            if quantity is not None and price is not None:
                value = rebate.cents(quantity * price)
            else:
                value = rebate._num(item.get("net"))
            if value is None:
                continue
            sign = -1 if item.get("before_correction") else 1
            code = str(item.get("vat_rate") or "").strip()
            weights[code] = weights.get(code, Decimal(0)) + sign * value
    return {code: value for code, value in weights.items() if value != 0}


def allocate(amount: Decimal, weights: dict[str, Decimal]) -> list[tuple[str, Decimal]]:
    """Kwota korekty na stawki VAT proporcjonalnie do obrotu; grosze reszty na największą."""

    positive = {code: value for code, value in weights.items() if value > 0}
    total = sum(positive.values(), Decimal(0))
    if total <= 0:
        return []
    ordered = sorted(positive.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = [(code, rebate.cents(amount * value / total)) for code, value in ordered]
    rest = rebate.cents(amount) - sum((part for _, part in parts), Decimal(0))
    code, first = parts[0]
    parts[0] = (code, first + rest)
    return [(code, part) for code, part in parts if part != 0]


def plan(
    status: rebate.YearRebate,
    *,
    month: int,
    currency: str,
    invoices: Sequence[MonthInvoice],
    words: Sequence[str],
) -> Draft:
    """Szkic z korekty roku i faktur miesiąca; ``IssueError`` bez przekroczenia progu."""

    label = _label(status.year, month)
    correction = next((c for c in status.corrections if c.month == month), None)
    if correction is None:
        raise issue.IssueError(
            f"W miesiącu {label} obrót nie przekroczył progu rabatu — korekty nie ma.",
            409,
        )
    amounts = dict(correction.amounts)
    amount = amounts.get(currency)
    if amount is None or amount <= 0:
        raise issue.IssueError(
            f"Za {label} nie ma korekty w {currency} — faktury miesiąca są w: "
            f"{', '.join(amounts) or 'brak'}.",
            409,
        )
    problems: list[str] = []
    weights = rate_weights(invoices, words)
    unknown = sorted(code or "brak" for code in weights if code not in VAT_RATES)
    if unknown:
        problems.append(
            "Pozycje faktur z miesiąca mają stawkę VAT, której szkic nie obsługuje: "
            + ", ".join(unknown)
            + "."
        )
    parts = allocate(amount, {c: v for c, v in weights.items() if c in VAT_RATES})
    if not parts:
        problems.append("Faktury z miesiąca nie mają pozycji usług ze stawką VAT.")
    name = (
        f"{rebate.REBATE_LINE_PREFIX} — usługi za {label}: dodatkowe "
        f"{_rate_text(correction.rate_diff)}% od części obrotu ponad próg"
    )
    lines = tuple(
        {
            "name": name,
            "quantity": "1",
            "unit_price": format(-part, "f"),
            "vat_rate": code,
        }
        for code, part in parts
    )
    corrected = []
    for invoice in invoices:
        if invoice.kind != "original":
            continue
        base, _ = rebate.service_base(invoice.net, invoice.items, words)
        if base > 0:
            corrected.append((invoice, base))
    corrected.sort(key=lambda pair: (pair[0].issue_date, pair[0].number))
    if not corrected:
        problems.append(
            f"Nie ma faktur w {currency} za {label} do wskazania w korekcie."
        )
    if len(corrected) > fa3_build.MAX_CORRECTED:
        problems.append(
            f"Faktur za miesiąc jest więcej niż {fa3_build.MAX_CORRECTED} — FA(3) ich nie zmieści."
        )
    return Draft(
        year=status.year,
        month=month,
        currency=currency,
        threshold_currency=status.threshold_currency,
        rate_diff=correction.rate_diff,
        excess=correction.excess,
        amount=amount,
        lines=lines,
        corrected=tuple(corrected),
        other_amounts=tuple((c, a) for c, a in correction.amounts if c != currency),
        problems=tuple(problems),
    )


def document(
    draft: Draft,
    *,
    settings: dict[str, Any],
    buyer: dict[str, Any],
    today: date,
    fx_rate: Optional[Decimal],
) -> fa3_build.InvoiceDocument:
    first, last = month_range(draft.year, draft.month)
    seller = settings["seller"]
    return fa3_build.InvoiceDocument(
        invoice_type="KOR",
        number=DRAFT_NUMBER,
        issue_date=today,
        currency=draft.currency,
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
        lines=[dict(line) for line in draft.lines],
        period_from=first,
        period_to=last,
        issue_place=seller["issue_place"] or None,
        fx_rate=fx_rate,
        exemption_basis=settings["exemption_basis"] or None,
        corrected_list=tuple(
            fa3_build.CorrectedInvoice(
                number=invoice.number,
                issue_date=invoice.issue_date,
                ksef_number=invoice.ksef_number,
                reason=None,
            )
            for invoice, _ in draft.corrected
        ),
        correction_reason=reason(draft),
        correction_type=CORRECTION_TYPE,
        corrected_period=period_text(draft.year, draft.month),
    )


def reason(draft: Draft) -> str:
    return (
        f"Rabat od obrotu rocznego za {_label(draft.year, draft.month)}: "
        "wyższa stawka od części obrotu ponad próg z umowy ramowej"
    )[:REASON_MAX]


def period_text(year: int, month: int) -> str:
    first, last = month_range(year, month)
    return f"{first:%d.%m.%Y}-{last:%d.%m.%Y}"


async def _month_invoices(
    db: AsyncSession, *, client_id: int, year: int, month: int, currency: str
) -> list[MonthInvoice]:
    first, last = month_range(year, month)
    in_month = or_(
        and_(
            ClientSalesInvoice.period_year == year,
            ClientSalesInvoice.period_month == month,
        ),
        and_(
            ClientSalesInvoice.period_year.is_(None),
            ClientSalesInvoice.issue_date >= first,
            ClientSalesInvoice.issue_date <= last,
        ),
    )
    rows = (
        await db.execute(
            select(
                ClientSalesInvoice.invoice_number,
                ClientSalesInvoice.issue_date,
                ClientSalesInvoice.ksef_number,
                ClientSalesInvoice.invoice_kind,
                ClientSalesInvoice.net_amount,
                ClientSalesInvoice.items,
            ).where(
                ClientSalesInvoice.client_id == client_id,
                ClientSalesInvoice.currency == currency,
                in_month,
            )
        )
    ).all()
    return [
        MonthInvoice(
            number=row.invoice_number,
            issue_date=row.issue_date,
            ksef_number=row.ksef_number,
            kind=row.invoice_kind,
            net=Decimal(row.net_amount),
            items=tuple(row.items or ()),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class Prepared:
    draft: Draft
    client_name: Optional[str]
    xml: Optional[bytes]
    xml_error: Optional[str]
    fx_rate: Optional[Decimal]
    fx_date: Optional[date]


async def prepare(
    db: AsyncSession,
    *,
    client_id: int,
    year: int,
    month: int,
    currency: str,
    today: date,
) -> Prepared:
    """Szkic za miesiąc z bazy: warunki klienta, stan roku, faktury miesiąca, XML."""

    if not 1 <= month <= 12:
        raise issue.IssueError("Miesiąc od 1 do 12.", 422)
    currency = currency.upper()
    client = await db.get(Client, client_id)
    if client is None:
        raise issue.IssueError("Nie ma takiego klienta.", 404)
    settings = await issue_settings.load(db)
    terms = issue_settings.client_rebate(settings, client_id)
    if terms is None:
        raise issue.IssueError(
            "Klient nie ma warunków rabatu od obrotu w ustawieniach wystawiania.", 409
        )
    status = await rebate.year_rebate(db, client_id=client_id, year=year, terms=terms)
    if status is None:
        raise issue.IssueError(f"Warunki rabatu klienta nie obejmują roku {year}.", 409)
    invoices = await _month_invoices(
        db, client_id=client_id, year=year, month=month, currency=currency
    )
    draft = plan(
        status,
        month=month,
        currency=currency,
        invoices=invoices,
        words=terms.exclude_words,
    )
    fx_rate, fx_date = await issue.fx_for(db, currency, month_range(year, month)[1])
    xml, error = None, None
    buyer = issue._buyer_snapshot(client)
    problems = list(draft.problems)
    if not buyer["name"] or not buyer["address_l1"]:
        problems.append(
            "Klient nie ma nazwy albo adresu w kartotece — uzupełnij je, "
            "żeby powstał XML korekty."
        )
    if problems:
        error = " ".join(problems)
    else:
        doc = document(
            draft,
            settings=settings,
            buyer=buyer,
            today=today,
            fx_rate=fx_rate,
        )
        try:
            xml = fa3_build.build_xml(doc)
        except fa3_build.InvoiceBuildError as exc:
            error = str(exc)
    return Prepared(
        draft=draft,
        client_name=client.legal_name or client.name,
        xml=xml,
        xml_error=error,
        fx_rate=fx_rate,
        fx_date=fx_date,
    )


def collective_json(draft: Draft) -> dict[str, Any]:
    """``collective_correction`` wystawionej korekty: faktury z KSeF, okres, typ."""

    return {
        "kind": "rebate",
        "year": draft.year,
        "month": draft.month,
        "period": period_text(draft.year, draft.month),
        "correction_type": CORRECTION_TYPE,
        "threshold_currency": draft.threshold_currency,
        "rate_diff": format(draft.rate_diff.normalize(), "f"),
        "excess": _amount(draft.excess),
        "invoices": [
            {
                "number": invoice.number,
                "issue_date": invoice.issue_date.isoformat(),
                "ksef_number": invoice.ksef_number,
                "base": _amount(base),
            }
            for invoice, base in draft.corrected
        ],
    }


def _already(label: str, currency: str, found: ClientIssuedInvoice) -> issue.IssueError:
    state = (
        f"{found.invoice_number}, {issue.STATUS_LABELS[found.status].lower()}"
        if found.invoice_number
        else "szkic bez numeru"
    )
    return issue.IssueError(
        f"Korekta rabatu za {label} w {currency} już jest ({state}). Druga korekta "
        "za ten sam miesiąc nie powstanie — popraw tę albo ją wycofaj.",
        409,
    )


async def create(
    db: AsyncSession,
    *,
    client_id: int,
    year: int,
    month: int,
    currency: str,
    actor_id: int,
    today: date,
) -> ClientIssuedInvoice:
    """„Wystaw korektę”: szkic ``KOR`` z podglądu (bez numeru i bez commita).

    Odmowa: druga korekta za ten sam miesiąc i walutę (także szkic), podgląd
    z problemem (brak XML-a). Unikalny indeks łapie wyścig dwóch kliknięć.
    """

    currency = currency.upper()
    label = _label(year, month)
    found = await issue.collective_issued(
        db, client_id=client_id, year=year, month=month, currency=currency
    )
    if found:
        raise _already(label, currency, found[0])
    prepared = await prepare(
        db, client_id=client_id, year=year, month=month, currency=currency, today=today
    )
    if prepared.xml is None:
        raise issue.IssueError(
            prepared.xml_error or "Szkic korekty nie jest kompletny.", 422
        )
    draft = prepared.draft
    client = await db.get(Client, client_id)
    settings = await issue_settings.load(db)
    buyer = issue._buyer_snapshot(client)
    first, last = month_range(year, month)
    invoice = ClientIssuedInvoice(
        client_id=client_id,
        invoice_type="KOR",
        series_code="KORUE" if issue._buyer_kind(buyer) == "eu" else "KOR",
        status="draft",
        period_year=year,
        period_month=month,
        corrects_id=None,
        correction_reason=reason(draft),
        currency=currency,
        issue_date=today,
        sale_date=None,
        period_from=first,
        period_to=last,
        due_date=today
        + timedelta(days=issue_settings.client_payment_days(settings, client_id)),
        buyer=buyer,
        lines=[issue.clean_line({**line, "unit": "usł."}) for line in draft.lines],
        lines_before=[],
        fx_rate=prepared.fx_rate,
        fx_date=prepared.fx_date,
        collective_correction=collective_json(draft),
        history=[],
        created_by=actor_id,
    )
    issue.recompute(invoice)
    issue._note(invoice, "created", actor_id, source=f"rabat {year}-{month:02d}")
    db.add(invoice)
    await db.flush()
    return invoice


def _amount(value: Decimal) -> str:
    return format(rebate.cents(value), "f")


def payload(prepared: Prepared, *, client_id: int) -> dict[str, Any]:
    draft = prepared.draft
    lines = [dict(line) for line in draft.lines]
    result = fa3_build.totals(lines) if lines else None
    return {
        "client_id": client_id,
        "client_name": prepared.client_name,
        "year": draft.year,
        "month": draft.month,
        "currency": draft.currency,
        "threshold_currency": draft.threshold_currency,
        "rate_diff": format(draft.rate_diff.normalize(), "f"),
        "excess": _amount(draft.excess),
        "amount": _amount(draft.amount),
        "lines": [
            {
                "name": line["name"],
                "vat_rate": line["vat_rate"],
                "vat_label": VAT_RATES[line["vat_rate"]].label,
                "net": _amount(fa3_build.line_net(line) or ZERO),
            }
            for line in lines
        ],
        "net": _amount(result.net) if result else None,
        "vat": _amount(result.vat) if result else None,
        "gross": _amount(result.gross) if result else None,
        "invoices": [
            {
                "number": invoice.number,
                "issue_date": invoice.issue_date.isoformat(),
                "ksef_number": invoice.ksef_number,
                "base": _amount(base),
            }
            for invoice, base in draft.corrected
        ],
        "invoice_count": len(draft.corrected),
        "other_amounts": [
            {"currency": currency, "amount": _amount(amount)}
            for currency, amount in draft.other_amounts
        ],
        "fx_rate": format(prepared.fx_rate, "f") if prepared.fx_rate else None,
        "fx_date": prepared.fx_date.isoformat() if prepared.fx_date else None,
        "xml_ready": prepared.xml is not None,
        "xml_error": prepared.xml_error,
        "correction_type": CORRECTION_TYPE,
    }


__all__ = [
    "Draft",
    "MonthInvoice",
    "allocate",
    "collective_json",
    "create",
    "document",
    "payload",
    "plan",
    "prepare",
    "rate_weights",
]
