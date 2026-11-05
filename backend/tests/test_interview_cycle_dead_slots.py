"""Martwe zadania z otwartych wniosków o terminy (pomiar z 04.11.2026).

„Wybierz termin” i „Potwierdź” wisiały przy terminach, które minęły (wybór to 422
„Ten termin już minął”), na kartach po rozmowie i w zamkniętych rekrutacjach.
Interfejs nie ma anulowania, więc zadanie zostawało na zawsze.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.models.client_interview_slot_request import all_slots_past
from app.services.interview_cycle import (
    EventRef,
    PairSnapshot,
    SlotRef,
    compute_badge,
    compute_steps,
    compute_todos,
    current_step_key,
    tentative_interview_start,
    todo_is_mine,
)

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)
DL = 22
RECRUITER = 11


def _slot(start: datetime, **extra) -> dict:
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        **extra,
    }


def _req(
    status: str = "awaiting_recruiter",
    *,
    starts: tuple[datetime, ...] = (NOW - timedelta(days=2), NOW - timedelta(days=1)),
    chosen: int | None = None,
    created_at: datetime | None = NOW - timedelta(days=5),
) -> SlotRef:
    return SlotRef(
        id=3,
        status=status,
        slots=tuple(_slot(s) for s in starts),
        chosen_index=chosen,
        respond_by=None,
        recruiter_id=RECRUITER,
        created_by=DL,
        duration_minutes=60,
        note=None,
        event_id=None,
        created_at=created_at,
    )


def _iv(start: datetime, *, ev_id: int = 7) -> EventRef:
    return EventRef(
        id=ev_id,
        start=start,
        end=start + timedelta(hours=1),
        title="R",
        status="scheduled",
    )


def _pair(req: SlotRef | None, **kwargs) -> PairSnapshot:
    kwargs.setdefault("latest_stage", "client_interview")
    return PairSnapshot(1, 2, slot_request=req, **kwargs)


def _kinds(pair: PairSnapshot, *, user_id: int, is_dl_view: bool) -> list[str]:
    return [
        t["kind"]
        for t in compute_todos(
            pair,
            NOW,
            call_window_minutes=30,
            user_id=user_id,
            is_dl_view=is_dl_view,
        )
    ]


# ── all_slots_past ───────────────────────────────────────────────────────────


def test_all_slots_past_needs_every_slot_behind_us() -> None:
    past = _slot(NOW - timedelta(days=1))
    ahead = _slot(NOW + timedelta(days=1))
    assert all_slots_past([past], NOW) is True
    assert all_slots_past([past, ahead], NOW) is False
    assert all_slots_past([], NOW) is False


def test_all_slots_past_has_the_same_tolerance_as_choosing() -> None:
    # ``_ensure_slot_ahead`` przyjmuje termin do 5 minut po starcie.
    assert all_slots_past([_slot(NOW - timedelta(minutes=4))], NOW) is False
    assert all_slots_past([_slot(NOW - timedelta(minutes=6))], NOW) is True


def test_all_slots_past_window_lives_until_it_ends() -> None:
    window = _slot(
        NOW - timedelta(hours=3),
        window_start=(NOW - timedelta(hours=3)).isoformat(),
        window_end=(NOW + timedelta(hours=1)).isoformat(),
    )
    assert all_slots_past([window], NOW) is False


# ── Wszystkie terminy minęły ─────────────────────────────────────────────────


def test_past_slots_give_recruiter_nothing() -> None:
    # Wniosek 27 i 108 na kopii z 03.11: „Wybierz termin” kończyło się 422.
    pair = _pair(_req())
    assert "slots_pick" not in _kinds(pair, user_id=RECRUITER, is_dl_view=False)
    assert "slots_expired" not in _kinds(pair, user_id=RECRUITER, is_dl_view=False)


def test_past_slots_give_dl_add_new_slots() -> None:
    pair = _pair(_req())
    assert _kinds(pair, user_id=DL, is_dl_view=False) == ["slots_expired"]
    todo = compute_todos(
        pair, NOW, call_window_minutes=30, user_id=DL, is_dl_view=True
    )[0]
    assert todo["owner_id"] == DL
    assert todo_is_mine(todo, {DL}) is True
    # Zakres „jobs” pokazuje zadanie rekruterowi w zespole, ale nie jako jego.
    assert todo_is_mine(todo, {RECRUITER}) is False


def test_request_from_client_panel_goes_to_the_job_dl() -> None:
    # Wniosek z panelu klienta nie ma autora.
    req = replace(_req(), created_by=None)
    todo = compute_todos(
        _pair(req), NOW, call_window_minutes=30, user_id=DL, is_dl_view=True
    )[0]
    assert todo["kind"] == "slots_expired"
    assert todo_is_mine(todo, {DL}, delivery_lead_id=DL) is True
    assert todo_is_mine(todo, {RECRUITER}, delivery_lead_id=DL) is False


def test_past_chosen_slot_no_longer_asks_dl_to_confirm() -> None:
    pair = _pair(_req("awaiting_dl", chosen=0))
    assert _kinds(pair, user_id=DL, is_dl_view=True) == ["slots_expired"]


def test_one_slot_ahead_keeps_the_task() -> None:
    starts = (NOW - timedelta(days=1), NOW + timedelta(days=1))
    pair = _pair(_req(starts=starts))
    assert _kinds(pair, user_id=RECRUITER, is_dl_view=False) == ["slots_pick"]
    confirm = _pair(_req("awaiting_dl", starts=starts, chosen=0))
    assert _kinds(confirm, user_id=DL, is_dl_view=False) == ["slots_confirm"]


def test_debrief_of_earlier_round_stays_with_recruiter() -> None:
    # Wniosek 108: rozmowa 30.10 bez debriefu, wniosek na kolejną rundę z 02.11.
    iv = _iv(NOW - timedelta(days=10))
    pair = _pair(_req(), interview=iv)
    assert _kinds(pair, user_id=RECRUITER, is_dl_view=False) == ["debrief_overdue"]
    assert "slots_expired" in _kinds(pair, user_id=DL, is_dl_view=True)


def test_interview_after_request_makes_it_a_leftover() -> None:
    iv = _iv(NOW - timedelta(days=1))
    pair = _pair(_req(), interview=iv)
    assert "slots_expired" not in _kinds(pair, user_id=DL, is_dl_view=True)


def test_scheduled_interview_makes_it_a_leftover() -> None:
    pair = _pair(_req(), interview=_iv(NOW + timedelta(days=2)))
    assert "slots_expired" not in _kinds(pair, user_id=DL, is_dl_view=True)
    assert compute_badge(pair, NOW, call_window_minutes=30)["kind"] != "slots_expired"


def test_steps_point_dl_at_slots_not_at_choice() -> None:
    steps = compute_steps(_pair(_req()), NOW, call_window_minutes=30)
    states = {s["key"]: s["state"] for s in steps}
    assert states["slots"] == "overdue"
    assert states["choice"] == "todo"
    assert current_step_key(steps) == "slots"


def test_steps_describe_new_round_after_earlier_interview() -> None:
    pair = _pair(_req(), interview=_iv(NOW - timedelta(days=10)))
    steps = compute_steps(pair, NOW, call_window_minutes=30)
    assert current_step_key(steps) == "slots"
    assert {s["key"]: s["state"] for s in steps}["interview"] == "todo"


def test_badge_says_slots_expired() -> None:
    badge = compute_badge(_pair(_req()), NOW, call_window_minutes=30)
    assert badge["kind"] == "slots_expired"
    assert badge["label"] == "Terminy minęły · czeka na DL"


def test_debrief_badge_beats_slots_expired() -> None:
    pair = _pair(_req(), interview=_iv(NOW - timedelta(days=10)))
    assert compute_badge(pair, NOW, call_window_minutes=30)["kind"] == "call_due"


def test_past_slots_are_not_a_tentative_interview() -> None:
    assert tentative_interview_start(_req(), NOW) is None
    ahead = _req(starts=(NOW + timedelta(days=1),))
    assert tentative_interview_start(ahead, NOW) == ahead.slots[0]["start"]


# ── Karta po rozmowie ────────────────────────────────────────────────────────


def test_card_past_interview_has_no_slot_task() -> None:
    # Wnioski 12 („Akceptacja”) i 29 („Zatrudniony”) na kopii z 03.11.
    for stage in ("acceptance", "negotiation", "onboarding", "hired"):
        pair = _pair(_req(), latest_stage=stage)
        assert _kinds(pair, user_id=DL, is_dl_view=True) == [], stage
        assert compute_badge(pair, NOW, call_window_minutes=30) is None, stage


# ── Zamknięta rekrutacja ─────────────────────────────────────────────────────


def test_closed_job_has_no_missing_slots_or_questions() -> None:
    # Wniosek otwarty w zamkniętej rekrutacji odpada już w ``load_snapshots``.
    pair = _pair(
        None,
        job_closed=True,
        latest_stage_at=NOW - timedelta(days=10),
    )
    assert _kinds(pair, user_id=DL, is_dl_view=True) == []
    assert _kinds(pair, user_id=RECRUITER, is_dl_view=False) == []


# ── Odznaka na zamkniętej karcie ─────────────────────────────────────────────


def test_closed_card_does_not_say_call() -> None:
    # Wniosek 31: rozmowa zakończona, karta „Wycofany”, odznaka „Zadzwoń”.
    pair = _pair(None, interview=_iv(NOW - timedelta(days=5)), latest_stage="withdrawn")
    badge = compute_badge(pair, NOW, call_window_minutes=30)
    assert badge["kind"] == "debrief_missing"
    assert badge["label"] == "Debrief niezapisany"
    assert badge["tone"] == "info"


def test_closed_card_right_after_interview_does_not_say_call() -> None:
    pair = _pair(None, interview=_iv(NOW - timedelta(hours=1)), latest_stage="rejected")
    assert compute_badge(pair, NOW, call_window_minutes=30)["kind"] == "debrief_missing"


def test_open_card_still_says_call() -> None:
    pair = _pair(None, interview=_iv(NOW - timedelta(days=5)))
    assert compute_badge(pair, NOW, call_window_minutes=30)["kind"] == "call_due"
