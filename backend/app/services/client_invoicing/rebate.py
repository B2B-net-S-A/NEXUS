"""Rabat roczny od obrotu klienta (spend discount) — warunki jako dane, stan narastająco.

Warunki leżą w ustawieniach wystawiania przy kliencie
(``app_settings['client_invoice_issue'].clients[<id>].rebate``) i wpisują je
Finanse z umowy ramowej; w kodzie nie ma ani progów, ani stawek::

    {"threshold_currency": "EUR",
     "periods": [{"from_year": 2026,
                  "tiers": [{"up_to": 15000000, "rate": 2.5},
                            {"up_to": null, "rate": 3}]}],
     "exclude_words": ["podróż"]}

* ``periods`` — od którego roku obowiązują jakie progi (aneks zmienia progi od
  roku, w którym wszedł: decyzja Artura 16.11.2026, „cały rok wg aneksu”);
* ``tiers`` — ``up_to`` to górna granica obrotu rocznego WŁĄCZNIE w walucie
  progu, ``null`` = bez granicy (dokładnie jeden, ostatni); ``rate`` w procentach;
* stawkę wybiera obrót całego roku i dotyczy ona CAŁEGO obrotu, nie tylko
  nadwyżki (decyzja Artura 16.11.2026);
* obrót = faktury sprzedaży z KSeF wystawione w roku kalendarzowym (po dacie
  wystawienia) razem z korektami; faktura, której każda pozycja zawiera słowo
  z ``exclude_words`` (podróże, refaktury), jest poza obrotem;
* próg w innej walucie niż faktura: każda faktura po kursie średnim NBP
  z ostatniego dnia z tabelą przed datą sprzedaży (decyzja Artura 16.11.2026);
  brak kursu = faktura poza obrotem progu i ostrzeżenie, nigdy kurs 1:1;
* rabat nie jest pozycją faktury: rozlicza go zbiorcza faktura korygująca za
  rok, wystawiana do 31 stycznia następnego roku (umowa i decyzja Artura
  16.11.2026). Ten moduł tylko liczy i pokazuje stan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.services import fx_service
from app.services.client_sales_invoices_schema import CURRENCIES

HUNDRED = Decimal(100)
CENT = Decimal("0.01")
YEARS = (2020, 2100)
MAX_PERIODS = 10
MAX_TIERS = 6
MAX_WORDS = 20
WORD_LEN = (2, 40)


class RebateTermsError(ValueError):
    """Złe warunki rabatu — komunikat dla Finansów."""


@dataclass(frozen=True)
class Tier:
    up_to: Optional[Decimal]
    rate: Decimal


@dataclass(frozen=True)
class Period:
    from_year: int
    tiers: tuple[Tier, ...]


@dataclass(frozen=True)
class Terms:
    threshold_currency: str
    periods: tuple[Period, ...]
    exclude_words: tuple[str, ...]


def _number(raw: Any, label: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise RebateTermsError(f"{label}: podaj liczbę.")
    try:
        value = Decimal(str(raw).replace(",", ".").strip())
    except ArithmeticError as exc:
        raise RebateTermsError(f"{label}: podaj liczbę.") from exc
    if not value.is_finite():
        raise RebateTermsError(f"{label}: podaj liczbę.")
    return value


def _tiers(raw: Any, year: int) -> tuple[Tier, ...]:
    where = f"Rabat od {year}"
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TIERS:
        raise RebateTermsError(f"{where}: od 1 do {MAX_TIERS} progów.")
    tiers = []
    for item in raw:
        if not isinstance(item, dict):
            raise RebateTermsError(f"{where}: zły próg.")
        rate = _number(item.get("rate"), f"{where}, stawka")
        if not Decimal(0) <= rate <= HUNDRED:
            raise RebateTermsError(f"{where}: stawka rabatu od 0 do 100%.")
        up_to = None
        if item.get("up_to") not in (None, ""):
            up_to = _number(item.get("up_to"), f"{where}, granica progu")
            if up_to <= 0:
                raise RebateTermsError(f"{where}: granica progu musi być dodatnia.")
        tiers.append(Tier(up_to, rate))
    tiers.sort(key=lambda t: (t.up_to is None, t.up_to or Decimal(0)))
    if sum(1 for t in tiers if t.up_to is None) != 1:
        raise RebateTermsError(
            f"{where}: dokładnie jeden próg bez górnej granicy (ostatni)."
        )
    bounds = [t.up_to for t in tiers if t.up_to is not None]
    if len(set(bounds)) != len(bounds):
        raise RebateTermsError(f"{where}: dwa progi z tą samą granicą.")
    return tuple(tiers)


def parse_terms(raw: Any) -> Optional[Terms]:
    """Warunki z formularza albo z bazy; ``None`` = klient bez rabatu."""

    if raw in (None, {}, ""):
        return None
    if not isinstance(raw, dict):
        raise RebateTermsError("Rabat: złe dane.")
    currency = str(raw.get("threshold_currency") or "").upper()
    if currency not in CURRENCIES:
        raise RebateTermsError("Rabat: waluta progu PLN, EUR albo USD.")
    periods_raw = raw.get("periods")
    if not isinstance(periods_raw, list) or not 1 <= len(periods_raw) <= MAX_PERIODS:
        raise RebateTermsError(
            f"Rabat: od 1 do {MAX_PERIODS} okresów (rok początku i progi)."
        )
    periods = []
    for item in periods_raw:
        if not isinstance(item, dict):
            raise RebateTermsError("Rabat: zły okres.")
        year = item.get("from_year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise RebateTermsError("Rabat: rok początku okresu musi być liczbą.")
        if not YEARS[0] <= year <= YEARS[1]:
            raise RebateTermsError(f"Rabat: rok początku od {YEARS[0]} do {YEARS[1]}.")
        periods.append(Period(year, _tiers(item.get("tiers"), year)))
    years = [p.from_year for p in periods]
    if len(set(years)) != len(years):
        raise RebateTermsError("Rabat: dwa okresy od tego samego roku.")
    words_raw = raw.get("exclude_words") or []
    if not isinstance(words_raw, list) or len(words_raw) > MAX_WORDS:
        raise RebateTermsError(f"Rabat: do {MAX_WORDS} słów wyłączających.")
    words = []
    for word in words_raw:
        text = " ".join(str(word or "").split()).lower()
        if not text:
            continue
        if not WORD_LEN[0] <= len(text) <= WORD_LEN[1]:
            raise RebateTermsError(
                f"Rabat: słowo wyłączające od {WORD_LEN[0]} do {WORD_LEN[1]} znaków."
            )
        words.append(text)
    return Terms(
        currency,
        tuple(sorted(periods, key=lambda p: p.from_year)),
        tuple(dict.fromkeys(words)),
    )


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def to_json(terms: Terms) -> dict[str, Any]:
    return {
        "threshold_currency": terms.threshold_currency,
        "periods": [
            {
                "from_year": period.from_year,
                "tiers": [
                    {
                        "up_to": None
                        if tier.up_to is None
                        else _json_number(tier.up_to),
                        "rate": _json_number(tier.rate),
                    }
                    for tier in period.tiers
                ],
            }
            for period in terms.periods
        ],
        "exclude_words": list(terms.exclude_words),
    }


def tiers_for(terms: Terms, year: int) -> Optional[tuple[Tier, ...]]:
    """Progi obowiązujące w roku: ostatni okres, który zaczął się najpóźniej w tym roku."""

    chosen = None
    for period in terms.periods:
        if period.from_year <= year:
            chosen = period.tiers
    return chosen


def tier_for(turnover: Decimal, tiers: Sequence[Tier]) -> Tier:
    """Próg dla obrotu rocznego; jego stawka dotyczy CAŁEGO obrotu."""

    for tier in tiers:
        if tier.up_to is None or turnover <= tier.up_to:
            return tier
    return tiers[-1]


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def excluded(items: Sequence[dict[str, Any]], words: Sequence[str]) -> bool:
    """Faktura poza obrotem: każda jej pozycja (stan po) zawiera słowo wyłączające."""

    if not words:
        return False
    names = [
        str(item.get("name") or "").lower()
        for item in items or []
        if not item.get("before_correction")
    ]
    return bool(names) and all(any(word in name for word in words) for name in names)


@dataclass(frozen=True)
class Entry:
    """Jedna faktura w obrocie: waluta, netto (korekta = różnica) i dzień kursu."""

    currency: str
    net: Decimal
    day: date
    items: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    net: Decimal
    rebate: Decimal


@dataclass(frozen=True)
class YearRebate:
    year: int
    threshold_currency: str
    tiers: tuple[Tier, ...]
    turnover: Decimal
    tier: Tier
    next_tier: Optional[Tier]
    totals: tuple[CurrencyTotal, ...]
    invoices: int
    excluded: int
    missing_fx: int
    settle_by: date

    @property
    def to_next(self) -> Optional[Decimal]:
        if self.tier.up_to is None:
            return None
        return max(self.tier.up_to - self.turnover, Decimal(0))


def summarize(
    year: int,
    terms: Terms,
    entries: Sequence[Entry],
    rates: dict[date, dict[str, Optional[Decimal]]],
) -> Optional[YearRebate]:
    """Stan rabatu za rok z listy faktur i kursów (``rates[dzień][waluta]`` → PLN)."""

    tiers = tiers_for(terms, year)
    if tiers is None:
        return None
    target = terms.threshold_currency
    turnover = Decimal(0)
    by_currency: dict[str, Decimal] = {}
    counted = skipped = missing = 0
    for entry in entries:
        if excluded(entry.items, terms.exclude_words):
            skipped += 1
            continue
        counted += 1
        currency = entry.currency.upper()
        by_currency[currency] = by_currency.get(currency, Decimal(0)) + entry.net
        if currency == target:
            turnover += entry.net
            continue
        day_rates = rates.get(entry.day, {})
        source, dest = day_rates.get(currency), day_rates.get(target)
        if not source or not dest:
            missing += 1
            continue
        turnover += entry.net * source / dest
    turnover = cents(turnover)
    tier = tier_for(turnover, tiers)
    index = tiers.index(tier)
    return YearRebate(
        year=year,
        threshold_currency=target,
        tiers=tiers,
        turnover=turnover,
        tier=tier,
        next_tier=tiers[index + 1] if index + 1 < len(tiers) else None,
        totals=tuple(
            CurrencyTotal(
                currency,
                cents(net),
                cents(net * tier.rate / HUNDRED) if net > 0 else Decimal("0.00"),
            )
            for currency, net in sorted(by_currency.items())
        ),
        invoices=counted,
        excluded=skipped,
        missing_fx=missing,
        settle_by=date(year + 1, 1, 31),
    )


def rate_boundary(sale_date: Optional[date], issue_date: date) -> date:
    """Kurs z ostatniej tabeli NBP PRZED datą sprzedaży (dni bez tabeli się pomija)."""

    return (sale_date or issue_date) - timedelta(days=1)


async def year_rebate(
    db: AsyncSession,
    *,
    client_id: int,
    year: int,
    terms: Terms,
    extra: Sequence[Entry] = (),
) -> Optional[YearRebate]:
    """Stan rabatu klienta za rok: faktury z KSeF plus ``extra`` (np. szkic w NEXUSIE)."""

    if tiers_for(terms, year) is None:
        return None
    rows = (
        await db.execute(
            select(
                ClientSalesInvoice.currency,
                ClientSalesInvoice.net_amount,
                ClientSalesInvoice.sale_date,
                ClientSalesInvoice.issue_date,
                ClientSalesInvoice.items,
            ).where(
                ClientSalesInvoice.client_id == client_id,
                ClientSalesInvoice.issue_date >= date(year, 1, 1),
                ClientSalesInvoice.issue_date <= date(year, 12, 31),
            )
        )
    ).all()
    entries = [
        Entry(
            (row.currency or "PLN").upper(),
            Decimal(row.net_amount),
            rate_boundary(row.sale_date, row.issue_date),
            tuple(row.items or ()),
        )
        for row in rows
    ]
    entries.extend(extra)
    wanted: dict[date, set[str]] = {}
    for entry in entries:
        if entry.currency != terms.threshold_currency:
            wanted.setdefault(entry.day, set()).update(
                {entry.currency, terms.threshold_currency}
            )
    rates = await fx_service.rates_to_pln_by_date(db, wanted) if wanted else {}
    return summarize(year, terms, entries, rates)


def _amount(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(cents(value), "f")


def _rate(value: Decimal) -> str:
    return format(value.normalize(), "f")


def payload(
    status: YearRebate, *, invoice_net: Optional[Decimal], currency: str
) -> dict[str, Any]:
    """Stan rabatu dla karty faktury: obrót, próg, stawka, kwoty, udział tej faktury."""

    return {
        "year": status.year,
        "threshold_currency": status.threshold_currency,
        "tiers": [
            {"up_to": _amount(tier.up_to), "rate": _rate(tier.rate)}
            for tier in status.tiers
        ],
        "turnover": _amount(status.turnover),
        "rate": _rate(status.tier.rate),
        "next_rate": _rate(status.next_tier.rate) if status.next_tier else None,
        "to_next": _amount(status.to_next),
        "totals": [
            {
                "currency": total.currency,
                "net": _amount(total.net),
                "rebate": _amount(total.rebate),
            }
            for total in status.totals
        ],
        "this_invoice": _amount(invoice_net * status.tier.rate / HUNDRED)
        if invoice_net is not None
        else None,
        "currency": currency,
        "invoices": status.invoices,
        "excluded": status.excluded,
        "missing_fx": status.missing_fx,
        "settle_by": status.settle_by.isoformat(),
    }


__all__ = [
    "Entry",
    "RebateTermsError",
    "Terms",
    "Tier",
    "YearRebate",
    "parse_terms",
    "payload",
    "summarize",
    "tier_for",
    "tiers_for",
    "to_json",
    "year_rebate",
]
