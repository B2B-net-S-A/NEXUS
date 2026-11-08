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
    assert counts.done == 0 and counts.open_today == 0


# ── P5: „Do screeningu” dopiero po domknięciu ───────────────────────────────


async def test_rejection_counts_at_once_and_screening_waits(batch_on):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    first, second = await _fill(world["job_id"])

    await _move(world["job_id"], first, PipelineStage.rejected, a)
    await _move(world["job_id"], second, PipelineStage.screening, a)

    status = await _status(a)
    assert status.done_today == 1 and status.open_screenings == 1
    # Karta przesunięta na screening nie obniża wymaganego minimum.
    assert status.required == 2 and status.met is False


async def test_screening_of_whole_batch_does_not_unlock(batch_on):
    """Bez tego rekruter z 2 kartami wciska S dwa razy i ma required = 0."""
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    added = await _fill(world["job_id"])
    for cid in added:
        await _move(world["job_id"], cid, PipelineStage.screening, a)
    status = await _status(a)
    assert status.pending == 0 and status.required == 2 and status.met is False


async def test_screening_closed_by_saved_form_counts(batch_on):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    stage_id = await _move(world["job_id"], cid, PipelineStage.screening, a)
    assert (await _status(a)).done_today == 0
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


async def test_screening_older_than_window_does_not_count(batch_on):
    """S sprzed 2 dni roboczych zamknięte dziś już minimum nie zalicza."""
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
    assert row["done_today"] == 1
    assert row["pending"] == 1
    assert row["required"] == 3  # 1 decyzja + 1 w porcji + 1 niedomknięte S
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


async def test_day_plan_orders_p0_and_priority_first(tick_world):
    r = await _user()
    low = await _world(1, recruiters=[r], priority=JobPriority.low)
    urgent = await _world(1, recruiters=[r], priority=JobPriority.urgent)
    medium_newer = await _world(1, recruiters=[r], priority=JobPriority.medium)
    medium_older = await _world(1, recruiters=[r], priority=JobPriority.medium)
    # ``medium_newer`` jest starsza id-kiem niż ``medium_older``: nowsze idą pierwsze.
    ids = [
        low["job_id"],
        urgent["job_id"],
        medium_newer["job_id"],
        medium_older["job_id"],
    ]

    async def _only(_db):
        return ids

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    async with AsyncSessionLocal() as db:
        plan = await autofill._day_plan(db, "2026-11-09", _now())
    assert plan["pending"] == [
        urgent["job_id"],
        medium_older["job_id"],
        medium_newer["job_id"],
        low["job_id"],
    ]


async def test_every_job_gets_first_round_before_the_rest(tick_world):
    tick_world.setattr(rb, "BATCH_SIZE", 20)
    tick_world.setattr(autofill.settings, "NEW_COLUMN_AUTOFILL_MAX_PER_TICK", 10)
    r = await _user()
    urgent = await _world(12, recruiters=[r], priority=JobPriority.urgent)
    medium = await _world(12, recruiters=[r], priority=JobPriority.medium)
    for world in (urgent, medium):
        await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})

    async def _only(_db):
        return [medium["job_id"], urgent["job_id"]]

    tick_world.setattr(autofill, "_jobs_in_work", _only)
    result = await autofill.tick(now=_WORKDAY)

    assert result["filled"] == {urgent["job_id"]: 5, medium["job_id"]: 5}
    assert result["pending"] == 2


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
