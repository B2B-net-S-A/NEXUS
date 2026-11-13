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

Paczka załączników (E5.2): pliki RCP i maile miesiąca w zipie; przy regule
``cl.attachment_name`` plik RCP nosi numer KSeF faktury do klienta.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import ClientSettlement
from app.services.client_settlements import kesu, service, signoffs
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
    kind: str  # base · overtime · onboarding · correction
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
    return value.quantize(MONEY)


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
    db: AsyncSession, group_ids: set[int]
) -> dict[int, list[tuple[str, ClientSalesInvoice]]]:
    """Faktury do klienta per grupa zamówienia: (miesiąc usługi, faktura)."""

    if not group_ids:
        return {}
    rows = await db.execute(
        select(
            ClientSalesInvoiceLink.order_group_id,
            ClientSalesInvoiceLink.period_year,
            ClientSalesInvoiceLink.period_month,
            ClientSalesInvoice,
        )
        .join(
            ClientSalesInvoice,
            ClientSalesInvoice.id == ClientSalesInvoiceLink.invoice_id,
        )
        .where(ClientSalesInvoiceLink.order_group_id.in_(group_ids))
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


def extra_costs(
    s: ClientSettlement,
    items: list[Position],
    rules: dict[str, dict[str, Any]],
    *,
    name: str,
    currency: str = PLN,
) -> list[Position]:
    """Koszty dodatkowe z KEŚU na fakturze głównej (``cl.extra_costs_on_invoice``, E6.3).

    KEŚU podaje koszty brutto i liczy „Razem w PLN BRUTTO” razem z usługą, więc
    netto kosztów = brutto / 1,23 (brutto faktury = „Razem” z KEŚU). Parametr
    ``item`` pusty = jedna pozycja na całość, nazwa = osobna pozycja.
    """

    rule = rules["cl.extra_costs_on_invoice"]
    data = service.meta_of(s).get("kesu")
    if rule["level"] == "off" or not isinstance(data, dict) or currency != PLN:
        return items
    gross = Decimal(str(data.get("extra_costs") or "0"))
    if gross <= 0:
        return items
    net = _money(gross / kesu.VAT)
    label = str(rule["params"].get("item") or "").strip()
    if label:
        return [*items, Position(label, "usł.", Decimal("1"), net, net, "extra_costs")]
    base = next((p for p in items if p.kind == "base"), None)
    if base is None or base.unit_price is None:
        # Bez stawki na linii zamówienia nie da się podać jednej pozycji
        # „usługa z kosztami”: koszty idą osobno, kwota usługi czeka na stawkę.
        return [
            *items,
            Position(
                f"{name}; koszty dodatkowe",
                "usł.",
                Decimal("1"),
                net,
                net,
                "extra_costs",
            ),
        ]
    total = base.net + net
    merged = Position(base.name, "usł.", Decimal("1"), total, total, "base", currency)
    return [merged if p is base else p for p in items]


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
    db: AsyncSession, client_id: int, month: str, *, amounts: bool
) -> dict[str, Any]:
    """Wiersze „Do faktury dla klienta” za miesiąc klienta."""

    view = await service.month_view(db, client_id, month, amounts=amounts)
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
    order_ids = {s.order_id for s in settlements if s.order_id is not None}
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
        }
        prev_estimate = by_key.get((contract_id, previous, service.ESTIMATE))
        prev_actual = by_key.get((contract_id, previous, service.ACTUAL))
        basis = chosen or (prev_estimate if prev_actual is not None else None)
        if basis is None:
            rows.append(out)
            continue
        if chosen is None:
            out["kind"] = service.ACTUAL
        order = orders.get(basis.order_id) if basis.order_id else None
        price = client_price(order)
        rate = price.rate
        history = (
            invoices.get(order.order_group_id, [])
            if order and order.order_group_id
            else []
        )
        template = next(
            (
                base_name(inv.items or [], row["person"])
                for period, inv in reversed(history)
                if period < month and base_name(inv.items or [], row["person"])
            ),
            None,
        )
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
        if chosen is not None and chosen.kind == service.ACTUAL:
            items = extra_costs(
                chosen, items, rules, name=name, currency=price.currency
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
        net = sum((p.net for p in items), Decimal("0"))
        cost = (
            Decimal(chosen.amount_cost)
            if chosen is not None and chosen.amount_cost is not None
            else None
        )
        issued = next((inv for period, inv in history if period == month), None)
        out.update(
            currency=price.currency,
            state="issued"
            if issued
            else "awaiting_signature"
            if service.waits_for_signature(chosen, rules)
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
                extra = integration.get(contract_id, Decimal("0"))
                net_pln = _money(net * price.to_pln)
                margin = net_pln - cost - extra
                out["cost"] = f"{cost:.2f}"
                out["integration_cost"] = f"{extra:.2f}" if extra else None
                out["margin"] = f"{margin:.2f}"
                out["margin_pct"] = (
                    None if net_pln == 0 else f"{margin / net_pln * 100:.1f}"
                )
        rows.append(out)
    hold = None
    if document_kind is not None and not with_kesu:
        unsigned = sum(1 for signed in signed_by_row if not signed)
        if unsigned or not rows:
            hold = {
                "kind": document_kind,
                "label": "Czeka na podpisany protokół odbioru"
                if document_kind == signoffs.PROTOCOL
                else "Czeka na podpisane arkusze zbiorcze: bez podpisu "
                f"{unsigned} z {len(rows)} osób",
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
        "rows": rows,
    }


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
