"""Do faktury dla klienta (roadmapa E5.1, E5.2, E5.3).

Z przyjętych rozliczeń miesiąca składamy pozycje faktury do klienta tak, jak
dziś wyglądają w KSeF: nazwa pozycji z ostatniej faktury do klienta za tę grupę
zamówienia (bez przyrostka), MD × stawka klienta, praca dodatkowa osobną
pozycją z przyrostkiem z reguły ``cl.overtime_item`` po stawce × mnożnik, MD
wdrożeniowe pozycją za 0 zł. Nic tu nie wystawia faktury: Finanse kopiują
pozycje do programu, a wystawiona faktura wraca z KSeF (``client_invoicing``)
i przypięta do grupy zamówienia i miesiąca zmienia stan na „Wystawiona”.

Estymacja (E5.3): miesiąc z przyjętą estymacją fakturujemy z estymacji;
faktyczne RCP za ten miesiąc już nie wchodzi na fakturę, a gdy wyszło mniej MD,
różnica schodzi ujemną pozycją na fakturze za następny miesiąc (bez korekty).

Waluta (E6.2): linia zamówienia ze stawką klienta w innej walucie niż zł
(``rate_client_currency``, stawka dzienna) daje pozycje w tej walucie po
``rate_client`` — tak wystawiamy fakturę do klienta rozliczanego w euro.
Marża zostaje w zł: netto przeliczamy kursem z linii zamówienia
(``md_rate_revenue`` / ``rate_client``), tym samym, którym liczy się przychód.

Dodatki (13.11.2026): zatwierdzony dodatek z ``bill_to_client`` (np. koszty
dodatkowe z KEŚU Aliora — trafiają tu jako zgłoszony dodatek, ``extras.sync_from_kesu``)
idzie na fakturę według ``cl.extra_costs_on_invoice`` — parametr ``item`` pusty =
jedna pozycja 1 × (usługa + koszty), nazwa = osobna pozycja z tą nazwą. Dodatki zatwierdzone (także niefakturowane klientowi) są kosztem
miesiąca, więc obniżają marżę. Waluta linii inna niż zł: dodatek w zł nie
trafia do pozycji, wiersz dostaje uwagę.

Paczka załączników (E5.2): pliki RCP i maile miesiąca w zipie; przy regule
``cl.attachment_name`` plik RCP nosi numer KSeF faktury do klienta.

Podział na zamówienia z maila klienta (``service.split_orders``, 24.11.2026):
osoba ma wiersz na każde zamówienie — pozycja z MD tej części, stawką i nazwą
z historii faktur tego zamówienia, stan „Wystawiona” po fakturze na to
zamówienie. Dodatki i korekta planu idą na wiersz zamówienia rozliczenia.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import ClientSettlement
from app.services.client_settlements import extras as settlement_extras
from app.services.client_settlements import client_acceptance, service, signoffs
from app.services.client_settlements import t4t_invoice, time_reports
from app.services.client_settlements.rcp_checks import name_tokens
from app.services.consultant_portal import documents as portal_documents
from app.services.hr.payroll_periods import add_months

MONEY = Decimal("0.01")
PLN = "PLN"
ONBOARDING_SUFFIX = "_onbording"  # tak jak dziś w fakturach do BNP
CORRECTION_SUFFIX = "_korekta_estymacji"
_SUFFIX = re.compile(
    r"[_\s]+(nadgodziny|onbording|onboarding|korekta[\w ]*)\s*$", re.IGNORECASE
)
EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-outlook": ".msg",
    "message/rfc822": ".eml",
}


@dataclass(frozen=True)
class Position:
    name: str
    unit: str
    quantity: Decimal
    unit_price: Optional[Decimal]
    net: Decimal
    kind: str  # base · overtime · onboarding · correction · extra
    currency: str = PLN

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "name": self.name,
            "unit": self.unit,
            "quantity": f"{self.quantity.normalize():f}",
            "unit_price": None if self.unit_price is None else f"{self.unit_price:.2f}",
            "net": f"{self.net:.2f}",
            "kind": self.kind,
        }


def _money(value: Decimal) -> Decimal:
    # Połówka w górę jak silnik i FA(3): bankowe zaokrąglenie dawało grosz
    # różnicy między „Do faktury” a XML do KSeF (audyt 24.11.2026).
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _previous(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    year, mon = add_months(year, mon, -1)
    return f"{year}-{mon:02d}"


def base_name(items: list[dict[str, Any]], person: str) -> Optional[str]:
    """Nazwa pozycji zasadniczej z faktury: bez przyrostka; przy kilku osobach
    na fakturze — ta z nazwiskiem osoby."""

    names = [
        str(item.get("name") or "").strip()
        for item in items
        if isinstance(item, dict) and item.get("name")
    ]
    plain = [n for n in names if not _SUFFIX.search(n)] or [
        _SUFFIX.sub("", n) for n in names
    ]
    if not plain:
        return None
    if len(plain) > 1:
        tokens = name_tokens(person)
        mine = [n for n in plain if tokens and tokens <= name_tokens(n)]
        if mine:
            return mine[0]
    return plain[0]


async def _group_invoices(
    db: AsyncSession, group_ids: set[int], *, by_order: bool = False
) -> dict[int, list[tuple[str, ClientSalesInvoice]]]:
    """Faktury do klienta per grupa zamówienia: (miesiąc usługi, faktura).
    ``by_order`` — per linia zamówienia (Nordea: linie bez grup)."""

    if not group_ids:
        return {}
    key = (
        ClientSalesInvoiceLink.order_id
        if by_order
        else ClientSalesInvoiceLink.order_group_id
    )
    rows = await db.execute(
        select(
            key,
            ClientSalesInvoiceLink.period_year,
            ClientSalesInvoiceLink.period_month,
            ClientSalesInvoice,
        )
        .join(
            ClientSalesInvoice,
            ClientSalesInvoice.id == ClientSalesInvoiceLink.invoice_id,
        )
        .where(key.in_(group_ids))
        .order_by(ClientSalesInvoice.issue_date, ClientSalesInvoice.id)
    )
    out: dict[int, list[tuple[str, ClientSalesInvoice]]] = {}
    for group_id, year, month, invoice in rows.all():
        out.setdefault(int(group_id), []).append((f"{year}-{int(month):02d}", invoice))
    return out


@dataclass(frozen=True)
class ClientPrice:
    """Cena MD do faktury klienta i kurs do zł (przychód w bazie jest w zł)."""

    rate: Optional[Decimal]
    currency: str
    to_pln: Decimal


def client_price(order: Optional[ClientOrder]) -> ClientPrice:
    if order is None:
        return ClientPrice(None, PLN, Decimal("1"))
    currency = (order.rate_client_currency or PLN).upper()
    unit = getattr(order.rate_unit, "value", order.rate_unit)
    if (
        currency != PLN
        and unit == "daily"
        and order.rate_client
        and order.md_rate_revenue
    ):
        rate = Decimal(order.rate_client)
        return ClientPrice(rate, currency, Decimal(order.md_rate_revenue) / rate)
    # Linia ze stawką godzinową bez stawki MD (PKO): MD × 8 h × stawka za godzinę.
    return ClientPrice(service.md_rates(order)[1], PLN, Decimal("1"))


def _multiplier(s: ClientSettlement) -> Decimal:
    for line in s.lines or []:
        if isinstance(line, dict) and line.get("label") == "Praca dodatkowa":
            try:
                return Decimal(str(line.get("multiplier")))
            except ArithmeticError:
                break
    return Decimal("1")


def item_name(
    rules: dict[str, dict[str, Any]], order_number: Optional[str], person: str
) -> Optional[str]:
    """Opis pozycji ze wzoru ``cl.item_name`` (``{zamowienie}``, ``{osoba}``).

    Pola, których tu nie znamy (``{rola}``, ``{usluga}``, ``{miesiac}`` — wzór
    wspólny ze szkicem faktury z NEXUSA), znikają z opisu.
    """

    from app.services.client_invoicing.requirements import render_item_name

    rule = rules.get("cl.item_name")
    if not rule or rule["level"] == "off":
        return None
    pattern = str(rule["params"].get("template") or "").strip()
    if not pattern:
        return None
    return render_item_name(pattern, order_number=order_number, person=person)


def positions(
    s: ClientSettlement,
    *,
    name: str,
    rate: Optional[Decimal],
    overtime_suffix: Optional[str],
    currency: str = PLN,
) -> list[Position]:
    regular = Decimal(s.md_regular or 0)
    extra = Decimal(s.md_extra or 0)
    onboarding = Decimal(s.md_onboarding or 0)
    price = None if rate is None else _money(Decimal(rate))
    if service.md_over(s) and s.md_charged is not None:
        # Ponad pulę (10.11): do klienta tylko to, co zeszło z zamówienia —
        # najpierw dni zwykłe, potem praca dodatkowa.
        cap = Decimal(s.md_charged)
        base_cap = min(regular - onboarding, cap)
        mult = _multiplier(s)
        extra = min(extra, ((cap - base_cap) / mult).quantize(Decimal("0.001")))
        regular = base_cap + onboarding
    out = [
        Position(
            name,
            "MD",
            regular - onboarding,
            price,
            _money((regular - onboarding) * (price or 0)),
            "base",
            currency,
        )
    ]
    if onboarding > 0:
        out.append(
            Position(
                name + ONBOARDING_SUFFIX,
                "MD",
                onboarding,
                None,
                Decimal("0.00"),
                "onboarding",
                currency,
            )
        )
    if extra > 0:
        extra_price = None if price is None else _money(price * _multiplier(s))
        suffix = overtime_suffix if overtime_suffix is not None else "_nadgodziny"
        if overtime_suffix is None:
            # Bez reguły nadgodziny nie idą osobno: ta sama pozycja, cena × mnożnik.
            out.append(
                Position(
                    name,
                    "MD",
                    extra,
                    extra_price,
                    _money(extra * (extra_price or 0)),
                    "overtime",
                    currency,
                )
            )
        else:
            out.append(
                Position(
                    name + suffix,
                    "MD",
                    extra,
                    extra_price,
                    _money(extra * (extra_price or 0)),
                    "overtime",
                    currency,
                )
            )
    return out


def part_position(part: dict[str, Any], price: ClientPrice, *, name: str) -> Position:
    """Pozycja jednej części podziału na zamówienia (``service.split_orders``)."""

    md = Decimal(str(part["md"]))
    unit_price = None if price.rate is None else _money(Decimal(price.rate))
    return Position(
        name,
        "MD",
        md,
        unit_price,
        _money(md * (unit_price or 0)),
        "base",
        price.currency,
    )


def _history_template(
    history: list[tuple[str, ClientSalesInvoice]], month: str, person: str
) -> Optional[str]:
    """Nazwa pozycji z ostatniej faktury do klienta sprzed miesiąca."""

    return next(
        (
            base_name(inv.items or [], person)
            for period, inv in reversed(history)
            if period < month and base_name(inv.items or [], person)
        ),
        None,
    )


def _finish_row(
    out: dict[str, Any],
    items: list[Position],
    *,
    price: ClientPrice,
    cost: Optional[Decimal],
    integration_cost: Decimal,
    issued: Optional[ClientSalesInvoice],
    template: Optional[str],
    chosen: Optional[ClientSettlement],
    actual: Optional[ClientSettlement],
    rules: dict[str, dict[str, Any]],
    amounts: bool,
) -> dict[str, Any]:
    """Stan, pozycje i marża wiersza „Do faktury”."""

    net = sum((p.net for p in items), Decimal("0"))
    out.update(
        currency=price.currency,
        state="issued"
        if issued
        else "awaiting_signature"
        if service.waits_for_signature(chosen, rules)
        else "awaiting_client"
        if client_acceptance.waiting(actual, rules)
        else "ready",
        positions=[p.as_dict() for p in items]
        if amounts
        else [{**p.as_dict(), "unit_price": None, "net": None} for p in items],
        template=template is not None,
        ksef_number=issued.ksef_number if issued else None,
        invoice_number=issued.invoice_number if issued else None,
    )
    if amounts:
        out["net"] = f"{net:.2f}"
        if cost is not None:
            # Koszty integracji ze zgodą DL-a obniżają marżę miesiąca (E5.1).
            net_pln = _money(net * price.to_pln)
            margin = net_pln - cost - integration_cost
            out["cost"] = f"{cost:.2f}"
            out["integration_cost"] = (
                f"{integration_cost:.2f}" if integration_cost else None
            )
            out["margin"] = f"{margin:.2f}"
            out["margin_pct"] = (
                None if net_pln == 0 else f"{margin / net_pln * 100:.1f}"
            )
    return out


def _split_rows(
    out: dict[str, Any],
    parts: list[dict[str, Any]],
    *,
    chosen: ClientSettlement,
    actual: Optional[ClientSettlement],
    orders: dict[int, ClientOrder],
    invoices: dict[int, list[tuple[str, ClientSalesInvoice]]],
    month: str,
    rules: dict[str, dict[str, Any]],
    amounts: bool,
    correction: tuple[Optional[ClientSettlement], Optional[ClientSettlement]],
    extras: list[Any],
    extra_rule: dict[str, Any],
    extras_cost: Decimal,
    integration_cost: Decimal,
) -> list[dict[str, Any]]:
    """Wiersze osoby z podziałem na zamówienia: faktura na każde zamówienie, tak
    jak wystawiają je Finanse (próba IX–X 2026). Dodatki, korekta planu i koszty
    integracji idą na wiersz zamówienia rozliczenia (``main``)."""

    found: list[dict[str, Any]] = []
    for part in parts:
        order = orders.get(int(part["order_id"]))
        price = client_price(order)
        # Numer tej części; numery pozostałych zamówień nie są jej numerem.
        number = part.get("number")
        history = (
            invoices.get(order.order_group_id, [])
            if order and order.order_group_id
            else []
        )
        template = item_name(rules, number, out["person"]) or _history_template(
            history, month, out["person"]
        )
        name = template or (
            f"Usługi informatyczne; {out['person']}; nr zamówienia: {number or '—'}"
        )
        items = [part_position(part, price, name=name)]
        row = {**out, "order_number": number, "order_id": int(part["order_id"])}
        main = bool(part.get("main"))
        cost = (
            None
            if part.get("amount_cost") is None
            else Decimal(str(part["amount_cost"]))
        )
        if main:
            estimate, previous = correction
            if estimate is not None and previous is not None:
                fix = _correction(
                    estimate,
                    previous,
                    name=name,
                    rate=price.rate,
                    month_label=_previous(month),
                    currency=price.currency,
                )
                if fix is not None:
                    items.append(fix)
            items, row["extras_note"] = with_extras(
                items, extras, rule=extra_rule, currency=price.currency, name=name
            )
            cost = None if cost is None else cost + extras_cost
        found.append(
            _finish_row(
                row,
                items,
                price=price,
                cost=cost,
                integration_cost=integration_cost if main else Decimal("0"),
                issued=next((inv for period, inv in history if period == month), None),
                template=template,
                chosen=chosen,
                actual=actual,
                rules=rules,
                amounts=amounts,
            )
        )
    return found


def _correction(
    estimate: ClientSettlement,
    actual: ClientSettlement,
    *,
    name: str,
    rate: Optional[Decimal],
    month_label: str,
    currency: str = PLN,
) -> Optional[Position]:
    if estimate.md_charged is None or actual.md_charged is None:
        return None
    diff = Decimal(estimate.md_charged) - Decimal(actual.md_charged)
    if diff <= 0:
        return None
    price = None if rate is None else _money(Decimal(rate))
    return Position(
        f"{name}{CORRECTION_SUFFIX} {month_label}",
        "MD",
        -diff,
        price,
        _money(-diff * (price or 0)),
        "correction",
        currency,
    )


async def invoice_month(
    db: AsyncSession,
    client_id: int,
    month: str,
    *,
    amounts: bool,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Wiersze „Do faktury dla klienta” za miesiąc klienta.

    Klient z raportem T4T (``report.time_for_teams``) ma pozycje z godzin
    zatwierdzonych w ostatniej wersji raportu (``t4t_invoice``), nie z RCP.
    ``today`` włącza ostrzeżenie o terminie faktury."""

    view = await service.month_view(db, client_id, month, amounts=amounts)
    if t4t_invoice.is_on(await service.rules_for(db, client_id, month)):
        return await _t4t_month(
            db, view, client_id, month, amounts=amounts, today=today
        )
    previous = _previous(month)
    # Kontrakt zakończony w miesiącu planu nie ma już wiersza w kolejnym
    # miesiącu, a korekta planu musi trafić na fakturę (E5.3).
    listed = {r["contract_id"] for r in view["rows"]}
    ended = (
        await db.scalars(
            select(ClientSettlement.contract_id).where(
                ClientSettlement.client_id == client_id,
                ClientSettlement.period_month == previous,
                ClientSettlement.kind == service.ESTIMATE,
                ClientSettlement.status == "accepted",
                ClientSettlement.contract_id.not_in(listed) if listed else True,
            )
        )
    ).all()
    for contract_id in ended:
        person = await service._contract(db, contract_id)
        view["rows"].append(
            {"contract_id": contract_id, "person": person.name, "order_number": None}
        )
    ids = [r["contract_id"] for r in view["rows"]]
    settlements = (
        (
            await db.scalars(
                select(ClientSettlement).where(
                    ClientSettlement.contract_id.in_(ids),
                    ClientSettlement.period_month.in_((month, previous)),
                    ClientSettlement.status == "accepted",
                )
            )
        ).all()
        if ids
        else []
    )
    by_key = {(s.contract_id, s.period_month, s.kind): s for s in settlements}
    order_ids = {i for s in settlements for i in service.settlement_order_ids(s)}
    orders = (
        {
            o.id: o
            for o in (
                await db.scalars(
                    select(ClientOrder).where(ClientOrder.id.in_(order_ids))
                )
            ).all()
        }
        if order_ids
        else {}
    )
    groups = {o.order_group_id for o in orders.values() if o.order_group_id is not None}
    invoices = await _group_invoices(db, groups)
    rules = await service.rules_for(db, client_id, month)
    # E6: faktura do klienta po podpisanym protokole albo arkuszach (wszystkich).
    document_kind = (
        signoffs.document_rule(rules, month)
        if rules["cl.after_signed_document"]["level"] != "off"
        else None
    )
    integration = (
        await service.integration_by_contract(db, ids, month) if amounts else {}
    )
    suffix_rule = rules["cl.overtime_item"]
    overtime_suffix = (
        str(suffix_rule["params"].get("suffix") or "_nadgodziny")
        if suffix_rule["level"] != "off"
        else None
    )
    extra_rule = rules["cl.extra_costs_on_invoice"]
    billed = await settlement_extras.billed_to_client(db, ids, month)
    added = await settlement_extras.expected_by_contract(db, ids, month)
    rows = []
    signed_by_row: list[bool] = []
    # KEŚU (E6.3) ma własne wstrzymanie („Czeka na podpis klienta”).
    with_kesu = False
    for row in view["rows"]:
        contract_id = row["contract_id"]
        estimate = by_key.get((contract_id, month, service.ESTIMATE))
        actual = by_key.get((contract_id, month, service.ACTUAL))
        chosen = estimate or actual
        with_kesu = with_kesu or service.kesu_state(chosen) is not None
        signed_by_row.append(
            bool(document_kind)
            and actual is not None
            and signoffs.is_complete(actual.checks, document_kind)
        )
        out: dict[str, Any] = {
            "contract_id": contract_id,
            "person": row["person"],
            "order_number": row["order_number"],
            # Linia zamówienia wiersza: przy podziale osoba ma wiersz na każdą.
            "order_id": None,
            # Sama korekta planu (kontrakt już bez pracy) idzie jak RCP faktyczne.
            "kind": chosen.kind if chosen else None,
            "currency": PLN,
            "state": "waiting",
            "positions": [],
            "net": None,
            "cost": None,
            "integration_cost": None,
            "margin": None,
            "margin_pct": None,
            "template": False,
            "ksef_number": None,
            "invoice_number": None,
            "extras_note": None,
        }
        prev_estimate = by_key.get((contract_id, previous, service.ESTIMATE))
        prev_actual = by_key.get((contract_id, previous, service.ACTUAL))
        basis = chosen or (prev_estimate if prev_actual is not None else None)
        if basis is None:
            rows.append(out)
            continue
        if chosen is None:
            out["kind"] = service.ACTUAL
        parts = service.split_orders(chosen)
        if parts:
            rows.extend(
                _split_rows(
                    out,
                    parts,
                    chosen=chosen,
                    actual=actual,
                    orders=orders,
                    invoices=invoices,
                    month=month,
                    rules=rules,
                    amounts=amounts,
                    correction=(prev_estimate, prev_actual),
                    extras=billed.get(contract_id, []),
                    extra_rule=extra_rule,
                    extras_cost=getattr(
                        added.get(contract_id), "approved", Decimal("0")
                    ),
                    integration_cost=integration.get(contract_id, Decimal("0")),
                )
            )
            continue
        order = orders.get(basis.order_id) if basis.order_id else None
        out["order_id"] = order.id if order else None
        price = client_price(order)
        rate = price.rate
        history = (
            invoices.get(order.order_group_id, [])
            if order and order.order_group_id
            else []
        )
        template = _history_template(history, month, row["person"])
        # Wzór z reguły (E6.5) wygrywa z historią: u Banku Pocztowego linie nie
        # mają grup zamówień, a opisy w KSeF mają kilka pisowni.
        template = item_name(rules, row["order_number"], row["person"]) or template
        name = template or (
            f"Usługi informatyczne; {row['person']}; nr zamówienia: {row['order_number'] or '—'}"
        )
        items = (
            positions(
                chosen,
                name=name,
                rate=rate,
                overtime_suffix=overtime_suffix,
                currency=price.currency,
            )
            if chosen is not None
            else []
        )
        if prev_estimate is not None and prev_actual is not None:
            correction = _correction(
                prev_estimate,
                prev_actual,
                name=name,
                rate=rate,
                month_label=previous,
                currency=price.currency,
            )
            if correction is not None:
                items.append(correction)
        if chosen is not None:
            items, out["extras_note"] = with_extras(
                items,
                billed.get(contract_id, []),
                rule=extra_rule,
                currency=price.currency,
                name=name,
            )
        cost = (
            Decimal(chosen.amount_cost)
            + getattr(added.get(contract_id), "approved", Decimal("0"))
            if chosen is not None and chosen.amount_cost is not None
            else None
        )
        issued = next((inv for period, inv in history if period == month), None)
        rows.append(
            _finish_row(
                out,
                items,
                price=price,
                cost=cost,
                integration_cost=integration.get(contract_id, Decimal("0")),
                issued=issued,
                template=template,
                chosen=chosen,
                actual=actual,
                rules=rules,
                amounts=amounts,
            )
        )
    hold = None
    if document_kind is not None and not with_kesu:
        unsigned = sum(1 for signed in signed_by_row if not signed)
        if unsigned or not rows:
            hold = {
                "kind": document_kind,
                "label": "Czeka na podpisany protokół odbioru"
                if document_kind == signoffs.PROTOCOL
                else "Czeka na podpisane arkusze zbiorcze: bez podpisu "
                f"{unsigned} z {len(signed_by_row)} osób",
            }
            for row in rows:
                if row["state"] == "ready":
                    row["state"] = "awaiting_signature"
    return {
        "client_id": client_id,
        "client_name": view["client_name"],
        "month": month,
        "can_see_amounts": amounts,
        "signature_hold": hold,
        "time_report": None,
        "deadline": None,
        "rows": rows,
    }


