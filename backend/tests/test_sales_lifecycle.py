"""Cykl życia szansy (reguły z Atlasa) — bez bazy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.services.sales.lifecycle import apply_stage, deal_value
from app.services.sales_schema import DEFAULT_STAGES

T1 = datetime(2026, 10, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 5, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 9, tzinfo=timezone.utc)


@dataclass
class Stage:
    id: int
    position: int
    probability: int
    outcome: str
    qualifies: bool


@dataclass
class Opp:
    stage_id: int = 0
    status: str = "open"
    probability: int = 0
    won_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None
    qualified_at: Optional[datetime] = None


STAGES = [
    Stage(id=index + 1, position=index, probability=prob, outcome=outcome, qualifies=q)
    for index, (_key, _name, prob, outcome, q) in enumerate(DEFAULT_STAGES)
]
BY_KEY = {key: STAGES[i] for i, (key, *_rest) in enumerate(DEFAULT_STAGES)}


def test_open_stage_before_the_line_does_not_qualify() -> None:
    opp = Opp()
    apply_stage(opp, BY_KEY["qualifying-meeting"], STAGES, now=T1)
    assert (opp.status, opp.probability, opp.qualified_at) == ("open", 20, None)


def test_qualification_is_set_once_and_survives_moving_back() -> None:
    opp = Opp()
    apply_stage(opp, BY_KEY["offer-sent"], STAGES, now=T1)
    assert opp.qualified_at == T1
    apply_stage(opp, BY_KEY["lead"], STAGES, now=T2)
    assert opp.qualified_at == T1
    apply_stage(opp, BY_KEY["qualified"], STAGES, now=T3)
    assert opp.qualified_at == T1


def test_lost_stage_past_the_line_does_not_qualify() -> None:
    """„Niezakwalifikowany” stoi za linią kwalifikacji, ale to przegrana."""
    opp = Opp()
    apply_stage(opp, BY_KEY["not-qualified"], STAGES, now=T1)
    assert (opp.status, opp.lost_at, opp.qualified_at) == ("lost", T1, None)


def test_won_stamps_once_and_reopen_clears_dates() -> None:
    opp = Opp()
    apply_stage(opp, BY_KEY["won"], STAGES, now=T1)
    assert (opp.status, opp.won_at, opp.probability) == ("won", T1, 100)
    assert opp.qualified_at == T1
    apply_stage(opp, BY_KEY["won"], STAGES, now=T2)
    assert opp.won_at == T1
    apply_stage(opp, BY_KEY["offer-sent"], STAGES, now=T3)
    assert (opp.status, opp.won_at, opp.lost_at) == ("open", None, None)


def test_won_after_lost_clears_lost_at() -> None:
    opp = Opp()
    apply_stage(opp, BY_KEY["lost"], STAGES, now=T1)
    apply_stage(opp, BY_KEY["won"], STAGES, now=T2)
    assert (opp.status, opp.won_at, opp.lost_at) == ("won", T2, None)


def test_lost_again_keeps_the_first_lost_date() -> None:
    opp = Opp()
    apply_stage(opp, BY_KEY["lost"], STAGES, now=T1)
    apply_stage(opp, BY_KEY["not-qualified"], STAGES, now=T2)
    assert opp.lost_at == T1


def test_value_is_explicit_or_mrr_plus_one_off() -> None:
    assert deal_value(None, None, None) is None
    assert deal_value(Decimal("10000"), Decimal("5000"), None) == Decimal("15000")
    assert deal_value(Decimal("10000"), None, Decimal("1")) == Decimal("1")
