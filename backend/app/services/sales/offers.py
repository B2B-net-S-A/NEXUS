"""Sprzedaż → Oferty: sekcje „W toku” i „Do decyzji” oraz przejęcie szansy.

Decyzje Artura z 10.11.2026. Zakładka pokazuje trwające szanse na etapach z wysłaną
ofertą, a w „Do decyzji” także trwające szanse z każdego etapu i lejka, których opiekun
nie pracuje już w Sprzedaży.

**Do decyzji** trafia pozycja:

* opiekuna, który nie pracuje już w Sprzedaży: konto nieaktywne albo bez „Sprzedaż:
  podgląd” i „Sprzedaż: edycja”. Wyjściem jest „Przejmij” albo zamknięcie, odłożenie
  jej nie zdejmuje, bo nie ma kto do niej wrócić;
* bez ruchu ponad ``IDLE_DAYS`` dni (dokładnie 30 dni to jeszcze „W toku”), chyba że
  ktoś ją odłożył datą w przyszłości (``keep_open_until``). W dniu tej daty wraca.

**Bez ruchu** liczy się od późniejszej z dwóch chwil: ostatniego dotyku (``touch.py``)
i wejścia na obecny etap z historii szansy. Wysłanie oferty jest ruchem, a ``/move``
dotyku nie zapisuje, więc bez tego oferta wysłana dziś przy szansie sprzed kwartału
od razu lądowałaby w „Do decyzji”. Import historii etapów nie przeniósł, więc dla
starych ofert liczy się sam dotyk.

„Odłóż do…” zapisuje ``keep_open_until``: to samo pole chroni szansę przed automatem
archiwizacji (``tasks/sales_archive_shadow.py``), bo oba znaczą „zostaw otwartą do dnia”.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import DateTime, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import business_date
from app.models.sales import (
    SalesCompany,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.polish_ilike import polish_folded_ilike
from app.services.sales import history, owner_tasks
from app.services.sales.next_step import Step, load_signals
from app.services.sales.task_scope import live_opportunity
from app.services.sales.touch import last_touch_at

#: Etapy, na których szansa ma wysłaną ofertę.
OFFER_STAGE_KEYS = ("offer-sent", "tender-submitted")
#: Po tylu dniach bez ruchu oferta czeka na decyzję („ponad 30 dni”).
IDLE_DAYS = 30

Scope = Literal["mine", "unowned", "all"]
Section = Literal["in_progress", "to_decide"]
Reason = Literal["owner_left", "idle"]

SCOPES: tuple[Scope, ...] = ("mine", "unowned", "all")

CLOSED_DETAIL = "Ta szansa jest już zamknięta albo w archiwum."
OWNED_DETAIL = (
    "Ta szansa ma opiekuna, który pracuje w Sprzedaży. "
    "Opiekuna zmienia on sam albo administrator."
)


class TakeOverRefused(Exception):
    """Szansy nie da się przejąć; ``detail`` to komunikat dla człowieka."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class OfferRow:
    opportunity: SalesOpportunity
    stage: SalesPipelineStage
    pipeline_name: str
    company_name: str
    owner_name: Optional[str]
    #: Opiekun jest i pracuje w Sprzedaży; bez tego pozycję można przejąć.
    owner_in_sales: bool
    is_offer: bool
    idle_since: datetime
    idle_days: int
    close_overdue: bool
    #: Odłożona datą w przyszłości („Odłóż do…”).
    postponed: bool
    section: Section
    reason: Optional[Reason]
    step: Optional[Step]
    step_overdue: bool


@dataclass(frozen=True)
class SectionTotals:
    count: int = 0
    mrr: Decimal = Decimal(0)


@dataclass(frozen=True)
class Offers:
    scope: Scope
    rows: list[OfferRow]
    totals: dict[Scope, dict[Section, SectionTotals]]


def works_in_sales(user: User) -> bool:
    """Aktywne konto z uprawnieniem Sprzedaży; konto musi mieć dołączoną politykę."""

    return bool(user.is_active) and (
        has_permission(user, ProductAction.sales_view)
        or has_permission(user, ProductAction.sales_edit)
    )


def is_postponed(keep_open_until: Optional[date], today: date) -> bool:
    """Odłożona do dnia, który jeszcze nie nadszedł; w dniu daty pozycja wraca."""

    return keep_open_until is not None and keep_open_until > today


