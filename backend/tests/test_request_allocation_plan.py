"""Czysty planer przydziału ludzi do requestów (decyzje Artura 24.09.2026)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.request_allocation_plan import (
    RELEASE_REASONS,
    LiveAssignment,
    PersonInfo,
    PlanInput,
    RequestInfo,
    category_fit,
    is_silent_release,
    plan_assignments,
    release_reason_label,
)

INFRA, DEV, QA, PM = 1, 2, 4, 5


def req(
    job_id, cat=DEV, *, sent=0, deadline=None, base=None, p1=True, passive=False
) -> RequestInfo:
    # Domyślnie P1: tylko takim requestom automat dobiera ludzi.
    return RequestInfo(
        job_id=job_id,
        categories=frozenset({cat}),
        primary_category=cat,
        sent=sent,
        deadline=deadline,
        base_matches=base,
        priority_rank=0 if p1 else 1,
        passive=passive,
    )


def recruiter(user_id, first=DEV, second=()) -> PersonInfo:
    return PersonInfo(
        user_id=user_id,
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
def test_base_matches_do_not_change_the_work_role() -> None:
    """Do 0411 request z wieloma pasującymi w bazie (próg 15) szedł do sourcera.

    Rola pracy jest jedna: liczba pasujących nie wybiera już ani roli, ani
    osoby — request z 30 pasującymi dostaje rekrutera jak każdy inny.
    """
    changes = plan_assignments(
        PlanInput(
            requests=[req(40, base=30), req(41, base=3), req(42, base=None)],
            people=[recruiter(1), recruiter(2)],
            live=[],
        )
    )
    assigns = [c for c in changes if c.kind == "assign"]
    assert sorted(c.job_id for c in assigns) == [40, 41, 42]
    assert {c.role for c in assigns} == {"recruiter"}
    # Rozkład po obłożeniu, nie po liczbie pasujących w bazie.
    counts: dict[int, int] = {}
    for change in assigns:
        counts[change.user_id] = counts.get(change.user_id, 0) + 1
    assert sorted(counts.values()) == [1, 2]

    alone = plan_assignments(
        PlanInput(requests=[req(40, base=30)], people=[recruiter(1)], live=[])
    )
    assert [(c.user_id, c.role) for c in alone] == [(1, "recruiter")]


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
            job_id=60, user_id=2, role="recruiter", source="manual", state="active"
        ),
    ]
    changes = plan_assignments(
        PlanInput(
            requests=[],
            people=[recruiter(1), recruiter(2)],
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
def test_auto_mode_with_stale_compass_leave_assigns_nobody_but_shadow_proposes() -> (
    None
):
    # Urlopy z Compassa włączone, ale nieaktualne: request mógłby dostać ktoś
    # na urlopie, więc tryb automatyczny czeka.
    data = dict(requests=[req(91)], people=[recruiter(1)], live=[])
    stale = dict(availability_known=False, leave_blocks_auto=True)
    assert plan_assignments(PlanInput(**data, mode="auto", **stale)) == []
    assert assigned(plan_assignments(PlanInput(**data, mode="shadow", **stale))) == {
        91: 1
    }


@pytest.mark.unit
def test_auto_mode_without_compass_assigns_right_away() -> None:
    # Urlopy z Compassa wyłączone: danych nie będzie, więc nie ma na co
    # czekać — automat przydziela od razu.
    changes = plan_assignments(
        PlanInput(
            requests=[req(91)],
            people=[recruiter(1)],
            live=[],
            mode="auto",
            availability_known=False,
        )
    )
    assert assigned(changes) == {91: 1}


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
        priority_rank=0,
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
def test_auto_mode_with_stale_compass_leave_does_not_activate_proposals() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(1, DEV)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
            mode="auto",
            availability_known=False,
            leave_blocks_auto=True,
        )
    )
    assert [c.kind for c in changes] == []


@pytest.mark.unit
def test_auto_mode_without_compass_activates_proposals() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV)],
            people=[recruiter(1, DEV)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
            mode="auto",
            availability_known=False,
        )
    )
    assert [(c.kind, c.job_id, c.user_id) for c in changes] == [("activate", 10, 1)]


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


# ── Priorytet, obsada bez wiersza i propozycje do akceptacji (02.10.2026) ────


def released(changes) -> list[tuple[int, int, str]]:
    return [(c.job_id, c.user_id, c.reason) for c in changes if c.kind == "release"]


@pytest.mark.unit
def test_only_p1_requests_get_a_person() -> None:
    # Automat dobiera ludzi tylko do P1 (prośba Head of Recruitment,
    # 12.10.2026) — zwykły request zostaje bez rekrutera mimo bliższego terminu.
    changes = plan_assignments(
        PlanInput(
            requests=[
                req(10, sent=0, deadline=date(2026, 10, 5), p1=False),
                req(11, sent=3, deadline=date(2026, 12, 1), p1=True),
                req(12, sent=0, p1=True),
            ],
            people=[recruiter(1)],
            live=[],
        )
    )
    assert [c.job_id for c in changes if c.kind == "assign"] == [12, 11]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["shadow", "auto"])
def test_request_below_p1_stays_empty_after_manual_removal(mode: str) -> None:
    # Zgłoszenie: osoba zdjęta ręcznie z requestu P2, a automat dokładał
    # następną. Teraz request zostaje „Bez rekrutera”, w obu trybach.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV, p1=False)],
            people=[recruiter(1, DEV), recruiter(2, DEV)],
            live=[],
            mode=mode,
            blocked=frozenset({(10, 1)}),
        )
    )
    assert changes == []


@pytest.mark.unit
def test_request_below_p1_keeps_the_person_it_already_has() -> None:
    # Bramka dotyczy tylko nowych przydziałów — kto pracuje, zostaje.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False)],
            people=[recruiter(1), recruiter(2)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "active")],
            mode="auto",
        )
    )
    assert changes == []


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["shadow", "auto"])
def test_proposal_on_a_request_below_p1_is_released_not_activated(mode: str) -> None:
    # Propozycja sprzed zmiany priorytetu (albo sprzed tej reguły) znika —
    # w trybie „auto” inaczej stałaby się aktywnym przydziałem.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False)],
            people=[recruiter(1)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
            mode=mode,
        )
    )
    assert [(c.kind, c.job_id, c.user_id, c.reason) for c in changes] == [
        ("release", 10, 1, "not_p1")
    ]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["shadow", "auto"])
def test_person_on_leave_keeps_a_request_below_p1(mode: str) -> None:
    # Urlop zwalnia tam, gdzie automat dobierze następcę. Przy requeście
    # innym niż P1 nikt by go nie zastąpił, a zwolnienie automatu jest trwałe
    # — po jednym dniu urlopu request zostałby bez rekrutera na stałe.
    live = [LiveAssignment(10, 1, "recruiter", "auto", "active")]
    below = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False)],
            people=[recruiter(2)],
            live=live,
            mode=mode,
            availability_known=True,
            eligible_ids=frozenset({1, 2}),
        )
    )
    assert below == []
    # Ten sam urlop przy P1: zwolnienie i następca, jak dotąd.
    urgent = plan_assignments(
        PlanInput(
            requests=[req(10, p1=True)],
            people=[recruiter(2)],
            live=live,
            mode=mode,
            availability_known=True,
            eligible_ids=frozenset({1, 2}),
        )
    )
    assert released(urgent) == [(10, 1, "unavailable")]
    assert assigned(urgent) == {10: 2}


@pytest.mark.unit
def test_person_out_of_allocation_leaves_a_request_below_p1_empty() -> None:
    # „Poza przydziałem” to decyzja człowieka o tej osobie — przypisanie
    # automatu jest zwalniane także przy P2, ale nikt nie jest dokładany.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False)],
            people=[recruiter(2)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "active")],
            mode="auto",
            availability_known=False,
            eligible_ids=frozenset({2}),
        )
    )
    assert [(c.kind, c.job_id, c.user_id, c.reason) for c in changes] == [
        ("release", 10, 1, "excluded")
    ]


@pytest.mark.unit
def test_request_raised_to_p1_gets_a_person_despite_an_earlier_removal() -> None:
    # Ten sam request po zmianie P2 → P1: automat dobiera, ale nie osobę
    # zdjętą ręcznie w bieżącym stanie requestu.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, DEV, p1=True)],
            people=[recruiter(1, DEV), recruiter(2, DEV)],
            live=[],
            mode="auto",
            blocked=frozenset({(10, 1)}),
        )
    )
    assert assigned(changes) == {10: 2}


@pytest.mark.unit
def test_passive_request_gets_nobody_and_keeps_its_people() -> None:
    # „Przyjmujemy kandydatów”: nikogo nowego, ale kto przy nim jest, zostaje.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, passive=True), req(11, passive=True)],
            people=[recruiter(1), recruiter(2)],
            live=[LiveAssignment(11, 2, "recruiter", "auto", "active")],
        )
    )
    assert changes == []


@pytest.mark.unit
def test_request_with_a_person_working_without_a_row_is_covered() -> None:
    # Ręcznie dopisany współpracownik nie ma wiersza przypisania — request
    # z taką osobą nie dostaje propozycji.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10), req(11)],
            people=[recruiter(1)],
            live=[],
            staffed=frozenset({10}),
        )
    )
    assert assigned(changes) == {11: 1}


@pytest.mark.unit
def test_load_counts_only_p1_requests() -> None:
    # Obłożenie = requesty P1 (decyzja Artura 14.10.2026, ta sama liczba co
    # panel „Obłożenie”): osoba 1 ma trzy requesty bez priorytetu, osoba 2
    # jeden P1 — nowy P1 dostaje osoba 1. Do tej daty dostawała go osoba 2.
    data = PlanInput(
        requests=[
            req(10, p1=False),
            req(11, p1=False),
            req(12, p1=False),
            req(13),
            req(20),
        ],
        people=[recruiter(1), recruiter(2)],
        live=[
            LiveAssignment(10, 1, "recruiter", "manual", "active"),
            LiveAssignment(11, 1, "recruiter", "manual", "active"),
            LiveAssignment(12, 1, "recruiter", "manual", "active"),
            LiveAssignment(13, 2, "recruiter", "manual", "active"),
        ],
    )
    changes = plan_assignments(data)
    assert assigned(changes) == {20: 1}
    # Osoby przy requestach spoza P1 zostają (planer ich nie rusza).
    assert released(changes) == []


@pytest.mark.unit
def test_work_without_a_row_counts_in_the_persons_load() -> None:
    data = dict(requests=[req(20)], people=[recruiter(1), recruiter(2)], live=[])
    assert assigned(plan_assignments(PlanInput(**data))) == {20: 1}
    # Osoba 1 pracuje już przy trzech requestach jako współpracownik.
    assert assigned(plan_assignments(PlanInput(**data, extra_load={1: 3}))) == {20: 2}


@pytest.mark.unit
def test_proposal_is_released_when_someone_works_on_the_request() -> None:
    # Delivery Lead przypisał rekrutera (aktywny wiersz) — propozycja znika
    # i nikt nowy nie jest proponowany.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2), recruiter(3)],
            live=[
                LiveAssignment(10, 1, "recruiter", "auto", "proposed"),
                LiveAssignment(10, 2, "recruiter", "manual", "active"),
            ],
        )
    )
    assert released(changes) == [(10, 1, "superseded")]
    assert assigned(changes) == {}


@pytest.mark.unit
def test_proposal_is_released_when_a_collaborator_works_on_the_request() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
            staffed=frozenset({10}),
        )
    )
    assert released(changes) == [(10, 1, "superseded")]
    assert assigned(changes) == {}


@pytest.mark.unit
def test_auto_mode_does_not_activate_a_superseded_proposal() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2)],
            live=[
                LiveAssignment(10, 1, "recruiter", "auto", "proposed"),
                LiveAssignment(10, 2, "recruiter", "owner", "active"),
            ],
            mode="auto",
        )
    )
    assert [(c.kind, c.user_id, c.reason) for c in changes] == [
        ("release", 1, "superseded")
    ]


@pytest.mark.unit
def test_proposal_on_a_passive_request_is_released() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, passive=True)],
            people=[recruiter(1)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
        )
    )
    assert released(changes) == [(10, 1, "passive")]
    assert assigned(changes) == {}


@pytest.mark.unit
def test_lone_proposal_covers_the_request_and_counts_in_load() -> None:
    # Jedna żywa propozycja na request: nie dokładamy drugiej, a następny
    # request idzie do kogoś innego niż osoba z propozycją.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10), req(11)],
            people=[recruiter(1), recruiter(2)],
            live=[LiveAssignment(10, 1, "recruiter", "auto", "proposed")],
        )
    )
    assert released(changes) == []
    assert assigned(changes) == {11: 2}


@pytest.mark.unit
def test_proposal_stays_when_the_only_worker_is_released_in_the_same_run() -> None:
    # Osoba 9 (automat) jest na urlopie i schodzi z requestu — propozycja dla
    # osoby 1 nie jest wtedy „zastąpiona”, bo nikt przy requeście nie zostaje.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1)],
            live=[
                LiveAssignment(10, 1, "recruiter", "auto", "proposed"),
                LiveAssignment(10, 9, "recruiter", "auto", "active"),
            ],
        )
    )
    assert released(changes) == [(10, 9, "unavailable")]
    assert assigned(changes) == {}


@pytest.mark.unit
def test_rejected_person_is_not_proposed_to_the_same_request_again() -> None:
    # Odrzucona propozycja trafia do ``blocked`` planera: request dostaje
    # propozycję innej osoby, choć odrzucona ma mniej pracy.
    changes = plan_assignments(
        PlanInput(
            requests=[req(10), req(20)],
            people=[recruiter(1), recruiter(2)],
            live=[LiveAssignment(20, 2, "recruiter", "auto", "active")],
            blocked=frozenset({(10, 1)}),
        )
    )
    assert assigned(changes) == {10: 2}


@pytest.mark.unit
def test_category_fit_names_the_group_the_planner_uses() -> None:
    assert category_fit({DEV}, {DEV}, {QA}) == "first"
    assert category_fit({DEV, PM}, {QA}, {PM}) == "second"
    assert category_fit({DEV}, {QA}, {PM}) == "other"
    assert category_fit(set(), {DEV}, {QA}) == "other"
    # 1. priorytet wygrywa, gdy kategorie requestu trafiają w oba.
    assert category_fit({DEV, QA}, {QA}, {DEV}) == "first"


@pytest.mark.unit
def test_proposal_decisions_have_polish_labels() -> None:
    for code in ("superseded", "passive", "rejected", "replaced"):
        assert RELEASE_REASONS[code]
        assert release_reason_label(f"proposal:{code}") == RELEASE_REASONS[code]
        # ``release_reason`` to VARCHAR(40), a zapis niesie przedrostek.
        assert len(f"proposal:{code}") <= 40


def test_withdrawn_proposals_and_reassignments_are_not_staffing_changes() -> None:
    """„Zmiany od wczoraj” i poranny skrót pomijają zwolnienia, które nikomu
    niczego nie zabrały: propozycję (osoba nigdy nie pracowała) i ręczne
    zdjęcie, po którym przypisano tę samą osobę ponownie."""
    for reason in (
        "proposal:rejected",
        "proposal:replaced",
        "proposal:superseded",
        "proposal:champion",
        "reassigned",
    ):
        assert is_silent_release(reason) is True, reason
    for reason in (
        "manual",
        "champion",
        "leave",
        "inactive",
        "owner_changed",
        "",
        None,
    ):
        assert is_silent_release(reason) is False, reason


@pytest.mark.unit
def test_saved_rules_ignore_the_retired_sourcer_threshold() -> None:
    """Do 0411 zasady miały próg „od ilu pasujących w bazie wystarczy sourcer”.

    Stary klucz w zapisanej wartości (albo w żądaniu ze starej karty) jest
    ignorowany i nie wraca w wyniku — zostaje sama godzina przeglądu.
    """
    from app.services.request_allocation_rules import parse_rules, validate_rules

    stored = {"sourcer_threshold": 40, "review_time": "07:45"}
    assert parse_rules(stored).review_time == "07:45"
    assert "sourcer_threshold" not in parse_rules(stored).as_dict()
    assert validate_rules(stored).review_time == "07:45"
    assert "sourcer_threshold" not in validate_rules(stored).as_dict()
    # Sam stary klucz = wartości domyślne przy odczycie, błąd przy zapisie.
    assert parse_rules({"sourcer_threshold": 40}).review_time == "08:30"
    with pytest.raises(ValueError, match="Godzina przeglądu"):
        validate_rules({"sourcer_threshold": 15, "review_time": "8:30"})


# ── Zasady z Ustawień (29.10.2026) ───────────────────────────────────────────
#
# Artur: zasady zmieniają tylko nowe przydziały — „nic nie zmieniaj w tych,
# co są już przydzielone”.


def _rules(**kwargs):
    from app.services.request_allocation_plan import PlanRules

    return PlanRules(**kwargs)


def _auto(job_id, user_id, *, state="active", source="auto") -> LiveAssignment:
    return LiveAssignment(job_id, user_id, "recruiter", source, state)


@pytest.mark.unit
def test_p2_gets_people_only_with_the_p2_rule() -> None:
    data = dict(requests=[req(10, p1=False)], people=[recruiter(1)], live=[])
    assert assigned(plan_assignments(PlanInput(**data))) == {}
    with_p2 = plan_assignments(PlanInput(**data, rules=_rules(include_p2=True)))
    assert assigned(with_p2) == {10: 1}


@pytest.mark.unit
def test_accepting_never_gets_people_even_with_p2() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False, passive=True)],
            people=[recruiter(1)],
            live=[],
            rules=_rules(include_p2=True),
        )
    )
    assert assigned(changes) == {}


@pytest.mark.unit
def test_p2_spreads_over_runs_by_p1_plus_p2_load() -> None:
    """Osoba z dwiema P2 od automatu nie dostaje trzeciej przed kimś bez nich,
    choć obie mają tyle samo P1."""
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False), req(11, p1=False), req(12, p1=False)],
            people=[recruiter(1), recruiter(2)],
            live=[_auto(10, 1), _auto(11, 1)],
            rules=_rules(include_p2=True),
        )
    )
    assert assigned(changes) == {12: 2}


@pytest.mark.unit
def test_two_people_per_p1_adds_a_second_person_and_keeps_the_first() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2)],
            live=[_auto(10, 1)],
            rules=_rules(people_per_p1=2),
        )
    )
    assert [c for c in changes if c.kind == "release"] == []
    assert assigned(changes) == {10: 2}


@pytest.mark.unit
def test_people_per_p1_counts_unseen_workers_and_skips_them() -> None:
    """Ręcznie dopisany współpracownik (bez wiersza) jest obsadą i nie
    dostaje tego samego requestu drugi raz."""
    changes = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2), recruiter(3)],
            live=[],
            staffed=frozenset({10}),
            staffed_people={10: frozenset({1})},
            extra_load={1: 1},
            rules=_rules(people_per_p1=3),
        )
    )
    new = sorted(c.user_id for c in changes if c.kind == "assign")
    assert new == [2, 3]


@pytest.mark.unit
def test_proposal_stays_while_the_team_is_short() -> None:
    """Przy 2 osobach na P1 propozycja obok jednej pracującej osoby zostaje
    (dziś: znika jako „superseded”)."""
    live = [_auto(10, 1), _auto(10, 2, state="proposed")]
    default = plan_assignments(
        PlanInput(requests=[req(10)], people=[recruiter(1), recruiter(2)], live=live)
    )
    assert [(c.kind, c.reason) for c in default] == [("release", "superseded")]
    two = plan_assignments(
        PlanInput(
            requests=[req(10)],
            people=[recruiter(1), recruiter(2)],
            live=live,
            rules=_rules(people_per_p1=2),
        )
    )
    assert two == []


@pytest.mark.unit
def test_load_limit_stops_new_p1_and_takes_nothing_away() -> None:
    changes = plan_assignments(
        PlanInput(
            requests=[req(10), req(11), req(12)],
            people=[recruiter(1)],
            live=[_auto(10, 1), _auto(11, 1)],
            rules=_rules(max_load=2),
        )
    )
    assert changes == []


@pytest.mark.unit
def test_load_limit_counts_p1_only() -> None:
    """Limit to rekrutacje P1 — P2 nie zajmuje miejsca."""
    changes = plan_assignments(
        PlanInput(
            requests=[req(10, p1=False), req(11)],
            people=[recruiter(1)],
            live=[_auto(10, 1)],
            rules=_rules(max_load=1, include_p2=True),
        )
    )
    assert assigned(changes) == {11: 1}


@pytest.mark.unit
def test_overflow_rule_sets_when_another_category_steps_in() -> None:
    """QA-owiec ma 2 P1, deweloper 0. Dziś (różnica ponad 1) request QA idzie
    do dewelopera; przy różnicy ponad 2 zostaje w kategorii."""
    data = dict(
        requests=[req(10, QA), req(11, QA), req(20, QA)],
        people=[recruiter(1, QA), recruiter(2, DEV)],
        live=[_auto(10, 1), _auto(11, 1)],
    )
    assert assigned(plan_assignments(PlanInput(**data))) == {20: 2}
    assert assigned(plan_assignments(PlanInput(**data, rules=_rules(overflow=2)))) == {
        20: 1
    }


@pytest.mark.unit
def test_without_outsiders_a_request_outside_everyones_category_waits() -> None:
    data = dict(requests=[req(10, PM)], people=[recruiter(1, DEV)], live=[])
    assert assigned(plan_assignments(PlanInput(**data))) == {10: 1}
    assert (
        assigned(plan_assignments(PlanInput(**data, rules=_rules(outsiders=False))))
        == {}
    )


@pytest.mark.unit
def test_deadline_first_order() -> None:
    soon = date(2026, 11, 2)
    later = date(2026, 12, 1)
    data = dict(
        requests=[req(10, sent=3, deadline=soon), req(11, sent=0, deadline=later)],
        people=[recruiter(1)],
        live=[],
    )
    first_default = [c.job_id for c in plan_assignments(PlanInput(**data))]
    first_deadline = [
        c.job_id
        for c in plan_assignments(
            PlanInput(**data, rules=_rules(order="deadline_first"))
        )
    ]
    assert first_default[0] == 11
    assert first_deadline[0] == 10


@pytest.mark.unit
def test_no_rule_releases_people_who_already_work() -> None:
    """Każda kombinacja zasad: działające przypisania (automat, ręczne,
    prowadzący) przy P1 i P2 zostają — także po wyłączeniu P2."""
    import itertools

    live = [
        _auto(10, 1),
        _auto(11, 2, source="manual"),
        _auto(12, 3, source="owner"),
        _auto(13, 1),  # P2 od automatu z czasu, gdy P2 było włączone
    ]
    requests = [req(10, PM), req(11), req(12), req(13, p1=False)]
    people = [recruiter(1), recruiter(2), recruiter(3)]
    for p2, per, limit, overflow, outsiders, order in itertools.product(
        (False, True),
        (1, 2, 3),
        (None, 1),
        (0, 3),
        (False, True),
        ("sent_first", "deadline_first"),
    ):
        changes = plan_assignments(
            PlanInput(
                requests=requests,
                people=people,
                live=live,
                mode="auto",
                rules=_rules(
                    include_p2=p2,
                    people_per_p1=per,
                    max_load=limit,
                    overflow=overflow,
                    outsiders=outsiders,
                    order=order,
                ),
            )
        )
        assert [c for c in changes if c.kind == "release"] == []


@pytest.mark.unit
def test_rules_validation_and_lenient_read() -> None:
    from app.services.request_allocation_rules import (
        AllocationRules,
        changed_fields,
        parse_rules,
        validate_rules,
    )

    assert parse_rules(None) == AllocationRules()
    # Stary front wysyła samą godzinę — reszta zostaje domyślna.
    assert validate_rules({"review_time": "07:00"}) == AllocationRules(
        review_time="07:00"
    )
    broken = parse_rules({"people_per_p1": 9, "max_load": "6", "order": "x"})
    assert broken == AllocationRules()
    for bad, message in (
        ({"people_per_p1": 4}, "od 1 do 3"),
        ({"people_per_p1": True}, "od 1 do 3"),
        ({"max_load": 0}, "Limit na osobę"),
        ({"overflow": 5}, "Różnica"),
        ({"order": "random"}, "kolejność"),
        ({"leave_policy": "maybe"}, "urlopach"),
        ({"include_p2": "yes"}, "P2"),
    ):
        with pytest.raises(ValueError, match=message):
            validate_rules({"review_time": "08:30", **bad})
    saved = validate_rules({"review_time": "08:30", "max_load": 6, "include_p2": True})
    assert changed_fields(AllocationRules(), saved) == {
        "include_p2": [False, True],
        "max_load": [None, 6],
    }
