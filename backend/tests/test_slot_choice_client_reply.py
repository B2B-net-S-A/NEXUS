"""„Odpisz klientowi” (0487, 20.10.2026) — czyste reguły zadania i stanu wniosku."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.services import interview_slots
from app.services.interview_cycle import PairSnapshot, SlotRef, compute_todos

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


def _req(*, pending: bool, chosen_start: str = "2031-06-12T08:00:00+00:00") -> SlotRef:
    return SlotRef(
        id=3,
        status="confirmed",
        slots=({"start": chosen_start, "end": chosen_start},),
        chosen_index=0,
        respond_by=None,
        recruiter_id=11,
        created_by=22,
        duration_minutes=60,
        note=None,
        event_id=None,
        client_reply_pending=pending,
    )


def _kinds(pair: PairSnapshot, *, user_id: int, is_dl_view: bool = False) -> list[str]:
    return [
        t["kind"]
        for t in compute_todos(
            pair, NOW, call_window_minutes=30, user_id=user_id, is_dl_view=is_dl_view
        )
    ]


def test_reply_todo_goes_to_the_request_author():
    pair = PairSnapshot(1, 2, slot_request=_req(pending=True))
    assert "slots_reply" in _kinds(pair, user_id=22)
    # Rekruter wybrał termin — odpowiedź do klienta nie jest jego zadaniem.
    assert "slots_reply" not in _kinds(pair, user_id=11)
    # Delivery Lead w zakresie „jobs” widzi sprawę także cudzego wniosku.
    assert "slots_reply" in _kinds(pair, user_id=99, is_dl_view=True)


def test_no_reply_todo_without_the_flag_or_after_the_interview_started():
    assert "slots_reply" not in _kinds(
        PairSnapshot(1, 2, slot_request=_req(pending=False)), user_id=22
    )
    past = (NOW - timedelta(hours=1)).isoformat()
    assert "slots_reply" not in _kinds(
        PairSnapshot(1, 2, slot_request=_req(pending=True, chosen_start=past)),
        user_id=22,
    )


def test_mark_client_replied_is_idempotent_and_needs_a_confirmed_request():
    req = ClientInterviewSlotRequest(status="confirmed", client_reply_pending=True)
    interview_slots.mark_client_replied(req, user_id=22)
    first = req.client_replied_at
    assert req.client_reply_pending is False and req.client_replied_by == 22
    interview_slots.mark_client_replied(req, user_id=33)
    assert req.client_replied_at == first and req.client_replied_by == 22

    open_req = ClientInterviewSlotRequest(status="awaiting_recruiter")
    with pytest.raises(HTTPException) as exc:
        interview_slots.mark_client_replied(open_req, user_id=22)
    assert exc.value.status_code == 409