def decide_section(
    *,
    owner_left: bool,
    idle_days: int,
    keep_open_until: Optional[date],
    today: date,
) -> tuple[Section, Optional[Reason]]:
    """Sekcja pozycji i powód, dla którego czeka na decyzję."""

    if owner_left:
        return "to_decide", "owner_left"
    if idle_days > IDLE_DAYS and not is_postponed(keep_open_until, today):
        return "to_decide", "idle"
    return "in_progress", None


async def owners_outside_sales(db: AsyncSession) -> set[int]:
    """Opiekunowie trwających szans, którzy nie pracują już w Sprzedaży."""

    owner_ids = set(
        (
            await db.scalars(
                select(SalesOpportunity.owner_user_id)
                .where(live_opportunity(), SalesOpportunity.owner_user_id.is_not(None))
                .distinct()
            )
        ).all()
    )
    if not owner_ids:
        return set()
    owners = list((await db.scalars(select(User).where(User.id.in_(owner_ids)))).all())
    await resolve_effective_access(db, owners)
    return {owner.id for owner in owners if not works_in_sales(owner)}


def _entered_stage_at() -> Any:
    """Ostatnie wejście na obecny etap z historii; NULL dla szans z importu."""

    return (
        select(func.max(SalesOpportunityEvent.created_at))
        .where(
            SalesOpportunityEvent.opportunity_id == SalesOpportunity.id,
            SalesOpportunityEvent.field == "stage_id",
            SalesOpportunityEvent.new_value == cast(SalesOpportunity.stage_id, String),
        )
        .correlate(SalesOpportunity)
        .scalar_subquery()
    )


async def _has_own_offers(db: AsyncSession, user_id: int) -> bool:
    """Czy osoba prowadzi jakąkolwiek trwającą ofertę; wyszukiwanie tego nie zmienia."""

    found = await db.scalar(
        select(SalesOpportunity.id)
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .where(
            live_opportunity(),
            SalesOpportunity.owner_user_id == user_id,
            SalesPipelineStage.key.in_(OFFER_STAGE_KEYS),
        )
        .limit(1)
    )
    return found is not None


def _in_scope(row: OfferRow, scope: Scope, user_id: int) -> bool:
    if scope == "mine":
        return row.opportunity.owner_user_id == user_id
    if scope == "unowned":
        return not row.owner_in_sales
    return True


def _totals(rows: list[OfferRow]) -> dict[Section, SectionTotals]:
    totals: dict[Section, SectionTotals] = {
        "in_progress": SectionTotals(),
        "to_decide": SectionTotals(),
    }
    for row in rows:
        current = totals[row.section]
        totals[row.section] = SectionTotals(
            count=current.count + 1,
            mrr=current.mrr + (row.opportunity.mrr_value or Decimal(0)),
        )
    return totals


def _order(row: OfferRow) -> tuple[Any, ...]:
    """„W toku” od najbliższego kroku, „Do decyzji” i pozycje bez kroku od największej kwoty."""

    mrr = row.opportunity.mrr_value or Decimal(0)
    if row.section == "in_progress":
        due = row.step.at.timestamp() if row.step else 0.0
        return (0, row.step is None, due, -mrr)
    return (1, -mrr, -row.idle_days)


