"""Reguły championów bez bazy (D4, D5, D8 — 15.10.2026)."""

from __future__ import annotations

from types import SimpleNamespace

from app.models.job import JobPriority
from app.services import job_champion_rules as rules
from app.services.job_priority import priority_paused


def test_only_people_at_the_client_can_be_champions() -> None:
    for column in ("cv_sent", "client_interview", "contract", "hired"):
        assert rules.is_eligible_column(column), column
    for column in ("new", "screening", "verified", "cv_qc", "closed", None):
        assert not rules.is_eligible_column(column), column


def test_list_starts_from_the_furthest_column() -> None:
    columns = ["cv_sent", "hired", "client_interview", "contract"]
    assert sorted(columns, key=rules.column_rank) == [
        "hired",
        "contract",
        "client_interview",
        "cv_sent",
    ]
    assert rules.column_rank("screening") > rules.column_rank("cv_sent")


def test_one_seat_one_champion_stops_the_search() -> None:
    assert rules.search_stops([7], [], 1)
    # Kolejni championi to zapas — dalej „nie szukamy”.
    assert rules.search_stops([7, 8], [], 1)


def test_two_seats_need_two_champions_or_a_hire() -> None:
    assert not rules.search_stops([7], [], 2)
    assert rules.search_stops([7, 8], [], 2)
    assert rules.search_stops([7], [9], 2)
    # Zatrudniony champion liczy się raz.
    assert not rules.search_stops([7], [7], 2)


def test_no_champion_never_raises_the_flag() -> None:
    # Komplet zatrudnionych to „Obsadzona”, liczona osobno.
    assert not rules.search_stops([], [1, 2], 1)
    # Brak albo zero miejsc = jedno miejsce.
    assert rules.seats(None) == 1
    assert rules.seats(0) == 1
    assert rules.search_stops([7], [], 0)


def test_diff_keeps_request_order_and_ignores_duplicates() -> None:
    added, removed = rules.diff([1, 2, 3], [3, 4, 4, 5])
    assert added == [4, 5]
    assert removed == [1, 2]
    assert rules.diff([], []) == ([], [])


def test_bell_only_for_a_real_change_or_a_return_to_search() -> None:
    kind = rules.notification_kind
    # Powrót do szukania wygrywa — także przy pustej liście.
    assert (
        kind(
            before_stopped=True, after_stopped=False, changed=True, has_champions=False
        )
        == rules.NOTIFY_RESUMED
    )
    assert (
        kind(before_stopped=False, after_stopped=True, changed=True, has_champions=True)
        == rules.NOTIFY_CHANGED
    )
    # Zapis bez zmiany i zdjęcie zapasowego championa przy zostającym — cisza
    # tylko wtedy, gdy nic się nie zmieniło.
    assert (
        kind(before_stopped=True, after_stopped=True, changed=False, has_champions=True)
        is None
    )
    assert (
        kind(
            before_stopped=False, after_stopped=False, changed=True, has_champions=False
        )
        is None
    )


def _job(priority: JobPriority, work_state: str, champion: bool) -> SimpleNamespace:
    return SimpleNamespace(
        priority=priority,
        work_state=work_state,
        champion_found_at=object() if champion else None,
    )


def test_p1_is_paused_only_by_a_visible_champion() -> None:
    assert priority_paused(_job(JobPriority.urgent, "searching", True))
    assert priority_paused(_job(JobPriority.high, "searching", True))
    assert not priority_paused(_job(JobPriority.urgent, "searching", False))
    # Champion widać tylko przy „Szukamy” (reguła z 28.09.2026).
    assert not priority_paused(_job(JobPriority.urgent, "client_silent", True))
    assert not priority_paused(_job(JobPriority.medium, "searching", True))
