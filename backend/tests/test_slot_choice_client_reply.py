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


def test_no_reply_todo_when_the_interview_was_cancelled_in_the_calendar():
    """Audyt 22.10, F33: odwołana rozmowa nie zostawia „Odpisz klientowi”."""
    from dataclasses import replace

    req = replace(_req(pending=True), event_id=7, event_cancelled=True)
    assert "slots_reply" not in _kinds(PairSnapshot(1, 2, slot_request=req), user_id=22)


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


# ── Termin z przeszłości (audyt 21.10.2026) ──────────────────────────────────
# Od 0487 wybór rekrutera od razu zakłada rozmowę i blokadę w Outlooku, a DL
# może przepiąć rozmowę na inny termin wniosku. Termin sprawdzał tylko zapis
# wniosku (`normalize_slots`), więc dzień później dało się wybrać termin, który
# już minął — rozmowa `scheduled` w przeszłości.


def _two_slots(*, status: str, chosen_index=None) -> ClientInterviewSlotRequest:
    now = datetime.now(timezone.utc)
    past, future = now - timedelta(hours=2), now + timedelta(days=2)
    return ClientInterviewSlotRequest(
        status=status,
        chosen_index=chosen_index,
        duration_minutes=60,
        event_id=None,
        slots=[
            {"start": past.isoformat(), "end": (past + timedelta(hours=1)).isoformat()},
            {
                "start": future.isoformat(),
                "end": (future + timedelta(hours=1)).isoformat(),
            },
        ],
    )


def test_choose_refuses_a_slot_that_already_passed():
    req = _two_slots(status="awaiting_recruiter")
    with pytest.raises(HTTPException) as exc:
        interview_slots.choose(req, 0, user_id=11)
    assert exc.value.status_code == 422
    assert "minął" in exc.value.detail
    assert req.status == "awaiting_recruiter" and req.chosen_index is None
    interview_slots.choose(req, 1, user_id=11)
    assert req.status == "awaiting_dl" and req.chosen_index == 1


def test_a_slot_within_the_five_minute_tolerance_is_still_accepted():
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    req = ClientInterviewSlotRequest(
        status="awaiting_recruiter",
        duration_minutes=60,
        slots=[
            {"start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat()}
        ],
    )
    interview_slots.choose(req, 0, user_id=11)
    assert req.chosen_index == 0


async def test_confirm_refuses_a_slot_that_already_passed():
    # DL potwierdza sam z `awaiting_recruiter` …
    req = _two_slots(status="awaiting_recruiter")
    with pytest.raises(HTTPException) as exc:
        await interview_slots.confirm(
            None, req, user_id=22, index=0, add_to_outlook=False
        )
    assert exc.value.status_code == 422
    # … albo potwierdza INNY termin niż wybrał rekruter.
    req = _two_slots(status="awaiting_dl", chosen_index=1)
    with pytest.raises(HTTPException) as exc:
        await interview_slots.confirm(
            None, req, user_id=22, index=0, add_to_outlook=False
        )
    assert exc.value.status_code == 422
    assert req.chosen_index == 1


async def test_change_refuses_a_slot_that_already_passed():
    req = _two_slots(status="confirmed", chosen_index=1)
    with pytest.raises(HTTPException) as exc:
        await interview_slots.change_confirmed_slot(None, req, user_id=22, index=0)
    assert exc.value.status_code == 422
    assert "minął" in exc.value.detail
    assert req.chosen_index == 1