#: Wiersz „Do faktury” z raportu T4T (bez RCP): rodzaj i stan wstrzymania.
TIME_REPORT = "time_report"
AWAITING_T4T = "awaiting_t4t"


def t4t_positions(
    hours: Decimal, order: Optional[ClientOrder], *, name: str
) -> list[Position]:
    """Pozycja z godzin: linia godzinowa w zł — godziny × stawka klienta (jak
    dziś faktury Nordei, „godz.”); inna linia — MD (godziny ÷ 8) × stawka MD."""

    unit = getattr(order.rate_unit, "value", order.rate_unit) if order else None
    currency = ((order.rate_client_currency if order else None) or PLN).upper()
    if order is not None and unit == "hourly" and currency == PLN:
        rate = None if order.rate_client is None else _money(Decimal(order.rate_client))
        return [
            Position(name, "godz.", hours, rate, _money(hours * (rate or 0)), "base")
        ]
    price = client_price(order)
    md = (hours / service.HOURS_PER_MD).quantize(Decimal("0.001"))
    rate = None if price.rate is None else _money(Decimal(price.rate))
    return [
        Position(name, "MD", md, rate, _money(md * (rate or 0)), "base", price.currency)
    ]


ZERO_H = Decimal("0")


def invoiced_hours(invoices: list[ClientSalesInvoice]) -> Optional[Decimal]:
    """Godziny z pozycji „godz.” faktur za miesiąc (z korektami); ``None``,
    gdy żadna faktura nie ma pozycji godzinowej."""

    total: Optional[Decimal] = None
    for invoice in invoices:
        for item in invoice.items or []:
            if not isinstance(item, dict) or not _is_hours(item.get("unit")):
                continue
            try:
                quantity = Decimal(str(item.get("quantity")).replace(",", "."))
            except ArithmeticError:
                continue
            total = (total or Decimal("0")) + quantity
    return total


