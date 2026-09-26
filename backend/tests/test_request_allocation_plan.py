"""Czysty planer przydziału ludzi do requestów (decyzje Artura 24.09.2026)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.request_allocation_plan import (
    LiveAssignment,
    PersonInfo,
    PlanInput,
    RequestInfo,
    plan_assignments,
)

INFRA, DEV, QA, PM = 1, 2, 4, 5


def req(job_id, cat=DEV, *, sent=0, deadline=None, base=None) -> RequestInfo:
    return RequestInfo(
        job_id=job_id,
        categories=frozenset({cat}),
        primary_category=cat,
        sent=sent,
        deadline=deadline,
        base_matches=base,
    )


def recruiter(user_id, first=DEV, second=()) -> PersonInfo:
    return PersonInfo(
        user_id=user_id,
        can_recruit=True,
        can_source=False,
        first=frozenset({first}),
        second=frozenset(second),
    )


def sourcer(user_id, first=DEV, second=()) -> PersonInfo:
    return PersonInfo(
        user_id=user_id,
        can_recruit=False,
        can_source=True,
        first=frozenset({first}),
        second=frozenset(second),
    )


def assigned(changes) -> dict[int, int]:
    return {c.job_id: c.user_id for c in changes if c.kind == "assign"}


@pytest.mark.unit
def test_first_priority_person_gets_the_request() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, QA)],
            people=[recruiter(1, DEV), recruiter(2, QA)],
            live=[],
        )
    )
    assert assigned(changes) == {10: 2}


@pytest.mark.unit
def test_load_is_spread_evenly_inside_a_category() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10), req(11), req(12), req(13)],
            people=[recruiter(1), recruiter(2)],
            live=[],
        )
    )
    counts: dict[int, int] = {}
    for user_id in assigned(changes).values():
        counts[user_id] = counts.get(user_id, 0) + 1
    assert counts == {1: 2, 2: 2}


@pytest.mark.unit
def test_overflow_to_another_category_when_own_people_are_busier() -> None:
    # Developerka ma już 3 requesty, osoba z QA ma 0 — nowy request Dev idzie
    # do QA („przelew”), bo różnica przekracza 1.
    live = [
        LiveAssignment(
            job_id=j, user_id=1, role="recruiter", source="auto", state="active"
        )
        for j in (1, 2, 3)
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(1), req(2), req(3), req(20, DEV)],
            people=[recruiter(1, DEV), recruiter(2, QA)],
            live=live,
        )
    )
    assert assigned(changes) == {20: 2}


@pytest.mark.unit
def test_small_difference_keeps_the_request_in_its_category() -> None:
    live = [
        LiveAssignment(
            job_id=1, user_id=1, role="recruiter", source="auto", state="active"
        )
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(1), req(20, DEV)],
            people=[recruiter(1, DEV), recruiter(2, QA)],
            live=live,
        )
    )
    assert assigned(changes) == {20: 1}


@pytest.mark.unit
def test_second_priority_before_other_categories() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(30, PM)],
            people=[recruiter(1, DEV), recruiter(2, QA, second=[PM])],
            live=[],
        )
    )
    assert assigned(changes) == {30: 2}


@pytest.mark.unit
def test_many_matches_in_base_go_to_a_sourcer_few_to_a_recruiter() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(40, base=22), req(41, base=3), req(42, base=None)],
            people=[recruiter(1), sourcer(2)],
            live=[],
            sourcer_threshold=15,
        )
    )
    roles = {c.job_id: (c.user_id, c.role) for c in changes if c.kind == "assign"}
    assert roles[40] == (2, "sourcer")
    assert roles[41] == (1, "recruiter")
    assert roles[42] == (1, "recruiter")


@pytest.mark.unit
def test_no_sourcer_available_falls_back_to_a_recruiter() -> None:
    changes = plan_assignments(
        PlanInput(requests=[req(40, base=50)], people=[recruiter(1)], live=[])
    )
    assert [(c.user_id, c.role) for c in changes] == [(1, "recruiter")]


@pytest.mark.unit
def test_requests_without_anyone_sent_go_first_then_by_deadline() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[
                req(50, sent=3, deadline=date(2026, 9, 25)),
                req(51, sent=1, deadline=date(2026, 9, 26)),
                req(52, sent=0, deadline=date(2026, 10, 30)),
                req(53, sent=0, deadline=date(2026, 9, 30)),
            ],
            people=[recruiter(1)],
            live=[],
        )
    )
    assert [c.job_id for c in changes if c.kind == "assign"] == [53, 52, 51, 50]


@pytest.mark.unit
def test_request_leaving_the_pool_releases_its_people() -> None:
    live = [
        LiveAssignment(
            job_id=60, user_id=1, role="recruiter", source="auto", state="active"
        ),
        LiveAssignment(
            job_id=60, user_id=2, role="sourcer", source="manual", state="active"
        ),
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[],
            people=[recruiter(1), sourcer(2)],
            live=live,
            out_of_pool={60: "champion"},
        )
    )
    assert sorted((c.kind, c.user_id, c.reason) for c in changes) == [
        ("release", 1, "champion"),
        ("release", 2, "champion"),
    ]


@pytest.mark.unit
def test_unavailable_person_keeps_request_with_candidates_in_process() -> None:
    live = [
        LiveAssignment(
            job_id=70,
            user_id=9,
            role="recruiter",
            source="auto",
            state="active",
            in_process=True,
        ),
        LiveAssignment(
            job_id=71, user_id=9, role="recruiter", source="auto", state="active"
        ),
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(70), req(71)],
            people=[recruiter(1)],
            live=live,
        )
    )
    kinds = sorted((c.kind, c.job_id, c.user_id) for c in changes)
    assert ("release", 71, 9) in kinds
    assert ("assign", 71, 1) in kinds
    assert all(job != 70 for _, job, _ in kinds)


@pytest.mark.unit
def test_manual_assignment_is_never_released_for_availability() -> None:
    live = [
        LiveAssignment(
            job_id=80, user_id=9, role="recruiter", source="manual", state="active"
        )
    ]
    changes = plan_assignments(
        PlanInput(requests=[req(80)], people=[recruiter(1)], live=live)
    )
    assert changes == []


@pytest.mark.unit
def test_existing_assignments_are_not_rebalanced() -> None:
    live = [
        LiveAssignment(
            job_id=j, user_id=1, role="recruiter", source="auto", state="active"
        )
        for j in (1, 2, 3, 4)
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(1), req(2), req(3), req(4)],
            people=[recruiter(1), recruiter(2)],
            live=live,
        )
    )
    assert changes == []


@pytest.mark.unit
def test_shadow_proposals_are_activated_when_mode_becomes_auto() -> None:
    live = [
        LiveAssignment(
            job_id=90, user_id=1, role="recruiter", source="auto", state="proposed"
        )
    ]
    changes = plan_assignments(
        PlanInput(requests=[req(90)], people=[recruiter(1)], live=live, mode="auto")
    )
    assert [(c.kind, c.job_id) for c in changes] == [("activate", 90)]


@pytest.mark.unit
def test_auto_mode_without_leave_data_assigns_nobody_but_shadow_still_proposes() -> (
    None
):
    data = dict(requests=[req(91)], people=[recruiter(1)], live=[])
    assert (
        plan_assignments(PlanInput(**data, mode="auto", availability_known=False)) == []
    )
    assert assigned(
        plan_assignments(PlanInput(**data, mode="shadow", availability_known=False))
    ) == {91: 1}


@pytest.mark.unit
def test_off_mode_changes_nothing() -> None:
    assert (
        plan_assignments(
            PlanInput(requests=[req(1)], people=[recruiter(1)], live=[], mode="off")
        )
        == []
    )


@pytest.mark.unit
def test_off_mode_still_closes_what_is_over() -> None:
    """Runda 8 (R8-N7-4): ``off`` nie przydziela, ale zwalnia propozycje,
    przypisania przy requestach spoza puli i martwe konta."""
    live = [
        LiveAssignment(1, 11, "recruiter", "auto", "proposed"),
        LiveAssignment(1, 12, "recruiter", "manual", "active"),
        LiveAssignment(1, 13, "recruiter", "manual", "active"),
        LiveAssignment(2, 12, "recruiter", "owner", "active"),
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(1)],
            people=[recruiter(11), recruiter(12)],
            live=live,
            out_of_pool={2: "finished"},
            inactive_ids=frozenset({13}),
            mode="off",
        )
    )
    assert {(c.kind, c.job_id, c.user_id, c.reason) for c in changes} == {
        ("release", 1, 11, "mode_off"),
        ("release", 1, 13, "inactive"),
        ("release", 2, 12, "finished"),
    }

@pytest.mark.unit
def test_request_without_category_goes_to_the_least_loaded_person() -> None:
    uncategorised = RequestInfo(
        job_id=5,
        categories=frozenset(),
        primary_category=None,
        sent=0,
        deadline=None,
        base_matches=None,
    )
    live = [
        LiveAssignment(
            job_id=1, user_id=1, role="recruiter", source="auto", state="active"
        )
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[req(1), uncategorised],
            people=[recruiter(1), recruiter(2, QA)],
            live=live,
        )
    )
    assert assigned(changes) == {5: 2}


@pytest.mark.unit
def test_person_removed_by_hand_does_not_come_back_to_that_request() -> None:
    # X zdjęty ręcznie z requestu 10 ma najmniejsze obłożenie, ale automat
    # bierze kogoś innego — decyzja DL-a wygrywa, dopóki request trwa.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(1, DEV), recruiter(2, DEV)],
            live=[LiveAssignment(20, 2, "recruiter", "auto", "active")],
            mode="auto",
            blocked=frozenset({(10, 1)}),
        )
    )
    assert assigned(changes) == {10: 2}


@pytest.mark.unit
def test_nobody_assigned_when_every_capable_person_was_removed_by_hand() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(1, DEV)],
            live=[],
            mode="auto",
            blocked=frozenset({(10, 1)}),
        )
    )
    assert assigned(changes) == {}


@pytest.mark.unit
def test_auto_mode_without_leave_data_does_not_activate_proposals() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(1, DEV)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
            mode="auto",
            availability_known=False,
        )
    )
    assert [c.kind for c in changes] == []


@pytest.mark.unit
def test_person_out_of_allocation_is_released_even_without_leave_data() -> None:
    # „Poza przydziałem” nie zależy od Compassa — zwolnienie nie czeka na urlopy.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(2, DEV)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "active")],
            mode="shadow",
            availability_known=False,
            eligible_ids=frozenset({2}),
        )
    )
    released = [(c.job_id, c.user_id, c.reason) for c in changes if c.kind == "release"]
    assert released == [(10, 1, "excluded")]


@pytest.mark.unit
def test_person_on_leave_waits_for_leave_data_before_release() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "active")],
            mode="shadow",
            availability_known=False,
            eligible_ids=frozenset({1}),
        )
    )
    assert [c for c in changes if c.kind == "release"] == []


@pytest.mark.unit
def test_person_on_leave_with_candidates_in_process_is_not_activated() -> None:
    # Audyt 24.09: propozycja osoby na urlopie, która zostaje przy requeście
    # (kandydaci w toku), nie może zostać aktywowana — aktywacja robi z niej
    # prowadzącą rekrutacji.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(2, DEV)],
            live=[
                LiveAssignment(10, 1, "recruiter", "auto", "proposed", in_process=True)
            ],
            mode="auto",
            availability_known=True,
            eligible_ids=frozenset({1, 2}),
        )
    )
    assert [c for c in changes if c.kind == "activate"] == []
    assert [c for c in changes if c.kind == "release"] == []
