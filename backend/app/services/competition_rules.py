"""Reguły rozliczania konkursów PŁATNYCH: termin zamknięcia i remisy.

Wyniesione z `competitions.py`, bo to nie są rankingi, tylko regulamin
wypłaty (audyt 22.09.2026, decyzje właściciela):

* **Termin zamknięcia** — okres zamrażamy dopiero od 3. polskiego dnia
  roboczego po jego końcu ORAZ (gdy sync Traffita jest włączony) po udanym
  dziennym imporcie, który ruszył PO końcu okresu. Autofreeze liczył wcześniej
  `date.today()` (UTC) i zamrażał 1. dnia o 02:00–03:00 w Warszawie, zanim
  nocny import (04:00) dowiózł ruchy z ostatniego dnia — w kwietniu przepadły.
* **Remisy** — pozycja nagrodzona nie może zależeć od numeru konta. Wyścig
  placementów rozstrzyga suma marży na godzinę, wyścig rekomendacji precyzja
  i moment dojścia do wyniku; czego regulamin nie rozstrzyga, rozstrzyga
  admin (status `tie_pending`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, is_business_day

if TYPE_CHECKING:  # pragma: no cover
    from app.services.competitions import RankedUser

logger = logging.getLogger(__name__)

_WARSAW = ZoneInfo(DEFAULT_TZ)

# Okres zamrażamy od N-tego dnia roboczego po jego końcu (decyzja 22.09.2026).
FREEZE_AFTER_BUSINESS_DAYS = 3

# Ile wierszy podium zapisuje freeze (rank 1..3 — CHECK w `competition_winners`).
PODIUM_ROWS = 3


# ── Termin zamknięcia ────────────────────────────────────────────────────


def nth_business_day_after(day: date, n: int = FREEZE_AFTER_BUSINESS_DAYS) -> date:
    """N-ty polski dzień roboczy PO `day` (sam `day` się nie liczy)."""
    cursor = day
    counted = 0
    while counted < n:
        cursor += timedelta(days=1)
        # Południe lokalne — ten sam idiom co `business_days_elapsed_in_month`.
        if is_business_day(datetime.combine(cursor, time(12), tzinfo=_WARSAW)):
            counted += 1
    return cursor


async def traffit_daily_ran_after(db: AsyncSession, boundary_utc: datetime) -> bool:
    """Czy dzienny import Traffita, który RUSZYŁ po `boundary_utc`, skończył się czysto.

    Czytamy `last_synced_at` znacznika `__daily__`: bieg bez błędów zapisuje
    tam swój START (watermark), a bieg z błędami zostawia poprzednią wartość
    (COALESCE w `_UPSERT_STATE`). `last_synced_at >= granica` znaczy więc
    dokładnie „udany bieg, który wystartował po końcu okresu". Pełny reconcile
    stempluje ten sam znacznik tym samym watermarkiem.
    """
    from app.models.traffit_sync_state import TraffitSyncState

    watermark = (
        await db.execute(
            select(TraffitSyncState.last_synced_at).where(
                TraffitSyncState.phase == "__daily__"
            )
        )
    ).scalar_one_or_none()
    return watermark is not None and watermark >= boundary_utc


@dataclass(frozen=True)
class FreezeReadiness:
    ready: bool
    reason: str
    earliest_day: date


async def freeze_readiness(
    db: AsyncSession,
    *,
    period_last_day: date,
    period_end_utc: datetime,
    today: date,
) -> FreezeReadiness:
    """Czy okres kończący się `period_last_day` wolno już zamrozić."""
    earliest = nth_business_day_after(period_last_day)
    if today < earliest:
        return FreezeReadiness(False, "waiting_business_days", earliest)
    if settings.TRAFFIT_SYNC_ENABLED and not await traffit_daily_ran_after(
        db, period_end_utc
    ):
        return FreezeReadiness(False, "waiting_traffit_daily_sync", earliest)
    return FreezeReadiness(True, "ready", earliest)


# ── Remisy ───────────────────────────────────────────────────────────────


@dataclass
class TieGroup:
    """Remis, którego regulamin nie rozstrzyga — decyduje admin.

    `positions` to miejsca podium (1..3), które remis blokuje; `user_ids` —
    wszyscy remisujący (może ich być więcej niż miejsc).
    """

    positions: list[int]
    user_ids: list[int]
    reason: str
    entries: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "positions": self.positions,
            "user_ids": self.user_ids,
            "reason": self.reason,
            "entries": self.entries,
        }


def order_with_ties(
    entries: Sequence["RankedUser"],
    *,
    primary: Callable[["RankedUser"], tuple],
    tiebreak: Optional[Callable[["RankedUser"], Optional[tuple]]],
    paid_slots: int,
    admin_on_tie: bool,
    reason: str,
) -> tuple[list["RankedUser"], list[TieGroup]]:
    """Kolejność nagrodowa + remisy na płatnych miejscach do decyzji admina.

    Klucze są „im większy, tym lepiej". `tiebreak` zwraca `None`, gdy dla
    danej osoby rozstrzygnięcia nie da się policzyć (np. brak marży) — wtedy
    cały remis obejmujący płatne miejsce idzie do admina. `user_id` jest
    wyłącznie ostatecznym porządkiem PREZENTACJI: nie decyduje o nagrodzie,
    gdy `admin_on_tie=True`.
    """

    def _tb(entry: "RankedUser") -> Optional[tuple]:
        return tiebreak(entry) if tiebreak is not None else None

    def _key(entry: "RankedUser") -> tuple:
        tb = _tb(entry)
        return (
            primary(entry),
            tb is not None,
            tb if tb is not None else (),
            -entry.user_id,
        )

    ordered = sorted(entries, key=_key, reverse=True)
    ties: list[TieGroup] = []
    if not admin_on_tie:
        return ordered, ties

    def _groups(items: list, key: Callable) -> list[tuple[int, list]]:
        """[(pozycja startowa 1-based, członkowie)] kolejnych równych kluczy."""
        out: list[tuple[int, list]] = []
        start = 0
        while start < len(items):
            stop = start + 1
            while stop < len(items) and key(items[stop]) == key(items[start]):
                stop += 1
            out.append((start + 1, items[start:stop]))
            start = stop
        return out

    for start, members in _groups(ordered, primary):
        if start > paid_slots or len(members) < 2:
            continue
        tbs = [_tb(m) for m in members]
        if tiebreak is None or any(tb is None for tb in tbs):
            unresolved = [(start, members)]
        else:
            unresolved = [
                (sub_start, sub)
                for sub_start, sub in _groups(members, lambda m: _tb(m))
                if len(sub) > 1
            ]
            unresolved = [(start + sub_start - 1, sub) for sub_start, sub in unresolved]
        for group_start, group in unresolved:
            if group_start > paid_slots:
                continue
            last = min(group_start + len(group) - 1, PODIUM_ROWS)
            ties.append(
                TieGroup(
                    positions=list(range(group_start, last + 1)),
                    user_ids=[m.user_id for m in group],
                    reason=reason,
                    entries=[m.to_dict() for m in group],
                )
            )
    return ordered, ties


# ── Wyścig placementów: suma marży na godzinę ────────────────────────────


async def placement_margin_per_hour_by_user(
    db: AsyncSession,
    *,
    user_ids: Sequence[int],
    start: datetime,
    end: datetime,
) -> dict[int, dict]:
    """Suma marży/h (PLN) z placementów zaliczonych danej osobie w oknie.

    Placementy to TE SAME wiersze, które liczy wyścig (`VERIFIER_ANCHORED_CTE`,
    etap `hired`). Marża/h jednego placementu = stawka klienta − stawka
    kandydata z kontraktu tej osoby u klienta rekrutacji, obowiązujące w dniu
    placementu — liczona `fold_money` + `margin_per_hour`, czyli tą samą
    funkcją co kafel Rady (jednostki, harmonogramy, kursy NBP). `None` sumy =
    przynajmniej jeden placement bez policzalnej marży.
    """
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job
    from app.services.contract_rates import RATE_SCHEDULE_LOADS
    from app.services.fx_service import rates_to_pln_by_date
    from app.services.insights_board_money import fold_money, margin_per_hour
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    if not user_ids:
        return {}
    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                SELECT c.credit_user, c.candidate_id, c.job_id, c.reached_at
                FROM credited c
                WHERE c.stage = 'hired'
                  AND c.reached_at >= :start
                  AND c.reached_at < :end
                  AND c.credit_user = ANY(:uids)
                ORDER BY c.credit_user, c.reached_at, c.candidate_id
                """
            ),
            {"start": start, "end": end, "uids": list(user_ids)},
        )
    ).all()
    if not rows:
        return {
            uid: {"margin_per_hour_sum": None, "placements": []} for uid in user_ids
        }

    job_ids = {r.job_id for r in rows}
    candidate_ids = {r.candidate_id for r in rows}
    job_clients = dict(
        (
            await db.execute(select(Job.id, Job.client_id).where(Job.id.in_(job_ids)))
        ).all()
    )
    contracts = (
        (
            await db.execute(
                select(Contract)
                # `fold_money` liczy też headcount po `Contract.candidate` —
                # bez eager-loadu lazy-load w sesji async to MissingGreenlet.
                .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
                .where(
                    Contract.candidate_id.in_(candidate_ids),
                    Contract.status != ContractStatus.void,
                )
            )
        )
        .scalars()
        .all()
    )

    def _contract_for(candidate_id: int, job_id: int, on: date) -> Optional[Contract]:
        client_id = job_clients.get(job_id)
        pool = [
            c
            for c in contracts
            if c.candidate_id == candidate_id
            and (
                c.job_id == job_id
                or (client_id is not None and c.client_id == client_id)
            )
        ]
        if not pool:
            return None
        # Kontrakt tej rekrutacji wygrywa; potem ten, który obowiązywał
        # najpóźniej przed dniem placementu; ostatecznie najnowszy wiersz.
        return max(
            pool,
            key=lambda c: (
                c.job_id == job_id,
                c.start_date is not None and c.start_date <= on,
                c.start_date or date.min,
                c.id,
            ),
        )

    placements: list[tuple[int, date, Optional[Contract], int, int]] = []
    for r in rows:
        on = r.reached_at.astimezone(_WARSAW).date()
        placements.append(
            (
                r.credit_user,
                on,
                _contract_for(r.candidate_id, r.job_id, on),
                r.candidate_id,
                r.job_id,
            )
        )
    currencies_by_date: dict[date, set[str]] = {}
    for _uid, on, contract, _cid, _jid in placements:
        if contract is None:
            continue
        currencies_by_date.setdefault(on, set()).update(
            {
                contract.resolved_rate_client_currency,
                contract.resolved_rate_candidate_currency,
            }
        )
    rates_by_date = await rates_to_pln_by_date(db, currencies_by_date)

    out: dict[int, dict] = {
        uid: {"margin_per_hour_sum": Decimal("0"), "placements": []} for uid in user_ids
    }
    for uid, on, contract, candidate_id, job_id in placements:
        value: Optional[float] = None
        if contract is not None:
            fold = fold_money([contract], on, rates_by_date.get(on, {}))
            if fold.complete:
                value = margin_per_hour(fold)
        bucket = out.setdefault(
            uid, {"margin_per_hour_sum": Decimal("0"), "placements": []}
        )
        bucket["placements"].append(
            {
                "candidate_id": candidate_id,
                "job_id": job_id,
                "date": on.isoformat(),
                "contract_id": contract.id if contract is not None else None,
                "margin_per_hour": value,
            }
        )
        if value is None or bucket["margin_per_hour_sum"] is None:
            bucket["margin_per_hour_sum"] = None
        else:
            bucket["margin_per_hour_sum"] += Decimal(str(value))
    for bucket in out.values():
        if not bucket["placements"]:
            bucket["margin_per_hour_sum"] = None
    return out


