"""Cykl życia szansy — reguły przeniesione z Atlasa (``src/services/deal_lifecycle.py``).

* Etap z wynikiem ``won`` ustawia status ``won`` i ``won_at`` (tylko przy
  pierwszym wejściu w wygraną) i czyści ``lost_at``; ``lost`` lustrzanie;
  etap otwarty czyści obie daty i przywraca ``open``.
* Prawdopodobieństwo szansy idzie za etapem.
* Kwalifikacja: wejście na etap ``qualifies`` albo dalej (pozycja ≥ pierwszego
  takiego etapu, poza przegraną) albo na wygraną ustawia ``qualified_at``
  raz — cofnięcie szansy go nie czyści.

Moduł jest czysty (bez bazy): wywołujący podaje etapy lejka.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol


class StageLike(Protocol):
    id: int
    position: int
    probability: int
    outcome: str
    qualifies: bool


class OpportunityLike(Protocol):
    stage_id: int
    status: str
    probability: int
    won_at: Optional[datetime]
    lost_at: Optional[datetime]
    qualified_at: Optional[datetime]


def qualification_position(stages: Sequence[StageLike]) -> Optional[int]:
    positions = [stage.position for stage in stages if stage.qualifies]
    return min(positions) if positions else None


def apply_stage(
    opportunity: OpportunityLike,
    stage: StageLike,
    stages: Sequence[StageLike],
    *,
    now: datetime,
) -> None:
    """Ustaw szansę na etapie ``stage`` z kompletem skutków ubocznych."""

    previous = opportunity.status
    opportunity.stage_id = stage.id
    opportunity.probability = stage.probability
    if stage.outcome == "won":
        opportunity.status = "won"
        if previous != "won" or opportunity.won_at is None:
            opportunity.won_at = now
        opportunity.lost_at = None
    elif stage.outcome == "lost":
        opportunity.status = "lost"
        if previous != "lost" or opportunity.lost_at is None:
            opportunity.lost_at = now
        opportunity.won_at = None
    else:
        opportunity.status = "open"
        opportunity.won_at = None
        opportunity.lost_at = None

    if opportunity.qualified_at is None:
        line = qualification_position(stages)
        reached = stage.outcome == "won" or (
            line is not None and stage.outcome != "lost" and stage.position >= line
        )
        if reached:
            opportunity.qualified_at = now


def deal_value(
    mrr_value: Optional[Decimal],
    one_off_value: Optional[Decimal],
    explicit: Optional[Decimal],
) -> Optional[Decimal]:
    """Wartość szansy: jawnie podana albo MRR + jednorazowa — jak w Atlasie."""

    if explicit is not None:
        return explicit
    if mrr_value is None and one_off_value is None:
        return None
    return (mrr_value or Decimal(0)) + (one_off_value or Decimal(0))
