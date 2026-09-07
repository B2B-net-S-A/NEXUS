"""Allocation and substitution decisions, without a local database."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.job import JobStatus
from app.models.recruitment_priority import PriorityChannel
from app.models.user import User, UserRole
from app.schemas.priority_work import PriorityAssignmentInput, PriorityPlanMemberInput
from app.services.recruitment_allocation import Workload, choose_assignee
from app.services.recruitment_favorite_work import apply_favorite_work_state
from app.services.workforce_availability import (
    AvailabilitySnapshot,
    resolve_workforce,
    WorkforceContext,
)
from app.api.calendar_access import (
    user_can_mutate_event,
    personal_event_visibility_filter,
)

NOW = datetime(2026, 9, 7, 10, tzinfo=timezone.utc)


def user(number):
    return User(
        id=number,
        name=f"Person {number}",
        email=f"person{number}@example.com",
        role=UserRole.recruiter,
        roles=["recruiter"],
        is_active=True,
    )


def snapshot(*, absence=True, substitute=2, second_absent=False, duplicate=False):
    people = [
        {
            "id": str(UUID(int=n)),
            "email": f"person{n}@example.com",
            "employment_status": "active",
            "available": True,
            "absences": [],
        }
        for n in range(1, 4)
    ]
    if absence:
        people[0].update(
            available=False,
            absences=[
                {
                    "id": str(UUID(int=20)),
                    "start_date": "2026-09-07",
                    "end_date": "2026-09-08",
                    "substitute_id": str(UUID(int=substitute)) if substitute else None,
                }
            ],
        )
    if second_absent:
        people[1].update(
            available=False,
            absences=[
                {
                    "id": str(UUID(int=21)),
                    "start_date": "2026-09-07",
                    "end_date": "2026-09-08",
                    "substitute_id": str(UUID(int=3)),
                }
            ],
        )
    if duplicate:
        people[2]["email"] = people[1]["email"]
    return AvailabilitySnapshot.model_validate(
        {
            "schema_version": 1,
            "basis": "calendar_full_day_approved_absences",
            "complete": True,
            "generated_at": NOW.isoformat(),
            "date": "2026-09-07",
            "working_day": True,
            "window_end": "2026-10-07",
            "count": 3,
            "snapshot_version": "a" * 64,
            "people": people,
        }
    )


def context(source=None, *, now=NOW, success=NOW):
    return resolve_workforce(
        source or snapshot(),
        [user(1), user(2), user(3)],
        now=now,
        last_success_at=success,
    )


def choose(loads=None, **overrides):
    params = dict(
        channel=PriorityChannel.linkedin,
        job_categories={10},
        competencies={1: {10: 1}, 2: {10: 2}, 3: {10: 1}},
        workforce=WorkforceContext(fresh=True, available_ids={1, 2, 3}),
        loads=loads or {},
        last_assigned={},
        paused_users=set(),
    )
    params.update(overrides)
    return choose_assignee([user(1), user(2), user(3)], **params)


def test_next_requests_spread_evenly_and_secondary_can_win():
    loads = {}
    selected = []
    for job_id in range(24):
        person = choose(loads)
        selected.append(person.id)
        loads.setdefault(person.id, Workload()).searches.add(job_id)
    assert [selected.count(n) for n in (1, 2, 3)] == [8, 8, 8]
    assert selected[:3] == [1, 3, 2]


def test_all_busy_still_assigns_least_loaded_and_respects_tuple_order():
    loads = {
        1: Workload(searches={1}, overdue={("task", i) for i in range(50)}),
        2: Workload(searches={2, 3}),
        3: Workload(searches={4, 5}),
    }
    assert choose(loads).id == 1
    loads[1].searches.add(6)
    assert choose(loads).id == 3


def test_ties_use_primary_then_oldest_assignment_then_id():
    assert choose(last_assigned={1: NOW, 3: NOW - timedelta(days=1)}).id == 3
    assert choose(last_assigned={1: NOW, 3: NOW}).id == 1
    assert choose(paused_users={1, 3}).id == 2


def test_unavailable_unskilled_and_paused_do_not_receive_work():
    assert (
        choose(workforce=WorkforceContext(fresh=False, available_ids={1, 2, 3})) is None
    )
    assert choose(competencies={}) is None
    assert choose(paused_users={1, 2, 3}) is None


def test_contact_and_process_for_same_candidate_are_not_double_counted():
    load = Workload(candidate_processes={(9, 100), (9, 101)}, contacts={9, 10})
    assert load.followups == 3
    load.add_task("calendar", 1, NOW, now=NOW, inherited=True)
    load.add_task("calendar", 1, NOW, now=NOW, inherited=True)
    assert len(load.today) == len(load.inherited_tasks) == 1


def test_date_deadline_is_today_until_end_of_warsaw_day():
    load = Workload()
    load.add_task("onboarding", 1, date(2026, 9, 7), now=NOW, inherited=False)
    load.add_task("contact", 2, NOW - timedelta(seconds=1), now=NOW, inherited=False)
    assert load.comparison == (0, 1, 1, 0)


def test_direct_cover_and_stale_fail_closed_but_preserve_known_cover():
    current = context()
    assert current.performer(1) == 2
    assert current.owners_for(2) == {1, 2}
    stale = context(now=NOW + timedelta(minutes=6))
    assert not stale.fresh and not stale.available_ids
    assert stale.performer(1) == 2
    expired = context(now=NOW + timedelta(days=2))
    assert expired.performer(1) == 1 and expired.owners_for(2) == {2}


def test_cancel_and_change_recompute_without_mutating_nominal_owner():
    assert context(snapshot(absence=False)).performer(1) == 1
    assert context(snapshot(substitute=3)).performer(1) == 3
    assert context().performer(1) == 2


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"substitute": None}, "substitute_missing"),
        ({"substitute": 1}, "substitution_cycle"),
        ({"second_absent": True}, "substitute_absent"),
        ({"duplicate": True}, "substitute_unmapped"),
    ],
)
def test_invalid_substitution_keeps_original_work_visible_as_exception(options, reason):
    result = context(snapshot(**options))
    assert result.performer(1) == 1
    assert reason in {issue["code"] for issue in result.issues}


def test_conflicting_overlapping_absences_do_not_choose_arbitrarily():
    source = snapshot()
    source.people[0].absences.append(
        source.people[0]
        .absences[0]
        .model_copy(update={"id": UUID(int=22), "substitute_id": UUID(int=3)})
    )
    result = context(source)
    assert result.performer(1) == 1
    assert result.issues[0]["code"] == "substitution_conflict"


def test_partial_source_snapshot_is_rejected():
    value = snapshot().model_dump()
    value["people"] = value["people"][:2]
    with pytest.raises(ValidationError):
        AvailabilitySnapshot.model_validate(value)


def job(**changes):
    return SimpleNamespace(
        **(
            dict(
                favorite_candidate_id=9,
                needs_sourcing=True,
                favorite_sourcing_paused=False,
                is_open=True,
                status=JobStatus.published,
                recruiter_id=1,
            )
            | changes
        )
    )


def test_favorite_frees_search_then_loss_resumes_same_owner():
    item = job()
    assert apply_favorite_work_state(item, stage="interview", vacancies=1)
    assert not item.needs_sourcing and item.favorite_sourcing_paused
    assert apply_favorite_work_state(item, stage="rejected", vacancies=1)
    assert (
        item.needs_sourcing
        and item.favorite_candidate_id is None
        and item.recruiter_id == 1
    )


def test_one_favorite_cannot_pause_two_vacancies_and_manual_pause_survives_loss():
    item = job()
    apply_favorite_work_state(item, stage="interview", vacancies=2)
    assert item.needs_sourcing
    manual = job(needs_sourcing=False)
    apply_favorite_work_state(manual, stage="rejected", vacancies=1)
    assert not manual.needs_sourcing and not manual.favorite_sourcing_paused


def test_filled_or_closed_job_does_not_resume_when_favorite_is_lost():
    for changes, vacancies in [({}, 0), ({"status": JobStatus.closed}, 1)]:
        item = job(needs_sourcing=False, favorite_sourcing_paused=True, **changes)
        apply_favorite_work_state(item, stage="withdrawn", vacancies=vacancies)
        assert not item.needs_sourcing


def test_more_than_five_numeric_positions_and_legacy_aliases():
    rows = [
        PriorityAssignmentInput(job_id=n, demand_id=n, position=n, channel="linkedin")
        for n in range(1, 13)
    ]
    member = PriorityPlanMemberInput(user_id=1, assignments=rows)
    assert len(member.assignments) == 12
    assert (
        rows[0].rank.value == "A" and rows[4].rank.value == "E" and rows[5].rank is None
    )
    with pytest.raises(ValidationError):
        PriorityAssignmentInput(
            job_id=1, demand_id=1, position=6, rank="A", channel="linkedin"
        )


def test_calendar_substitute_can_complete_open_event_but_cannot_read_unrelated_history():
    with Session() as session:
        substitute = user(2)
        session.add(substitute)
        session.info["workforce_context"] = context()
        event = CalendarEvent(
            created_by=1, operational_owner_id=1, status=EventStatus.scheduled
        )
        assert user_can_mutate_event(event, substitute)
        event.status = EventStatus.completed
        assert not user_can_mutate_event(event, substitute)
        event.status = EventStatus.scheduled
        event.operational_owner_id = 3  # explicit manual transfer is authoritative
        assert not user_can_mutate_event(event, substitute)
        assert "operational_owner_id" in str(
            personal_event_visibility_filter(substitute)
        )


def test_favorite_pause_is_visible_and_does_not_block_lower_priority_work():
    from app.services.priority_work_service import assignment_gate_states
    from app.models.recruitment_priority import PriorityMemberStatus
    from types import SimpleNamespace

    first = SimpleNamespace(
        id=1, job_id=11, position=1, verification_target=5, recommendation_target=3
    )
    second = SimpleNamespace(
        id=2, job_id=12, position=6, verification_target=1, recommendation_target=1
    )
    member = SimpleNamespace(
        status=PriorityMemberStatus.active, assignments=[first, second]
    )
    state = assignment_gate_states(
        member, {2: {"verifications": 1, "recommendations": 1}}, {}, paused_job_ids={11}
    )
    assert state == {1: "sourcing_paused", 2: "target_reached"}


def test_cover_scope_requires_open_work_and_the_same_owners_membership():
    import sqlite3
    from sqlalchemy import literal, select
    from sqlalchemy.dialects import sqlite
    from app.services.workforce_availability import inherited_collaborator_work_clause

    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE recruitment_processes(job_id INTEGER, owner_user_id INTEGER, status TEXT);
            CREATE TABLE calendar_events(job_id INTEGER, created_by INTEGER, operational_owner_id INTEGER, status TEXT);
            CREATE TABLE candidate_contact_cases(id INTEGER, owner_user_id INTEGER, state TEXT);
            CREATE TABLE candidate_contact_opportunities(case_id INTEGER, job_id INTEGER, closed_at TEXT);
            CREATE TABLE job_collaborators(job_id INTEGER, user_id INTEGER, removed_from_auto_cc BOOLEAN);
            INSERT INTO job_collaborators VALUES
                (1,10,0), (2,20,0), (3,10,0), (4,10,0),
                (5,10,0), (6,10,0), (7,10,0), (8,10,1);
            INSERT INTO recruitment_processes VALUES (4,10,'open'), (5,10,'closed');
            INSERT INTO calendar_events VALUES
                (6,99,10,'scheduled'), (7,10,NULL,'completed');
            INSERT INTO candidate_contact_cases VALUES
                (1,10,'queued'), (2,10,'completed'), (3,10,'queued');
            INSERT INTO candidate_contact_opportunities VALUES
                (1,1,NULL), (1,2,NULL), (1,9,NULL), (2,5,NULL), (3,8,NULL);
        """)

        def visible_jobs():
            visible = []
            for job_id in range(1, 10):
                column = literal(job_id)
                statement = select(column).where(
                    inherited_collaborator_work_clause(column, {10, 20})
                )
                sql = str(
                    statement.compile(
                        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
                    )
                )
                if db.execute(sql).fetchone():
                    visible.append(job_id)
            return visible

        # Covering two people must not combine one's case with the other's
        # unrelated collaboration. An observer, completed task, removed access
        # and a candidate's unrelated opportunity remain outside the scope.
        assert visible_jobs() == [1, 4, 6]
        db.executescript("""
            UPDATE recruitment_processes SET status='closed';
            UPDATE calendar_events SET status='completed';
            UPDATE candidate_contact_cases SET state='completed';
        """)
        assert visible_jobs() == []