async def load_rows(
    db: AsyncSession, *, q: Optional[str] = None, now: datetime
) -> list[OfferRow]:
    """Wszystkie pozycje zakładki z sekcją, bez zakresu i kolejności ekranu.

    Z tej samej listy poniedziałkowe odświeżenie punktów bota bierze firmy pozycji
    „Do decyzji” (``signal_targets.to_decide_company_ids``), żeby sekcja znaczyła
    w obu miejscach to samo.
    """

    today = business_date(now)
    left = await owners_outside_sales(db)
    owner = aliased(User)
    query = (
        select(
            SalesOpportunity,
            SalesPipelineStage,
            SalesPipeline.name.label("pipeline_name"),
            SalesCompany.name.label("company_name"),
            owner.name.label("owner_name"),
            func.greatest(
                last_touch_at(now),
                _entered_stage_at(),
                type_=DateTime(timezone=True),
            ).label("idle_since"),
        )
        .join(SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id)
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .join(SalesCompany, SalesCompany.id == SalesOpportunity.company_id)
        .outerjoin(owner, owner.id == SalesOpportunity.owner_user_id)
        .where(
            live_opportunity(),
            or_(
                SalesPipelineStage.key.in_(OFFER_STAGE_KEYS),
                SalesOpportunity.owner_user_id.in_(left),
            ),
        )
        .order_by(SalesOpportunity.id)
    )
    text = (q or "").strip()
    if text:
        query = query.where(
            or_(
                polish_folded_ilike(SalesOpportunity.title, text),
                polish_folded_ilike(SalesCompany.name, text),
            )
        )
    records = (await db.execute(query)).all()
    signals = await load_signals(
        db, [record.SalesOpportunity for record in records], now=now
    )

    rows: list[OfferRow] = []
    for record in records:
        opp: SalesOpportunity = record.SalesOpportunity
        stage: SalesPipelineStage = record.SalesPipelineStage
        owner_left = opp.owner_user_id in left
        idle_days = max(0, (today - business_date(record.idle_since)).days)
        section, reason = decide_section(
            owner_left=owner_left,
            idle_days=idle_days,
            keep_open_until=opp.keep_open_until,
            today=today,
        )
        signal = signals[opp.id]
        rows.append(
            OfferRow(
                opportunity=opp,
                stage=stage,
                pipeline_name=record.pipeline_name,
                company_name=record.company_name,
                owner_name=record.owner_name,
                owner_in_sales=opp.owner_user_id is not None and not owner_left,
                is_offer=stage.key in OFFER_STAGE_KEYS,
                idle_since=record.idle_since,
                idle_days=idle_days,
                close_overdue=(
                    opp.expected_close_date is not None
                    and opp.expected_close_date < today
                ),
                postponed=is_postponed(opp.keep_open_until, today),
                section=section,
                reason=reason,
                # Zaległość przed krokiem z przyszłości: to ją trzeba teraz odhaczyć.
                step=signal.overdue_step or signal.next_step,
                step_overdue=signal.overdue_step is not None,
            )
        )
    return rows


async def load_offers(
    db: AsyncSession,
    user: User,
    *,
    scope: Optional[Scope],
    q: Optional[str],
    now: datetime,
) -> Offers:
    """Pozycje zakładki w wybranym zakresie i liczniki wszystkich trzech zakresów.

    Bez ``scope`` wybiera „Moje”, gdy osoba prowadzi jakąś ofertę, a inaczej „Wszystkie”.
    Fraza ``q`` na ten wybór nie wpływa, bo zakres skakałby w trakcie pisania. Ekran pyta
    bez ``scope`` tylko raz, przy wejściu, i dalej podaje zakres jawnie.
    """

    rows = await load_rows(db, q=q, now=now)
    by_scope = {
        name: [row for row in rows if _in_scope(row, name, user.id)] for name in SCOPES
    }
    applied: Scope = scope or ("mine" if await _has_own_offers(db, user.id) else "all")
    return Offers(
        scope=applied,
        rows=sorted(by_scope[applied], key=_order),
        totals={name: _totals(items) for name, items in by_scope.items()},
    )


async def take_over(
    db: AsyncSession, opportunity: SalesOpportunity, user: User
) -> None:
    """Zrób ``user`` opiekunem szansy, której nikt ze Sprzedaży nie prowadzi.

    Zmiana idzie do historii szansy jak przekazanie w ``scripts/sales_cleanup.py``.
    Otwarte zadania poprzedniego opiekuna przy tej szansie przechodzą razem z nią
    (``owner_tasks.hand_over``), bo na koncie spoza Sprzedaży nikt by ich nie zobaczył.
    Wywołujący trzyma blokadę wiersza i robi commit.
    """

    if opportunity.status != "open" or opportunity.archived_at is not None:
        raise TakeOverRefused(CLOSED_DETAIL)
    previous_id = opportunity.owner_user_id
    if previous_id == user.id:
        return
    if previous_id is not None:
        previous = await db.get(User, previous_id)
        if previous is not None:
            await resolve_effective_access(db, [previous])
            if works_in_sales(previous):
                raise TakeOverRefused(OWNED_DETAIL)
    before = history.snapshot(opportunity)
    opportunity.owner_user_id = user.id
    history.record_changes(db, opportunity, before, user_id=user.id)
    await owner_tasks.hand_over(
        db, opportunity.id, previous_owner_id=previous_id, new_owner_id=user.id
    )
