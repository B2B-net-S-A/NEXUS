"""Scalenie rekrutacji-duplikatów po migracji z Traffita (12.10.2026) — Postgres.

Kopia z Traffita oddaje pary rekrutacji założonej w NEXUSIE i się zamyka.
Unikalność prób procesu, blokady i „najwyżej jeden otwarty proces pary” siedzą
w bazie, więc atrapa niczego by nie dowiodła.

Baza testowa jest wspólna i nieczyszczona — każdy test ma własnego klienta,
rekrutacje i osoby; asercje tylko na własnych wierszach.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.job_proposal import JobProposal
from app.models.job_work_assignment import JobWorkAssignment
from app.models.note import Note
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

# Relacja `CortexSkillFact` → `Skill` (patrz test_traffit_managed_in_nexus).
from app.models.skill import Skill  # noqa: F401
from app.services import job_lifecycle
from app.services import job_twin_merge as merge
from app.services import traffit_transfer as transfer
from tests._job_factory import new_recruiter

UTC = timezone.utc
PEOPLE = ("only_copy", "both", "returning", "applied", "applied_twice")


async def _admin_id() -> int:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"twin-merge-admin-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Twin merge admin",
            role=UserRole.admin,
            roles=["admin"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _seed(
    *,
    exact: bool = True,
    target_status: JobStatus = JobStatus.published,
    copy_closed_by_person: bool = False,
    kpi_gap: bool = False,
) -> dict[str, Any]:
    """Kopia z Traffita i rekrutacja NEXUSA tego samego requestu.

    * ``only_copy``     — karta tylko w kopii: dwa wiersze historii, notatka,
      karta rekomendacji, termin rozmowy u klienta, „Stawka od” z kopii;
      w NEXUSIE jest jej propozycją;
    * ``both``          — karta w obu rekrutacjach;
    * ``returning``     — w kopii druga próba; w NEXUSIE unieważniony proces
      po karcie ze scrapera zamienionej na propozycję;
    * ``applied``       — zgłoszenie z ogłoszenia: propozycja i notatka tylko
      w kopii;
    * ``applied_twice`` — to samo zgłoszenie jako propozycja w obu;
    * ``held`` (``kpi_gap``) — w kopii „CV wysłane” bez sklasyfikowanego
      procesu, w NEXUSIE wcześniejszy unieważniony proces sklasyfikowany.
    """
    unique = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    when = now - timedelta(days=3)
    owner, helper = await new_recruiter(), await new_recruiter()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Twin merge client {unique}")
        db.add(client)
        await db.flush()
        copy = Job(
            title=f"Twin merge {unique} (ZOB-1)",
            status=JobStatus.closed if copy_closed_by_person else JobStatus.published,
            client_id=client.id,
            external_source="traffit",
            external_id=f"tm-rec-{unique}",
            managed_in_nexus=True,
            is_open=not copy_closed_by_person,
            work_state="finished" if copy_closed_by_person else "searching",
            recruiter_id=owner,
        )
        if copy_closed_by_person:
            copy.closed_at = now - timedelta(hours=1)
            copy.close_reason = JobCloseReason.budget
            copy.close_notes = "Klient wstrzymał budżet."
        target_open = target_status == JobStatus.published
        nexus = Job(
            title=f"Twin merge {unique} (ZOB-1)",
            status=target_status,
            client_id=client.id,
            external_source="manual",
            is_open=target_open,
            work_state="searching" if target_open else "finished",
            recruiter_id=owner,
        )
        people = {
            key: Candidate(
                name="Twin",
                lastname=f"{key}-{unique}",
                external_source="traffit",
                external_id=f"tm-emp-{key}-{unique}",
            )
            for key in (*PEOPLE, *(("held",) if kpi_gap else ()))
        }
        db.add_all([copy, nexus, *people.values()])
        await db.flush()
        people["only_copy"].rate_from_job_id = copy.id

        def row(who: str, job: Job, stage: PipelineStage, *, at=when, traffit=True):
            return CandidateStage(
                candidate_id=people[who].id,
                job_id=job.id,
                stage=stage,
                moved_at=at,
                external_source="traffit" if traffit else None,
                external_id=f"tm-h-{uuid.uuid4().hex[:10]}" if traffit else None,
            )

        def process(
            who: str,
            job: Job,
            status: ProcessStatus,
            attempt: int = 1,
            origin: Optional[PriorityOriginKind] = None,
        ):
            return RecruitmentProcess(
                candidate_id=people[who].id,
                job_id=job.id,
                client_id=client.id,
                attempt_no=attempt,
                status=status,
                origin_kind=origin,
                opened_at=when,
                closed_at=now if status == ProcessStatus.closed else None,
                voided_at=now if status == ProcessStatus.voided else None,
            )

        db.add_all(
            [
                row("only_copy", copy, PipelineStage.new),
                row(
                    "only_copy",
                    copy,
                    PipelineStage.screening,
                    at=when + timedelta(hours=1),
                ),
                row("both", copy, PipelineStage.screening),
                row("both", nexus, PipelineStage.new, traffit=False),
                row("returning", copy, PipelineStage.screening),
                process("only_copy", copy, ProcessStatus.open),
                process("both", copy, ProcessStatus.open),
                process("both", nexus, ProcessStatus.open),
                process("returning", copy, ProcessStatus.closed, 1),
                process("returning", copy, ProcessStatus.open, 2),
                process("returning", nexus, ProcessStatus.voided, 1),
                Note(
                    content="Ustalenia z rozmowy.",
                    candidate_id=people["only_copy"].id,
                    job_id=copy.id,
                ),
                Note(
                    content="Notatka osoby z obu rekrutacji.",
                    candidate_id=people["both"].id,
                    job_id=copy.id,
                ),
                Note(
                    content="Odpowiedzi z formularza zgłoszenia.",
                    candidate_id=people["applied"].id,
                    job_id=copy.id,
                ),
                CalendarEvent(
                    title="Rozmowa u klienta",
                    event_type=EventType.client_interview,
                    start_time=now + timedelta(days=1),
                    end_time=now + timedelta(days=1, hours=1),
                    candidate_id=people["only_copy"].id,
                    job_id=copy.id,
                    client_id=client.id,
                ),
                RecommendationCard(candidate_id=people["only_copy"].id, job_id=copy.id),
                JobProposal(
                    job_id=copy.id,
                    candidate_id=people["applied"].id,
                    source="job_board",
                ),
                JobProposal(
                    job_id=copy.id,
                    candidate_id=people["applied_twice"].id,
                    source="job_board",
                ),
                JobProposal(
                    job_id=nexus.id,
                    candidate_id=people["applied_twice"].id,
                    source="job_board",
                ),
                JobProposal(
                    job_id=nexus.id,
                    candidate_id=people["only_copy"].id,
                    source="full_base",
                ),
                JobWorkAssignment(
                    job_id=copy.id,
                    user_id=owner,
                    role="recruiter",
                    source="owner",
                    state="active",
                    assigned_at=when,
                ),
                JobWorkAssignment(
                    job_id=nexus.id,
                    user_id=owner,
                    role="recruiter",
                    source="owner",
                    state="active",
                    assigned_at=when,
                ),
                JobWorkAssignment(
                    job_id=copy.id,
                    user_id=helper,
                    role="recruiter",
                    source="manual",
                    state="active",
                    assigned_at=when,
                ),
                # Paragon przeniesienia: stąd narzędzie zna parę.
                Activity(
                    entity_type="job",
                    entity_id=copy.id,
                    action="traffit_transfer",
                    details={"twin_job_id": nexus.id, "twin_exact": exact},
                ),
            ]
        )
        if kpi_gap:
            db.add_all(
                [
                    row(
                        "held",
                        copy,
                        PipelineStage.cv_sent,
                        at=when + timedelta(hours=2),
                    ),
                    process("held", copy, ProcessStatus.open),
                    process(
                        "held",
                        nexus,
                        ProcessStatus.voided,
                        origin=PriorityOriginKind.assigned,
                    ),
                ]
            )
        await db.commit()
        return {
            "copy": copy.id,
            "nexus": nexus.id,
            "owner": owner,
            "helper": helper,
            "people": {key: person.id for key, person in people.items()},
        }


async def _all(sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with AsyncSessionLocal() as db:
        return [tuple(row) for row in (await db.execute(text(sql), params)).all()]


async def _rows(job_id: int, candidate_id: int) -> int:
    ((count,),) = await _all(
        "SELECT count(*) FROM candidate_stages WHERE job_id = :j AND candidate_id = :c",
        j=job_id,
        c=candidate_id,
    )
    return int(count)


async def _processes(job_id: int, candidate_id: int) -> dict[int, str]:
    return {
        int(attempt): status
        for attempt, status in await _all(
            "SELECT attempt_no, CAST(status AS text) FROM recruitment_processes "
            "WHERE job_id = :j AND candidate_id = :c",
            j=job_id,
            c=candidate_id,
        )
    }


async def _proposals(candidate_id: int) -> dict[int, str]:
    return {
        int(job_id): status
        for job_id, status in await _all(
            "SELECT job_id, status FROM job_proposals WHERE candidate_id = :c",
            c=candidate_id,
        )
    }


async def _job(job_id: int) -> dict[str, Any]:
    (
        (status, is_open, managed, work_state, closed_at, reason, notes, recruiter),
    ) = await _all(
        "SELECT CAST(status AS text), is_open, managed_in_nexus, work_state, "
        "closed_at, CAST(close_reason AS text), close_notes, recruiter_id "
        "FROM jobs WHERE id = :i",
        i=job_id,
    )
    return {
        "status": status,
        "is_open": is_open,
        "managed": managed,
        "work_state": work_state,
        "closed_at": closed_at,
        "close_reason": reason,
        "close_notes": notes,
        "recruiter_id": recruiter,
    }


async def _assignments(job_id: int) -> dict[int, tuple[str, Optional[str]]]:
    return {
        int(user_id): (state, reason)
        for user_id, state, reason in await _all(
            "SELECT user_id, state, release_reason FROM job_work_assignments "
            "WHERE job_id = :j",
            j=job_id,
        )
    }


async def _merge_activities(job_id: int) -> list[dict[str, Any]]:
    return [
        json.loads(details) if isinstance(details, str) else details
        for (details,) in await _all(
            "SELECT details FROM activities WHERE entity_type = 'job' "
            "AND entity_id = :i AND action = :a ORDER BY id",
            i=job_id,
            a=merge.MERGE_ACTION,
        )
    ]


async def _run(
    seed: dict[str, Any],
    *,
    dry_run: bool,
    actor: Optional[int],
    reviewed: Optional[frozenset[int]] = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await merge.process(
            db,
            merge.Scope(job_ids=(seed["copy"],)),
            dry_run=dry_run,
            actor_user_id=actor,
            actor_label="test",
            reviewed=reviewed,
        )


@pytest.fixture
def post_commit_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Efekty po commicie (Qdrant, cache raportów) nie należą do tego testu."""
    calls: list[Any] = []

    async def _record(effects: Any) -> Any:
        calls.append(effects)
        return effects

    monkeypatch.setattr(job_lifecycle, "run_post_commit", _record)
    return calls


