"""Zdrowie relacji z konsultantem: Dobrze · Uwaga · Ryzyko (przebudowa opieki, 22.10.2026).

Etykietę i zdanie „dlaczego” widzi krąg D11 (opiekun z roli, Delivery Lead,
Head of Recruitment, admin) — liczą się w niej opinie menedżera u klienta.
Finanse i inni dostają ``health: null`` (``health_for_contracts``), tak samo
kontrakt klienta spoza zakresu czytającego (portfel Delivery Leada, audyt
bezpieczeństwa 22.10.2026 — tablica Spraw pokazuje kontrakty wszystkich).

Reguły (``assess`` — czysta funkcja, testy brzegów w ``test_care_health.py``):

**Ryzyko**, gdy choć jedno:

* aktywny wpis „Do przepięcia” z powodem „ryzyko odejścia”,
* aktywne „chce zmiany projektu” i koniec zamówienia albo umowy za ≤ 60 dni,
* ostatnia opinia menedżera (średnia ocen) < 3,
* ostatnie zadowolenie z rozmowy ≤ 2.

**Uwaga**, gdy choć jedno:

* zaległa rozmowa (następny kontakt ``plan.next_contact`` > 0 dni po terminie),
* ostatnie zadowolenie = 3 albo spadek o ≥ 2 względem poprzedniej rozmowy,
* koniec za ≤ 45 dni bez decyzji (decyzja = wpis „Do przepięcia” w toku,
  przepięty albo „nie dotyczy” z ostatnich 120 dni, albo przekazanie do
  front office),
* aktywne „chce zmiany projektu”,
* brak rozmowy od N dni, gdy N > 2 × odstęp rytmu (co 2 tygodnie = 14,
  co miesiąc = 30, co kwartał = 91; wstrzymany i „tylko kamienie” — bez tej
  reguły). N liczy się od ostatniej rozmowy, a bez rozmów — od startu.

Inaczej **Dobrze**. Kontrakt młodszy niż 14 dni bez żadnej rozmowy = Dobrze
z powodem „brak rozmów”. Powody to powody poziomu, który wygrał (najwyżej 3).
Zakończony kontrakt nie ma etykiety (``None``).

Zadowolenie bierze się z rozmów opiekuna (od 22.10.2026 okno „Rozmowa”
zapisuje kartę z tej samej rozmowy, więc karta nie jest drugim źródłem).
Odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.contract_care import CareConversation, RedeployQueueItem
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import client_feedback, front_office
from app.services.care import plan as care_plan
from app.services.care.access import CareContract
from app.services.care.cadence_rules import level_on

RISK_FEEDBACK_BELOW = 3.0
RISK_SATISFACTION_MAX = 2
WATCH_SATISFACTION = 3
WATCH_SATISFACTION_DROP = 2
RISK_CHANGE_END_DAYS = 60
WATCH_END_UNDECIDED_DAYS = 45
NEW_CONTRACT_DAYS = 14
SILENCE_FACTOR = 2
DECISION_LOOKBACK_DAYS = 120
MAX_REASONS = 3
#: Odstęp rozmów w rytmie (dni). Wstrzymany i „tylko kamienie” — bez reguły ciszy.
CADENCE_INTERVAL_DAYS: dict[str, int] = {
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 91,
}
LEVEL_LABELS: dict[str, str] = {"ok": "Dobrze", "watch": "Uwaga", "risk": "Ryzyko"}


@dataclass(frozen=True)
class HealthSignals:
    """Wszystko, czego potrzebuje reguła — bez bazy."""

    today: date
    live: bool = True
    start_on: Optional[date] = None
    end_on: Optional[date] = None
    #: ``order`` | ``contract`` — co się kończy (do zdania „dlaczego”).
    end_kind: str = "order"
    attrition_risk_on: Optional[date] = None
    wants_change_on: Optional[date] = None
    attrition_risk: bool = False
    wants_change: bool = False
    end_decided: bool = False
    feedback_average: Optional[float] = None
    feedback_on: Optional[date] = None
    satisfaction: Optional[int] = None
    satisfaction_on: Optional[date] = None
    previous_satisfaction: Optional[int] = None
    overdue_days: int = 0
    last_conversation_on: Optional[date] = None
    cadence_level: Optional[str] = None


@dataclass(frozen=True)
class Health:
    level: str  # ok | watch | risk
    reasons: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.level]

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "label": self.label, "reasons": list(self.reasons)}


def _day(value: Optional[date]) -> str:
    return f" ({value.strftime('%d.%m')})" if value is not None else ""


def _days(count: int) -> str:
    return "1 dzień" if count == 1 else f"{count} dni"


def _score(value: float) -> str:
    text = f"{value:.1f}".replace(".", ",")
    return (text[:-2] if text.endswith(",0") else text) + "/5"


def _end_phrase(s: HealthSignals, days: int) -> str:
    what = "umowa kończy się" if s.end_kind == "contract" else "zamówienie kończy się"
    if days == 0:
        return f"{what} dziś"
    return f"{what} za {_days(days)}"


def assess(s: HealthSignals) -> Optional[Health]:
    """Poziom i powody (czysta reguła — opis w docstringu modułu)."""

    if not s.live:
        return None
    end_days = (s.end_on - s.today).days if s.end_on is not None else None
    ending = end_days is not None and end_days >= 0

    risk: list[str] = []
    if s.attrition_risk:
        risk.append("ryzyko odejścia" + _day(s.attrition_risk_on))
    if s.wants_change and ending and end_days <= RISK_CHANGE_END_DAYS:
        risk.append("chce zmiany projektu" + _day(s.wants_change_on))
        risk.append(_end_phrase(s, end_days))
    if s.feedback_average is not None and s.feedback_average < RISK_FEEDBACK_BELOW:
        risk.append(
            f"opinia menedżera {_score(s.feedback_average)}" + _day(s.feedback_on)
        )
    if s.satisfaction is not None and s.satisfaction <= RISK_SATISFACTION_MAX:
        risk.append(f"zadowolenie {s.satisfaction}/5" + _day(s.satisfaction_on))
    if risk:
        return Health("risk", tuple(risk[:MAX_REASONS]))

    watch: list[str] = []
    if s.overdue_days > 0:
        watch.append(f"rozmowa zaległa {_days(s.overdue_days)}")
    if s.satisfaction is not None:
        dropped = (
            s.previous_satisfaction is not None
            and s.previous_satisfaction - s.satisfaction >= WATCH_SATISFACTION_DROP
        )
        if dropped:
            watch.append(
                f"zadowolenie spadło z {s.previous_satisfaction} na {s.satisfaction}"
            )
        elif s.satisfaction == WATCH_SATISFACTION:
            watch.append("zadowolenie 3/5" + _day(s.satisfaction_on))
    if ending and end_days <= WATCH_END_UNDECIDED_DAYS and not s.end_decided:
        watch.append(_end_phrase(s, end_days) + ", bez decyzji")
    if s.wants_change:
        watch.append("chce zmiany projektu" + _day(s.wants_change_on))
    silence = _silence_days(s)
    interval = CADENCE_INTERVAL_DAYS.get(s.cadence_level or "")
    if (
        silence is not None
        and interval is not None
        and silence > SILENCE_FACTOR * interval
    ):
        watch.append(f"brak rozmowy od {_days(silence)}")
    if watch:
        return Health("watch", tuple(watch[:MAX_REASONS]))

    if (
        s.last_conversation_on is None
        and s.start_on is not None
        and (s.today - s.start_on).days < NEW_CONTRACT_DAYS
    ):
        return Health("ok", ("brak rozmów",))
    return Health("ok")


def _silence_days(s: HealthSignals) -> Optional[int]:
    since = s.last_conversation_on or s.start_on
    if since is None or since > s.today:
        return None
    return (s.today - since).days


# ── Dane z bazy ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Satisfaction:
    value: int
    on: date
    previous: Optional[int]


async def last_satisfactions(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, _Satisfaction]:
    """Ostatnie i poprzednie zadowolenie z rozmów opiekuna (jedno zapytanie)."""

    if not contract_ids:
        return {}
    ranked = (
        select(
            CareConversation.contract_id,
            CareConversation.satisfaction,
            CareConversation.occurred_on,
            func.row_number()
            .over(
                partition_by=CareConversation.contract_id,
                order_by=(
                    CareConversation.occurred_on.desc(),
                    CareConversation.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(
            CareConversation.contract_id.in_(list(contract_ids)),
            CareConversation.satisfaction.is_not(None),
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                ranked.c.contract_id,
                ranked.c.satisfaction,
                ranked.c.occurred_on,
                ranked.c.rank,
            )
            .where(ranked.c.rank <= 2)
            .order_by(ranked.c.contract_id, ranked.c.rank)
        )
    ).all()
    out: dict[int, _Satisfaction] = {}
    for contract_id, value, occurred_on, rank in rows:
        if rank == 1:
            out[contract_id] = _Satisfaction(int(value), occurred_on, None)
        elif contract_id in out:
            first = out[contract_id]
            out[contract_id] = _Satisfaction(first.value, first.on, int(value))
    return out


async def _decided(
    db: AsyncSession, contract_ids: Sequence[int], today: date
) -> set[int]:
    """Kontrakty z decyzją o końcu: wpis w toku albo rozstrzygnięty, przekazanie."""

    if not contract_ids:
        return set()
    since = today - timedelta(days=DECISION_LOOKBACK_DAYS)
    decided = set(
        (
            await db.scalars(
                select(RedeployQueueItem.contract_id).where(
                    RedeployQueueItem.contract_id.in_(list(contract_ids)),
                    RedeployQueueItem.status.in_(("in_progress", "done", "dismissed")),
                    func.date(RedeployQueueItem.updated_at) >= since,
                )
            )
        ).all()
    )
    handed = await front_office.handoffs(db, contract_ids)
    decided |= {cid for cid, events in handed.items() if events}
    return decided


def _end_kind(contract: CareContract) -> str:
    if (
        contract.order_end_date is not None
        and contract.order_end_date == contract.end_date
    ):
        return "order"
    return "contract"


async def health_for(
    db: AsyncSession,
    contracts: Sequence[CareContract],
    *,
    today: date,
    overdue_days: Optional[Mapping[int, int]] = None,
    periods: Optional[Mapping[int, Sequence[Any]]] = None,
) -> dict[int, Optional[dict[str, Any]]]:
    """Zdrowie kontraktów hurtem (bez sprawdzania kręgu D11 — robi to wołający).

    ``overdue_days`` i ``periods`` może podać lista, która je już policzyła
    („Konsultanci”) — wtedy nie liczymy drugi raz.
    """

    ids = [contract.id for contract in contracts]
    if not ids:
        return {}
    if periods is None:
        periods = await care_plan.periods_by_contract(db, ids)
    if overdue_days is None:
        items = await care_plan.open_items(db, ids)
        latest = await care_plan.latest_conversations(db, ids)
        overdue_days = {}
        for contract in contracts:
            upcoming = care_plan.next_contact(
                items.get(contract.id, []), latest.get(contract.id), today
            )
            if upcoming is not None and upcoming.due_on < today:
                overdue_days[contract.id] = (today - upcoming.due_on).days
    active = await front_office.active_redeploy(db, ids)
    satisfaction = await last_satisfactions(db, ids)
    feedback = await client_feedback.last_by_contract(db, ids)
    talked = await care_plan.last_talk_days(db, ids)
    decided = await _decided(db, ids, today)

    out: dict[int, Optional[dict[str, Any]]] = {}
    for contract in contracts:
        entries = active.get(contract.id, [])
        risk_item = next((i for i in entries if i.reason == "attrition_risk"), None)
        change_item = next((i for i in entries if i.reason == "wants_change"), None)
        sat = satisfaction.get(contract.id)
        last = feedback.get(contract.id)
        level = None
        if contract.start_date is not None:
            level = level_on(
                contract.start_date, periods.get(contract.id, ()), today
            ).level
        result = assess(
            HealthSignals(
                today=today,
                live=contract.is_live,
                start_on=contract.start_date,
                end_on=contract.end_date,
                end_kind=_end_kind(contract),
                attrition_risk=risk_item is not None,
                attrition_risk_on=_created_day(risk_item),
                wants_change=change_item is not None,
                wants_change_on=_created_day(change_item),
                end_decided=contract.id in decided,
                feedback_average=last.average if last else None,
                feedback_on=last.held_on if last else None,
                satisfaction=sat.value if sat else None,
                satisfaction_on=sat.on if sat else None,
                previous_satisfaction=sat.previous if sat else None,
                overdue_days=overdue_days.get(contract.id, 0),
                last_conversation_on=talked.get(contract.id),
                cadence_level=level,
            )
        )
        out[contract.id] = result.as_dict() if result is not None else None
    return out


def _created_day(item: Optional[RedeployQueueItem]) -> Optional[date]:
    """Dzień założenia wpisu „Do przepięcia” (kalendarz firmy)."""

    if item is None or item.created_at is None:
        return None
    return item.created_at.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def health_for_contracts(
    db: AsyncSession, contract_ids: Iterable[int], *, viewer: User
) -> dict[int, Optional[dict[str, Any]]]:
    """Zdrowie po identyfikatorach; ``None`` poza D11 i poza zakresem klientów."""

    ids = sorted(set(contract_ids))
    if not care_access.reads_client_people(viewer):
        return {cid: None for cid in ids}
    contracts = await care_access.contracts_by_id(db, ids)
    allowed = await care_access.allowed_client_ids(viewer, db)
    visible = [
        contract
        for contract in contracts.values()
        if care_access.client_in_scope(contract.client_id, allowed)
    ]
    result = await health_for(db, visible, today=business_today())
    return {cid: result.get(cid) for cid in ids}