def _is_hours(unit: Any) -> bool:
    text = str(unit or "").strip().lower()
    return text.startswith("godz") or text in ("h", "hours", "hour")


def hours_item_name(items: list[dict[str, Any]]) -> Optional[str]:
    """Nazwa pozycji godzinowej z faktury („godz.”); faktura za koszty
    podróży (PKP, hotel w „szt.”) do tej samej linii nazwy nie daje."""

    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        if _is_hours(item.get("unit")):
            return str(item["name"]).strip()
    return None


async def _t4t_month(
    db: AsyncSession,
    view: dict[str, Any],
    client_id: int,
    month: str,
    *,
    amounts: bool,
    today: Optional[date],
) -> dict[str, Any]:
    """„Do faktury” klienta z T4T: tylko godziny zatwierdzone w ostatniej wersji."""

    rules = await service.rules_for(db, client_id, month)
    basis = await t4t_invoice.basis(db, client_id, month)
    ids = [r["contract_id"] for r in view["rows"]]
    orders = await t4t_invoice.orders_for(db, ids, month)
    pending_ids = [cid for cid in ids if (h := basis.hours.get(cid)) and h.pending > 0]
    mails = await t4t_invoice.mail_acceptances(db, client_id, month, pending_ids)
    groups = {o.order_group_id for o in orders.values() if o.order_group_id is not None}
    invoices = await _group_invoices(db, groups)
    by_line = await _group_invoices(db, {o.id for o in orders.values()}, by_order=True)
    extra_rule = rules["cl.extra_costs_on_invoice"]
    billed = await settlement_extras.billed_to_client(db, ids, month)
    added = await settlement_extras.expected_by_contract(db, ids, month)
    integration = (
        await service.integration_by_contract(db, ids, month) if amounts else {}
    )
    reason = f"Godziny niezatwierdzone w T4T ({basis.version_label})"
    rows = []
    missing: list[str] = []
    for row in view["rows"]:
        contract_id = row["contract_id"]
        hours = basis.hours.get(contract_id)
        order = orders.get(contract_id)
        out: dict[str, Any] = {
            "contract_id": contract_id,
            "person": row["person"],
            "order_number": row["order_number"],
            "kind": None,
            "currency": PLN,
            "state": "waiting",
            "hold_reason": None,
            "t4t": None,
            "positions": [],
            "net": None,
            "cost": None,
            "integration_cost": None,
            "margin": None,
            "margin_pct": None,
            "template": False,
            "ksef_number": None,
            "invoice_number": None,
            "extras_note": None,
        }
        approved = hours.approved if hours else Decimal("0")
        pending = hours.pending if hours else Decimal("0")
        mail = mails.get(contract_id)
        contract = basis.contracts.get(contract_id)
        billable = approved
        notes: list[str] = []
        state = "ready"
        if pending > 0:
            # Akceptacja managera mailem przechodzi, gdy osoba odeszła z projektu
            # albo okres w T4T jest już zamknięty (Cost Control przyjmuje oba).
            if mail is not None and mail.ok:
                billable = mail.hours or ZERO_H
                notes.append(mail.note)
            else:
                state = AWAITING_T4T
                out["hold_reason"] = (
                    f"{reason}: {t4t_invoice._fmt(pending)} h czeka na akceptację."
                )
                if mail is not None:
                    notes.append(mail.note)
        if order is None:
            history = []
        elif order.order_group_id:
            history = invoices.get(order.order_group_id, [])
        else:
            history = by_line.get(order.id, [])
        issued_now = [inv for period, inv in history if period == month]
        issued = issued_now[0] if issued_now else None
        invoiced = invoiced_hours(issued_now)
        if invoiced is not None and invoiced - billable > time_reports.HOURS_Q:
            # Nordea odrzuca fakturę ponad godziny zatwierdzone (IX: 18 faktur).
            notes.append(
                f"Wystawiona faktura ma {t4t_invoice._fmt(invoiced)} h, zatwierdzone "
                f"w T4T {t4t_invoice._fmt(billable)} h: klient może ją odrzucić, "
                "potrzebna korekta."
            )
        out["t4t"] = {
            "approved": f"{approved:.2f}",
            "pending": f"{pending:.2f}",
            "billed": f"{billable:.2f}",
            "invoiced": None if invoiced is None else f"{invoiced:.2f}",
            "notes": notes,
        }
        if issued is None and (billable <= 0 or state == AWAITING_T4T):
            missing.append(row["person"])
        if billable <= 0:
            out["hold_reason"] = out["hold_reason"] or (
                f"Brak zatwierdzonych godzin w T4T ({basis.version_label})"
            )
            if issued is not None:
                out.update(
                    state="issued",
                    ksef_number=issued.ksef_number,
                    invoice_number=issued.invoice_number,
                )
            rows.append(out)
            continue
        template = next(
            (
                name
                for period, inv in reversed(history)
                if period < month and (name := hours_item_name(inv.items or []))
            ),
            None,
        )
        template = item_name(rules, row["order_number"], row["person"]) or template
        name = template or (
            f"Usługi informatyczne; {row['person']}; nr zamówienia: {row['order_number'] or '—'}"
        )
        items = t4t_positions(billable, order, name=name)
        currency = items[0].currency
        items, out["extras_note"] = with_extras(
            items,
            billed.get(contract_id, []),
            rule=extra_rule,
            currency=currency,
            name=name,
        )
        net = sum((p.net for p in items), Decimal("0"))
        cost_hours = (
            time_reports._hours_to_amount(contract, billable, month)
            if contract is not None
            else None
        )
        cost = (
            cost_hours + getattr(added.get(contract_id), "approved", Decimal("0"))
            if cost_hours is not None
            else None
        )
        out.update(
            kind=TIME_REPORT,
            currency=currency,
            state="issued" if issued else state,
            positions=[p.as_dict() for p in items]
            if amounts
            else [{**p.as_dict(), "unit_price": None, "net": None} for p in items],
            template=template is not None,
            ksef_number=issued.ksef_number if issued else None,
            invoice_number=issued.invoice_number if issued else None,
        )
        if amounts:
            out["net"] = f"{net:.2f}"
            if cost is not None:
                to_pln = client_price(order).to_pln if currency != PLN else Decimal("1")
                extra = integration.get(contract_id, Decimal("0"))
                net_pln = _money(net * to_pln)
                margin = net_pln - cost - extra
                out["cost"] = f"{cost:.2f}"
                out["integration_cost"] = f"{extra:.2f}" if extra else None
                out["margin"] = f"{margin:.2f}"
                out["margin_pct"] = (
                    None if net_pln == 0 else f"{margin / net_pln * 100:.1f}"
                )
        rows.append(out)
    return {
        "client_id": client_id,
        "client_name": view["client_name"],
        "month": month,
        "can_see_amounts": amounts,
        "signature_hold": None,
        "time_report": {
            "version_id": basis.version_id,
            "received_on": basis.received_on.isoformat() if basis.received_on else None,
            "label": basis.version_label,
        },
        "deadline": t4t_invoice.deadline_warning(month, today, rules, missing),
        "rows": rows,
    }


