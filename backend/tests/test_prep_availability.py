"""Podpowiedź godzin prepów z kalendarzy (20.10.2026, PR 2) — czyste funkcje."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.services import interview_slots
from app.services import prep_availability as pa

WAW = ZoneInfo("Europe/Warsaw")
# Wtorek 20.10.2026, 11:00; rozmowa u klienta w czwartek 22.10 o 14:30.
NOW = datetime(2026, 10, 20, 11, 0, tzinfo=WAW)
INTERVIEW = datetime(2026, 10, 22, 14, 30, tzinfo=WAW)


def _local(options):
    return [o.start.astimezone(WAW).strftime("%a %d.%m %H:%M") for o in options]


def test_prep1_on_the_business_day_before_in_the_morning_without_calendar():
    out = pa.suggest(prep_no=1, interview_start=INTERVIEW, now=NOW, busy=None)
    assert _local(out) == ["Wed 21.10 08:00", "Wed 21.10 09:00", "Wed 21.10 10:00"]


def test_prep1_skips_busy_blocks_and_respects_candidate_window():
    busy = [
        (datetime(2026, 10, 21, 8, 0, tzinfo=WAW), datetime(2026, 10, 21, 12, 0, tzinfo=WAW)),
        (datetime(2026, 10, 21, 17, 0, tzinfo=WAW), datetime(2026, 10, 21, 17, 30, tzinfo=WAW)),
    ]
    out = pa.suggest(
        prep_no=1,
        interview_start=INTERVIEW,
        now=NOW,
        busy=busy,
        candidate_windows=[(time(16, 0), time(20, 0))],
    )
    # 17:00 zajęte; okno kandydata przedłuża dzień do 20:00.
    assert _local(out) == ["Wed 21.10 16:00", "Wed 21.10 17:30", "Wed 21.10 18:30"]


def test_prep2_close_to_two_hours_before_and_not_on_top_of_prep1():
    prep1 = (datetime(2026, 10, 22, 12, 30, tzinfo=WAW), datetime(2026, 10, 22, 13, 15, tzinfo=WAW))
    out = pa.suggest(prep_no=2, interview_start=INTERVIEW, now=NOW, busy=[], avoid=[prep1])
    assert _local(out) == ["Thu 22.10 11:30", "Thu 22.10 10:30", "Thu 22.10 09:30"]
    for o in out:
        assert not (o.start < prep1[1] and prep1[0] < o.end)
        assert o.end <= INTERVIEW - pa.PREP2_GAP


def test_prep2_without_conflicts_starts_at_two_hours_before():
    out = pa.suggest(prep_no=2, interview_start=INTERVIEW, now=NOW, busy=[])
    assert _local(out)[0] == "Thu 22.10 12:30"
    assert all(o.end <= INTERVIEW - pa.PREP2_GAP for o in out)


def test_prep2_falls_back_to_the_evening_before_when_candidate_only_after_work():
    out = pa.suggest(
        prep_no=2,
        interview_start=INTERVIEW,
        now=NOW,
        busy=[],
        candidate_windows=[(time(16, 0), time(20, 0))],
    )
    assert _local(out) == ["Wed 21.10 19:00", "Wed 21.10 18:00", "Wed 21.10 17:00"]


def test_holiday_is_not_a_prep_day():
    # 11.11.2026 (środa) to święto — Prep 1 przed rozmową w czwartek 12.11 wtedy we wtorek.
    interview = datetime(2026, 11, 12, 10, 0, tzinfo=WAW)
    out = pa.suggest(prep_no=1, interview_start=interview, now=NOW, busy=None)
    assert _local(out)[0] == "Tue 10.11 08:00"


def test_nothing_in_the_past_or_too_soon():
    interview = NOW + timedelta(hours=3)
    out = pa.suggest(prep_no=1, interview_start=interview, now=NOW, busy=None)
    assert out == []
    out2 = pa.suggest(prep_no=2, interview_start=interview, now=NOW, busy=None)
    assert all(o.start >= NOW + pa.MIN_LEAD for o in out2)


def test_busy_from_schedule_marks_errors_as_unknown_calendar():
    start = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "DL@example.org",
                "scheduleItems": [
                    {"status": "busy", "start": {"dateTime": "2026-10-21T08:00:00"}, "end": {"dateTime": "2026-10-21T09:00:00"}},
                    {"status": "free", "start": {"dateTime": "2026-10-21T10:00:00"}, "end": {"dateTime": "2026-10-21T11:00:00"}},
                    {"status": "tentative", "start": {"dateTime": "2026-10-21T12:00:00"}, "end": {"dateTime": "2026-10-21T12:30:00"}},
                ],
            },
            {"scheduleId": "outside@example.org", "error": {"responseCode": "ErrorAccessDenied"}},
        ]
    }
    out = pa.busy_from_schedule(payload, window_start=start)
    assert len(out["dl@example.org"]) == 2
    assert out["outside@example.org"] is None


# ── „Inna godzina…” (22.10.2026) ────────────────────────────────────────────


def _at_waw(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 29, h, m, tzinfo=WAW)


def test_busy_overlap_merges_the_blocks_the_prep_falls_on():
    busy = [
        (_at_waw(10), _at_waw(10, 30)),
        (_at_waw(11, 30), _at_waw(12)),
        (_at_waw(12), _at_waw(13)),
    ]
    span = pa.busy_overlap(_at_waw(11, 45), _at_waw(12, 30), busy)
    assert span == (_at_waw(11, 30), _at_waw(13))
    assert pa.span_label(span) == "11:30–13:00"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        # Koniec prepu dokładnie na początku zajętego — to nie kolizja.
        (_at_waw(10, 45), _at_waw(11, 30)),
        # Start dokładnie na końcu zajętego.
        (_at_waw(13), _at_waw(13, 45)),
    ],
)
def test_busy_overlap_touching_edges_is_free(start, end):
    busy = [(_at_waw(11, 30), _at_waw(13))]
    assert pa.busy_overlap(start, end, busy) is None


def test_busy_overlap_ignores_the_prep_itself_from_an_earlier_attempt():
    # Outlook przyjął spotkanie, zapis w NEXUSIE padł — powtórka widzi „siebie”.
    own = (_at_waw(10), _at_waw(10, 45))
    assert pa.busy_overlap(own[0], own[1], [own]) is None
    other = (_at_waw(10, 30), _at_waw(11))
    assert pa.busy_overlap(own[0], own[1], [own, other]) == other


def test_busy_overlap_counts_another_nexus_prep_even_with_the_same_span():
    """Audyt 22.10, F32: prep innego kandydata u tego samego prowadzącego
    w identycznym przedziale to kolizja, nie „sierota z poprzedniej próby”."""
    span = (_at_waw(10), _at_waw(10, 45))
    assert pa.busy_overlap(span[0], span[1], [span], nexus_preps=[span]) == span
    # Kalendarz nieznany, ale NEXUS wie o prepie prowadzącego.
    assert pa.busy_overlap(span[0], span[1], None, nexus_preps=[span]) == span
    # Prep NEXUS obok — bez kolizji.
    later = (_at_waw(10, 45), _at_waw(11, 30))
    assert pa.busy_overlap(span[0], span[1], [span], nexus_preps=[later]) is None


def test_busy_overlap_unknown_calendar_is_never_a_clash():
    assert pa.busy_overlap(_at_waw(11), _at_waw(11, 45), None) is None


# ── Okna klienta („piątek 9–12”) ────────────────────────────────────────────


def _window_request() -> ClientInterviewSlotRequest:
    slots = interview_slots.normalize_slots(
        [
            {
                "start": datetime(2026, 10, 23, 9, 0, tzinfo=WAW),
                "end": None,
                "window_end": datetime(2026, 10, 23, 12, 0, tzinfo=WAW),
            },
            {"start": datetime(2026, 10, 22, 10, 0, tzinfo=WAW), "end": None, "window_end": None},
        ],
        duration_minutes=45,
        now=NOW,
    )
    return ClientInterviewSlotRequest(
        slots=slots, duration_minutes=45, status="awaiting_recruiter"
    )


def test_normalize_keeps_window_end_only_for_windows():
    req = _window_request()
    window = next(s for s in req.slots if "window_end" in s)
    assert window["window_end"] == "2026-10-23T10:00:00+00:00"
    assert sum("window_end" in s for s in req.slots) == 1


def test_window_shorter_than_interview_is_refused():
    with pytest.raises(HTTPException) as exc:
        interview_slots.normalize_slots(
            [
                {
                    "start": datetime(2026, 10, 23, 9, 0, tzinfo=WAW),
                    "end": None,
                    "window_end": datetime(2026, 10, 23, 9, 30, tzinfo=WAW),
                }
            ],
            duration_minutes=45,
            now=NOW,
        )
    assert exc.value.status_code == 422


def test_window_over_midnight_is_refused():
    with pytest.raises(HTTPException) as exc:
        interview_slots.normalize_slots(
            [
                {
                    "start": datetime(2026, 10, 22, 10, 0, tzinfo=WAW),
                    "end": None,
                    "window_end": datetime(2026, 10, 23, 12, 0, tzinfo=WAW),
                }
            ],
            duration_minutes=45,
            now=NOW,
        )
    assert exc.value.status_code == 422


def test_choose_hour_inside_window_rewrites_the_slot():
    req = _window_request()
    index = next(i for i, s in enumerate(req.slots) if "window_end" in s)
    interview_slots.choose(
        req, index, user_id=1, start=datetime(2026, 10, 23, 10, 30, tzinfo=WAW)
    )
    slot = req.slots[index]
    assert slot["start"] == "2026-10-23T08:30:00+00:00"
    assert slot["end"] == "2026-10-23T09:15:00+00:00"
    assert slot["window_start"] == "2026-10-23T07:00:00+00:00"
    assert req.status == "awaiting_dl"


@pytest.mark.parametrize(
    "hour,minute", [(8, 30), (11, 30)]  # przed oknem; koniec po 12:00
)
def test_choose_hour_outside_window_is_refused(hour, minute):
    req = _window_request()
    index = next(i for i, s in enumerate(req.slots) if "window_end" in s)
    with pytest.raises(HTTPException) as exc:
        interview_slots.choose(
            req, index, user_id=1, start=datetime(2026, 10, 23, hour, minute, tzinfo=WAW)
        )
    assert exc.value.status_code == 422
    assert req.status == "awaiting_recruiter"


def test_choose_hour_on_a_fixed_slot_is_refused():
    req = _window_request()
    index = next(i for i, s in enumerate(req.slots) if "window_end" not in s)
    with pytest.raises(HTTPException):
        interview_slots.choose(
            req, index, user_id=1, start=datetime(2026, 10, 22, 11, 0, tzinfo=WAW)
        )
