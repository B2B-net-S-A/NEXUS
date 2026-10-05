"""Krok na karcie w „Rozmowie u klienta” z cyklu rozmowy (05.10.2026).

Przeklikanie produkcji: karta w kolumnie „Rozmowa u klienta” zawsze mówiła
„Klient · Zbierz feedback HM”, choć rekruter miał wybrać termin od klienta.
Faza cyklu (``interview_cycle.badge_phase``) idzie z odznaki terminarza karty
i rozstrzyga krok w regule „kto ma ruch” (``pipeline_next_action``). Same
etykiety i właściciele są w pliku przypadków wspólnym z frontem
(``test_next_action_parity.py``); tu — mapowanie odznaki na fazę.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.api.candidates import _history_next_action_owner, _history_stage_column
from app.models.recruitment_pipeline import PipelineStage
from app.services.interview_cycle import EventRef, PairSnapshot, badge_phase
from app.services.pipeline_next_action import StageColumn, next_action_for

NOW = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)


def _ev(eid: int, start: datetime) -> EventRef:
    return EventRef(
        id=eid,
        start=start,
        end=start + timedelta(hours=1),
        title="Rozmowa",
        status="scheduled",
    )


def test_badge_kinds_map_to_phases() -> None:
    pair = PairSnapshot(candidate_id=1, job_id=2)
    assert badge_phase(pair, None) == (None, None)
    assert badge_phase(pair, {"kind": "choose_slot"}) == (
        "awaiting_recruiter_pick",
        None,
    )
    assert badge_phase(pair, {"kind": "awaiting_dl"}) == ("awaiting_dl_confirm", None)
    assert badge_phase(pair, {"kind": "call_due"}) == ("debrief_due", None)
    assert badge_phase(pair, {"kind": "debrief_done"}) == ("debriefed", None)
    assert badge_phase(pair, {"kind": "nieznany"}) == (None, None)


def test_scheduled_phase_carries_the_interview_day_in_business_time() -> None:
    # 22:30 UTC 7.10 = 00:30 8.10 w Warszawie — data karty to 8.10.
    interview = _ev(5, datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc))
    pair = PairSnapshot(candidate_id=1, job_id=2, interview=interview)
    for kind in ("slot", "prep2", "prep_done", "prep_weak", "prep_missing"):
        assert badge_phase(pair, {"kind": kind}) == ("scheduled", "2026-10-08")


def test_scheduled_phase_uses_the_prep_round_interview() -> None:
    past = _ev(5, NOW - timedelta(days=3))
    upcoming = _ev(6, datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    pair = PairSnapshot(
        candidate_id=1, job_id=2, interview=past, prep_interview=upcoming
    )
    assert badge_phase(pair, {"kind": "slot"}) == ("scheduled", "2026-10-09")


def _client_interview_col() -> StageColumn:
    return StageColumn(
        stage="client_interview", category="external", name="Rozmowa u klienta"
    )


def test_no_phase_keeps_the_old_step() -> None:
    action = next_action_for(_client_interview_col(), days_in_stage=1, group="client")
    assert (action.label, action.owner) == ("Zbierz feedback HM", "client")


def test_offer_stage_ignores_a_stale_phase() -> None:
    col = StageColumn(stage="acceptance", category="external", name="Akceptacja")
    action = next_action_for(
        col, days_in_stage=1, group="client", interview_phase="debriefed"
    )
    assert (action.label, action.owner) == ("Reakcja kandydata na ofertę", "candidate")


def _history_owner(badge):
    column = _history_stage_column(
        PipelineStage.client_interview,
        stage_def_id=None,
        name=None,
        legacy=None,
        category=None,
        terminal=None,
        order=None,
    )
    return _history_next_action_owner(
        {"job_status": "published", "latest_stage": "client_interview"},
        (column, datetime(2026, 10, 4, 10, tzinfo=timezone.utc)),
        today=date(2026, 10, 5),
        interview_badge=badge,
    )


def test_profile_history_uses_the_same_phase_as_the_board() -> None:
    assert _history_owner(None) == "client"
    assert _history_owner({"phase": "awaiting_recruiter_pick"}) == "recruiter"
    assert _history_owner({"phase": "awaiting_dl_confirm"}) == "delivery"
    assert _history_owner({"phase": "debrief_due"}) == "recruiter"
    assert _history_owner({"phase": "debriefed"}) == "client"
