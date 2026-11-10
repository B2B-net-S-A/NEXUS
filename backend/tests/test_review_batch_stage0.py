"""Etap 0 porcji dnia przed pilotem (audyt 08.11.2026) — prawdziwy Postgres.

P5/P6 decyzje, P7 kolejność jak na Tablicy, S-C4 premia i próg, P8 ślad blokady
i widok zespołu, P11 nieobecni, P12 pierwszy rekruter, W8 kolejność dnia, P4
strumienie. Baza testowa jest wspólna: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.hr_leave import LeaveRequest
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb
from app.services import review_batch_streams as streams
from app.services import review_batch_team as team


# Poniedziałek 09.11.2026, 9:00 w Warszawie: silnik pracuje tylko w dni robocze.
_WORKDAY = datetime(2026, 11, 9, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw")).astimezone(
    timezone.utc
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _user(role: UserRole = UserRole.recruiter) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rb0-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Batch"),
            name=f"RB0 {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(
    people: int,
    *,
    recruiters: list[int],
    priority: JobPriority = JobPriority.medium,
) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RB0 client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RB0 job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiters[0] if recruiters else None,
            priority=priority,
        )
        candidates = [
            Candidate(name="P0", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
        await db.flush()
        for uid in recruiters[1:]:
            db.add(JobCollaborator(job_id=job.id, user_id=uid, source="manual"))
        await db.commit()
        return {"job_id": job.id, "ids": [c.id for c in candidates]}


async def _pool(job_id: int, scores: dict[int, float]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobAutofillPool(
                    job_id=job_id,
                    candidate_id=cid,
                    score=Decimal(str(score)),
                    run_id="run-rb0",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _fill(job_id: int, **kw) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_now(), batch=True, **kw)
        await db.commit()
        return added


async def _move(
    job_id: int,
    candidate_id: int,
    stage: PipelineStage,
    by: int,
    *,
    at: datetime | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id, job_id=job_id, stage=stage, moved_by=by
        )
        if at is not None:
            row.moved_at = at
        db.add(row)
        await db.commit()
        return row.id


async def _status(user_id: int) -> rb.BatchStatus:
    async with AsyncSessionLocal() as db:
        return await rb.status_for(db, await db.get(User, user_id), now=_now())


@pytest.fixture
def batch_on(monkeypatch):
    monkeypatch.setattr(rb, "BATCH_SIZE", 4)
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    return monkeypatch


# ── P6: decyzja to wyjście z „Nowych” ───────────────────────────────────────


async def test_move_after_screening_is_not_a_decision(batch_on):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    long_ago = _now() - timedelta(days=20)
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == cid,
                )
            )
        ).one()
        process.opened_at = long_ago - timedelta(days=1)
        stage = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == world["job_id"],
                    CandidateStage.candidate_id == cid,
                )
            )
        ).one()
        stage.moved_at = long_ago - timedelta(days=1)
        await db.commit()
    await _move(world["job_id"], cid, PipelineStage.screening, a, at=long_ago)

    await _move(world["job_id"], cid, PipelineStage.cv_sent, a)

    async with AsyncSessionLocal() as db:
        assert await rb.decided_today(db, a, now=_now()) == 0


async def test_card_moved_back_to_new_is_not_a_decision(batch_on):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    await _move(world["job_id"], cid, PipelineStage.rejected, a)
    await _move(world["job_id"], cid, PipelineStage.new, a)
    async with AsyncSessionLocal() as db:
        counts = await rb.day_counts(db, a, now=_now())
    assert counts.done == 0


# ── „Do screeningu” zalicza od razu, termin domknięcia (decyzja z 09.11) ────


async def test_rejection_and_screening_both_count_at_once(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    first, second = await _fill(world["job_id"])

    await _move(world["job_id"], first, PipelineStage.rejected, a)
    await _move(world["job_id"], second, PipelineStage.screening, a)

    status = await _status(a)
    assert status.done_today == 2 and status.open_screenings == 1
    assert status.required == 2 and status.met is True


async def test_screening_of_whole_batch_unlocks_until_the_deadline(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    added = await _fill(world["job_id"])
    for cid in added:
        await _move(world["job_id"], cid, PipelineStage.screening, a)
    status = await _status(a)
    assert status.pending == 0 and status.required == 2 and status.met is True
    assert status.overdue_screenings == 0


async def _age_batch_screening(job_id: int, cid: int, user: int) -> None:
    """S z własnej porcji sprzed okna domknięcia."""
    old = rb.close_window_start() - timedelta(hours=2)
    await _rewrite_process(job_id, cid, opened_at=old - timedelta(hours=1))
    async with AsyncSessionLocal() as db:
        stage = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == job_id,
                    CandidateStage.candidate_id == cid,
                )
            )
        ).one()
        stage.moved_at = old - timedelta(hours=1)
        await db.commit()
    await _move(job_id, cid, PipelineStage.screening, user, at=old)


async def test_overdue_screening_blocks_again_until_closed(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    late, fresh = await _fill(world["job_id"])
    await _age_batch_screening(world["job_id"], late, a)
    await _move(world["job_id"], fresh, PipelineStage.rejected, a)

    status = await _status(a)
    assert status.overdue_screenings == 1 and status.met is False
    assert status.remaining == 0
    row = next(r for r in status.open_today_screenings if r.candidate_id == late)
    assert row.overdue is True

    await _move(world["job_id"], late, PipelineStage.verified, a)
    status = await _status(a)
    assert status.overdue_screenings == 0 and status.met is True


async def _rewrite_process(job_id: int, cid: int, **changes) -> None:
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == job_id,
                    RecruitmentProcess.candidate_id == cid,
                )
            )
        ).one()
        for name, value in changes.items():
            setattr(process, name, value)
        await db.commit()


async def test_old_card_moved_on_the_board_does_not_block_again(batch_on):
    """Starsza karta nie jest porcją: jej S nie cofa zrobionego minimum."""
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    first, old = await _fill(world["job_id"])
    await _move(world["job_id"], first, PipelineStage.rejected, a)
    await _rewrite_process(
        world["job_id"], old, opened_at=_now() - timedelta(days=rb.MAX_AGE_DAYS + 3)
    )
    assert (await _status(a)).met is True

    await _move(world["job_id"], old, PipelineStage.screening, a)

    status = await _status(a)
    assert status.done_today == 2 and status.met is True
    assert status.open_today_screenings == ()


async def test_screening_of_someone_elses_card_does_not_hold_my_minimum(batch_on):
    a = await _user()
    b = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    await _rewrite_process(
        world["job_id"], cid, entry_meta={"score": 90, rb.OWNER_KEY: b}
    )

    await _move(world["job_id"], cid, PipelineStage.screening, a)

    status = await _status(a)
    assert status.required == 1 and status.met is True
    assert status.open_today_screenings == ()


async def test_status_lists_todays_open_screenings_from_own_batch(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    added = await _fill(world["job_id"])
    for cid in added:
        await _move(world["job_id"], cid, PipelineStage.screening, a)

    status = await _status(a)

    assert status.pending == 0 and status.met is True
    assert {row.candidate_id for row in status.open_today_screenings} == set(added)
    row = status.as_dict()["open_today_screenings"][0]
    assert row["job_id"] == world["job_id"] and row["job_title"] and row["name"]


async def test_screening_closed_by_saved_form_counts(batch_on):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    stage_id = await _move(world["job_id"], cid, PipelineStage.screening, a)
    before = await _status(a)
    assert before.done_today == 1 and before.open_screenings == 1
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="candidate_stage",
                entity_id=stage_id,
                action="screening_answered",
                user_id=a,
                details={"candidate_id": cid, "job_id": world["job_id"]},
            )
        )
        await db.commit()
    status = await _status(a)
    assert status.done_today == 1 and status.open_screenings == 0 and status.met


async def test_screening_closed_by_next_move_counts(batch_on):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    await _move(world["job_id"], cid, PipelineStage.screening, a)
    await _move(world["job_id"], cid, PipelineStage.verified, a)
    assert (await _status(a)).done_today == 1


async def test_old_screening_closed_today_is_not_todays_decision(batch_on):
    """S sprzed 2 dni roboczych liczyło się w dniu ruchu, nie w dniu wyniku."""
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    old = rb.close_window_start() - timedelta(hours=2)
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == cid,
                )
            )
        ).one()
        process.opened_at = old - timedelta(hours=1)
        stage = (
            await db.scalars(
                select(CandidateStage).where(
                    CandidateStage.job_id == world["job_id"],
                    CandidateStage.candidate_id == cid,
                )
            )
        ).one()
        stage.moved_at = old - timedelta(hours=1)
        await db.commit()
    await _move(world["job_id"], cid, PipelineStage.screening, a, at=old)
    await _move(world["job_id"], cid, PipelineStage.verified, a)
    assert (await _status(a)).done_today == 0


async def test_card_moved_to_screening_today_cannot_be_removed(batch_on):
    """S, a potem usunięcie z rekrutacji zerowałoby wymagane minimum."""
    from fastapi import HTTPException

    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    screened, rejected = await _fill(world["job_id"])
    await _move(world["job_id"], screened, PipelineStage.screening, a)
    await _move(world["job_id"], rejected, PipelineStage.rejected, a)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, a)
        with pytest.raises(HTTPException) as exc:
            await rb.assert_removal_allowed(
                db, user, candidate_id=screened, job_id=world["job_id"]
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == rb.REMOVAL_CODE
        # Odrzucona osoba nie trzyma minimum, można ją zdjąć.
        await rb.assert_removal_allowed(
            db, user, candidate_id=rejected, job_id=world["job_id"]
        )


async def _assert_removable_after_screening(
    job_id: int, cid: int, user_id: int
) -> None:
    await _move(job_id, cid, PipelineStage.screening, user_id)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        await rb.assert_removal_allowed(db, user, candidate_id=cid, job_id=job_id)


async def test_old_card_moved_to_screening_today_can_be_removed(batch_on):
    """Starsza karta nie jest porcją, więc jej S nie trzyma minimum."""
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [old] = await _fill(world["job_id"])
    await _rewrite_process(
        world["job_id"], old, opened_at=_now() - timedelta(days=rb.MAX_AGE_DAYS + 3)
    )

    await _assert_removable_after_screening(world["job_id"], old, a)


async def test_someone_elses_card_moved_to_screening_today_can_be_removed(batch_on):
    a = await _user()
    b = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    await _rewrite_process(
        world["job_id"], cid, entry_meta={"score": 90, rb.OWNER_KEY: b}
    )

    await _assert_removable_after_screening(world["job_id"], cid, a)


async def test_card_in_cpro_column_with_new_enum_is_not_in_batch(batch_on):
    """Etap „Wysłać do Cpro” ma enum ``new``, ale na Tablicy to inna kolumna:
    rekruter nie może takiej karty odrzucić z porcji (422 ruchu) i stałaby
    na początku kolejki."""
    from app.models.pipeline_template import (
        PipelineStageDef,
        PipelineTemplate,
        StageCategoryEnum,
    )

    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    stuck, fine = await _fill(world["job_id"])
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        template = PipelineTemplate(name=f"RB0 {tag}")
        db.add(template)
        await db.flush()
        stage_def = PipelineStageDef(
            template_id=template.id,
            name="Wysłać do Cpro",
            order=5,
            category=StageCategoryEnum.internal,
        )
        db.add(stage_def)
        await db.flush()
        row = CandidateStage(
            candidate_id=stuck,
            job_id=world["job_id"],
            stage=PipelineStage.new,
            stage_def_id=stage_def.id,
            moved_by=a,
        )
        db.add(row)
        await db.commit()
    async with AsyncSessionLocal() as db:
        left = {
            c.candidate_id
            for c in await rb.pending_cards(db, job_ids=[world["job_id"]])
        }
    assert left == {fine}


# ── S-C4: próg z ustawień ───────────────────────────────────────────────────


async def test_min_score_from_settings_limits_the_batch(batch_on):
    a = await _user()
    world = await _world(3, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {ids[0]: 90, ids[1]: 72, ids[2]: 66})
    async with AsyncSessionLocal() as db:
        await rb.write_settings(db, rb.BatchSettings(min_score=70.0), user_id=None)
        await db.commit()
    try:
        added = await _fill(world["job_id"])
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == rb.SETTING_KEY))
            await db.commit()
    assert set(added) == {ids[0], ids[1]}


async def test_pick_bonuses_read_effective_rate_and_status(batch_on):
    from app.models.candidate import AvailabilityStatus
    from app.services import review_batch_order as order

    a = await _user()
    world = await _world(2, recruiters=[a])
    active, plain = world["ids"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.rate_budget_hourly = Decimal("170")
        person = await db.get(Candidate, active)
        person.availability_status = AvailabilityStatus.actively_looking
        person.expected_rate_hourly = Decimal("150")
        person.expected_rate_currency = "PLN"
        await db.commit()
    picks = [autofill.Pick(cid, 80.0, "run", (), ()) for cid in (active, plain)]
    async with AsyncSessionLocal() as db:
        bonus = await order.pick_bonuses(db, world["job_id"], picks)
    assert bonus == {active: 8, plain: 0}


# ── P8: ślad blokady i widok zespołu ────────────────────────────────────────


async def test_block_is_logged_once_per_ten_minutes(batch_on):
    a = await _user()
    status = rb.BatchStatus(
        enabled=True,
        applies=True,
        minimum=10,
        done_today=0,
        pending=5,
        required=5,
        met=False,
    )
    await rb._record_block(a, status, now=_now())
    await rb._record_block(a, status, now=_now())
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.action == rb.BLOCK_ACTION, Activity.user_id == a
            )
        )
    assert count == 1


async def test_team_view_row_counts_decisions_blocks_and_ratio(batch_on):
    a = await _user()
    world = await _world(3, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    first, second, _third = await _fill(world["job_id"])
    await _move(world["job_id"], first, PipelineStage.rejected, a)
    await _move(world["job_id"], second, PipelineStage.screening, a)
    status = rb.BatchStatus(
        enabled=True,
        applies=True,
        minimum=10,
        done_today=1,
        pending=1,
        required=3,
        met=False,
    )
    await rb._record_block(a, status, now=_now())

    async with AsyncSessionLocal() as db:
        view = await team.team_view(db, now=_now())

    row = next(r for r in view["rows"] if r["user_id"] == a)
    assert row["done_today"] == 2  # odrzucenie i „Do screeningu”
    assert row["pending"] == 1
    assert row["required"] == 3  # 2 decyzje + 1 w porcji
    assert row["screened"] == 1 and row["rejected"] == 1
    assert row["open_screenings"] == 1
    assert row["blocked_today"] == 1
    assert row["minimum_at"] is None


async def test_team_route_refuses_recruiter(app_client, batch_on):
    from app.core.security import create_access_token

    a = await _user()
    token = create_access_token(a, "recruiter")
    headers = {"Authorization": f"Bearer {token}"}
    response = await app_client.get("/api/review-batch/team", headers=headers)
    assert response.status_code == 403


# ── P11: nieobecni ──────────────────────────────────────────────────────────


async def test_absent_recruiter_loses_cards_and_has_no_block(batch_on):
    a, b = await _user(), await _user()
    world = await _world(4, recruiters=[a, b])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    await _fill(world["job_id"])
    today: date = business_today()
    async with AsyncSessionLocal() as db:
        db.add(
            LeaveRequest(
                user_id=a,
                leave_type="vacation",
                status="approved",
                start_date=today,
                end_date=today,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await rb.recruiter_ids_for_jobs(db, [world["job_id"]]) == {
            world["job_id"]: [b]
        }
        await rb.assign_owners(db, world["job_id"], now=_now())
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"]
                )
            )
        ).all()
    assert {p.entry_meta[rb.OWNER_KEY] for p in rows} == {b}

    status = await _status(a)
    assert status.applies is False and status.met is True


# ── P12 i W8: dzienny przebieg ──────────────────────────────────────────────


@pytest.fixture
async def tick_world(batch_on):
    batch_on.setattr(
        autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True, raising=False
    )

    async def _no_new(_db):
        return []

    batch_on.setattr(autofill, "_jobs_without_batch", _no_new)
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, autofill.BATCH_DAY_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return batch_on


async def test_first_recruiter_gets_batch_the_same_day(tick_world):
    from app.services import autofill_withdraw

    world = await _world(3, recruiters=[])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})

    async def _only(_db):
        return [world["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    now = _WORKDAY
    first = await autofill.tick(now=now)
    assert first["filled"] == {}

    # Stara karta od systemu sprzed przypisania rekrutera.
    stale_id = world["ids"][0]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        client_id = job.client_id
        await db.execute(
            delete(JobAutofillPool).where(
                JobAutofillPool.job_id == world["job_id"],
                JobAutofillPool.candidate_id == stale_id,
            )
        )
        from app.api.proposals_bulk import add_candidates_to_job

        await add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[stale_id],
            actor_user_id=None,
            entry_source="system",
            claim=False,
            entry_meta={"kind": "autofill", "score": 90},
            mark_proposals=False,
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == stale_id,
                )
            )
        ).one()
        process.opened_at = now - timedelta(days=12)
        await db.commit()
    assert client_id is not None

    a = await _user()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.recruiter_id = a
        await db.commit()

    again = await autofill.tick(now=now + timedelta(hours=1))

    assert again["filled"] == {world["job_id"]: 2}
    async with AsyncSessionLocal() as db:
        left = {
            c.candidate_id
            for c in await rb.pending_cards(db, job_ids=[world["job_id"]])
        }
        planned = await autofill_withdraw.plan_batch_reset(
            db, now=now, job_ids=[world["job_id"]]
        )
    assert stale_id not in left and planned == []


# ── Porcja na osobę (decyzje Artura 10.11.2026) ─────────────────────────────


def _portion(monkeypatch, size: int) -> None:
    """Poziom każdej nowej osoby = ``size`` (minimum z ustawień, bez zapisanych)."""

    async def _settings(_db):
        return rb.BatchSettings(minimum=size)

    monkeypatch.setattr(rb, "read_settings", _settings)
    monkeypatch.setattr(autofill._state, "last_plan", None)


async def _p0(job_id: int, now: datetime) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.p0_until = now + timedelta(days=1)
        job.p0_reason = "test porcji"
        job.p0_set_at = now
        await db.commit()


async def _owned(job_id: int) -> dict[int, int]:
    async with AsyncSessionLocal() as db:
        out: dict[int, int] = {}
        for card in await rb.pending_cards(db, job_ids=[job_id]):
            if card.owner_id is not None:
                out[card.owner_id] = out.get(card.owner_id, 0) + 1
        return out


async def test_portion_takes_p0_first_and_only_assigned_jobs(tick_world):
    _portion(tick_world, 4)
    r, other = await _user(), await _user()
    p0 = await _world(12, recruiters=[r], priority=JobPriority.medium)
    urgent = await _world(12, recruiters=[r], priority=JobPriority.urgent)
    foreign = await _world(12, recruiters=[other], priority=JobPriority.urgent)
    for world in (p0, urgent, foreign):
        await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    await _p0(p0["job_id"], _WORKDAY)

    async def _only(_db):
        return [urgent["job_id"], p0["job_id"], foreign["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    result = await autofill.tick(now=_WORKDAY)

    # Cała porcja r z P0, nic z P1; cudza rekrutacja daje karty tylko swojej osobie.
    assert result["filled"] == {p0["job_id"]: 4, foreign["job_id"]: 4}
    assert await _owned(p0["job_id"]) == {r: 4}
    assert await _owned(foreign["job_id"]) == {other: 4}


async def test_shared_p0_pool_splits_then_lower_priority(tick_world):
    _portion(tick_world, 4)
    a, b = await _user(), await _user()
    p0 = await _world(5, recruiters=[a, b])
    urgent = await _world(12, recruiters=[a, b], priority=JobPriority.urgent)
    for world in (p0, urgent):
        await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    await _p0(p0["job_id"], _WORKDAY)

    async def _only(_db):
        return [urgent["job_id"], p0["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    result = await autofill.tick(now=_WORKDAY)

    # 5 osób w P0 na dwie porcje po 4: na zmianę 3 i 2, reszta z P1 Pilne.
    assert result["filled"] == {p0["job_id"]: 5, urgent["job_id"]: 3}
    assert sorted((await _owned(p0["job_id"])).values()) == [2, 3]
    assert sum((await _owned(urgent["job_id"])).values()) == 3


async def test_p0_set_during_the_day_gets_cards_without_taking_any(tick_world):
    _portion(tick_world, 4)
    r = await _user()
    urgent = await _world(8, recruiters=[r], priority=JobPriority.urgent)
    later = await _world(8, recruiters=[r])
    for world in (urgent, later):
        await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})

    async def _only(_db):
        return [urgent["job_id"], later["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    morning = await autofill.tick(now=_WORKDAY)
    assert morning["filled"] == {urgent["job_id"]: 4}

    await _p0(later["job_id"], _WORKDAY)
    noon = await autofill.tick(
        now=_WORKDAY + autofill.REPLAN_EVERY + timedelta(minutes=1)
    )

    # P0 z południa dostaje porcję, a karty z rana zostają u osoby.
    assert noon["filled"] == {later["job_id"]: 4}
    assert await _owned(urgent["job_id"]) == {r: 4}
    async with AsyncSessionLocal() as db:
        queue = await rb.review_queue(db, await db.get(User, r), now=_WORKDAY)
    assert {c.job_id for c in queue[:4]} == {later["job_id"]}


async def test_unassigned_person_loses_cards_on_the_next_plan(tick_world):
    _portion(tick_world, 4)
    a, b = await _user(), await _user()
    world = await _world(12, recruiters=[a, b])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})

    async def _only(_db):
        return [world["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    await autofill.tick(now=_WORKDAY)
    assert await _owned(world["job_id"]) == {a: 4, b: 4}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobCollaborator).where(
                JobCollaborator.job_id == world["job_id"], JobCollaborator.user_id == b
            )
        )
        await db.commit()
    await autofill.tick(now=_WORKDAY + autofill.REPLAN_EVERY + timedelta(minutes=1))

    # „Dla: b” znika; a ma już swoją porcję, więc karty b czekają bez właściciela.
    assert await _owned(world["job_id"]) == {a: 4}


async def test_morning_releases_untouched_cards_over_the_portion(tick_world):
    _portion(tick_world, 6)
    r = await _user()
    world = await _world(8, recruiters=[r])
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(world["ids"])})
    assert len(await _fill(world["job_id"])) == 6

    _portion(tick_world, 4)

    async def _only(_db):
        return [world["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    result = await autofill.tick(now=_WORKDAY)

    # Porcja spadła do 4: dwie najsłabsze karty schodzą z osoby, nic nie dochodzi.
    assert result["filled"] == {}
    assert await _owned(world["job_id"]) == {r: 4}


async def test_cards_handed_over_in_the_morning_do_not_exhaust_the_pool(tick_world):
    """Rano karty osoby zajętej P0 przechodzą na drugą przypisaną; rekrutacja nie
    może przez to wypaść z puli na cały dzień (review 10.11.2026)."""
    _portion(tick_world, 4)
    a, b = await _user(), await _user()
    job = await _world(20, recruiters=[a], priority=JobPriority.urgent)
    await _pool(job["job_id"], {cid: 90 for cid in job["ids"]})
    assert len(await _fill(job["job_id"])) == 4
    async with AsyncSessionLocal() as db:
        db.add(JobCollaborator(job_id=job["job_id"], user_id=b, source="manual"))
        await db.commit()
    p0 = await _world(10, recruiters=[a])
    await _pool(p0["job_id"], {cid: 90 for cid in p0["ids"]})
    await _p0(p0["job_id"], _WORKDAY)

    async def _only(_db):
        return [job["job_id"], p0["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    await autofill.tick(now=_WORKDAY)

    assert await _owned(job["job_id"]) == {b: 4}
    async with AsyncSessionLocal() as db:
        state = (await db.get(AppSetting, autofill.BATCH_DAY_KEY)).value
    assert job["job_id"] not in state["exhausted"]


# ── P4: strumienie ──────────────────────────────────────────────────────────


async def test_streams_split_system_and_manual_with_found_via(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [system_cid] = await _fill(world["job_id"])
    manual_cid = world["ids"][1]
    async with AsyncSessionLocal() as db:
        from app.api.proposals_bulk import add_candidates_to_job

        job = await db.get(Job, world["job_id"])
        await add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[manual_cid],
            actor_user_id=a,
            entry_source="added_manual",
            claim=False,
            entry_meta={"found_via": "search"},
            mark_proposals=False,
        )
        await db.commit()
    now = _now()
    async with AsyncSessionLocal() as db:
        before = await streams.weekly_streams(db, now=now, weeks=1)
    await _move(world["job_id"], system_cid, PipelineStage.cv_sent, a)
    await _move(world["job_id"], manual_cid, PipelineStage.cv_sent, a)
    async with AsyncSessionLocal() as db:
        after = await streams.weekly_streams(db, now=now, weeks=1)
    week_before, week_after = before["weeks"][-1], after["weeks"][-1]
    assert week_after["system"] - week_before["system"] == 1
    assert week_after["manual"] - week_before["manual"] == 1
    assert (
        week_after["found_via"].get("search", 0)
        - week_before["found_via"].get("search", 0)
        == 1
    )
