"""Karty bez śladu wracają do „Nowych” (decyzja Artura z 23.11.2026) — reguły
bez bazy: kalendarz firmy, znacznik powrotu w porcji i w terminie decyzji."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import autofill_decisions, review_batch
from app.services import screening_stale as svc

WAW = ZoneInfo("Europe/Warsaw")


def _at(day: str, hour: int = 10) -> datetime:
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hour, tzinfo=WAW)


def test_card_returns_on_the_third_workday_after_the_trace() -> None:
    # Ślad w poniedziałek: wtorek i środa ciszy, wraca w czwartek.
    assert svc.return_day(_at("2026-11-16")) == date(2026, 11, 19)
    assert not svc.is_due(_at("2026-11-16"), date(2026, 11, 18))
    assert svc.is_due(_at("2026-11-16"), date(2026, 11, 19))


def test_weekend_does_not_count() -> None:
    # Ślad w czwartek: piątek, poniedziałek, wraca we wtorek.
    assert svc.return_day(_at("2026-11-19")) == date(2026, 11, 24)
    assert not svc.is_due(_at("2026-11-19"), date(2026, 11, 23))


def test_trace_on_saturday_counts_from_monday() -> None:
    # Sobota nie jest dniem roboczym: poniedziałek i wtorek ciszy, wraca w środę.
    assert svc.return_day(_at("2026-11-21")) == date(2026, 11, 25)


def test_public_holiday_does_not_count() -> None:
    # 11.11.2026 (środa) to święto: ślad we wtorek 10.11 → czw., pt., wraca w pon.
    assert svc.return_day(_at("2026-11-10")) == date(2026, 11, 16)


def test_late_evening_trace_counts_in_warsaw_time() -> None:
    # Dzień śladu to dzień w Warszawie: 23:30 w poniedziałek to poniedziałek,
    # 00:30 we wtorek to wtorek, choć w UTC-ie oba są jeszcze poniedziałkiem.
    late = datetime(2026, 11, 16, 22, 30, tzinfo=timezone.utc)  # 23:30 pon.
    after_midnight = datetime(2026, 11, 16, 23, 30, tzinfo=timezone.utc)  # 00:30 wt.
    assert svc.return_day(late) == date(2026, 11, 19)
    assert svc.return_day(after_midnight) == date(2026, 11, 20)


def test_naive_trace_is_read_as_utc() -> None:
    assert svc.return_day(datetime(2026, 11, 16, 9)) == date(2026, 11, 19)


def test_released_meta_drops_owner_and_call_decision() -> None:
    now = datetime(2026, 11, 19, 6, tzinfo=timezone.utc)
    meta = {
        "kind": "autofill",
        "score": 81,
        "review_owner_id": 7,
        "decided_at": "2026-11-16T09:00:00+00:00",
        "decided_by": 7,
        "decision": "call",
    }
    out = svc._released_meta(meta, now=now, kind=svc.KIND_SCREENING, holder=7)
    assert out["score"] == 81 and out["kind"] == "autofill"
    for key in ("review_owner_id", "decided_at", "decided_by", "decision"):
        assert key not in out
    assert out[svc.META_RETURNED_AT] == now.isoformat()
    assert out["returned_from"] == svc.KIND_SCREENING
    assert out["returned_holder"] == 7
    # Oryginał bez zmian (nowy słownik dla JSONB).
    assert meta["review_owner_id"] == 7


def test_returned_after_compares_with_the_decision() -> None:
    meta = {svc.META_RETURNED_AT: "2026-11-19T06:00:00+00:00"}
    assert svc.returned_after(meta, datetime(2026, 11, 16, 9, tzinfo=timezone.utc))
    assert not svc.returned_after(meta, datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
    assert not svc.returned_after({}, datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert not svc.returned_after(None, datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert not svc.returned_after(
        {svc.META_RETURNED_AT: "zle"}, datetime.now(timezone.utc)
    )


def _card(**kw) -> review_batch.PendingCard:
    base = dict(
        process_id=1,
        job_id=1,
        candidate_id=1,
        owner_id=7,
        score=90.0,
        opened_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    return review_batch.PendingCard(**{**base, **kw})


def test_returned_card_is_not_in_any_portion() -> None:
    now = datetime.now(timezone.utc)
    assert review_batch.in_batch(_card(), now)
    assert not review_batch.in_batch(_card(returned=True), now)


def test_decision_clock_restarts_when_the_card_comes_back() -> None:
    entered = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    plain = autofill_decisions.waiting_days(
        meta={"kind": "autofill"}, entered_at=entered, recruiter_since=entered, now=now
    )
    back = autofill_decisions.waiting_days(
        meta={"kind": "autofill", svc.META_RETURNED_AT: "2026-11-19T06:00:00+00:00"},
        entered_at=entered,
        recruiter_since=entered,
        now=now,
    )
    assert plain is not None and plain > autofill_decisions.DECISION_DAYS
    assert back == 0


def test_bell_lists_every_person_per_recruitment_biggest_first() -> None:
    """26.11.2026: dzwonek wymieniał trzy nazwiska i „i N więcej” — rekruter
    nie wiedział, kto mu wrócił. Teraz pełna lista, po rekrutacjach."""
    lines = svc._job_lines(
        {10: [1], 20: [2, 3, 4, 5]},
        {10: "Java", 20: "DBA"},
        {1: "Anna N.", 2: "B", 3: "C", 4: "D", 5: "E"},
    )
    assert lines == ["DBA (4): B, C, D, E", "Java (1): Anna N."]


def test_people_in_polish() -> None:
    assert [svc.people(n) for n in (1, 2, 4, 5, 12, 22, 25)] == [
        "1 osoba",
        "2 osoby",
        "4 osoby",
        "5 osób",
        "12 osób",
        "22 osoby",
        "25 osób",
    ]
    assert svc.returned_bell_title(3, 1) == "Wróciło do „Nowych”: 3 osoby"
    assert svc.returned_bell_title(0, 2) == "„Biorę” wygasło: 2 osoby"


def test_soon_bell_says_tomorrow_or_the_weekday() -> None:
    # Środa → czwartek: „Jutro”; piątek → poniedziałek: „W poniedziałek”.
    assert (
        svc.soon_bell_title(2, date(2026, 11, 18), date(2026, 11, 19))
        == "Jutro wrócą do „Nowych”: 2 osoby"
    )
    assert (
        svc.soon_bell_title(5, date(2026, 11, 20), date(2026, 11, 23))
        == "W poniedziałek wrócą do „Nowych”: 5 osób"
    )
    assert svc.next_workday(date(2026, 11, 20)) == date(2026, 11, 23)


def test_warning_only_on_workdays_between_8_and_20() -> None:
    assert svc.warn_due(_at("2026-11-18", 8))
    assert not svc.warn_due(_at("2026-11-18", 7))
    assert not svc.warn_due(_at("2026-11-18", 20))
    assert not svc.warn_due(_at("2026-11-21", 10))  # sobota