@pytest.mark.asyncio
async def test_dry_run_reports_the_plan_and_changes_nothing(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    people, copy, nexus = seed["people"], seed["copy"], seed["nexus"]

    report = await _run(seed, dry_run=True, actor=None)

    (pair,) = report["pairs"]
    assert pair["status"] == "ready", pair
    assert (pair["job_id"], pair["target_job_id"]) == (copy, nexus)
    assert (pair["people"], pair["moved"], pair["in_both"]) == (3, 2, 1)
    assert pair["in_both_ids"] == [people["both"]]
    assert pair["columns"] == {"screening": 2}
    assert pair["kpi_hold_ids"] == []
    # Notatka osoby z kartą i notatka osoby, której propozycja przechodzi.
    assert (pair["notes"], pair["recommendation_cards"], pair["rate_from"]) == (2, 1, 1)
    assert (pair["proposals"], pair["calendar_events"]) == (1, 1)
    assert pair["copy_already_closed"] is False
    assert report["totals"]["by_status"] == {"ready": 1}
    # Zero zmian.
    assert await _rows(copy, people["only_copy"]) == 2
    assert await _rows(nexus, people["only_copy"]) == 0
    assert (await _job(copy))["status"] == "published"
    assert await _merge_activities(copy) == []
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_merge_moves_pairs_with_history_and_closes_the_copy(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()
    people, copy, nexus = seed["people"], seed["copy"], seed["nexus"]

    ((before_run,),) = await _all("SELECT clock_timestamp()")

    report = await _run(seed, dry_run=False, actor=actor)

    (pair,) = report["pairs"]
    assert pair["status"] == "merged", pair
    assert pair["moved_candidate_ids"] == sorted(
        [people["only_copy"], people["returning"]]
    )
    assert pair["in_both_ids"] == [people["both"]]
    assert pair["copy_closed"] is True
    assert (pair["notes"], pair["recommendation_cards"], pair["rate_from"]) == (2, 1, 1)
    assert (pair["proposals"], pair["proposals_added"]) == (1, 1)
    assert pair["calendar_events"] == 1

    # Cała historia pary przechodzi: nic nie zostaje w kopii, nic się nie dubluje.
    assert await _rows(copy, people["only_copy"]) == 0
    assert await _rows(nexus, people["only_copy"]) == 2
    assert await _processes(copy, people["only_copy"]) == {}
    assert await _processes(nexus, people["only_copy"]) == {1: "open"}
    # Próby z kopii stają ZA unieważnioną próbą rekrutacji NEXUSA.
    assert await _rows(nexus, people["returning"]) == 1
    assert await _processes(nexus, people["returning"]) == {
        1: "voided",
        2: "closed",
        3: "open",
    }
    # Kto ma kartę w obu, zostaje przy karcie z NEXUSA; historia z Traffita
    # przy zamkniętej kopii.
    assert await _rows(copy, people["both"]) == 1
    assert await _rows(nexus, people["both"]) == 1
    assert await _processes(copy, people["both"]) == {1: "open"}

    notes = dict(
        await _all(
            "SELECT candidate_id, job_id FROM notes WHERE candidate_id IN (:a, :b, :c)",
            a=people["only_copy"],
            b=people["both"],
            c=people["applied"],
        )
    )
    # Notatka idzie za kartą i za przeniesioną propozycją; osoba z obu zostaje.
    assert notes == {
        people["only_copy"]: nexus,
        people["both"]: copy,
        people["applied"]: nexus,
    }
    # Termin rozmowy u klienta: po nim bramka debriefu i checklista ruchu
    # znajdują parę.
    assert await _all(
        "SELECT job_id FROM calendar_events WHERE candidate_id = :c",
        c=people["only_copy"],
    ) == [(nexus,)]
    # Przepięcie nie jest ruchem: `updated_at` historii zostaje.
    assert await _all(
        "SELECT count(*) FROM candidate_stages WHERE job_id = :j AND updated_at >= :t",
        j=nexus,
        t=before_run,
    ) == [(0,)]
    assert await _all(
        "SELECT count(*) FROM recruitment_processes "
        "WHERE job_id = :j AND status <> 'voided' AND updated_at >= :t",
        j=nexus,
        t=before_run,
    ) == [(0,)]
    assert await _all(
        "SELECT job_id FROM recommendation_cards WHERE candidate_id = :c",
        c=people["only_copy"],
    ) == [(nexus,)]
    assert await _all(
        "SELECT rate_from_job_id FROM candidates WHERE id = :c", c=people["only_copy"]
    ) == [(nexus,)]

    # Zgłoszenie z ogłoszenia nie znika razem z kopią.
    assert await _proposals(people["applied"]) == {nexus: "proposed"}
    assert await _proposals(people["applied_twice"]) == {
        copy: "expired",
        nexus: "proposed",
    }
    # Osoba, która przeszła z kartą, nie jest już propozycją.
    assert await _proposals(people["only_copy"]) == {nexus: "added"}

    # Kopia zamknięta jak archiwum: bez daty i powodu, dalej „w NEXUSIE”.
    closed = await _job(copy)
    assert (closed["status"], closed["is_open"], closed["work_state"]) == (
        "closed",
        False,
        "finished",
    )
    assert closed["managed"] is True
    assert (closed["closed_at"], closed["close_reason"]) == (None, None)
    assert f"#{nexus}" in closed["close_notes"]
    # Rekrutacja NEXUSA i jej zespół bez zmian.
    kept = await _job(nexus)
    assert (kept["status"], kept["is_open"], kept["work_state"]) == (
        "published",
        True,
        "searching",
    )
    assert kept["recruiter_id"] == seed["owner"]
    assert await _assignments(nexus) == {seed["owner"]: ("active", None)}
    # Ten sam request ma dalej prowadzący — bez „Zwolnione: …” w skrócie.
    assert await _assignments(copy) == {
        seed["owner"]: ("released", "reassigned"),
        seed["helper"]: ("released", "finished"),
    }

    (on_copy,) = await _merge_activities(copy)
    (on_nexus,) = await _merge_activities(nexus)
    assert (on_copy["merged_into"], on_copy["moved"]) == (nexus, 2)
    assert (on_nexus["merged_from"], on_nexus["moved"]) == (copy, 2)
    # Pełny paragon przy kopii — w tej samej transakcji co przepięcie.
    assert on_copy["moved_candidate_ids"] == pair["moved_candidate_ids"]
    assert "moved_candidate_ids" not in on_nexus
    assert len(post_commit_calls) == 1

    # Scalona kopia wygląda jak „przełączona, ale zamknięta” — przeniesienie
    # wskazane wprost nie może jej otworzyć ponownie.
    async with AsyncSessionLocal() as db:
        assert await transfer.load_wave(db, transfer.Scope(job_ids=(copy,))) == []

    # Drugi bieg niczego nie rusza.
    again = await _run(seed, dry_run=False, actor=actor)
    (pair,) = again["pairs"]
    assert (pair["status"], pair["skip_reason"]) == ("skipped", merge.SKIP_MERGED)
    assert await _rows(nexus, people["only_copy"]) == 2
    assert len(post_commit_calls) == 1


@pytest.mark.asyncio
async def test_person_whose_kpi_credit_would_be_lost_stays_in_the_copy(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed(kpi_gap=True)
    actor = await _admin_id()
    people, copy, nexus = seed["people"], seed["copy"], seed["nexus"]

    rehearsal = await _run(seed, dry_run=True, actor=None)
    (pair,) = rehearsal["pairs"]
    assert pair["kpi_hold_ids"] == [people["held"]]
    assert (pair["people"], pair["moved"], pair["kpi_hold"]) == (4, 2, 1)

    report = await _run(seed, dry_run=False, actor=actor)

    (pair,) = report["pairs"]
    assert pair["status"] == "merged", pair
    assert pair["kpi_hold_ids"] == [people["held"]]
    assert people["held"] not in pair["moved_candidate_ids"]
    assert await _rows(copy, people["held"]) == 1
    assert await _rows(nexus, people["held"]) == 0
    assert await _processes(nexus, people["held"]) == {1: "voided"}
    # Reszta pary przechodzi normalnie.
    assert await _rows(nexus, people["only_copy"]) == 2


@pytest.mark.asyncio
async def test_execution_merges_only_pairs_shown_by_the_dry_run(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()
    actor = await _admin_id()

    report = await _run(seed, dry_run=False, actor=actor, reviewed=frozenset())

    (pair,) = report["pairs"]
    assert (pair["status"], pair["skip_reason"]) == (
        "skipped",
        merge.SKIP_NOT_REVIEWED,
    )
    assert await _rows(seed["copy"], seed["people"]["only_copy"]) == 2
    assert (await _job(seed["copy"]))["status"] == "published"
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_closed_nexus_recruitment_keeps_the_pair_apart(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed(target_status=JobStatus.closed)
    actor = await _admin_id()

    report = await _run(seed, dry_run=False, actor=actor)

    (pair,) = report["pairs"]
    assert (pair["status"], pair["skip_reason"]) == (
        "skipped",
        merge.SKIP_TARGET_CLOSED,
    )
    assert await _rows(seed["copy"], seed["people"]["only_copy"]) == 2
    assert (await _job(seed["copy"]))["status"] == "published"
    assert await _merge_activities(seed["copy"]) == []
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_similar_title_from_the_receipt_is_not_a_pair(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed(exact=False)
    actor = await _admin_id()

    report = await _run(seed, dry_run=False, actor=actor)

    assert report["pairs"] == []
    assert await _rows(seed["copy"], seed["people"]["only_copy"]) == 2
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_merge_without_an_actor_fails_before_any_write(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed()

    report = await _run(seed, dry_run=False, actor=None)

    (pair,) = report["pairs"]
    assert (pair["status"], pair["error"]) == ("failed", "brak wykonawcy")
    assert await _rows(seed["copy"], seed["people"]["only_copy"]) == 2
    assert (await _job(seed["copy"]))["status"] == "published"
    assert post_commit_calls == []


@pytest.mark.asyncio
async def test_copy_closed_by_a_person_gives_people_away_and_keeps_its_reason(
    post_commit_calls: list[Any],
) -> None:
    seed = await _seed(copy_closed_by_person=True)
    actor = await _admin_id()
    people, copy, nexus = seed["people"], seed["copy"], seed["nexus"]

    report = await _run(seed, dry_run=False, actor=actor)

    (pair,) = report["pairs"]
    assert pair["status"] == "merged", pair
    assert pair["copy_closed"] is False
    assert await _rows(nexus, people["only_copy"]) == 2
    closed = await _job(copy)
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None
    assert closed["close_reason"] == "budget"
    assert closed["close_notes"] == "Klient wstrzymał budżet."


@pytest.mark.asyncio
async def test_execution_needs_a_fresh_dry_run_of_the_same_scope() -> None:
    started = datetime.now(UTC)
    scope, other = merge.Scope(job_ids=(987_001,)), merge.Scope(job_ids=(987_002,))
    report = {
        "dry_run": True,
        "scope": scope.as_dict(),
        "scope_key": scope.key(),
        "actor": "test",
        "totals": {},
        "pairs": [],
    }
    async with AsyncSessionLocal() as db:
        await merge.finish_run(db, report, started=started)
        assert await merge.fresh_dry_run_exists(db, scope)
        assert not await merge.fresh_dry_run_exists(db, other)
        await merge._write_setting(  # noqa: SLF001
            db,
            merge.DRY_RUN_KEY,
            {**report, "finished_at": (started - timedelta(hours=25)).isoformat()},
        )
        await db.commit()
        assert not await merge.fresh_dry_run_exists(db, scope)
