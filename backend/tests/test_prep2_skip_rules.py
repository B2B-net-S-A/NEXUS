"""Rozmowa bez Prepu 2 — wyjątek, nie wybór (0482, decyzja Artura 20.10.2026).

Pominąć Prep 2 da się tylko tuż przed rozmową (dziś albo w najbliższy dzień
roboczy), po odbytym Prepie 1, który nie jest słaby ani bez nagrania.
Zapisane pominięcie nigdy nie wygląda jak zrobiony prep: krok jest szary
z powodem, zamiast „Zaplanuj Prep 2” jest telefon przed rozmową, a plakietka
mówi „Bez Prepu 2”.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    SkipRef,
    assign_prep_ordinals,
    compute_badge,
    compute_steps,
    compute_todos,
    prep1_remaining,
    prep2_skip_status,
    prep2_skip_valid,
)
from app.services.prep2_skips import tally_skip_stats, tally_two_preps

# Wtorek 20.10.2026, 14:00 w Warszawie.
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _ev(eid: int, start: datetime, **extra) -> EventRef:
    return EventRef(
        id=eid,
        start=start,
        end=start + timedelta(minutes=45),
        title="E",
        status="scheduled",
        **extra,
    )


def _prep1(**extra) -> EventRef:
    """Prep 1 odbyty dziś rano, z oceną „dobry”."""
    base = {
        "prep_no": 1,
        "transcript_status": "fetched",
        "review_status": "ok",
        "review_level": "good",
    }
    return _ev(1, NOW - timedelta(hours=3), **{**base, **extra})


def _pair(iv_start: datetime, preps: list[EventRef], **extra) -> PairSnapshot:
    return PairSnapshot(
        1,
        2,
        interview=_ev(9, iv_start, owner_id=11),
        preps=assign_prep_ordinals(preps),
        **extra,
    )


def _skip(**extra) -> SkipRef:
    base = {
        "id": 5,
        "interview_event_id": 9,
        "reason": "no_slot",
        "reason_note": None,
        "call_at": NOW + timedelta(hours=4),
        "call_done_at": None,
        "call_note": None,
        "created_by": 11,
        "created_by_name": "Anna Rekruterka",
        "created_at": NOW,
    }
    return SkipRef(**{**base, **extra})


TOMORROW_9 = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc)
FRIDAY_9 = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)


def _steps(pair: PairSnapshot, now: datetime = NOW) -> dict[str, dict]:
    return {s["key"]: s for s in compute_steps(pair, now, call_window_minutes=30)}


def _todos(pair: PairSnapshot, now: datetime = NOW) -> list[dict]:
    return compute_todos(
        pair, now, call_window_minutes=30, user_id=11, is_dl_view=False
    )


# ── Kiedy wolno ──────────────────────────────────────────────────────────────


def test_allowed_for_tomorrows_interview_after_a_good_prep1() -> None:
    assert prep2_skip_status(_pair(TOMORROW_9, [_prep1()]), NOW) == "allowed"


def test_allowed_while_prep1_transcript_is_still_pending() -> None:
    pending = _prep1(transcript_status="waiting", review_status=None, review_level=None)
    assert prep2_skip_status(_pair(TOMORROW_9, [pending]), NOW) == "allowed"


def test_interview_in_three_days_leaves_time_for_prep2() -> None:
    assert prep2_skip_status(_pair(FRIDAY_9, [_prep1()]), NOW) == "too_early"


def test_friday_to_monday_counts_as_the_next_business_day() -> None:
    friday_noon = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    monday_9 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
    prep = _ev(
        1,
        friday_noon - timedelta(hours=2),
        prep_no=1,
        transcript_status="fetched",
        review_status="ok",
        review_level="ok",
    )
    assert prep2_skip_status(_pair(monday_9, [prep]), friday_noon) == "allowed"
    tuesday_9 = monday_9 + timedelta(days=1)
    assert prep2_skip_status(_pair(tuesday_9, [prep]), friday_noon) == "too_early"


def test_public_holiday_is_not_a_business_day() -> None:
    # 11.11.2026 (środa) to święto: z wtorku 10.11 najbliższy dzień roboczy
    # to czwartek 12.11.
    tuesday = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)
    thursday_9 = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    prep = _ev(1, tuesday - timedelta(hours=2), prep_no=1)
    assert prep2_skip_status(_pair(thursday_9, [prep]), tuesday) == "allowed"


def test_prep1_must_happen_first() -> None:
    assert prep2_skip_status(_pair(TOMORROW_9, []), NOW) == "prep1_missing"
    later_today = _ev(1, NOW + timedelta(hours=2), prep_no=1)
    assert prep2_skip_status(_pair(TOMORROW_9, [later_today]), NOW) == "prep1_missing"


def test_weak_or_unrecorded_prep1_makes_prep2_mandatory() -> None:
    weak = _prep1(review_level="weak")
    unrecorded = _prep1(transcript_status="missing", review_status=None)
    assert prep2_skip_status(_pair(TOMORROW_9, [weak]), NOW) == "prep1_weak"
    assert prep2_skip_status(_pair(TOMORROW_9, [unrecorded]), NOW) == "prep1_weak"


def test_not_needed_when_prep2_is_in_the_calendar_or_no_interview_ahead() -> None:
    prep2 = _ev(2, NOW + timedelta(hours=3), prep_no=2)
    assert prep2_skip_status(_pair(TOMORROW_9, [_prep1(), prep2]), NOW) == "not_needed"
    past = NOW - timedelta(hours=1)
    assert prep2_skip_status(_pair(past, [_prep1()]), NOW) == "not_needed"
    assert prep2_skip_status(PairSnapshot(1, 2), NOW) == "not_needed"


def test_already_skipped() -> None:
    pair = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip()})
    assert prep2_skip_status(pair, NOW) == "skipped"


# ── Ślad pominięcia ──────────────────────────────────────────────────────────


def test_skipped_step_is_grey_with_reason_and_author() -> None:
    pair = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip()})
    step = _steps(pair)["prep2"]
    assert step["state"] == "skipped"
    assert step["meta"] == ("kandydat nie miał wolnego terminu · Anna Rekruterka")
    assert _steps(pair)["interview"]["state"] == "scheduled"


def test_other_reason_shows_the_written_note() -> None:
    skip = _skip(reason="other", reason_note="kandydat w delegacji")
    pair = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: skip})
    assert _steps(pair)["prep2"]["meta"].startswith("kandydat w delegacji")


def test_silent_skip_after_the_interview_says_nobody_gave_a_reason() -> None:
    past = NOW - timedelta(hours=2)
    step = _steps(_pair(past, [_ev(1, past - timedelta(days=1), prep_no=1)]))["prep2"]
    assert step["state"] == "skipped"
    assert step["meta"] == "bez zapisanego powodu"


def test_skip_replaces_prep2_todo_with_the_call_before_the_interview() -> None:
    plain = _pair(TOMORROW_9, [_prep1()])
    assert [t["kind"] for t in _todos(plain)] == ["prep2_missing"]

    skipped = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip()})
    todos = _todos(skipped)
    assert [t["kind"] for t in todos] == ["precall_due"]
    assert todos[0]["owner_id"] == 11
    assert todos[0]["due"] == NOW + timedelta(hours=4)
    assert todos[0]["urgent"] is False


def test_call_time_passed_makes_the_todo_urgent_and_done_call_clears_it() -> None:
    late = _pair(
        TOMORROW_9,
        [_prep1()],
        prep2_skips={9: _skip(call_at=NOW - timedelta(minutes=10))},
    )
    assert _todos(late)[0]["urgent"] is True
    done = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip(call_done_at=NOW)})
    assert _todos(done) == []


def test_skip_of_another_interview_does_not_count() -> None:
    pair = _pair(TOMORROW_9, [_prep1()], prep2_skips={77: _skip(interview_event_id=77)})
    assert prep2_skip_status(pair, NOW) == "allowed"
    assert [t["kind"] for t in _todos(pair)] == ["prep2_missing"]


def test_badge_says_without_prep2_instead_of_missing_prep() -> None:
    plain = compute_badge(_pair(TOMORROW_9, [_prep1()]), NOW, call_window_minutes=30)
    assert plain is not None and plain["kind"] == "prep_missing"

    skipped = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip()})
    badge = compute_badge(skipped, NOW, call_window_minutes=30)
    assert badge is not None
    assert badge["kind"] == "prep2_skipped"
    assert badge["label"] == "Bez Prepu 2 · telefon dziś 18:00"
    assert badge["tone"] == "wait"

    called = _pair(TOMORROW_9, [_prep1()], prep2_skips={9: _skip(call_done_at=NOW)})
    badge = compute_badge(called, NOW, call_window_minutes=30)
    assert badge is not None
    assert badge["label"] == "Bez Prepu 2 · rozmowa jutro"
    assert badge["tone"] == "info"


def test_prep1_remaining_points_feed_the_call() -> None:
    prep = _prep1(remaining=("Power Apps w bankowości",))
    assert prep1_remaining(_pair(TOMORROW_9, [prep])) == ["Power Apps w bankowości"]
    assert prep1_remaining(_pair(TOMORROW_9, [])) == []


def test_skip_does_not_survive_moving_the_interview_later() -> None:
    # Przegląd 20.10: rozmowa przełożona (ten sam wpis kalendarza) na za
    # tydzień nie może zachować wyjątku zapisanego „na jutro”.
    next_week = TOMORROW_9 + timedelta(days=7)
    moved = _pair(next_week, [_prep1()], prep2_skips={9: _skip()})
    assert prep2_skip_status(moved, NOW) == "too_early"
    assert [t["kind"] for t in _todos(moved)] == ["prep2_missing"]
    assert _steps(moved)["prep2"]["state"] == "current"
    badge = compute_badge(moved, NOW, call_window_minutes=30)
    assert badge is None or badge["kind"] != "prep2_skipped"


def test_skip_survives_moving_the_interview_earlier_or_same_day() -> None:
    earlier = _pair(
        TOMORROW_9 - timedelta(hours=20), [_prep1()], prep2_skips={9: _skip()}
    )
    assert prep2_skip_status(earlier, NOW - timedelta(hours=2)) == "skipped"


# ── Wyjątek po przełożeniu rozmowy (audyt 21.10.2026) ────────────────────────
# Wiersz `prep2_skips` zostaje po przełożeniu rozmowy (UNIQUE na
# `interview_event_id`). Ekran mówił „allowed”, a ponowny zapis dawał 409;
# raport liczył nieważny wyjątek jako rozmowę „z powodem”.


def test_skip_validity_is_one_rule_for_screen_and_report() -> None:
    assert prep2_skip_valid(NOW, TOMORROW_9)
    assert prep2_skip_valid(NOW, NOW + timedelta(hours=2))
    assert not prep2_skip_valid(NOW, TOMORROW_9 + timedelta(days=7))
    # Piątek → poniedziałek to dalej „najbliższy dzień roboczy”.
    friday = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    assert prep2_skip_valid(friday, datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc))


def test_report_does_not_count_a_skip_lost_by_moving_the_interview() -> None:
    past_iv = NOW - timedelta(hours=1)
    interviews = [
        # (id, kandydat, rekrutacja, start, właściciel, założona)
        (1, 10, 20, past_iv, 11, NOW - timedelta(days=8)),
        (2, 12, 20, past_iv, 11, NOW - timedelta(days=8)),
    ]
    skips = {
        1: ("no_slot", NOW - timedelta(hours=3)),
        # Zapisany tydzień wcześniej „na jutro”, rozmowa przełożona na dziś.
        2: ("short_notice", NOW - timedelta(days=7)),
    }
    stat = tally_skip_stats(interviews, skips, preps={}, now=NOW)[11]
    assert stat.interviews == 2
    assert stat.with_reason == 1
    assert stat.reasons == {"no_slot": 1}
    # Nieważny wyjątek = rozmowa bez Prepu 2 i bez powodu.
    assert stat.silent == 1


# Audyt 22.10.2026 (F28), decyzja Artura: rozmowa zapisana PO FAKCIE (pytania
# z datą wstecz, import z notatek, „Kiedy rozmowa?” wstecz) nie była w kalendarzu
# przed startem — nie dało się do niej zrobić prepów ani zapisać „bez Prepu 2”.
# Raport liczy ją osobno jako „zapisane po fakcie”, nie jako „bez słowa”.


def test_interview_recorded_after_the_fact_is_its_own_bucket_not_silent() -> None:
    held = NOW - timedelta(days=2)
    interviews = [
        # Założona dzień przed rozmową, bez prepów — „bez słowa”.
        (1, 10, 20, held, 11, held - timedelta(days=1)),
        # Założona po rozmowie (pytania z datą wstecz) — „po fakcie”.
        (2, 12, 20, held, 11, NOW - timedelta(hours=1)),
        # Założona w chwili startu — też po fakcie (nie było jej wcześniej).
        (3, 13, 20, held, 11, held),
    ]
    stat = tally_skip_stats(interviews, {}, preps={}, now=NOW)[11]
    assert stat.interviews == 3
    assert stat.silent == 1
    assert stat.after_the_fact == 2


def test_two_preps_line_leaves_out_interviews_recorded_after_the_fact() -> None:
    held = NOW - timedelta(days=2)
    preps = {(10, 20): [held - timedelta(days=2), held - timedelta(days=1)]}
    interviews = [
        (10, 20, held, held - timedelta(days=5)),  # dwa prepy
        (12, 20, held, held - timedelta(days=5)),  # bez prepów
        (13, 20, held, NOW - timedelta(hours=1)),  # zapisana po fakcie
    ]
    assert tally_two_preps(interviews, preps) == (2, 1, 1)
