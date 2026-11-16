"""Jedna kolejność kart od systemu: Tablica, ekran porcji i podział w zespole.

Audyt z 08.11.2026 (P7, S-C4). Ekran porcji sortował po samym wyniku, a Tablica
po wyniku z punktami „znamy tę osobę” i z miejscami dla nowych, więc ta sama
karta miała inne miejsce na dwóch ekranach. Punkty podniosły trafienia w top 20
z 32% do 38% (``docs/claude/rekrutacja-tablica/kolejka-w-nowych.md``).

``order_cards`` to lustro ``orderNewColumn`` z ``frontend/src/lib/new-column-queue.ts``.
Brak krytycznej czytamy z migawki ``entry_meta.missing_must``: Tablica ma go
z ``pipeline_base_fit``, a ta trasa trwa kilka sekund i nie nadaje się do kolejki.

Premia porcji zmienia tylko kolejność, procent na karcie zostaje, i działa
wyłącznie przy włączonej porcji (flaga ``REVIEW_BATCH_ENABLED``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.job import Job

if TYPE_CHECKING:
    from app.services.known_queue_points import KnownFacts
    from app.services.review_batch import PendingCard

ACTIVE_BONUS = 5
IN_BUDGET_BONUS = 3
ACTIVE_STATUS = "actively_looking"
# Polski nieojczysty i „brak danych” w rekrutacji wymagającej polskiego idą dalej
# (pomiar 16.11.2026 na 1 948 decyzjach od 15.10: ojczysty 61% „Pasuje”, poziom
# w profilu 34%, brak danych 42%; w obrębie rekrutacji-dnia górna połowa kart
# 13.11 i 16.11 z 50,2% do 57,1%). Nikt nie wypada: od 15.10 19 takich osób
# doszło do klienta. Kara nasyca się przy tych wartościach.
POLISH_LEVEL_PENALTY = 8
POLISH_UNKNOWN_PENALTY = 5
# Rekrutacja na lidera, osoba wykonawca: dalej w kolejce (``role_family.leader_gap``).
# Na decyzjach od 15.10 „Pasuje” w górnej połowie bez zmian, do klienta 83 → 85.
LEADER_GAP_PENALTY = 5


@dataclass(frozen=True)
class Bonus:
    active: bool = False
    in_budget: bool = False
    polish: Optional[str] = None
    leader_gap: bool = False

    @property
    def points(self) -> int:
        return (
            (ACTIVE_BONUS if self.active else 0)
            + (IN_BUDGET_BONUS if self.in_budget else 0)
            - polish_penalty(self.polish)
            - (LEADER_GAP_PENALTY if self.leader_gap else 0)
        )


def polish_penalty(state: Optional[str]) -> int:
    if state in ("level", "no"):
        return POLISH_LEVEL_PENALTY
    if state == "unknown":
        return POLISH_UNKNOWN_PENALTY
    return 0


@dataclass(frozen=True)
class OrderFacts:
    known: Optional["KnownFacts"] = None
    bonus: Bonus = Bonus()
    fresh_first: bool = False
    fresh: bool = False


def rate_in_budget(rate, currency, budget_hourly: Optional[float]) -> bool:
    """Znana stawka w PLN nie wyższa niż budżet. Stawka poniżej
    ``_MIN_PLAUSIBLE_RATE`` to literówka, więc premii nie daje."""
    from app.services.new_column_autofill import _MIN_PLAUSIBLE_RATE

    if rate is None or budget_hourly is None:
        return False
    if str(currency or "").strip().upper() != "PLN":
        return False
    try:
        amount = Decimal(str(rate))
    except InvalidOperation:
        return False
    return _MIN_PLAUSIBLE_RATE <= amount <= Decimal(str(budget_hourly))


def bonus_for(
    availability_status,
    rate,
    currency,
    budget_hourly: Optional[float],
    polish: Optional[str] = None,
    leader_gap: bool = False,
) -> Bonus:
    from app.services import review_batch

    if not review_batch.enabled():
        return Bonus()
    status = getattr(availability_status, "value", availability_status)
    return Bonus(
        active=status == ACTIVE_STATUS,
        in_budget=rate_in_budget(rate, currency, budget_hourly),
        polish=polish,
        leader_gap=leader_gap,
    )


def queue_value(card: "PendingCard") -> float:
    facts = card.facts if isinstance(card.facts, OrderFacts) else OrderFacts()
    known = facts.known.points if facts.known is not None else 0
    return card.score + known + facts.bonus.points


def _tier(card: "PendingCard") -> int:
    if card.missing_must:
        return 2
    if card.cautions:
        return 1
    return -1 if isinstance(card.facts, OrderFacts) and card.facts.fresh_first else 0


def order_cards(cards: list["PendingCard"]) -> list["PendingCard"]:
    """Kolejność czekających kart jak w kolumnie „Nowi”: nowi w bazie od progu,
    bez uwag (co 5. miejsce dla osoby bez procesu), z ostrzeżeniem, z brakiem."""
    from app.services.new_column_autofill import with_fresh_slots

    ranked = sorted(cards, key=lambda c: (_tier(c), -queue_value(c), c.candidate_id))
    first = [card for card in ranked if _tier(card) < 0]
    clean = [card for card in ranked if _tier(card) == 0]
    late = [card for card in ranked if _tier(card) > 0]
    fresh = {
        card.candidate_id
        for card in clean
        if isinstance(card.facts, OrderFacts) and card.facts.fresh
    }
    return [*first, *with_fresh_slots(clean, fresh, start=len(first)), *late]


async def with_order_facts(
    db, job: Job, cards: list["PendingCard"], *, now: datetime
) -> list["PendingCard"]:
    """Dokłada do kart te same fakty, które Tablica liczy przy odczycie."""
    from app.services import known_queue_points, new_column_autofill
    from app.services.candidate_added_date import added_to_base
    from app.services.dealbreaker_filters import resolve_job_budget_hourly
    from app.services.job_proposals import proposal_threshold

    if not cards:
        return []
    candidate_ids = [card.candidate_id for card in cards]
    known = await known_queue_points.facts_for(
        db, job_id=job.id, client_id=job.client_id, candidate_ids=candidate_ids, now=now
    )
    without_process = await known_queue_points.without_process(
        db, job_id=job.id, candidate_ids=candidate_ids
    )
    threshold = await proposal_threshold(db)
    people = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.created_at,
                Candidate.source_created_at,
                Candidate.external_source,
                *_SIGNAL_COLUMNS,
            ).where(Candidate.id.in_(candidate_ids))
        )
    ).all()
    added = {
        row.id: added_to_base(
            row.created_at, row.source_created_at, row.external_source
        )
        for row in people
    }
    signals = await order_signals_if_enabled(db, job, people)
    budget = resolve_job_budget_hourly(job)
    enriched = []
    for card in cards:
        in_base = added.get(card.candidate_id)
        facts = OrderFacts(
            known=known.get(card.candidate_id),
            bonus=bonus_for(
                card.availability_status,
                card.rate_from_hourly,
                card.rate_currency,
                budget,
                *signals.get(card.candidate_id, (None, False)),
            ),
            fresh_first=in_base is not None
            and new_column_autofill.has_fresh_first(
                {"score": card.score, "cautions": list(card.cautions)},
                in_base,
                threshold=threshold,
                now=now,
            ),
            fresh=card.candidate_id in without_process,
        )
        enriched.append(replace(card, facts=facts))
    return enriched


async def pick_bonuses(db, job_id: int, picks: list) -> dict[int, int]:
    """Premia porcji dla osób jeszcze bez karty (kolejność w ``ranked_picks``)."""
    from app.services import review_batch
    from app.services.candidate_rate_from import (
        effective_currency_sql,
        effective_rate_sql,
    )
    from app.services.dealbreaker_filters import resolve_job_budget_hourly

    if not review_batch.enabled() or not picks:
        return {}
    job = await db.get(Job, job_id)
    budget = resolve_job_budget_hourly(job) if job is not None else None
    rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.availability_status,
                effective_rate_sql(Candidate).label("rate"),
                effective_currency_sql(Candidate).label("currency"),
                *_SIGNAL_COLUMNS,
            ).where(Candidate.id.in_([p.candidate_id for p in picks]))
        )
    ).all()
    signals = await order_signals_if_enabled(db, job, rows) if job is not None else {}
    out: dict[int, int] = {}
    for row in rows:
        out[row.id] = bonus_for(
            row.availability_status,
            row.rate,
            row.currency,
            budget,
            *signals.get(row.id, (None, False)),
        ).points
    return out


# Kolumny osoby potrzebne do sygnałów kolejności (polski, lider/wykonawca).
_SIGNAL_COLUMNS = (
    Candidate.name,
    Candidate.lastname,
    Candidate.cv_language,
    Candidate.cv_extracted_data,
    Candidate.linkedin_current_title,
    Candidate.linkedin_current_company,
    Candidate.experience,
)


async def order_signals_if_enabled(
    db, job, people
) -> dict[int, tuple[Optional[str], bool]]:
    """``{candidate_id: (stan polskiego, lider/wykonawca)}`` tylko przy włączonej
    porcji — bez niej kolejność jak przed 16.11.2026."""
    from app.services import review_batch
    from app.services.review_batch_facts import polish_states
    from app.services.role_family import current_position, leader_gap

    if not review_batch.enabled():
        return {}
    people = list(people)
    polish = await polish_states(db, job, people)
    title = getattr(job, "title", None)
    return {
        p.id: (polish.get(p.id), leader_gap(title, current_position(p))) for p in people
    }


async def order_signals_for_ids(
    db, job, candidate_ids: list[int]
) -> dict[int, tuple[Optional[str], bool]]:
    """Jak ``order_signals_if_enabled``, gdy w ręku są same id (Tablica)."""
    from app.services import review_batch

    if not review_batch.enabled() or not candidate_ids or job is None:
        return {}
    people = (
        await db.execute(
            select(Candidate.id, *_SIGNAL_COLUMNS).where(
                Candidate.id.in_(candidate_ids)
            )
        )
    ).all()
    return await order_signals_if_enabled(db, job, people)
