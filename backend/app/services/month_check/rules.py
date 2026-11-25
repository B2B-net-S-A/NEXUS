"""Kontrola miesiąca: rozbieżności faktur klient ↔ konsultant per osoba i miesiąc.

Czyste funkcje (testy bez bazy); wejście składa ``collect``, zapis robi
``service``. Reguła z audytu fakturowania z 25.11.2026 (16 spraw na setki
tysięcy złotych, których nikt nie zauważył) — decyzja Artura, żeby NEXUS
łapał je sam co noc.

Cztery kontrole dla każdej osoby w zamkniętym miesiącu:

* ``hours_mismatch`` — godziny (MD) z faktury do klienta × stawka kosztowa
  kontraktu ≠ netto faktury konsultanta o więcej niż pół dnia (4 h × stawka);
* ``cost_without_sale`` — konsultant zafakturował, a klient do 15. dnia
  następnego miesiąca nie ma faktury z tą osobą;
* ``sale_without_cost`` — klient zafakturowany, a faktury konsultanta do 15.
  dnia następnego miesiąca nie ma;
* ``over_working_days`` — więcej godzin (MD) na fakturach do klienta niż dni
  roboczych w miesiącu, gdy faktura konsultanta z tego miesiąca nie potwierdza
  tych godzin (nadgodziny zafakturowane po obu stronach to nie błąd).

Okno ±1 miesiąca: faktura konsultanta nie ma okresu, więc miesiąc bierzemy
z dnia wystawienia (od 25. bieżący, do 10. poprzedni, pomiędzy — ten, który
lepiej pasuje do godzin u klienta), a rozbieżność, którą znosi przesunięcie
o miesiąc (dwa miesiące razem się zgadzają), nie jest sprawą.

Pomijamy (i liczymy osobno): klientów z fakturą zbiorczą
(``cl.collective_invoice``) i klientów bez nazwisk w pozycjach, osoby z dwoma
kontraktami w miesiącu, osoby bez żadnej faktury w KSeF (papier, nieznany NIP)
i faktury konsultantów poza kontraktem.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Optional

HOURS_MISMATCH = "hours_mismatch"
COST_WITHOUT_SALE = "cost_without_sale"
SALE_WITHOUT_COST = "sale_without_cost"
OVER_WORKING_DAYS = "over_working_days"
KINDS: tuple[str, ...] = (
    HOURS_MISMATCH,
    COST_WITHOUT_SALE,
    SALE_WITHOUT_COST,
    OVER_WORKING_DAYS,
)
#: Sprawy, na które czeka się do 15. dnia następnego miesiąca.
DEADLINE_KINDS = frozenset({COST_WITHOUT_SALE, SALE_WITHOUT_COST})
DEADLINE_DAY = 15

NO_CONTRACT = "no_contract"
NO_ORDER = "no_order"

HOURS_PER_DAY = Decimal(8)
#: Tolerancja: pół dnia pracy.
TOLERANCE_HOURS = Decimal(4)
LATE_ISSUE_DAY = 25
EARLY_ISSUE_DAY = 10
#: Przegląd wariantów miesiąca dla faktur z połowy miesiąca (2^n).
MAX_FREE_DOCS = 10
CENT = Decimal("0.01")

#: Liczniki pominięć (klucze ``stats``).
SKIP_PARALLEL = "parallel_contracts"
SKIP_CLIENT = "client_without_names"
SKIP_NO_KSEF = "no_ksef_invoices"
SKIP_OUTSIDE = "outside_contracts"
SKIP_NOT_COMPARABLE = "not_comparable"
SKIP_UNASSIGNED = "sale_waits_for_buyer"
WAITING = "waiting_for_deadline"


def month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def shift(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) + delta
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


def deadline(month: str) -> date:
    nxt = shift(month, 1)
    return date(int(nxt[:4]), int(nxt[5:7]), DEADLINE_DAY)


def closed_months(today: date, count: int = 3) -> list[str]:
    """Ostatnie ``count`` zakończone miesiące kalendarzowe, od najstarszego."""

    last = shift(month_key(today), -1)
    return [shift(last, -i) for i in range(count - 1, -1, -1)]


@dataclass(frozen=True)
class SaleLine:
    """Pozycja faktury do klienta (stan po korektach) z osobą."""

    candidate_id: int
    contract_id: int
    client_id: int
    month: str
    invoice_number: str
    #: ``None`` — jednostka bez godzin (szt., ryczałt).
    hours: Optional[Decimal]
    net: Decimal


@dataclass(frozen=True)
class CostDoc:
    """Faktura konsultanta z KSeF przypięta do osoby."""

    candidate_id: int
    number: str
    issue_date: date
    net: Decimal
    currency: str
    correction: bool
    #: Miesiąc ustalony już przez rozliczenia (``client_contractor_invoices``).
    fixed_month: Optional[str] = None


@dataclass(frozen=True)
class Context:
    """Osoba w miesiącu według kontraktów."""

    live: tuple[int, ...] = ()
    contract_id: Optional[int] = None
    client_id: Optional[int] = None
    #: Stawka kosztowa za godzinę; ``None`` — ryczałt, zmiana w miesiącu, brak.
    rate: Optional[Decimal] = None
    rate_currency: str = "PLN"
    has_order: bool = False
    #: Bez trwającego kontraktu, ale zakończony niedawno (spóźniona faktura,
    #: zła data końca) — sprawa dla DL, nie szum po dawno zakończonej współpracy.
    recent: bool = False


@dataclass(frozen=True)
class Finding:
    kind: str
    candidate_id: int
    month: str
    contract_id: Optional[int]
    client_id: Optional[int]
    amount: Optional[Decimal]
    currency: str
    data_issue: Optional[str]
    details: dict

    @property
    def key(self) -> str:
        base = f"{self.kind}:{self.candidate_id}:{self.month}"
        return f"{base}:{self.client_id}" if self.kind == OVER_WORKING_DAYS else base


@dataclass
class MonthStats:
    person_months: int = 0
    matched: int = 0
    cases: dict[str, int] = field(default_factory=lambda: {k: 0 for k in KINDS})
    skipped: dict[str, int] = field(default_factory=dict)
    #: Więcej godzin niż dni roboczych, potwierdzone fakturą konsultanta.
    overtime_confirmed: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_dict(self) -> dict:
        return {
            "person_months": self.person_months,
            "matched": self.matched,
            "cases": dict(self.cases),
            "skipped": dict(sorted(self.skipped.items())),
            "overtime_confirmed": self.overtime_confirmed,
        }


@dataclass(frozen=True)
class Inputs:
    months: tuple[str, ...]
    today: date
    sales: tuple[SaleLine, ...]
    costs: tuple[CostDoc, ...]
    context: Mapping[tuple[int, str], Context]
    #: Klient-miesiąc z fakturą zbiorczą albo bez nazwisk w pozycjach.
    unnamed_clients: Mapping[str, frozenset[int]]
    working_days: Mapping[str, int]
    #: Osoba-miesiąc nazwana na fakturze, która czeka na przypisanie nabywcy
    #: („Nieznani nabywcy”): sprzedaż jest, tylko bez klienta w NEXUSIE.
    unassigned_sales: frozenset[tuple[int, str]] = frozenset()


@dataclass
class Result:
    findings: list[Finding]
    stats: dict[str, MonthStats]


# ── Miesiąc faktury konsultanta ──────────────────────────────────────────────


def _default_month(issue: date) -> str:
    current = month_key(issue)
    return current if issue.day >= LATE_ISSUE_DAY else shift(current, -1)


def assign_months(
    docs: Iterable[CostDoc], expected: Mapping[str, Optional[Decimal]]
) -> dict[str, list[CostDoc]]:
    """Faktury jednej osoby rozłożone na miesiące usług.

    Od 25. dnia — bieżący miesiąc, do 10. — poprzedni; pomiędzy przegląd
    wariantów: najmniejsza suma |koszt − koszt z godzin klienta| (remis —
    reguła 25. dnia). Korekta idzie do miesiąca faktury o przeciwnej kwocie,
    a bez takiej do ostatniej wcześniejszej faktury.
    """

    ordered = sorted(docs, key=lambda d: (d.issue_date, d.correction, d.number))
    fixed: list[tuple[CostDoc, str]] = []
    free: list[CostDoc] = []
    for doc in ordered:
        if doc.correction:
            continue
        if doc.fixed_month:
            fixed.append((doc, doc.fixed_month))
        elif doc.issue_date.day >= LATE_ISSUE_DAY:
            fixed.append((doc, month_key(doc.issue_date)))
        elif doc.issue_date.day <= EARLY_ISSUE_DAY:
            fixed.append((doc, shift(month_key(doc.issue_date), -1)))
        else:
            free.append(doc)

    def score(assign: list[tuple[CostDoc, str]]) -> Decimal:
        total: dict[str, Decimal] = defaultdict(Decimal)
        for doc, month in assign:
            total[month] += doc.net
        return sum(
            (
                abs(total.get(m, Decimal(0)) - want)
                for m, want in expected.items()
                if want is not None
            ),
            Decimal(0),
        )

    if len(free) <= MAX_FREE_DOCS and free:
        best: Optional[tuple[tuple[Decimal, int], list[tuple[CostDoc, str]]]] = None
        for combo in itertools.product((0, 1), repeat=len(free)):
            assign = fixed + [
                (
                    doc,
                    month_key(doc.issue_date)
                    if pick
                    else shift(month_key(doc.issue_date), -1),
                )
                for doc, pick in zip(free, combo)
            ]
            against_rule = sum(
                1
                for doc, pick in zip(free, combo)
                if bool(pick)
                != (_default_month(doc.issue_date) == month_key(doc.issue_date))
            )
            candidate = (score(assign), against_rule)
            if best is None or candidate < best[0]:
                best = (candidate, assign)
        assigned = best[1] if best else fixed
    else:
        assigned = fixed + [(doc, _default_month(doc.issue_date)) for doc in free]

    out: dict[str, list[CostDoc]] = defaultdict(list)
    for doc, month in assigned:
        out[month].append(doc)
    for doc in ordered:
        if not doc.correction:
            continue
        if doc.fixed_month:
            out[doc.fixed_month].append(doc)
            continue
        earlier = [(d, m) for d, m in assigned if d.issue_date <= doc.issue_date]
        target = next(
            (
                m
                for d, m in sorted(earlier, key=lambda x: x[0].issue_date, reverse=True)
                if abs(d.net + doc.net) < CENT
            ),
            None,
        )
        if target is None and earlier:
            target = max(earlier, key=lambda x: x[0].issue_date)[1]
        out[target or _default_month(doc.issue_date)].append(doc)
    return dict(out)


# ── Kontrole ─────────────────────────────────────────────────────────────────


@dataclass
class _Side:
    hours: Decimal = Decimal(0)
    hours_known: bool = True
    net: Decimal = Decimal(0)
    invoices: list[str] = field(default_factory=list)
    present: bool = False


def _sales_side(lines: Iterable[SaleLine]) -> _Side:
    side = _Side()
    for line in lines:
        side.present = True
        side.net += line.net
        if line.hours is None:
            side.hours_known = False
        else:
            side.hours += line.hours
        if line.invoice_number not in side.invoices:
            side.invoices.append(line.invoice_number)
    return side


def _q(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value.quantize(CENT))


def _docs(docs: Iterable[CostDoc]) -> list[dict]:
    return [
        {
            "number": d.number,
            "issue_date": d.issue_date.isoformat(),
            "net": _q(d.net),
            "correction": d.correction,
        }
        for d in docs
    ]


def evaluate(data: Inputs) -> Result:
    sales_by: dict[tuple[int, str], list[SaleLine]] = defaultdict(list)
    for line in data.sales:
        sales_by[(line.candidate_id, line.month)].append(line)
    costs_by: dict[int, list[CostDoc]] = defaultdict(list)
    for doc in data.costs:
        costs_by[doc.candidate_id].append(doc)

    window = set(data.months) | {shift(m, d) for m in data.months for d in (-1, 1)}
    findings: list[Finding] = []
    stats = {m: MonthStats() for m in data.months}
    people = {c for c, m in sales_by if m in data.months} | {c for c in costs_by}

    for cand in sorted(people):
        sides = {m: _sales_side(sales_by.get((cand, m), [])) for m in window}

        def rate_of(month: str) -> Optional[Decimal]:
            ctx = data.context.get((cand, month))
            return ctx.rate if ctx else None

        expected = {
            m: (
                s.hours * rate_of(m)
                if s.present and s.hours_known and rate_of(m) is not None
                else None
            )
            for m, s in sides.items()
        }
        cost = assign_months(costs_by.get(cand, []), expected)
        has_history = any(d.net > 0 for d in costs_by.get(cand, []))

        def cost_net(month: str) -> Decimal:
            return sum((d.net for d in cost.get(month, [])), Decimal(0))

        for month in data.months:
            side = sides[month]
            c_net = cost_net(month)
            if not side.present and c_net <= 0:
                continue
            st = stats[month]
            st.person_months += 1
            ctx = data.context.get((cand, month), Context())
            if len(ctx.live) > 1:
                st.skip(SKIP_PARALLEL)
                continue
            if not side.present and not ctx.live and not ctx.recent:
                st.skip(SKIP_OUTSIDE)
                continue
            skipped_before = sum(st.skipped.values())
            found = _check_person_month(
                data, cand, month, side, sides, cost, ctx, has_history, st
            )
            # Więcej godzin niż dni roboczych liczy się osobno, per klient.
            over = _over_days(data, month, cand, sales_by.get((cand, month), []))
            checked = sum(st.skipped.values()) == skipped_before
            # Nadgodziny, które konsultant zafakturował tak samo (Nordea: 14–39 osób
            # w miesiącu), to nie błąd faktury — liczymy je, ale bez sprawy.
            if over and _same_month_match(side, cost_net(month), ctx):
                st.overtime_confirmed += len(over)
                over = []
            if found is None and not over and checked:
                st.matched += 1
            for item in ([found] if found else []) + over:
                st.cases[item.kind] += 1
                findings.append(item)
    return Result(findings=findings, stats=stats)


def _check_person_month(
    data: Inputs,
    cand: int,
    month: str,
    side: _Side,
    sides: Mapping[str, _Side],
    cost: Mapping[str, list[CostDoc]],
    ctx: Context,
    has_history: bool,
    st: MonthStats,
) -> Optional[Finding]:
    docs = cost.get(month, [])
    c_net = sum((d.net for d in docs), Decimal(0))
    rate = ctx.rate
    currency_ok = all(d.currency == ctx.rate_currency for d in docs)
    tol = TOLERANCE_HOURS * rate if rate is not None else None
    neighbours = (shift(month, -1), shift(month, 1))

    def neighbour_net(k: str) -> Decimal:
        return sum((d.net for d in cost.get(k, [])), Decimal(0))

    def details(**extra: object) -> dict:
        base = {
            "client_hours": _q(side.hours)
            if side.present and side.hours_known
            else None,
            "client_net": _q(side.net) if side.present else None,
            "sales_invoices": list(side.invoices),
            "contractor_net": _q(c_net) if docs else None,
            "contractor_invoices": _docs(docs),
            "cost_rate": _q(rate),
        }
        base.update(extra)
        return base

    def finding(
        kind: str, amount: Optional[Decimal], issue: Optional[str], **extra: object
    ) -> Finding:
        return Finding(
            kind=kind,
            candidate_id=cand,
            month=month,
            contract_id=ctx.contract_id,
            client_id=ctx.client_id,
            amount=amount.quantize(CENT) if amount is not None else None,
            currency=ctx.rate_currency,
            data_issue=issue,
            details=details(**extra),
        )

    if side.present and c_net > 0:
        if not side.hours_known or rate is None or not currency_ok or side.hours <= 0:
            st.skip(SKIP_NOT_COMPARABLE)
            return None
        expected = side.hours * rate
        diff = c_net - expected
        if abs(diff) <= tol:
            return None
        for k in neighbours:
            other = sides.get(k)
            k_hours = (
                other.hours
                if other and other.present and other.hours_known
                else Decimal(0)
            )
            if other and other.present and not other.hours_known:
                continue
            if abs((c_net + neighbour_net(k)) - (side.hours + k_hours) * rate) <= tol:
                return None
        return finding(
            HOURS_MISMATCH,
            diff,
            None,
            expected_cost=_q(expected),
            contractor_hours=_q(c_net / rate),
        )

    deadline_passed = data.today > deadline(month)
    if not side.present:
        # Konsultant zafakturował, klient nie.
        if not deadline_passed:
            st.skip(WAITING)
            return None
        if ctx.client_id is not None and ctx.client_id in data.unnamed_clients.get(
            month, frozenset()
        ):
            st.skip(SKIP_CLIENT)
            return None
        if any((cand, k) in data.unassigned_sales for k in (month, *neighbours)):
            st.skip(SKIP_UNASSIGNED)
            return None
        for k in neighbours:
            other = sides.get(k)
            if not other or not other.present:
                continue
            k_net = neighbour_net(k)
            if rate is not None and other.hours_known:
                if abs((c_net + k_net) - other.hours * rate) <= tol:
                    return None
            elif k_net <= 0:
                return None
        issue = NO_CONTRACT if not ctx.live else (None if ctx.has_order else NO_ORDER)
        return finding(COST_WITHOUT_SALE, c_net, issue)

    # Klient zafakturowany, konsultant nie.
    if not deadline_passed:
        st.skip(WAITING)
        return None
    if not has_history:
        st.skip(SKIP_NO_KSEF)
        return None
    for k in neighbours:
        k_net = neighbour_net(k)
        if k_net <= 0:
            continue
        other = sides.get(k)
        if (
            rate is not None
            and side.hours_known
            and other is not None
            and (not other.present or other.hours_known)
        ):
            k_hours = other.hours if other.present else Decimal(0)
            if abs(k_net - (k_hours + side.hours) * rate) <= tol:
                return None
        elif other is None or not other.present:
            return None
    expected = side.hours * rate if rate is not None and side.hours_known else None
    issue = None if ctx.has_order else NO_ORDER
    return finding(SALE_WITHOUT_COST, expected, issue, expected_cost=_q(expected))


def _same_month_match(side: _Side, c_net: Decimal, ctx: Context) -> bool:
    """Faktura konsultanta z tego samego miesiąca potwierdza godziny klienta (±pół dnia)."""

    if not side.present or not side.hours_known or ctx.rate is None or c_net <= 0:
        return False
    return abs(c_net - side.hours * ctx.rate) <= TOLERANCE_HOURS * ctx.rate


def _over_days(
    data: Inputs, month: str, cand: int, lines: list[SaleLine]
) -> list[Finding]:
    days = data.working_days.get(month)
    if not days:
        return []
    limit = Decimal(days) * HOURS_PER_DAY
    per_client: dict[int, list[SaleLine]] = defaultdict(list)
    for line in lines:
        per_client[line.client_id].append(line)
    out = []
    for client_id, client_lines in sorted(per_client.items()):
        side = _sales_side(client_lines)
        if not side.hours_known or side.hours <= limit:
            continue
        excess = side.hours - limit
        price = side.net / side.hours if side.hours else None
        out.append(
            Finding(
                kind=OVER_WORKING_DAYS,
                candidate_id=cand,
                month=month,
                contract_id=client_lines[0].contract_id,
                client_id=client_id,
                amount=(excess * price).quantize(CENT) if price is not None else None,
                currency="PLN",
                data_issue=None,
                details={
                    "client_hours": _q(side.hours),
                    "client_net": _q(side.net),
                    "sales_invoices": list(side.invoices),
                    "working_days": days,
                    "limit_hours": _q(limit),
                    "excess_hours": _q(excess),
                },
            )
        )
    return out