def with_extras(
    items: list[Position],
    billed: list[Any],
    *,
    rule: dict[str, Any],
    currency: str,
    name: str,
) -> tuple[list[Position], Optional[str]]:
    """Dodatki fakturowane klientowi w pozycjach (``cl.extra_costs_on_invoice``).

    Parametr ``item`` z nazwą = osobna pozycja; pusty = jedna pozycja „usługa
    z kosztami” (1 × suma, jak faktura główna Aliora z KEŚU). Bez stawki na
    pozycji zasadniczej koszt idzie osobno, żeby nie udawał całej usługi.
    Zwraca pozycje i uwagę dla Finansów, gdy dodatek czeka poza fakturą."""

    if not billed:
        return items, None
    total = _money(sum((Decimal(e.amount) for e in billed), Decimal("0")))
    if rule["level"] == "off":
        return items, (
            f"Dodatek do faktury klienta ({settlement_extras.pln(total)}) czeka: "
            "reguła „Koszty dodatkowe na fakturze głównej” jest wyłączona."
        )
    if currency != PLN:
        return items, (
            f"Dodatek w zł ({settlement_extras.pln(total)}) nie wchodzi do faktury "
            f"w {currency} — dolicz go ręcznie."
        )
    label = str(rule["params"].get("item") or "").strip()
    if label:
        return [
            *items,
            Position(label, "usł.", Decimal("1"), total, total, "extra"),
        ], None
    base = next((p for p in items if p.kind == "base"), None)
    if base is None or base.unit_price is None:
        return [
            *items,
            Position(
                f"{name}; koszty dodatkowe",
                "usł.",
                Decimal("1"),
                total,
                total,
                "extra",
            ),
        ], None
    merged_net = _money(base.net + total)
    merged = Position(
        base.name, "usł.", Decimal("1"), merged_net, merged_net, "base", currency
    )
    return [merged if p is base else p for p in items], None


