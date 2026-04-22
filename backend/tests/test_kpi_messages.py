"""Unit tests for app.services.kpi_messages — pure render logic, no DB."""

from __future__ import annotations

from app.models.kpi_nudge_log import KpiNudgeType
from app.services.kpi_messages import (
    render,
    select_reminder_variant,
)


# ── select_reminder_variant ────────────────────────────────────────────────


def test_select_reminder_variant_zero_is_gentle():
    assert select_reminder_variant(0) == 0


def test_select_reminder_variant_one_is_firm():
    assert select_reminder_variant(1) == 1


def test_select_reminder_variant_caps_at_last_call():
    assert select_reminder_variant(2) == 2
    assert select_reminder_variant(5) == 2
    assert select_reminder_variant(100) == 2


def test_select_reminder_variant_handles_negative_defensively():
    assert select_reminder_variant(-1) == 0


# ── render: praise_hit ─────────────────────────────────────────────────────


def _render_praise(kpi_id: str = "daily_activity_count"):
    return render(
        nudge_type=KpiNudgeType.praise_hit,
        kpi_id=kpi_id,
        kpi_title_pl="Aktywności dziś",
        user_id=42,
        user_name="Anna Kowalska",
        user_email="anna@b2bnet.pl",
        current=12,
        target=10,
        progress_pct=120.0,
        period_bucket="2026-04-22",
    )


def test_render_praise_hit_includes_first_name():
    msg = _render_praise()
    assert "Anna" in msg.body
    assert msg.tone == "praise"


def test_render_praise_hit_substitutes_current_and_target():
    msg = _render_praise()
    assert "12" in msg.body
    assert "10" in msg.body


def test_render_praise_hit_is_deterministic_per_bucket():
    m1 = _render_praise()
    m2 = _render_praise()
    assert m1.variant == m2.variant
    assert m1.title == m2.title


def test_render_praise_hit_different_buckets_can_differ_or_match():
    # Deterministic per (user, kpi, bucket) — different buckets may or may
    # not hit the same variant but must be deterministic.
    a = render(
        nudge_type=KpiNudgeType.praise_hit,
        kpi_id="daily_activity_count",
        kpi_title_pl="X",
        user_id=1,
        user_name="A",
        user_email="a@x",
        current=10,
        target=10,
        progress_pct=100.0,
        period_bucket="2026-04-22",
    )
    a2 = render(
        nudge_type=KpiNudgeType.praise_hit,
        kpi_id="daily_activity_count",
        kpi_title_pl="X",
        user_id=1,
        user_name="A",
        user_email="a@x",
        current=10,
        target=10,
        progress_pct=100.0,
        period_bucket="2026-04-22",
    )
    assert a.variant == a2.variant  # same bucket → same variant


def test_render_praise_hit_unknown_kpi_falls_back_to_generic():
    msg = render(
        nudge_type=KpiNudgeType.praise_hit,
        kpi_id="__nonexistent__",
        kpi_title_pl="Custom KPI",
        user_id=1,
        user_name="Jan Nowak",
        user_email="jan@x.pl",
        current=5,
        target=5,
        progress_pct=100.0,
        period_bucket="2026-04-22",
    )
    assert "Jan" in msg.body
    # Generic template mentions the title_pl
    assert "Custom KPI" in msg.body


def test_render_first_name_fallback_to_email_local_part():
    msg = render(
        nudge_type=KpiNudgeType.praise_hit,
        kpi_id="daily_activity_count",
        kpi_title_pl="X",
        user_id=1,
        user_name="   ",  # empty/whitespace
        user_email="jsmith@corp.com",
        current=10,
        target=10,
        progress_pct=100.0,
        period_bucket="2026-04-22",
    )
    assert "jsmith" in msg.body


# ── render: remind_behind (forced variants = escalation) ───────────────────


def _render_remind(forced_variant: int, kpi_id: str = "daily_activity_count"):
    return render(
        nudge_type=KpiNudgeType.remind_behind,
        kpi_id=kpi_id,
        kpi_title_pl="Aktywności dziś",
        user_id=42,
        user_name="Anna",
        user_email="anna@b2bnet.pl",
        current=2,
        target=10,
        progress_pct=20.0,
        period_bucket="2026-04-22",
        forced_variant=forced_variant,
    )


def test_render_remind_escalation_variant_0_gentle():
    msg = _render_remind(0)
    assert msg.variant == 0
    assert msg.tone == "remind"


def test_render_remind_escalation_variant_1_firm():
    msg = _render_remind(1)
    assert msg.variant == 1


def test_render_remind_escalation_variant_2_last_call():
    msg = _render_remind(2)
    assert msg.variant == 2


def test_render_remind_forced_variant_clamps_to_available():
    # Should not raise even when caller passes out-of-range index.
    msg = _render_remind(99)
    assert 0 <= msg.variant <= 2


def test_render_remind_includes_remaining():
    msg = _render_remind(0)
    assert "8" in msg.body  # target 10 - current 2 = 8 remaining


# ── render: eod_summary ────────────────────────────────────────────────────


def test_render_eod_summary_includes_progress_and_name():
    msg = render(
        nudge_type=KpiNudgeType.eod_summary,
        kpi_id="__eod_summary__",
        kpi_title_pl="Podsumowanie",
        user_id=42,
        user_name="Anna",
        user_email="anna@x.pl",
        current=0,
        target=0,
        progress_pct=75.0,
        period_bucket="2026-04-22",
    )
    assert msg.tone == "summary"
    assert "Anna" in msg.body
    assert "75" in msg.body  # progress_pct rendered as int


# ── render: streak_bonus (phase 2 reserve) ─────────────────────────────────


def test_render_streak_bonus_renders_without_error():
    msg = render(
        nudge_type=KpiNudgeType.streak_bonus,
        kpi_id="daily_activity_count",
        kpi_title_pl="Aktywności",
        user_id=1,
        user_name="Anna",
        user_email="anna@x.pl",
        current=10,
        target=10,
        progress_pct=100.0,
        period_bucket="2026-04-22",
    )
    # Streak falls back to a praise tone.
    assert msg.tone == "praise"
    assert "Anna" in msg.body