def margin_tiebreak(entry: "RankedUser") -> Optional[tuple]:
    value = entry.extras.get("margin_per_hour_sum")
    if value is None:
        return None
    # Porównanie „do grosza".
    return (Decimal(str(value)).quantize(Decimal("0.01")),)


# ── Wyścig rekomendacji: precyzja, potem moment dojścia do wyniku ────────


async def last_recommendation_at_by_user(
    db: AsyncSession,
    *,
    user_ids: Sequence[int],
    start: datetime,
    end: datetime,
) -> dict[int, datetime]:
    """Moment ostatniej zaliczonej rekomendacji (`cv_sent`) w oknie."""
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    if not user_ids:
        return {}
    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                SELECT c.credit_user, max(c.reached_at) AS last_at
                FROM credited c
                WHERE c.stage = 'cv_sent'
                  AND c.reached_at >= :start
                  AND c.reached_at < :end
                  AND c.credit_user = ANY(:uids)
                GROUP BY c.credit_user
                """
            ),
            {"start": start, "end": end, "uids": list(user_ids)},
        )
    ).all()
    return {r.credit_user: r.last_at for r in rows}


def recommendation_tiebreak(entry: "RankedUser") -> tuple:
    """Wyższa precyzja, potem WCZEŚNIEJSZE dojście do końcowego wyniku."""
    verified = int(entry.extras.get("verifications") or 0)
    recommendations = int(entry.extras.get("recommendations") or 0)
    precision = Fraction(recommendations, verified) if verified else Fraction(0)
    last_at = entry.extras.get("last_recommendation_at")
    # „Większy lepszy": wcześniejszy moment = mniejszy timestamp → minus.
    ts = -datetime.fromisoformat(last_at).timestamp() if last_at else float("-inf")
    return (precision, ts)
