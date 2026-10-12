"""Podpowiedzi stawek pary bez stawki na etapie — czyste reguły (12.10.2026).

Treści fikcyjne. Reguły z bazą: ``test_recruitment_rate_hints_db.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest

from app.services import candidate_rate_from
from app.services import recruitment_rate_hints as hints
from app.services.candidate_rate_observations import RateObservation

SENT_AT = datetime(2026, 9, 22, 9, 52, tzinfo=timezone.utc)
DL, OTHER_DL = 30, 31
JOB, OTHER_JOB = 100, 200


def _send(job_id: int = JOB, *, at: datetime = SENT_AT, by: int = DL) -> hints.Send:
    return hints.Send(job_id=job_id, moved_at=at, moved_by=by)


def _note(
    note_id: int,
    *,
    minutes: float = 1,
    job_id: Optional[int] = None,
    author_id: int = DL,
    base: datetime = SENT_AT,
) -> hints.SendNote:
    return hints.SendNote(
        id=note_id,
        job_id=job_id,
        author_id=author_id,
        at=base + timedelta(minutes=minutes),
        text="Wysłany 150/100-110",
    )


def test_note_written_by_the_sender_right_after_the_move_is_picked():
    picked = hints.pick_send_notes([_send()], [_note(1)])
    assert picked[JOB].id == 1


def test_note_without_recruitment_and_note_pinned_to_this_recruitment_both_count():
    assert hints.pick_send_notes([_send()], [_note(1, job_id=None)])
    assert hints.pick_send_notes([_send()], [_note(2, job_id=JOB)])


def test_note_pinned_to_another_recruitment_is_ignored():
    assert hints.pick_send_notes([_send()], [_note(1, job_id=OTHER_JOB)]) == {}


def test_note_of_another_person_is_ignored():
    assert hints.pick_send_notes([_send()], [_note(1, author_id=OTHER_DL)]) == {}


@pytest.mark.parametrize(
    ("minutes", "counts"), [(-30, True), (30, True), (-31, False), (31, False)]
)
def test_window_is_thirty_minutes_before_and_after_the_move(minutes: int, counts: bool):
    picked = hints.pick_send_notes([_send()], [_note(1, minutes=minutes)])
    assert (JOB in picked) is counts


def test_nearest_note_wins_and_equal_distance_falls_back_to_lower_id():
    picked = hints.pick_send_notes(
        [_send()], [_note(1, minutes=20), _note(2, minutes=-2), _note(3, minutes=2)]
    )
    assert picked[JOB].id == 2


def test_newest_send_with_a_note_decides_for_a_pair_sent_twice():
    resend = SENT_AT + timedelta(days=14)
    picked = hints.pick_send_notes(
        [_send(), _send(at=resend)],
        [_note(1), _note(2, base=resend)],
    )
    assert picked[JOB].id == 2
    # Ponowna wysyłka bez notatki nie zabiera notatki z pierwszej.
    picked = hints.pick_send_notes([_send(), _send(at=resend)], [_note(1)])
    assert picked[JOB].id == 1


def test_note_without_recruitment_stands_under_both_recruitments_sent_in_the_window():
    # Nie wiemy, której rekrutacji dotyczy — czyta ją człowiek.
    picked = hints.pick_send_notes(
        [_send(JOB), _send(OTHER_JOB, at=SENT_AT + timedelta(minutes=3))],
        [_note(1, minutes=4)],
    )
    assert picked[JOB].id == 1 and picked[OTHER_JOB].id == 1


def test_naive_timestamps_are_read_as_utc():
    naive_send = hints.Send(JOB, SENT_AT.replace(tzinfo=None), DL)
    assert hints.pick_send_notes([naive_send], [_note(1)])[JOB].id == 1


@pytest.mark.parametrize(
    ("plain", "expected"),
    [
        ("Wysłany 150/100-110", True),
        ("stawka 40", True),
        ("stawka 400", True),
        ("stawka 39", False),
        ("stawka 401", False),
        ("zadzwonić 22.09 o 14:30", False),
        ("zapotrzebowanie 2026", False),
        ("@user prośba o kontakt", False),
        ("", False),
    ],
)
def test_has_amount_reads_only_numbers_in_the_hourly_rate_range(
    plain: str, expected: bool
):
    assert hints.has_amount(plain) is expected


def test_long_note_is_shortened_with_an_ellipsis():
    assert hints.shorten("a" * 300) == "a" * 300
    shortened = hints.shorten("słowo " * 100)
    assert len(shortened) <= hints.SEND_NOTE_MAX_CHARS
    assert shortened.endswith("…")


def _obs(
    key: str,
    job_id: Optional[int],
    amount: Optional[str],
    *,
    days: int = 0,
    not_comparable: bool = False,
) -> RateObservation:
    return RateObservation(
        key=key,
        candidate_id=1,
        amount_hourly=Decimal(amount) if amount else None,
        raw=None,
        at=SENT_AT + timedelta(days=days),
        source="card",
        job_id=job_id,
        not_comparable=not_comparable,
    )


def test_rate_given_in_a_recruitment_is_the_newest_comparable_one_per_job():
    newest = candidate_rate_from._newest_by_job(
        [
            _obs("card:1", JOB, "90"),
            _obs("card:2", JOB, "100", days=5),
            _obs("card:3", JOB, None, days=9, not_comparable=True),
            _obs("card:4", OTHER_JOB, "70"),
            _obs("profile-current", None, "60", days=20),
        ]
    )
    assert {job_id: obs.key for job_id, obs in newest.items()} == {
        JOB: "card:2",
        OTHER_JOB: "card:4",
    }
