"""Rabat od obrotu rocznego: obrót netto z faktur sprzedaży i rabat wg progów.

Obrót = suma netto faktur sprzedaży z KSeF wystawionych w okresie (po dacie
wystawienia), razem z korektami (korekta niesie różnicę, także ujemną)
i fakturami zaliczkowymi. Rabat liczy się od obrotu w walucie progów
(parametr „Waluta progów”): faktury w innej walucie przeliczamy kursem średnim
NBP z ostatniej tabeli przed datą sprzedaży, a bez daty sprzedaży — przed
datą wystawienia (decyzja Artura 16.11.2026, ta sama co przy nocie rabatowej
w ``client_invoicing``; progi Nordei są w EUR, faktury w PLN). Faktura bez kursu w ``fx_rates`` wypada
z obrotu i trafia do kontroli.

Progi: ``[{"up_to": 15000000, "rate": 2.5}, {"up_to": null, "rate": 3}]`` —
``up_to`` to górna granica włącznie, ``null`` = bez górnej granicy, ``rate``
w procentach. Kolejność z formularza nie ma znaczenia (sortujemy po granicy).

* z „Progowo” (domyślnie): każda część obrotu po stawce swojego progu — obrót
  do progu po niższej stawce, nadwyżka po wyższej. Tak liczy się rabat Nordei
  (umowa ramowa, Appendix 6; decyzja Artura 16.11.2026 po lekturze umowy);
* bez „Progowo”: cały obrót po stawce progu, w który wpada (dla umów, które
  wprost tak mówią).

Obrót ponad najwyższą granicą, gdy żaden próg nie jest otwarty, liczy się po
stawce ostatniego progu, a podgląd to zgłasza. Ujemny obrót (same korekty)
daje rabat 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.client_data import (
    InvoiceRow,
    cents,
    invoice_type_label,
    sales_invoices,
    sheet_amount,
    totals_by_currency,
)
from app.services.fx_service import rates_to_pln_by_date
from app.services.client_reports.registry import (
    Generator,
    ParamField,
    ReportContext,
    ReportData,
    Sheet,
    SummaryLine,
    format_amount,
    param,
    register,
)

HUNDRED = Decimal(100)
MANUAL_EXCLUSION_NOTE = (
    "Koszty podróży i faktury nieusługowe (refaktury) trzeba wyłączyć ręcznie, "
    "jeśli umowa liczy rabat tylko od usług."
)


@dataclass(frozen=True)
class RebateBand:
    lower: Decimal
    upper: Optional[Decimal]
    rate: Decimal
    base: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Rebate:
    turnover: Decimal
    #: Stawka efektywna w procentach (przy „Progowo” średnia ważona).
    rate: Decimal
    amount: Decimal
    bands: tuple[RebateBand, ...]
    above_top: bool


def _sorted_tiers(
    tiers: Sequence[Mapping[str, Any]],
) -> list[tuple[Optional[Decimal], Decimal]]:
    parsed = [
        (
            None if t.get("up_to") is None else Decimal(str(t["up_to"])),
            Decimal(str(t["rate"])),
        )
        for t in tiers
    ]
    return sorted(parsed, key=lambda t: (t[0] is None, t[0] or Decimal(0)))


def compute_rebate(
    turnover: Decimal, tiers: Sequence[Mapping[str, Any]], *, marginal: bool = False
) -> Optional[Rebate]:
    """Rabat od obrotu; ``None`` bez progów."""
    ordered = _sorted_tiers(tiers)
    if not ordered:
        return None
    base = max(Decimal(turnover), Decimal(0))
    above_top = ordered[-1][0] is not None and base > ordered[-1][0]

    if not marginal:
        lower = Decimal(0)
        chosen = ordered[-1]
        for up_to, rate in ordered:
            if up_to is None or base <= up_to:
                chosen = (up_to, rate)
                break
            lower = up_to
        if above_top:
            lower = ordered[-2][0] if len(ordered) > 1 else Decimal(0)
        amount = cents(base * chosen[1] / HUNDRED)
        band = RebateBand(lower, chosen[0], chosen[1], base, amount)
        return Rebate(Decimal(turnover), chosen[1], amount, (band,), above_top)

    bands: list[RebateBand] = []
    lower = Decimal(0)
    for index, (up_to, rate) in enumerate(ordered):
        last = index == len(ordered) - 1
        upper = None if (up_to is None or last) else up_to
        portion = base - lower if upper is None else min(base, upper) - lower
        if portion > 0:
            bands.append(
                RebateBand(lower, up_to, rate, portion, cents(portion * rate / HUNDRED))
            )
        if up_to is None:
            break
        lower = up_to
    amount = sum((b.amount for b in bands), Decimal(0))
    rate = (
        (amount / base * HUNDRED).quantize(Decimal("0.0001")) if base else ordered[0][1]
    )
    return Rebate(Decimal(turnover), rate, amount, tuple(bands), above_top)


@dataclass(frozen=True)
class Turnover:
    currency: str
    count: int
    corrections: int
    net: Decimal


def turnover_by_currency(invoices: Sequence[InvoiceRow]) -> list[Turnover]:
    totals = totals_by_currency((i.currency, i.net_amount) for i in invoices)
    out = []
    for currency, net in totals.items():
        same = [i for i in invoices if (i.currency or "—").upper() == currency]
        out.append(
            Turnover(currency, len(same), sum(1 for i in same if i.is_correction), net)
        )
    return out


@dataclass(frozen=True)
class ConvertedTurnover:
    """Obrót w walucie progów: faktury w tej walucie + przeliczone kursem NBP."""

    currency: str
    amount: Decimal
    #: Ile faktur przeliczono kursem (inna waluta niż progów).
    converted: int
    #: Waluty bez kursu w ``fx_rates`` — te faktury wypadły z obrotu.
    missing: tuple[str, ...]


def fx_day(day: date) -> date:
    """Granica kursu: ostatnia tabela NBP z dnia przed ``day``."""
    return day - timedelta(days=1)


def rate_day(invoice: InvoiceRow) -> Optional[date]:
    """Dzień kursu faktury: przed datą sprzedaży, bez niej — przed wystawieniem."""
    day = invoice.sale_date or invoice.issue_date
    return fx_day(day) if day else None


RatesByDate = Mapping[date, Mapping[str, Optional[Decimal]]]


def convert_turnover(
    invoices: Sequence[InvoiceRow], currency: str, rates: RatesByDate
) -> ConvertedTurnover:
    """Suma netto w ``currency``; ``rates`` to kurs waluty → PLN per dzień kursu."""
    target = currency.upper()
    total = Decimal(0)
    converted = 0
    missing: list[str] = []
    for invoice in invoices:
        source = (invoice.currency or "PLN").upper()
        if source == target:
            total += invoice.net_amount
            continue
        day = rate_day(invoice)
        snapshot = rates.get(day, {}) if day else {}
        source_rate, target_rate = snapshot.get(source), snapshot.get(target)
        if not source_rate or not target_rate:
            if source not in missing:
                missing.append(source)
            continue
        total += invoice.net_amount * source_rate / target_rate
        converted += 1
    return ConvertedTurnover(target, cents(total), converted, tuple(missing))


async def turnover_in(
    db: AsyncSession, invoices: Sequence[InvoiceRow], currency: str
) -> ConvertedTurnover:
    target = currency.upper()
    needed: dict[date, set[str]] = {}
    for invoice in invoices:
        source = (invoice.currency or "PLN").upper()
        day = rate_day(invoice)
        if source != target and day is not None:
            needed.setdefault(day, set()).update({source, target})
    rates = await rates_to_pln_by_date(db, needed) if needed else {}
    return convert_turnover(invoices, target, rates)


def turnover_checks(converted: ConvertedTurnover) -> list[str]:
    checks = []
    if converted.converted:
        checks.append(
            f"{converted.converted} faktur w innej walucie przeliczono na {converted.currency} "
            "kursem średnim NBP sprzed daty sprzedaży — sprawdź, czy umowa nie podaje innego kursu."
        )
    if converted.missing:
        checks.append(
            f"Brak kursu NBP dla {', '.join(converted.missing)} — te faktury nie weszły do obrotu; "
            "uzupełnij kursy (Ustawienia → Kursy walut) albo dolicz ręcznie."
        )
    return checks


#: Pierwsza faktura później niż tyle dni po początku okresu = okres niepełny.
INCOMPLETE_GRACE_DAYS = 31


def incomplete_from(first_invoice: date, period_start: date) -> bool:
    """Czy faktury w NEXUSIE zaczynają się wyraźnie po początku okresu.

    Pobieranie z KSeF cofa się tylko kilka miesięcy wstecz, więc rabat za cały
    rok liczony z tabeli faktur bywa zaniżony — trzeba to powiedzieć przed
    wysłaniem, nie zgadywać brakujących kwot.
    """
    return (first_invoice - period_start).days > INCOMPLETE_GRACE_DAYS


async def first_invoice_date(db: AsyncSession, client_id: int) -> Optional[date]:
    return await db.scalar(
        text("SELECT min(issue_date) FROM client_sales_invoices WHERE client_id = :c"),
        {"c": client_id},
    )


def rate_text(rate: Decimal) -> str:
    return f"{rate.normalize():f}".replace(".", ",") + "%"


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    currency = (param(ctx, GENERATOR, "currency") or "PLN").strip().upper() or "PLN"
    tiers = param(ctx, GENERATOR, "tiers") or []
    marginal = bool(param(ctx, GENERATOR, "marginal"))

    invoices = await sales_invoices(db, ctx.client_id, period.start, period.end)
    turnovers = turnover_by_currency(invoices)
    converted = await turnover_in(db, invoices, currency)
    base = converted.amount
    rebate = compute_rebate(base, tiers, marginal=marginal)

    label = f"Obrót netto ({currency}" + (
        ", z przeliczeniem NBP)" if converted.converted else ")"
    )
    lines = [SummaryLine(label, format_amount(base), True)]
    lines += [
        SummaryLine(
            f"w tym faktury w {t.currency} (netto {t.currency})", format_amount(t.net)
        )
        for t in turnovers
        if t.currency != currency
    ]
    if rebate:
        lines.append(
            SummaryLine(
                "Stawka rabatu" + (" (efektywna)" if marginal else ""),
                rate_text(rebate.rate),
            )
        )
        lines.append(
            SummaryLine(
                f"Kwota rabatu ({currency})", format_amount(rebate.amount), True
            )
        )

    checks: list[str] = [MANUAL_EXCLUSION_NOTE]
    if not tiers:
        checks.append(
            "Definicja nie ma progów rabatu — uzupełnij je w ustawieniach raportu."
        )
    checks += turnover_checks(converted)
    if rebate and rebate.above_top:
        checks.append(
            "Obrót przekracza najwyższy próg — przyjęto stawkę ostatniego progu."
        )
    if any(i.invoice_type == "ZAL" for i in invoices):
        checks.append(
            "W okresie są faktury zaliczkowe — sprawdź, czy faktura końcowa nie dubluje kwoty."
        )
    if not invoices:
        checks.append(
            "Brak faktur sprzedaży wystawionych w okresie — sprawdź pobranie z KSeF."
        )
    first = await first_invoice_date(db, ctx.client_id)
    if first is not None and incomplete_from(first, period.start):
        checks.append(
            f"Faktury z KSeF są w NEXUSIE od {first:%d.%m.%Y} — obrót za wcześniejsze "
            "miesiące okresu jest niepełny; uzupełnij pobranie z KSeF przed wysłaniem."
        )

    sheets = [
        Sheet(
            "Obrót",
            ("Waluta", "Liczba faktur", "w tym korekty", "Obrót netto"),
            tuple(
                (t.currency, t.count, t.corrections, sheet_amount(t.net))
                for t in turnovers
            ),
            widths=(10, 14, 14, 18),
            note=f"Rabat liczony od obrotu w {currency} (inne waluty kursem NBP sprzed daty "
            f"sprzedaży). {MANUAL_EXCLUSION_NOTE}",
        )
    ]
    if rebate:
        sheets.append(
            Sheet(
                "Rabat",
                ("Próg od", "Próg do", "Stawka %", "Obrót w progu", "Rabat"),
                tuple(
                    (
                        sheet_amount(b.lower),
                        sheet_amount(b.upper),
                        float(b.rate),
                        sheet_amount(b.base),
                        sheet_amount(b.amount),
                    )
                    for b in rebate.bands
                ),
                widths=(16, 16, 10, 18, 16),
                note="Każda część obrotu po stawce swojego progu."
                if marginal
                else "Cały obrót po stawce progu, w który wpada.",
            )
        )
    sheets.append(
        Sheet(
            "Faktury",
            ("Numer faktury", "Data wystawienia", "Rodzaj", "Waluta", "Netto"),
            tuple(
                (
                    i.invoice_number,
                    i.issue_date,
                    invoice_type_label(i),
                    i.currency,
                    sheet_amount(i.net_amount),
                )
                for i in invoices
            ),
            widths=(24, 16, 12, 8, 16),
        )
    )
    return ReportData(lines=tuple(lines), sheets=tuple(sheets), checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="annual_spend",
        label="Rabat od obrotu rocznego",
        description="Obrót netto z faktur sprzedaży w okresie (z korektami) i rabat wg progów z umowy.",
        rhythms=("annual",),
        loader=_load,
        needs_amounts=True,
        params=(
            ParamField(
                "currency",
                "Waluta progów",
                "text",
                "PLN",
                "Faktury w innej walucie przeliczamy kursem średnim NBP sprzed daty sprzedaży.",
            ),
            ParamField(
                "tiers",
                "Progi rabatu",
                "tiers",
                None,
                "Górna granica obrotu (puste = bez granicy) i stawka rabatu w %.",
            ),
            ParamField(
                "marginal",
                "Progowo (każdy próg osobno)",
                "bool",
                True,
                "Włączone (domyślnie, tak liczy Nordea): obrót do progu po niższej stawce, "
                "nadwyżka po wyższej. Wyłącz tylko, gdy umowa daje stawkę progu od całego obrotu.",
            ),
        ),
    )
)
