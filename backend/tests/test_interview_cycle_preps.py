"""Dwa prepy przed rozmową u klienta + ocena prepu w cyklu (0355).

Decyzje Artura 23.09.2026: Prep 1 i Prep 2 są zawsze wymagane (miękko —
nic nie blokuje), prep słaby albo bez nagrania daje zadanie, a brak prepu
na dobę przed rozmową jest pilny. Stan prepu (transkrypt, ocena) pokazuje
krok w stepperze i plakietka karty.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    assign_prep_ordinals,
    compute_badge,
    compute_steps,
    compute_todos,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


def _ev(eid: int, start: datetime, **extra) -> EventRef:
    return EventRef(
        id=eid,
        start=start,
        end=start + timedelta(minutes=45),
        title="E",
        status="scheduled",
        **extra,
    )


def _pair(*, iv_in: timedelta, preps: list[EventRef]) -> PairSnapshot:
    return PairSnapshot(
        1, 2, interview=_ev(9, NOW + iv_in), preps=assign_prep_ordinals(preps)
    )


def _todos(pair: PairSnapshot) -> list[dict]:
    return compute_todos(
        pair, NOW, call_window_minutes=30, user_id=11, is_dl_view=False
    )


def _steps(pair: PairSnapshot) -> dict[str, dict]:
    return {s["key"]: s for s in compute_steps(pair, NOW, call_window_minutes=30)}


def test_prep2_is_required_even_when_interview_is_far_away() -> None:
    done1 = _ev(1, NOW - timedelta(days=1))
    kinds = [t["kind"] for t in _todos(_pair(iv_in=timedelta(days=20), preps=[done1]))]
    assert kinds == ["prep2_missing"]


def test_prep1_missing_is_asked_first_not_both_at_once() -> None:
    kinds = [t["kind"] for t in _todos(_pair(iv_in=timedelta(days=5), preps=[]))]
    assert kinds == ["prep_missing"]


def test_missing_prep_within_24h_is_urgent() -> None:
    todos = _todos(_pair(iv_in=timedelta(hours=20), preps=[]))
    assert todos[0]["kind"] == "prep_missing"
    assert todos[0]["urgent"] is True
    far = _todos(_pair(iv_in=timedelta(days=3), preps=[]))
    assert far[0]["urgent"] is False


def test_numbered_prep2_does_not_take_the_prep1_slot() -> None:
    only_second = _ev(2, NOW + timedelta(days=1), prep_no=2)
    pair = _pair(iv_in=timedelta(days=3), preps=[only_second])
    steps = _steps(pair)
    assert steps["prep"]["state"] == "current"
    assert steps["prep2"]["state"] == "scheduled"
    assert [t["kind"] for t in _todos(pair)] == ["prep_missing"]


def test_legacy_preps_without_number_fill_slots_by_start() -> None:
    a = _ev(1, NOW - timedelta(days=2))
    b = _ev(2, NOW - timedelta(days=1))
    ordered = assign_prep_ordinals([b, a])
    assert [(p.id, p.ordinal) for p in ordered] == [(1, 1), (2, 2)]


def test_weak_prep_gives_a_todo_and_step_quality() -> None:
    weak = _ev(
        1,
        NOW - timedelta(days=1),
        prep_no=1,
        transcript_status="fetched",
        review_status="ok",
        review_level="weak",
    )
    planned2 = _ev(2, NOW + timedelta(days=1), prep_no=2)
    pair = _pair(iv_in=timedelta(days=3), preps=[weak, planned2])
    assert [t["kind"] for t in _todos(pair)] == ["prep_weak"]
    step = _steps(pair)["prep"]
    assert step["state"] == "done"
    assert step["quality"] == "weak"
    assert step["meta"] == "ocena: słaby"


def test_prep_without_recording_gives_a_todo() -> None:
    silent = _ev(1, NOW - timedelta(days=1), prep_no=1, transcript_status="missing")
    planned2 = _ev(2, NOW + timedelta(days=1), prep_no=2)
    pair = _pair(iv_in=timedelta(days=3), preps=[silent, planned2])
    assert [t["kind"] for t in _todos(pair)] == ["prep_unrecorded"]
    assert _steps(pair)["prep"]["quality"] == "unrecorded"


def test_unavailable_ai_review_is_not_weak() -> None:
    ev = _ev(
        1,
        NOW - timedelta(days=1),
        prep_no=1,
        transcript_status="fetched",
        review_status="unavailable",
        review_level=None,
    )
    pair = _pair(iv_in=timedelta(days=3), preps=[ev, _ev(2, NOW + timedelta(days=1))])
    assert _todos(pair) == []
    assert _steps(pair)["prep"]["quality"] is None


def test_prep_waiting_for_transcript_says_so() -> None:
    ev = _ev(1, NOW - timedelta(hours=1), prep_no=1, transcript_status="waiting")
    step = _steps(_pair(iv_in=timedelta(days=3), preps=[ev]))["prep"]
    assert step["quality"] == "pending"
    assert step["meta"] == "czeka na transkrypt"


def test_failed_transcription_setup_warns_on_scheduled_prep() -> None:
    ev = _ev(1, NOW + timedelta(days=1), prep_no=1, transcription_setup="failed")
    step = _steps(_pair(iv_in=timedelta(days=3), preps=[ev]))["prep"]
    assert step["state"] == "scheduled"
    assert "ręcznie" in (step["meta"] or "")


def test_badge_prefers_weak_prep_and_missing_prep_before_interview() -> None:
    weak = _ev(
        1,
        NOW - timedelta(days=1),
        prep_no=1,
        transcript_status="fetched",
        review_status="ok",
        review_level="weak",
    )
    badge = compute_badge(
        _pair(iv_in=timedelta(days=3), preps=[weak]), NOW, call_window_minutes=30
    )
    assert badge is not None and badge["kind"] == "prep_weak"

    soon = compute_badge(
        _pair(iv_in=timedelta(hours=20), preps=[]), NOW, call_window_minutes=30
    )
    assert soon is not None and soon["kind"] == "prep_missing"
    assert soon["tone"] == "urgent"


def test_good_preps_keep_the_old_badge() -> None:
    good = _ev(
        1,
        NOW - timedelta(days=2),
        prep_no=1,
        transcript_status="fetched",
        review_status="ok",
        review_level="good",
    )
    good2 = replace(good, id=2, start=NOW - timedelta(days=1), prep_no=2)
    badge = compute_badge(
        _pair(iv_in=timedelta(days=3), preps=[good, good2]), NOW, call_window_minutes=30
    )
    assert badge is not None and badge["kind"] == "prep_done"


def test_repeated_prep_wins_over_the_unrecorded_one() -> None:
    silent = _ev(1, NOW - timedelta(days=2), prep_no=1, transcript_status="missing")
    retry = _ev(3, NOW + timedelta(hours=5), prep_no=1)
    pair = _pair(iv_in=timedelta(days=3), preps=[silent, retry])
    assert pair.prep_slot(1).id == 3
    assert _steps(pair)["prep"]["state"] == "scheduled"
