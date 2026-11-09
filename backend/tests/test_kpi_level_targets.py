"""Poziom rekrutera a cel placementów (decyzja Artura 09.11.2026).

Junior 1, Senior 2, Expert 3. Senior: 6 placementów w 6 miesięcy albo 12 w 12,
także 6 w jednym miesiącu. Expert: 12 w 6 albo 24 w 12, liczone od miesiąca
po awansie na Seniora. Cel rośnie od miesiąca po awansie i nigdy nie spada.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.kpi_target import UserKpiTarget
from app.models.kpi_target_event import KpiTargetEvent
from app.models.user import UserRole
from app.services.hr.bonus_rules import DoubleBonusRule
from app.services.insights_seniority import (
    DEFAULT_THRESHOLDS,
    SeniorityThresholds,
    _resolve_levels,
    compute_seniority,
)
from app.services.kpi_level_targets import (
    AUTOMATION_ACTOR_NAME,
    apply_level_targets,
    double_bonus_pending,
    level_floor_for_target,
    planned_raises,
    promotion_cutoff,
    target_level_floors,
)
from tests.test_insights_seniority import SEED_YEAR, _seed_placements, _seed_user

RULES = SeniorityThresholds(
    senior_placements=DEFAULT_THRESHOLDS["seniority_senior_placements"],
    senior_window_months=DEFAULT_THRESHOLDS["seniority_senior_window_months"],
    expert_placements=DEFAULT_THRESHOLDS["seniority_expert_placements"],
    expert_window_months=DEFAULT_THRESHOLDS["seniority_expert_window_months"],
    senior_alt_placements=DEFAULT_THRESHOLDS["seniority_senior_alt_placements"],
    senior_alt_window_months=DEFAULT_THRESHOLDS["seniority_senior_alt_window_months"],
    expert_alt_placements=DEFAULT_THRESHOLDS["seniority_expert_alt_placements"],
    expert_alt_window_months=DEFAULT_THRESHOLDS["seniority_expert_alt_window_months"],
)
JUNE = 2026 * 12 + 5


def test_thresholds_are_the_ones_from_the_decision():
    assert (RULES.senior_placements, RULES.senior_window_months) == (6, 6)
    assert (RULES.senior_alt_placements, RULES.senior_alt_window_months) == (12, 12)
    assert (RULES.expert_placements, RULES.expert_window_months) == (12, 6)
    assert (RULES.expert_alt_placements, RULES.expert_alt_window_months) == (24, 12)


def test_six_placements_in_a_single_month_make_a_senior():
    assert _resolve_levels({JUNE: 6}, RULES) == ("senior", JUNE, None)


def test_five_placements_stay_junior():
    assert _resolve_levels({JUNE: 5}, RULES) == ("junior", None, None)


def test_twelve_in_twelve_months_make_a_senior():
    counts = {JUNE + i: 1 for i in range(12)}
    level, senior_since, _ = _resolve_levels(counts, RULES)
    assert level == "senior"
    assert senior_since == JUNE + 5, "6 w 6 miesięcy spełnia próg wcześniej"


def test_placements_from_the_promotion_month_do_not_count_towards_expert():
    assert _resolve_levels({JUNE: 18}, RULES) == ("senior", JUNE, None)


def test_expert_counts_from_the_month_after_the_promotion():
    assert _resolve_levels({JUNE: 6, JUNE + 1: 11}, RULES)[0] == "senior"
    assert _resolve_levels({JUNE: 6, JUNE + 1: 12}, RULES) == (
        "expert",
        JUNE,
        JUNE + 1,
    )


def test_twenty_four_in_twelve_months_make_an_expert():
    counts = {JUNE: 6, **{JUNE + 1 + i: 2 for i in range(12)}}
    level, _, expert_since = _resolve_levels(counts, RULES)
    assert (level, expert_since) == ("expert", JUNE + 6)


@pytest.mark.parametrize(
    ("target", "floor"),
    [(None, None), (0, None), (1, None), (2, "senior"), (3, "expert"), (5, "expert")],
)
def test_level_floor_follows_the_personal_target(target, floor):
    assert level_floor_for_target(target) == floor


def test_promotion_counts_up_to_the_end_of_the_previous_month():
    assert promotion_cutoff(date(2026, 12, 1)) == date(2026, 11, 30)
    assert promotion_cutoff(date(2026, 12, 19)) == date(2026, 11, 30)
    assert promotion_cutoff(date(2027, 1, 2)) == date(2026, 12, 31)


def test_planned_raises_only_go_up():
    levels = {1: "junior", 2: "senior", 3: "expert", 4: "senior", 5: "expert"}
    overrides = {3: 2, 4: 3, 5: 3}
    assert planned_raises(levels, overrides) == {2: 2, 3: 3}


def test_a_deliberate_zero_target_is_left_alone():
    assert planned_raises({1: "expert"}, {1: 0}) == {}


def _double(*months: tuple[int, int]) -> DoubleBonusRule:
    return DoubleBonusRule(
        months=months,
        verifications_per_day=4,
        precision_pct=75,
        dl_min_margin=50,
    )


def test_raise_waits_until_the_double_bonus_month_is_settled():
    cutoff = date(2026, 11, 30)
    rule = _double((2026, 11), (2026, 12))
    assert double_bonus_pending(rule, {}, cutoff) == "2026-11"
    assert double_bonus_pending(rule, {"2026-11": {}}, cutoff) is None


def test_month_outside_the_double_bonus_program_does_not_wait():
    rule = _double((2026, 11))
    assert double_bonus_pending(rule, {}, date(2027, 1, 31)) is None
    assert double_bonus_pending(None, {}, date(2026, 11, 30)) is None


async def _cleanup(*user_ids: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(UserKpiTarget).where(UserKpiTarget.user_id.in_(user_ids))
        )
        await db.execute(
            delete(KpiTargetEvent).where(KpiTargetEvent.subject_user_id.in_(user_ids))
        )
        await db.commit()


@pytest.mark.asyncio
async def test_target_rises_the_month_after_the_promotion_and_leaves_a_trace():
    user_id = await _seed_user(UserRole.recruiter, "lvl-target")
    await _seed_placements(user_id, [6] * 6)
    try:
        async with AsyncSessionLocal() as db:
            await apply_level_targets(db, today=date(SEED_YEAR, 6, 20))
        async with AsyncSessionLocal() as db:
            before = await db.scalar(
                select(UserKpiTarget.target_value).where(
                    UserKpiTarget.user_id == user_id
                )
            )
        assert before is None, "cel nie może wzrosnąć w miesiącu awansu"

        async with AsyncSessionLocal() as db:
            await apply_level_targets(db, today=date(SEED_YEAR, 7, 1))
            await apply_level_targets(db, today=date(SEED_YEAR, 7, 2))
        async with AsyncSessionLocal() as db:
            stored = await db.scalar(
                select(UserKpiTarget.target_value).where(
                    UserKpiTarget.user_id == user_id,
                    UserKpiTarget.kpi_id == "monthly_placements",
                )
            )
            events = (
                await db.execute(
                    select(KpiTargetEvent).where(
                        KpiTargetEvent.subject_user_id == user_id
                    )
                )
            ).scalars()
            events = list(events)
        assert stored == 2
        assert len(events) == 1, "drugi przebieg nie może dopisać historii"
        assert events[0].actor_user_id is None
        assert events[0].actor_name == AUTOMATION_ACTOR_NAME
        assert events[0].changes == {"target_value": {"from": None, "to": 2}}
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_person_with_expert_target_shows_as_expert_without_placements():
    user_id = await _seed_user(UserRole.recruiter, "lvl-floor")
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                UserKpiTarget(
                    user_id=user_id, kpi_id="monthly_placements", target_value=3
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            as_of = date(SEED_YEAR, 12, 31)
            plain = await compute_seniority(db, as_of=as_of, thresholds=RULES)
            floored = await compute_seniority(
                db,
                as_of=as_of,
                thresholds=RULES,
                level_floors=await target_level_floors(db),
            )
        assert next(r for r in plain.rows if r.user_id == user_id).level == "junior"
        row = next(r for r in floored.rows if r.user_id == user_id)
        assert row.level == "expert"
        assert row.expert_since is None
        assert row.placements_to_next_level is None
    finally:
        await _cleanup(user_id)
