"""Rabat od obrotu rocznego klienta (spend discount) — warunki jako dane, pozycja na fakturze.

Warunki leżą w ustawieniach wystawiania przy kliencie
(``app_settings['client_invoice_issue'].clients[<id>].rebate``) i wpisują je
Finanse z umowy ramowej; w kodzie nie ma ani progów, ani stawek::

    {"threshold_currency": "EUR",
     "periods": [{"from_year": 2026,
                  "tiers": [{"up_to": 15000000, "rate": 2.5},
                            {"up_to": null, "rate": 3}]}],
     "exclude_words": ["podróż"]}

Decyzje Artura 16.11.2026 (Nordea, druga odpowiedź tego dnia — zastępuje
„korektę roczną” z pierwszej):

* rabat jest RABATEM % NA KAŻDYM WIERSZU usługi (cena przed rabatem, rabat,
  wartość po rabacie — ``P_10`` w FA(3)), tak jak Nordea dostaje go z eBI24,
  po stawce progu, w którym jest narastający obrót roku SPRZED miesiąca faktury;
* stawka wyższego progu dotyczy tylko NADWYŻKI ponad próg; faktury za miesiąc,
  w którym obrót przekroczył próg, idą jeszcze po niższej stawce, a różnicę od
  części obrotu tego miesiąca ponad próg (np. 0,5%) rozlicza korekta
  (``YearRebate.corrections``; do KSeF tylko po „tak” Artura);
* obrót = usługi PRZED rabatem (ilość × cena) z faktur sprzedaży z KSeF za
  miesiące roku (okres usługi, bez okresu — data wystawienia), razem
  z korektami, bez pozycji ze słowem z ``exclude_words`` (podróże, refaktury);
  faktury sprzed KSeF dochodzą z archiwum eBI24 (``rebate_archive``, 24.11.2026);
* próg w innej walucie niż faktura: każda faktura po kursie średnim NBP
  z ostatniej tabeli przed datą sprzedaży; brak kursu = faktura poza obrotem
  progu i ostrzeżenie, nigdy kurs 1:1;
* ``periods`` — od którego roku obowiązują jakie progi; ``tiers`` — ``up_to``
  to górna granica obrotu rocznego WŁĄCZNIE w walucie progu, ``null`` = bez
  granicy (dokładnie jeden, ostatni); ``rate`` w procentach.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.services import fx_service
from app.services.client_invoicing import rebate_archive
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
    """Próg, w którym jest obrót (granica włącznie) — jego stawka idzie na fakturę."""

    for tier in tiers:
        if tier.up_to is None or turnover <= tier.up_to:
            return tier
    return tiers[-1]


def due(turnover: Decimal, tiers: Sequence[Tier]) -> Decimal:
    """Rabat należny od obrotu w walucie progu: każda część po stawce swojego progu."""

    total, lower = Decimal(0), Decimal(0)
    for tier in tiers:
        upper = turnover if tier.up_to is None else min(turnover, tier.up_to)
        if upper > lower:
            total += (upper - lower) * tier.rate / HUNDRED
        if tier.up_to is None or turnover <= tier.up_to:
            break
        lower = tier.up_to
    return total


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


#: Początek nazwy pozycji korekty zbiorczej rabatu (``rebate_correction``). Opust
#: to rabat, nie obrót: obrót do progu liczy się przed rabatem, więc ta pozycja
#: nie zmniejsza obrotu (inaczej przyjęta korekta zaniżałaby licznik do progu).
REBATE_LINE_PREFIX = "Opust (rabat od obrotu)"


def is_rebate_line(item: dict[str, Any]) -> bool:
    return str(item.get("name") or "").startswith(REBATE_LINE_PREFIX)


def _excluded(item: dict[str, Any], words: Sequence[str]) -> bool:
    name = str(item.get("name") or "").lower()
    return any(word in name for word in words)


def _num(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except ArithmeticError:
        return None
    return value if value.is_finite() else None


def service_base(
    net_amount: Decimal, items: Sequence[dict[str, Any]], words: Sequence[str]
) -> tuple[Decimal, bool]:
    """Obrót z faktury PRZED rabatem (decyzja Artura 16.11.2026), bez pozycji wyłączonych.

    Faktury z eBI24 mają rabat % na wierszu: cena jednostkowa (``P_9A``) jest
    przed rabatem, a netto (``P_11``) po nim. Od netto faktury doliczamy więc
    opust każdej pozycji (ilość × cena − netto) i odejmujemy pozycje wyłączone
    oraz pozycje korekty zbiorczej rabatu (``REBATE_LINE_PREFIX``).
    Pozycja bez ilości, ceny albo netto niczego nie zmienia. Korekta: stan przed
    ze znakiem minus. Zwraca też, czy coś wyłączono.
    """

    total = Decimal(net_amount)
    touched = False
    for item in items or ():
        sign = -1 if item.get("before_correction") else 1
        net = _num(item.get("net"))
        if is_rebate_line(item):
            if net is not None:
                total -= sign * net
            continue
        if _excluded(item, words):
            touched = True
            if net is not None:
                total -= sign * net
            continue
        quantity, price = _num(item.get("quantity")), _num(item.get("unit_price"))
        if net is not None and quantity is not None and price is not None:
            total += sign * (cents(quantity * price) - net)
    return cents(total), touched


def pre_discount(net_amount: Decimal, items: Sequence[dict[str, Any]]) -> Decimal:
    """Netto faktury przed rabatem % na wierszach — do porównań z zamówieniem.

    Rabat obniża fakturę, nie zamówienie: zamówienie ma cenę przed rabatem, więc
    bez tego każdy wiersz klienta z rabatem w „Do faktury” miałby różnicę.
    """

    return service_base(net_amount, items, ())[0]


def with_discount(
    lines: Sequence[dict[str, Any]], tier: Tier, words: Sequence[str]
) -> list[dict[str, Any]]:
    """Pozycje z rabatem % progu na usługach; pozycje wyłączone bez rabatu."""

    out = []
    for line in lines:
        item = {k: v for k, v in line.items() if k != "discount_pct"}
        if tier.rate > 0 and not _excluded(item, words):
            item["discount_pct"] = format(tier.rate.normalize(), "f")
        out.append(item)
    return out


@dataclass(frozen=True)
class Entry:
    """Jedna faktura w obrocie: waluta, obrót usług (korekta = różnica), dzień kursu, miesiąc.

    ``archived`` — faktura sprzed KSeF z archiwum eBI24.
    """

    currency: str
    net: Decimal
    day: date
    month: int
    excluded: bool = False
    archived: bool = False


@dataclass(frozen=True)
class Correction:
    """Wyrównanie za miesiąc przekroczenia progu (stawka różnicy od części ponad próg)."""

    month: int
    rate_diff: Decimal
    excess: Decimal
    amounts: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class YearRebate:
    year: int
    threshold_currency: str
    tiers: tuple[Tier, ...]
    turnover: Decimal
    month_turnover: dict[int, Decimal]
    corrections: tuple[Correction, ...]
    invoices: int
    excluded: int
    missing_fx: int
    #: Faktury sprzed KSeF z archiwum eBI24 w obrocie i dokumenty z plikiem nieczytelnym.
    archived: int = 0
    unreadable: int = 0

    def turnover_before(self, month: int) -> Decimal:
        return sum(
            (net for m, net in self.month_turnover.items() if m < month), Decimal(0)
        )

    def rate_for(self, month: int) -> Tier:
        """Stawka dla faktur za miesiąc: próg obrotu narastającego SPRZED tego miesiąca."""

        return tier_for(self.turnover_before(month), self.tiers)

    def next_tier(self, month: int) -> Optional[Tier]:
        tier = self.rate_for(month)
        index = self.tiers.index(tier)
        return self.tiers[index + 1] if index + 1 < len(self.tiers) else None

    def to_next(self) -> Optional[Decimal]:
        tier = tier_for(self.turnover, self.tiers)
        if tier.up_to is None:
            return None
        return max(tier.up_to - self.turnover, Decimal(0))

    @property
    def due(self) -> Decimal:
        return due(max(self.turnover, Decimal(0)), self.tiers)


def summarize(
    year: int,
    terms: Terms,
    entries: Sequence[Entry],
    rates: dict[date, dict[str, Optional[Decimal]]],
) -> Optional[YearRebate]:
    """Stan roku z faktur i kursów (``rates[dzień][waluta]`` → PLN)."""

    tiers = tiers_for(terms, year)
    if tiers is None:
        return None
    target = terms.threshold_currency
    months: dict[int, Decimal] = {}
    month_currency: dict[int, dict[str, Decimal]] = {}
    missing = skipped = 0
    for entry in entries:
        skipped += int(entry.excluded)
        currency = entry.currency.upper()
        per = month_currency.setdefault(entry.month, {})
        per[currency] = per.get(currency, Decimal(0)) + entry.net
        if currency == target:
            value = entry.net
        else:
            day_rates = rates.get(entry.day, {})
            source, dest = day_rates.get(currency), day_rates.get(target)
            if not source or not dest:
                missing += 1
                continue
            value = entry.net * source / dest
        months[entry.month] = months.get(entry.month, Decimal(0)) + value

    corrections = []
    running = Decimal(0)
    for month in sorted(months):
        month_net = months[month]
        before, after = running, running + month_net
        running = after
        if month_net <= 0:
            continue
        billed_rate = tier_for(before, tiers).rate
        owed = due(after, tiers) - due(max(before, Decimal(0)), tiers)
        extra = owed - month_net * billed_rate / HUNDRED
        if extra <= Decimal("0.005"):
            continue
        share = extra / month_net
        threshold = tier_for(before, tiers).up_to or Decimal(0)
        corrections.append(
            Correction(
                month=month,
                rate_diff=tier_for(after, tiers).rate - billed_rate,
                excess=cents(after - threshold),
                amounts=tuple(
                    (currency, cents(net * share))
                    for currency, net in sorted(month_currency[month].items())
                    if net > 0
                ),
            )
        )
    return YearRebate(
        year=year,
        threshold_currency=target,
        tiers=tiers,
        turnover=cents(sum(months.values(), Decimal(0))),
        month_turnover={m: cents(v) for m, v in sorted(months.items())},
        corrections=tuple(corrections),
        invoices=len(entries),
        excluded=skipped,
        missing_fx=missing,
        archived=sum(1 for entry in entries if entry.archived),
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
    """Stan roku klienta: faktury z KSeF i sprzed KSeF (archiwum eBI24) plus ``extra`` (szkic)."""

    if tiers_for(terms, year) is None:
        return None
    in_year = or_(
        ClientSalesInvoice.period_year == year,
        and_(
            ClientSalesInvoice.period_year.is_(None),
            ClientSalesInvoice.issue_date >= date(year, 1, 1),
            ClientSalesInvoice.issue_date <= date(year, 12, 31),
        ),
    )
    rows = (
        await db.execute(
            select(
                ClientSalesInvoice.currency,
                ClientSalesInvoice.net_amount,
                ClientSalesInvoice.sale_date,
                ClientSalesInvoice.issue_date,
                ClientSalesInvoice.period_month,
                ClientSalesInvoice.items,
            ).where(ClientSalesInvoice.client_id == client_id, in_year)
        )
    ).all()
    entries = []
    for row in rows:
        net, touched = service_base(
            Decimal(row.net_amount), list(row.items or ()), terms.exclude_words
        )
        entries.append(
            Entry(
                (row.currency or "PLN").upper(),
                net,
                rate_boundary(row.sale_date, row.issue_date),
                row.period_month or row.issue_date.month,
                touched,
            )
        )
    archived, unreadable = await rebate_archive.pre_ksef_invoices(
        db, client_id=client_id, year=year
    )
    for doc in archived:
        net, touched = service_base(doc.net_amount, doc.items, terms.exclude_words)
        entries.append(
            Entry(
                doc.currency,
                net,
                rate_boundary(doc.sale_date, doc.sale_date),
                doc.sale_date.month,
                touched,
                archived=True,
            )
        )
    entries.extend(extra)
    wanted: dict[date, set[str]] = {}
    for entry in entries:
        if entry.currency != terms.threshold_currency:
            wanted.setdefault(entry.day, set()).update(
                {entry.currency, terms.threshold_currency}
            )
    rates = await fx_service.rates_to_pln_by_date(db, wanted) if wanted else {}
    status = summarize(year, terms, entries, rates)
    return replace(status, unreadable=unreadable) if status else None


def _rate_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _amount(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(cents(value), "f")


def payload(
    status: YearRebate, *, month: int, on_invoice: Optional[Decimal], currency: str
) -> dict[str, Any]:
    """Stan rabatu dla karty faktury za ``month``: stawka, licznik do progu, korekty."""

    tier = status.rate_for(month)
    upcoming = status.next_tier(month)
    return {
        "year": status.year,
        "month": month,
        "threshold_currency": status.threshold_currency,
        "tiers": [
            {"up_to": _amount(t.up_to), "rate": _rate_text(t.rate)}
            for t in status.tiers
        ],
        "turnover": _amount(status.turnover),
        "turnover_before": _amount(status.turnover_before(month)),
        "rate": _rate_text(tier.rate),
        "next_rate": _rate_text(upcoming.rate) if upcoming else None,
        "to_next": _amount(status.to_next()),
        "due": _amount(status.due),
        "on_invoice": _amount(on_invoice),
        "currency": currency,
        "corrections": [
            {
                "month": c.month,
                "rate_diff": _rate_text(c.rate_diff),
                "excess": _amount(c.excess),
                "amounts": [
                    {"currency": cur, "amount": _amount(amount)}
                    for cur, amount in c.amounts
                ],
            }
            for c in status.corrections
        ],
        "invoices": status.invoices,
        "excluded": status.excluded,
        "missing_fx": status.missing_fx,
        "archived": status.archived,
        "unreadable": status.unreadable,
    }


__all__ = [
    "REBATE_LINE_PREFIX",
    "Entry",
    "RebateTermsError",
    "Terms",
    "Tier",
    "YearRebate",
    "due",
    "is_rebate_line",
    "parse_terms",
    "payload",
    "pre_discount",
    "service_base",
    "summarize",
    "tier_for",
    "tiers_for",
    "to_json",
    "with_discount",
    "year_rebate",
]