def copy_text(rows: list[dict[str, Any]]) -> str:
    """Pozycje do wklejenia w program do faktur: kolumny oddzielone tabulatorem."""

    lines = []
    for row in rows:
        for p in row["positions"]:
            lines.append(
                "\t".join(
                    [
                        p["name"],
                        p["quantity"].replace(".", ","),
                        p["unit"],
                        (p["unit_price"] or "").replace(".", ","),
                        (p["net"] or "").replace(".", ","),
                    ]
                )
            )
    return "\n".join(lines)


def _safe(text: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("_")[:80] or "plik"


async def attachments_zip(
    db: AsyncSession,
    client_id: int,
    month: str,
    *,
    contract_id: Optional[int] = None,
    issued_only: bool = False,
) -> tuple[bytes, int]:
    """Zip z plikami RCP i maili rozliczeń przyjętych w miesiącu (E5.2).

    Przy regule ``cl.attachment_name`` RCP nazywa się numerem KSeF faktury do
    klienta (gdy już jest), reszta plików dostaje ten sam przedrostek.
    ``contract_id`` — jedna osoba; ``issued_only`` — tylko osoby z wystawioną
    fakturą, czyli z nazwą z numeru KSeF (pytanie rozliczeń 10.11). Zwraca
    zawartość i liczbę plików."""

    data = await invoice_month(db, client_id, month, amounts=False)
    rules = await service.rules_for(db, client_id, month)
    by_ksef = rules["cl.attachment_name"]["level"] != "off"
    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in data["rows"]:
            if row["kind"] is None:
                continue
            if contract_id is not None and row["contract_id"] != contract_id:
                continue
            if issued_only and not row["ksef_number"]:
                continue
            s = await service._settlement(
                db, row["contract_id"], month, kind=row["kind"]
            )
            if s is None:
                continue
            docs = await service._month_reports(
                db, row["contract_id"], month, kind=s.kind
            )
            # Najpierw RCP (nazwa bez przyrostka), potem maile i reszta.
            docs.sort(
                key=lambda d: (
                    d.mime not in service.RCP_MIMES,
                    d.id != s.report_document_id,
                    d.created_at,
                )
            )
            prefix = (
                row["ksef_number"]
                if by_ksef and row["ksef_number"]
                else f"{row['order_number'] or 'bez_zamowienia'}_{row['person']}"
            )
            for index, doc in enumerate(docs):
                try:
                    content = portal_documents.path_for(doc.file_path).read_bytes()
                except OSError:
                    continue
                ext = EXTENSIONS.get(doc.mime, "")
                name = _safe(prefix) + ("" if index == 0 else f"_{index}") + ext
                archive.writestr(name, content)
                count += 1
    return buffer.getvalue(), count


async def estimates(
    db: AsyncSession, client_id: int, month: str, *, amounts: bool
) -> dict[str, Any]:
    """Ekran „<poprzedni miesiąc> i plan <miesiąca>” (E5.4): stan poprzedniego
    miesiąca, reszta puli po nim, plan i ile pójdzie na fakturę."""

    view = await service.month_view(db, client_id, month, amounts=amounts)
    previous = _previous(month)
    ids = [r["contract_id"] for r in view["rows"]]
    found = (
        (
            await db.scalars(
                select(ClientSettlement).where(
                    ClientSettlement.contract_id.in_(ids),
                    or_(
                        and_(
                            ClientSettlement.period_month == previous,
                            ClientSettlement.kind == service.ACTUAL,
                        ),
                        and_(
                            ClientSettlement.period_month == month,
                            ClientSettlement.kind == service.ESTIMATE,
                        ),
                    ),
                )
            )
        ).all()
        if ids
        else []
    )
    by_key = {(s.contract_id, s.kind): s for s in found}
    order_ids = {s.order_id for s in found if s.order_id is not None}
    orders = (
        {
            o.id: o
            for o in (
                await db.scalars(
                    select(ClientOrder).where(ClientOrder.id.in_(order_ids))
                )
            ).all()
        }
        if order_ids
        else {}
    )

    def invoice_amount(s: Optional[ClientSettlement]) -> tuple[Optional[str], str]:
        """Przychód w walucie faktury klienta (w bazie jest w zł)."""

        price = client_price(orders.get(s.order_id) if s and s.order_id else None)
        if s is None or s.amount_revenue is None:
            return None, price.currency
        return f"{_money(Decimal(s.amount_revenue) / price.to_pln):.2f}", price.currency

    rows = []
    for row in view["rows"]:
        before = by_key.get((row["contract_id"], service.ACTUAL))
        plan = by_key.get((row["contract_id"], service.ESTIMATE))
        remaining = None
        if before is not None and before.status == "accepted":
            remaining = next(
                (
                    c.get("remaining_after")
                    for c in before.checks or []
                    if isinstance(c, dict) and "remaining_after" in c
                ),
                None,
            )
        stored_over = service.md_over(plan) if plan is not None else None
        over = f"{stored_over:.3f}" if stored_over else None
        # Dwie osobne faktury do klienta: za poprzedni miesiąc i za plan
        # (rozliczenia 10.11 — nie łączymy na jednej).
        previous_amount, currency = invoice_amount(
            before if before is not None and before.status == "accepted" else None
        )
        plan_amount, plan_currency = invoice_amount(plan)
        previous_invoice = previous_amount if amounts else None
        plan_invoice = plan_amount if amounts else None
        rows.append(
            {
                "contract_id": row["contract_id"],
                "person": row["person"],
                "order_number": row["order_number"],
                "previous_status": before.status if before else "missing",
                "previous_md": None
                if before is None or before.md_charged is None
                else f"{before.md_charged:.3f}",
                "remaining_after_previous": remaining,
                "plan_status": plan.status if plan else "missing",
                "plan_md": None
                if plan is None or plan.md_charged is None
                else f"{plan.md_charged:.3f}",
                "over_pool": over,
                "previous_invoice": previous_invoice,
                "plan_invoice": plan_invoice,
                "currency": plan_currency if plan is not None else currency,
            }
        )
    # Najpierw osoby z planem, potem z przyjętym poprzednim miesiącem.
    rows.sort(
        key=lambda r: (
            r["plan_status"] == "missing",
            r["previous_status"] != "accepted",
        )
    )
    return {
        "client_id": client_id,
        "client_name": view["client_name"],
        "month": month,
        "previous_month": previous,
        "enabled": await service.estimate_allowed(db, client_id, month),
        "can_see_amounts": amounts,
        "rows": rows,
    }
