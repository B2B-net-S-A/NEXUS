"""Przegląd „Stawki ramowe” klienta i raport kwartalny Governance (F2, 15.11.2026).

Ile osób jest w limicie z umowy ramowej, ile dzięki dopłacie, ile ponad i co
umowa daje tym ponad (dopłata za technologię albo awans poziomu). Stan na
dowolny dzień liczy się z harmonogramów stawek (``contract_client_rates``,
``contract_framework_rates``), które mają daty obowiązywania — dlatego raport
kwartału nie potrzebuje osobnej tabeli migawek.

Do Nordei idą liczby i lista osób z kategorią, stawką i limitem; marża jest
osobnym raportem (decyzja Artura z 15.11.2026).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contract import Contract, ContractStatus
from app.services.framework_category import ClientTerms, load_terms
from app.services.framework_limits import (
    CardView,
    addon_choices,
    category_label,
    framework_limit,
    percent_text,
)

STATUS_IN = "in"
STATUS_IN_ADDON = "in_addon"
STATUS_OVER = "over"
STATUS_NO_LIMIT = "no_limit"
_LEVEL_ORDER = ("Junior", None, "Senior", "Expert")


def classify(
    rate: Optional[Decimal], limit: Optional[Decimal], base: Optional[Decimal]
) -> str:
    """W limicie / w limicie dzięki dopłacie / ponad / bez limitu."""
    if rate is None or limit is None:
        return STATUS_NO_LIMIT
    if rate <= limit:
        return STATUS_IN_ADDON if base is not None and rate > base else STATUS_IN
    return STATUS_OVER


@dataclass(frozen=True)
class Lever:
    kind: str  # addon | level | level_addon
    label: str
    limit: Decimal


def _norm(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _next_cards(terms: ClientTerms, card: CardView) -> list[CardView]:
    """Wyższe poziomy tej samej kategorii z cennika, od najbliższego."""
    try:
        start = _LEVEL_ORDER.index(card.seniority)
    except ValueError:
        return []
    out = []
    for level in _LEVEL_ORDER[start + 1 :]:
        hit = next(
            (
                c
                for c in terms.cards
                if _norm(c.role) == _norm(card.role)
                and _norm(c.seniority) == _norm(level)
            ),
            None,
        )
        if hit is not None:
            out.append(hit)
    return out


def levers(
    terms: ClientTerms, card: Optional[CardView], rate: Optional[Decimal], on: date
) -> list[Lever]:
    """Co umowa daje osobie ponad limitem, od najtańszego dla klienta.

    Dopłata wymaga technologii, której klient zażąda w zapytaniu (CPRO) —
    tu tylko możliwość z umowy; „zna / korzysta” dochodzi w F3.
    """
    if card is None or rate is None:
        return []
    out: list[Lever] = []
    for adder in sorted(
        addon_choices(terms.adders, card, on=on), key=lambda a: a.percent
    ):
        limit = framework_limit(card, adder.percent)
        if limit is not None and rate <= limit:
            out.append(
                Lever(
                    "addon",
                    f"Dopłata +{percent_text(adder.percent)}% ({adder.technology})",
                    limit,
                )
            )
            break
    for higher in _next_cards(terms, card):
        limit = framework_limit(higher, None)
        if limit is not None and rate <= limit:
            out.append(
                Lever(
                    "level",
                    f"Awans na {category_label(higher.role, higher.seniority)}",
                    limit,
                )
            )
            break
        for adder in sorted(
            addon_choices(terms.adders, higher, on=on), key=lambda a: a.percent
        ):
            limit = framework_limit(higher, adder.percent)
            if limit is not None and rate <= limit:
                out.append(
                    Lever(
                        "level_addon",
                        f"Awans na {category_label(higher.role, higher.seniority)} + dopłata {percent_text(adder.percent)}%",
                        limit,
                    )
                )
                break
        if out and out[-1].kind != "addon":
            break
    return out


@dataclass
class OverviewRow:
    contract_id: int
    person: str
    category: Optional[str]
    source: Optional[str]
    coa_label: Optional[str]
    rate: Optional[Decimal]
    limit: Optional[Decimal]
    base: Optional[Decimal]
    addon: Optional[str]
    status: str
    gap: Optional[Decimal]
    order_end: Optional[date]
    levers: list[Lever] = field(default_factory=list)
    limit_mismatch: bool = False


@dataclass
class Overview:
    on: date
    rows: list[OverviewRow]

    @property
    def counts(self) -> dict[str, int]:
        c = Counter(r.status for r in self.rows)
        return {
            k: c.get(k, 0)
            for k in (STATUS_IN, STATUS_IN_ADDON, STATUS_OVER, STATUS_NO_LIMIT)
        }

    @property
    def over_gap(self) -> Decimal:
        return sum(
            (r.gap for r in self.rows if r.status == STATUS_OVER and r.gap), Decimal(0)
        )

    def by_category(self) -> list[tuple[str, dict[str, int]]]:
        groups: dict[str, Counter] = {}
        for row in self.rows:
            if row.status == STATUS_NO_LIMIT:
                continue
            family = re.sub(
                r" - (Junior|Senior|Expert)$", "", row.category or "Bez kategorii"
            )
            groups.setdefault(family, Counter())[row.status] += 1
        return sorted(
            (
                (k, {s: v.get(s, 0) for s in (STATUS_IN, STATUS_IN_ADDON, STATUS_OVER)})
                for k, v in groups.items()
            ),
            key=lambda kv: -sum(kv[1].values()),
        )


def _population(client_id: int, on: date, today: date):
    from app.services.contractor_identity import current_contract_clause

    query = (
        select(Contract)
        .options(
            selectinload(Contract.framework_rate_schedule),
            selectinload(Contract.client_rate_schedule),
            selectinload(Contract.candidate),
        )
        .where(Contract.client_id == client_id)
    )
    if on >= today:
        return query.where(
            Contract.status.in_((ContractStatus.active, ContractStatus.ending))
        )
    # Stan z przeszłości: kontrakty obowiązujące w tym dniu, także zakończone później.
    return query.where(
        Contract.status.in_(
            (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
        ),
        current_contract_clause(on),
        or_(Contract.end_date.is_(None), Contract.end_date >= on),
    )


async def build_overview(
    db: AsyncSession, client_id: int, *, on: date, today: date
) -> Overview:
    terms = await load_terms(db, client_id)
    contracts = (await db.execute(_population(client_id, on, today))).scalars().all()
    rows = []
    for contract in contracts:
        card = terms.card(contract.client_rate_card_id)
        rate = contract.effective_client_rate(on)
        limit = contract.effective_framework_rate(on)
        base = framework_limit(card, None) if card else None
        status = classify(rate, limit, base)
        addon_pct = (
            contract.framework_addon_percent
            if contract.framework_addon_technology
            else None
        )
        expected = framework_limit(card, addon_pct) if card else None
        # Limit na kontrakcie inny niż z cennika (dawny import, ręczny krok):
        # dźwignie liczone od cennika wprowadzałyby w błąd.
        mismatch = expected is not None and limit is not None and expected != limit
        candidate = contract.candidate
        rows.append(
            OverviewRow(
                contract_id=contract.id,
                person=f"{candidate.name} {candidate.lastname}".strip()
                if candidate
                else f"Kontrakt #{contract.id}",
                category=category_label(card.role, card.seniority) if card else None,
                source=contract.rate_card_source,
                coa_label=contract.rate_card_coa_label,
                rate=rate,
                limit=limit,
                base=base,
                addon=(
                    f"{contract.framework_addon_technology} {percent_text(contract.framework_addon_percent)}%"
                    if contract.framework_addon_technology
                    and contract.framework_addon_percent is not None
                    else None
                ),
                status=status,
                gap=(rate - limit) if rate is not None and limit is not None else None,
                order_end=contract.client_order_end_date,
                levers=levers(terms, card, rate, on)
                if status == STATUS_OVER and not mismatch
                else [],
                limit_mismatch=mismatch,
            )
        )
    rows.sort(key=lambda r: (r.status != STATUS_OVER, -(r.gap or 0), r.person))
    return Overview(on=on, rows=rows)


def quarter_ends(today: date, count: int = 4) -> list[date]:
    """Ostatnie dni ``count`` zakończonych kwartałów, od najstarszego."""
    year, quarter = today.year, (today.month - 1) // 3  # bieżący kwartał 0..3
    out = []
    for _ in range(count):
        quarter -= 1
        if quarter < 0:
            quarter, year = 3, year - 1
        month = quarter * 3 + 3
        out.append(date(year, month, 31 if month in (3, 12) else 30))
    return list(reversed(out))
