"""Marża per konsultant dla klienta (Governance, np. Nordea Appendix 2).

Wzór z modelu marży Nordei (raport H1 2026, sprawdzony co do złotówki na
270 z 281 osób; decyzje Artura 15–16.11.2026):

* ``narzut = koszty bezpośrednie na miesiąc ÷ godziny w miesiącu``
  (domyślnie 648 zł ÷ 168 h);
* ``Cost = ZAOKR(K + narzut + udział × MAX(0; D − K − narzut); 0)``, gdzie
  K = stawka konsultanta, D = stawka klienta, udział domyślnie 50%;
* ``po rabacie E = D × (1 − rabat)``, rabat = stawka efektywna roku: domyślnie
  progowo, od nadwyżki (obrót do progu po niższej stawce, część ponad progiem
  po wyższej — umowa ramowa Nordei, Appendix 6; decyzja Artura 16.11.2026);
  obrót z faktur sprzedaży od 1 stycznia do końca okresu razem z fakturami
  sprzed KSeF z archiwum eBI24 (od 24.11.2026), inne waluty kursem NBP — jak
  w „Rabacie od obrotu”;
* marża osoby ``(E − Cost) ÷ E``, portfela ``(ΣE − ΣCost) ÷ ΣE``, każda osoba
  raz (bez ważenia godzinami, jak w H1).

Skład = kontrakty aktywne w dniu generowania, stawki z harmonogramów na ten
dzień. W pliku dla klienta nie ma stawki konsultanta ani rozbicia kosztów.
Stawka konsultanta w NEXUSIE jest źródłem prawdy — gdy różni się od dawnego
Excela, poprawia się kontrakt, nie raport.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.rate_card import RateCard
from app.services.client_reports.generators.annual_spend import (
    archive_checks,
    archive_invoices,
    compute_rebate,
    earliest_invoice,
    exclude_words_for,
    incomplete_from,
    rate_text,
    turnover_checks,
    turnover_in,
)
from app.services.client_reports.generators.client_data import (
    sales_invoices,
    sheet_amount,
)
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
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.framework_limits import category_label

HUNDRED = Decimal(100)
RATIO = Decimal("0.0001")
TARGET_MARGIN = Decimal("0.15")
LIVE_STATUSES = (ContractStatus.active, ContractStatus.ending)


@dataclass(frozen=True)
class MarginAssumptions:
    monthly_cost: Decimal = Decimal(648)
    hours: Decimal = Decimal(168)
    #: Udział w nadwyżce stawki klienta ponad koszt, w procentach.
    share: Decimal = Decimal(50)

    @property
    def overhead(self) -> Decimal:
        return self.monthly_cost / self.hours if self.hours else Decimal(0)


def consultant_cost(k: Decimal, d: Decimal, a: MarginAssumptions) -> Decimal:
    """``ZAOKR(K + narzut + udział × MAX(0; D − K − narzut); 0)`` jak w Excelu."""
    base = k + a.overhead
    value = base + a.share / HUNDRED * max(Decimal(0), d - base)
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ConsultantRate:
    contract_id: int
    person: str
    role: Optional[str]
    candidate_rate: Decimal
    client_rate: Decimal


@dataclass(frozen=True)
class MarginRow:
    contract_id: int
    person: str
    role: Optional[str]
    cost: Decimal
    client_rate: Decimal
    after_rebate: Decimal
    margin: Optional[Decimal]


def margin_rows(
    people: Sequence[ConsultantRate], rebate_percent: Decimal, a: MarginAssumptions
) -> list[MarginRow]:
    keep = Decimal(1) - rebate_percent / HUNDRED
    rows = []
    for p in people:
        cost = consultant_cost(p.candidate_rate, p.client_rate, a)
        after = (p.client_rate * keep).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        margin = ((after - cost) / after).quantize(RATIO) if after else None
        rows.append(
            MarginRow(
                p.contract_id, p.person, p.role, cost, p.client_rate, after, margin
            )
        )
    return rows


def portfolio_margin(rows: Sequence[MarginRow]) -> Optional[Decimal]:
    total = sum((r.after_rebate for r in rows), Decimal(0))
    if not total:
        return None
    return ((total - sum((r.cost for r in rows), Decimal(0))) / total).quantize(RATIO)


def run_rate(amount: Decimal, covered_from: date, until: date) -> Optional[Decimal]:
    """Obrót roku w tempie z dni pokrytych fakturami (rok kalendarzowy ``until``)."""
    days = (until - covered_from).days + 1
    if days <= 0:
        return None
    year_days = (date(until.year, 12, 31) - date(until.year, 1, 1)).days + 1
    return (amount * year_days / days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def year_rebate_percent(
    turnover: Decimal, tiers: Sequence[Mapping[str, Any]], *, marginal: bool
) -> Decimal:
    """Stawka rabatu roku w procentach (przy „Progowo” średnia ważona); 0 bez progów."""
    rebate = compute_rebate(turnover, tiers, marginal=marginal)
    return rebate.rate if rebate else Decimal(0)


def pct_text(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    return f"{(value * HUNDRED).quantize(Decimal('0.01'))}".replace(".", ",") + "%"


@dataclass(frozen=True)
class Roster:
    people: list[ConsultantRate]
    #: Kontrakty poza raportem: inna jednostka niż godzina, inna waluta, brak stawki.
    skipped: int


async def roster(db: AsyncSession, client_id: int, on: date) -> Roster:
    contracts = list(
        await db.scalars(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .where(
                Contract.client_id == client_id,
                Contract.voided_at.is_(None),
                Contract.status.in_(LIVE_STATUSES),
                Contract.start_date <= on,
                (Contract.end_date.is_(None)) | (Contract.end_date >= on),
            )
            .order_by(Contract.start_date.desc(), Contract.id.desc())
        )
    )
    names: dict[int, str] = {}
    if contracts:
        found = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_({c.candidate_id for c in contracts})
            )
        )
        names = {
            cid: " ".join(p for p in (first, last) if p).strip()
            for cid, first, last in found.all()
        }
    card_ids = {c.client_rate_card_id for c in contracts if c.client_rate_card_id}
    cards = (
        {
            card.id: category_label(card.role, card.seniority)
            for card in await db.scalars(
                select(RateCard).where(RateCard.id.in_(card_ids))
            )
        }
        if card_ids
        else {}
    )
    people: list[ConsultantRate] = []
    seen: set[int] = set()
    skipped = 0
    for contract in contracts:
        if contract.candidate_id in seen:
            continue  # kolejny kontrakt tej samej osoby — liczy się najnowszy
        seen.add(contract.candidate_id)
        rates = effective_rate_fields(contract, on)
        k, d = rates["rate_candidate"], rates["rate_client"]
        if (
            contract.rate_unit != RateUnit.hourly
            or k is None
            or d is None
            or rates["rate_candidate_currency"] != "PLN"
            or rates["rate_client_currency"] != "PLN"
        ):
            skipped += 1
            continue
        role = cards.get(contract.client_rate_card_id) or (
            (contract.rate_card_coa_label or "").strip() or None
        )
        people.append(
            ConsultantRate(
                contract.id,
                names.get(contract.candidate_id, "") or f"kontrakt {contract.id}",
                role,
                Decimal(k),
                Decimal(d),
            )
        )
    people.sort(key=lambda p: p.person)
    return Roster(people, skipped)


def _assumptions(ctx: ReportContext) -> MarginAssumptions:
    def number(key: str) -> Decimal:
        return Decimal(str(param(ctx, GENERATOR, key)))

    return MarginAssumptions(number("monthly_cost"), number("hours"), number("share"))


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    currency = (param(ctx, GENERATOR, "currency") or "EUR").strip().upper() or "EUR"
    tiers = param(ctx, GENERATOR, "tiers") or []
    a = _assumptions(ctx)

    year_start = date(period.end.year, 1, 1)
    until = min(period.end, ctx.today)
    # Obrót roku jak w „Rabacie od obrotu”: KSeF po miesiącu usługi, faktury
    # sprzed KSeF z archiwum eBI24 po miesiącu daty sprzedaży.
    ksef = await sales_invoices(
        db, ctx.client_id, year_start, until, by_service_month=True
    )
    archived, unreadable = await archive_invoices(db, ctx.client_id, year_start, until)
    words = await exclude_words_for(db, ctx.client_id)
    turnover = await turnover_in(db, [*archived, *ksef], currency, words)
    marginal = bool(param(ctx, GENERATOR, "marginal"))
    rebate_percent = year_rebate_percent(turnover.amount, tiers, marginal=marginal)

    team = await roster(db, ctx.client_id, ctx.today)
    rows = margin_rows(team.people, rebate_percent, a)
    overall = portfolio_margin(rows)
    at_target = sum(
        1 for r in rows if r.margin is not None and r.margin >= TARGET_MARGIN
    )
    negative = sum(1 for r in rows if r.margin is not None and r.margin < 0)

    lines = [
        SummaryLine("Marża portfela (cel 15%)", pct_text(overall), True),
        SummaryLine("Konsultanci w raporcie", str(len(rows))),
        SummaryLine("z marżą ≥ 15% / ujemną", f"{at_target} / {negative}"),
        SummaryLine(
            f"Obrót {period.end.year} do {until:%d.%m} ({currency})",
            format_amount(turnover.amount),
        ),
        SummaryLine(
            "Rabat roku" + (" (efektywny, od nadwyżki)" if marginal else ""),
            rate_text(rebate_percent),
        ),
        SummaryLine(
            "Koszty bezpośrednie / udział",
            f"{format_amount(a.overhead)} zł/h / {rate_text(a.share)}",
        ),
    ]

    checks: list[str] = []
    if not tiers:
        checks.append("Definicja nie ma progów rabatu — marża liczona bez rabatu.")
    checks += turnover_checks(turnover, words)
    checks += archive_checks(archived, unreadable)
    first = await earliest_invoice(db, ctx.client_id, archived)
    if first is not None and incomplete_from(first, year_start):
        source = "KSeF i archiwum eBI24" if archived else "KSeF"
        fill = "KSeF albo archiwum eBI24" if archived else "KSeF"
        checks.append(
            f"Faktury z {source} są w NEXUSIE od {first:%d.%m.%Y} — obrót roku jest niepełny, "
            f"a stawka rabatu może być za niska; uzupełnij pobranie z {fill} przed wysłaniem."
        )
        covered = max(first, year_start)
        projected = run_rate(turnover.amount, covered, until)
        projected_rate = (
            year_rebate_percent(projected, tiers, marginal=marginal)
            if projected
            else None
        )
        if projected_rate is not None and projected_rate != rebate_percent:
            checks.append(
                f"W tempie z faktur obrót roku wyniesie ok. {format_amount(projected)} {currency} — "
                f"rabat {'efektywny ' if marginal else ''}{rate_text(projected_rate)}."
            )
    no_role = sum(1 for r in rows if not r.role)
    if no_role:
        checks.append(
            f"{no_role} osób bez kategorii z umowy ramowej — uzupełnij w stawkach ramowych klienta."
        )
    if team.skipped:
        checks.append(
            f"{team.skipped} kontraktów poza raportem: stawka nie godzinowa, nie w PLN albo bez stawki."
        )
    if not rows:
        checks.append("Brak aktywnych kontraktów ze stawkami w dniu generowania.")

    sheet = Sheet(
        "MARGIN",
        (
            "Consultant",
            "Role",
            "Cost",
            "Client rate",
            f"Rate after FwC {rate_text(rebate_percent)}",
            "Margin %",
        ),
        tuple(
            (
                r.person,
                r.role or "",
                sheet_amount(r.cost),
                sheet_amount(r.client_rate),
                sheet_amount(r.after_rebate),
                None
                if r.margin is None
                else float((r.margin * HUNDRED).quantize(Decimal("0.01"))),
            )
            for r in rows
        )
        + (
            (
                "OVERALL MARGIN",
                "",
                sheet_amount(sum((r.cost for r in rows), Decimal(0))),
                sheet_amount(sum((r.client_rate for r in rows), Decimal(0))),
                sheet_amount(sum((r.after_rebate for r in rows), Decimal(0))),
                None
                if overall is None
                else float((overall * HUNDRED).quantize(Decimal("0.01"))),
            ),
        ),
        widths=(30, 32, 12, 14, 20, 12),
        note=f"Skład z dnia {ctx.today:%d.%m.%Y}; stawki w PLN za godzinę; "
        "marża portfela = (Σ po rabacie − Σ Cost) / Σ po rabacie.",
    )
    return ReportData(lines=tuple(lines), sheets=(sheet,), checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="margin_per_consultant",
        label="Marża per konsultant",
        description=(
            "Marża każdej osoby i portfela po rabacie od obrotu — koszt wg modelu marży "
            "(koszty bezpośrednie + udział w nadwyżce)."
        ),
        rhythms=("quarterly", "semiannual", "annual", "on_request"),
        loader=_load,
        needs_amounts=True,
        needs_client_rate=True,
        preview_sheet="MARGIN",
        params=(
            ParamField(
                "currency",
                "Waluta progów",
                "text",
                "EUR",
                "Obrót w innej walucie przeliczamy kursem NBP sprzed daty sprzedaży.",
            ),
            ParamField(
                "tiers",
                "Progi rabatu",
                "tiers",
                None,
                "Rabat od obrotu roku (1.01–31.12) netto, bez podróży i faktur nieusługowych.",
            ),
            ParamField(
                "marginal",
                "Progowo (każdy próg osobno)",
                "bool",
                True,
                "Włączone (domyślnie, tak liczy Nordea): obrót do progu po niższej stawce, "
                "nadwyżka po wyższej; w kolumnie po rabacie stawka efektywna roku.",
            ),
            ParamField("monthly_cost", "Koszty bezpośrednie (zł/mies.)", "number", 648),
            ParamField("hours", "Godziny w miesiącu", "number", 168),
            ParamField(
                "share",
                "Udział w nadwyżce (%)",
                "number",
                50,
                "Część różnicy między stawką klienta a kosztem, która wchodzi do Cost.",
            ),
        ),
    )
)
