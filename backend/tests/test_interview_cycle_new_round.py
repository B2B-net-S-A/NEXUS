"""Runda 10 (F26): nowe terminy od klienta po odbytej rozmowie = nowa runda.

Kroki pary opisują otwarty wniosek o terminy, nie poprzednią rozmowę —
„Wybór terminu” i „Rozmowa u klienta” nie mogą świecić jako zrobione z datą
starej rozmowy, a bieżącym krokiem jest wybór terminu. Zaległy debrief
poprzedniej rozmowy zostaje zadaniem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    SlotRef,
    compute_steps,
    compute_todos,
    current_step_key,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


def _iv(start: datetime, *, ev_id: int = 7, minutes: int = 15) -> EventRef:
    return EventRef(
        id=ev_id,
        start=start,
        end=start + timedelta(minutes=minutes),
        title="R",
        status="scheduled",
    )


def _req(status: str, *, chosen: int | None = None) -> SlotRef:
    return SlotRef(
        id=3,
        status=status,
        slots=(
            {"start": "2031-06-11T17:15:00+00:00", "end": "2031-06-11T17:45:00+00:00"},
        ),
        chosen_index=chosen,
        respond_by=None,
        recruiter_id=11,
        created_by=22,
        duration_minutes=30,
        note=None,
        event_id=None,
    )


def _by_key(steps: list[dict]) -> dict[str, dict]:
    return {s["key"]: s for s in steps}


def test_open_request_after_past_interview_starts_a_new_round():
    past = _iv(NOW - timedelta(hours=4))
    old_prep = EventRef(8, NOW - timedelta(days=1), None, "P", "completed")
    pair = PairSnapshot(
        1, 2, slot_request=_req("awaiting_recruiter"), interview=past, preps=[old_prep]
    )

    steps = _by_key(compute_steps(pair, NOW, call_window_minutes=30))

    assert steps["slots"]["state"] == "done"
    assert steps["choice"]["state"] == "current"
    assert steps["choice"]["at"] is None
    assert steps["prep"]["state"] == "todo"
    assert steps["prep2"]["state"] == "todo"
    assert steps["interview"]["state"] == "todo"
    assert steps["interview"]["at"] is None
    assert steps["call"]["state"] == "todo"
    assert steps["debrief"]["state"] == "todo"
    assert current_step_key(list(steps.values())) == "choice"

    # Zaległy debrief starej rozmowy nie znika — zostaje zadaniem obok wyboru.
    kinds = {
        t["kind"]
        for t in compute_todos(
            pair, NOW, call_window_minutes=30, user_id=11, is_dl_view=False
        )
    }
    assert kinds == {"debrief_overdue", "slots_pick"}


def test_awaiting_dl_after_past_interview_waits_for_dl():
    pair = PairSnapshot(
        1,
        2,
        slot_request=_req("awaiting_dl", chosen=0),
        interview=_iv(NOW - timedelta(hours=4)),
    )
    steps = _by_key(compute_steps(pair, NOW, call_window_minutes=30))
    assert steps["choice"]["state"] == "waiting"
    assert steps["interview"]["state"] == "todo"


def test_new_terms_for_a_future_interview_ask_for_a_choice_again():
    # Klient przysłał nowe terminy przed zaplanowaną rozmową (przełożenie):
    # rozmowa zostaje zaplanowana, ale wybór terminu znów czeka na rekrutera.
    future = _iv(NOW + timedelta(days=2))
    pair = PairSnapshot(1, 2, slot_request=_req("awaiting_recruiter"), interview=future)
    steps = _by_key(compute_steps(pair, NOW, call_window_minutes=30))
    assert steps["choice"]["state"] == "current"
    assert steps["interview"]["state"] == "scheduled"


def test_next_round_already_scheduled_describes_that_round():
    past = _iv(NOW - timedelta(hours=4))
    nxt = _iv(NOW + timedelta(days=3), ev_id=9)
    pair = PairSnapshot(
        1,
        2,
        slot_request=_req("awaiting_recruiter"),
        interview=past,
        prep_interview=nxt,
    )
    steps = _by_key(compute_steps(pair, NOW, call_window_minutes=30))
    assert steps["interview"]["state"] == "scheduled"
    assert steps["interview"]["event_id"] == 9
    assert steps["choice"]["state"] == "current"


def test_confirmed_request_keeps_the_interview_steps():
    past = _iv(NOW - timedelta(hours=4))
    pair = PairSnapshot(1, 2, slot_request=_req("confirmed", chosen=0), interview=past)
    steps = _by_key(compute_steps(pair, NOW, call_window_minutes=30))
    assert steps["choice"]["state"] == "done"
    assert steps["interview"]["state"] == "done"
    assert steps["call"]["state"] == "overdue"
