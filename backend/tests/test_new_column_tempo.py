"""Cel kart wg tempa i miejsce dla świeżych (08.11.2026) — prawdziwy Postgres.

Kontrakty (``NEW_COLUMN_TEMPO_TARGET_ENABLED``):

- cel kart od systemu: 0 decyzji = 5, 1–9 = 10, 10+ = 20, rekrutacja do 14 dni
  i P0 = 20; liczą się czekające karty od systemu, reszta stoi poza celem;
- poranny przebieg raz dziennie, odporny na restart, a w dzień po ruchu karty
  tylko gorące, nowe i P0;
- osoba nowa w bazie zajmuje miejsce karty nietkniętej 7 dni, od najniższego
  wyniku, najwyżej 5 zamian dziennie; karta ruszona nie schodzi, a zdjęta
  osoba może wrócić;
- „Dodaj 10 kolejnych”: osoba z prawem edycji, także poza porcją; odmowy.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.models  # noqa: F401
from app.api import review_batch as batch_api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import auto_full_review, autofill_withdraw
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb

_WARSAW = ZoneInfo("Europe/Warsaw")
# Środa 21.10.2026, 9:00 w Warszawie: wpisy archiwum z zegara bazy są od niej młodsze.
_WORKDAY = datetime(2026, 10, 21, 9, 0, tzinfo=_WARSAW).astimezone(timezone.utc)
_LONG_AGO = _WORKDAY - timedelta(days=60)


@pytest.fixture
def tempo_on(monkeypatch):
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", True)
    monkeypatch.setattr(settings, "NEW_COLUMN_FRESH_FIRST_ENABLED", True)
    return monkeypatch


async def _user(role: UserRole = UserRole.recruiter) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"tempo-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Tempo"),
            name=f"Tempo {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(
    people: int,
    *,
    opened: datetime = _LONG_AGO,
    work_state: str = "searching",
    p0_until: datetime | None = None,
    recruiter_id: int | None = None,
) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Tempo client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Tempo job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state=work_state,
            opened_at=opened,
            p0_until=p0_until,
            recruiter_id=recruiter_id,
        )
        candidates = [
            Candidate(name="Tempo", lastname=f"{i}-{tag}") for i in range(people)
        ]
        db.add_all([job, *candidates])
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
                    run_id="run-tempo",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _fill(job_id: int, **kw) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_WORKDAY, **kw)
        await db.commit()
        return added


async def _stage(
    cid: int, job_id: int, stage: PipelineStage, by: int | None, at: datetime
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cid, job_id=job_id, stage=stage, moved_by=by, moved_at=at
            )
        )
        await db.commit()


async def _decisions(job_id: int, cids: list[int], by: int) -> None:
    for cid in cids:
        await _stage(cid, job_id, PipelineStage.new, None, _WORKDAY - timedelta(days=3))
        await _stage(
            cid, job_id, PipelineStage.screening, by, _WORKDAY - timedelta(days=2)
        )


async def _tempo(job_id: int) -> autofill.Tempo:
    async with AsyncSessionLocal() as db:
        return (await autofill.tempo_for_jobs(db, [job_id], _WORKDAY))[job_id]


async def _system_card(job_id: int, cid: int, score: float, age_days: int) -> int:
    """Karta od systemu w „Nowych”, otwarta ``age_days`` dni temu."""
    opened = _WORKDAY - timedelta(days=age_days)
    async with AsyncSessionLocal() as db:
        process = RecruitmentProcess(
            job_id=job_id,
            candidate_id=cid,
            entry_source="system",
            opened_at=opened,
            attempt_no=1,
            entry_meta={"kind": "autofill", "score": score, "cautions": []},
        )
        db.add(process)
        db.add(
            CandidateStage(
                candidate_id=cid,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_by=None,
                moved_at=opened,
            )
        )
        await db.commit()
        return process.id


async def _new_in_base(cid: int, days: int = 3) -> None:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, cid)
        candidate.created_at = _WORKDAY - timedelta(days=days)
        await db.commit()


async def _board(job_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        return {
            int(c)
            for c in (
                await db.scalars(
                    select(CandidateStage.candidate_id).where(
                        CandidateStage.job_id == job_id
                    )
                )
            ).all()
        }


async def _removals(job_id: int) -> list[CandidateStageRemoval]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateStageRemoval).where(
                        CandidateStageRemoval.job_id == job_id
                    )
                )
            ).all()
        )


# ── Progi ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("decisions", "new_job", "p0", "tier", "target", "refills"),
    [
        (0, False, False, "quiet", 5, False),
        (1, False, False, "moderate", 10, False),
        (9, False, False, "moderate", 10, False),
        (10, False, False, "hot", 20, True),
        (0, True, False, "new", 20, True),
        (0, False, True, "p0", 20, True),
    ],
)
def test_target_follows_the_tempo(decisions, new_job, p0, tier, target, refills):
    tempo = autofill.tempo_of(decisions, new_job=new_job, p0=p0)
    assert (tempo.tier, tempo.target, tempo.refills_during_day) == (
        tier,
        target,
        refills,
    )


async def test_only_human_exits_from_new_within_21_days_count():
    user = await _user()
    world = await _world(6)
    job_id = world["job_id"]
    exited, moved_twice, stale, machine, past_new, _ = world["ids"]
    await _decisions(job_id, [exited], user)
    # Jedna osoba = jedna decyzja, także gdy wróciła i wyszła drugi raz.
    await _decisions(job_id, [moved_twice], user)
    await _stage(
        moved_twice, job_id, PipelineStage.new, user, _WORKDAY - timedelta(days=1)
    )
    await _stage(
        moved_twice,
        job_id,
        PipelineStage.rejected,
        user,
        _WORKDAY - timedelta(hours=1),
    )
    # Starsze niż 21 dni.
    await _stage(stale, job_id, PipelineStage.new, None, _WORKDAY - timedelta(days=40))
    await _stage(
        stale, job_id, PipelineStage.screening, user, _WORKDAY - timedelta(days=30)
    )
    # Bez człowieka.
    await _stage(machine, job_id, PipelineStage.new, None, _WORKDAY - timedelta(days=3))
    await _stage(
        machine, job_id, PipelineStage.screening, None, _WORKDAY - timedelta(days=2)
    )
    # Ruch już poza „Nowymi”.
    await _stage(
        past_new, job_id, PipelineStage.screening, user, _WORKDAY - timedelta(days=3)
    )
    await _stage(
        past_new, job_id, PipelineStage.cv_sent, user, _WORKDAY - timedelta(days=2)
    )
    assert (await _tempo(job_id)).decisions == 2


async def test_active_p0_and_a_young_job_get_the_full_target():
    p0 = await _world(0, p0_until=_WORKDAY + timedelta(hours=20))
    assert (await _tempo(p0["job_id"])).tier == "p0"
    young = await _world(0, opened=_WORKDAY - timedelta(days=13))
    assert (await _tempo(young["job_id"])).tier == "new"
    old = await _world(0, opened=_WORKDAY - timedelta(days=15))
    assert (await _tempo(old["job_id"])).tier == "quiet"


# ── Cel ─────────────────────────────────────────────────────────────────────


async def test_switch_off_keeps_twenty_and_on_a_quiet_job_gets_five(monkeypatch):
    world = await _world(30)
    await _pool(world["job_id"], {cid: 60 for cid in world["ids"]})
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", False)
    assert len(await _fill(world["job_id"])) == 20

    world = await _world(30)
    await _pool(world["job_id"], {cid: 60 for cid in world["ids"]})
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", True)
    assert len(await _fill(world["job_id"])) == 5


async def test_team_cards_and_taken_cards_stand_outside_the_target(tempo_on):
    user = await _user()
    world = await _world(12)
    job_id = world["job_id"]
    team, called, claimed, *rest = world["ids"]
    await _pool(job_id, {cid: 60 for cid in rest})
    # Osoba od zespołu, „Dzwonię” i aktywna blokada nie zajmują celu 5.
    await _stage(team, job_id, PipelineStage.new, user, _WORKDAY)
    await _system_card(job_id, called, 70, 1)
    await _system_card(job_id, claimed, 70, 1)
    async with AsyncSessionLocal() as db:
        for cid, change in (
            (called, {"entry_meta": {"score": 70, "decided_at": "2026-11-09"}}),
            (
                claimed,
                {
                    "claimed_by_user_id": user,
                    "claimed_until": datetime.now(timezone.utc) + timedelta(hours=6),
                },
            ),
        ):
            process = await db.scalar(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == job_id,
                    RecruitmentProcess.candidate_id == cid,
                )
            )
            for key, value in change.items():
                setattr(process, key, value)
        await db.commit()
    assert len(await _fill(job_id)) == 5


async def test_above_target_adds_nobody_and_removes_nobody(tempo_on):
    world = await _world(9)
    job_id = world["job_id"]
    waiting, pool = world["ids"][:7], world["ids"][7:]
    for cid in waiting:
        await _system_card(job_id, cid, 70, 1)
    await _pool(job_id, {cid: 90 for cid in pool})
    assert await _fill(job_id) == []
    assert await _board(job_id) == set(waiting)


async def test_new_in_base_does_not_exceed_the_target(tempo_on):
    world = await _world(8)
    job_id = world["job_id"]
    waiting, pool = world["ids"][:5], world["ids"][5:]
    for cid in waiting:
        await _system_card(job_id, cid, 70, 1)
    await _pool(job_id, {cid: 95 for cid in pool})
    for cid in pool:
        await _new_in_base(cid)
    assert await _fill(job_id) == []


async def test_batch_uses_the_tempo_target_instead_of_twenty(tempo_on):
    recruiter = await _user()
    world = await _world(30, recruiter_id=recruiter)
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    assert len(await _fill(world["job_id"], batch=True)) == 5


# ── Miejsce dla świeżych ────────────────────────────────────────────────────


async def _seats(ages_scores: list[tuple[int, float]], newcomers: int, **job) -> dict:
    world = await _world(len(ages_scores) + newcomers, **job)
    job_id = world["job_id"]
    on_board = world["ids"][: len(ages_scores)]
    for cid, (age, score) in zip(on_board, ages_scores, strict=True):
        await _system_card(job_id, cid, score, age)
    fresh = world["ids"][len(ages_scores) :]
    await _pool(job_id, {cid: 75 for cid in fresh})
    for cid in fresh:
        await _new_in_base(cid)
    return {"job_id": job_id, "board": on_board, "fresh": fresh}


async def test_fresh_person_takes_the_lowest_scored_stale_seat(tempo_on):
    world = await _seats([(10, 80), (10, 71), (10, 90), (6, 60), (10, 85)], newcomers=1)
    added = await _fill(world["job_id"], swap=True)
    assert added == world["fresh"]
    board = await _board(world["job_id"])
    # Karta z 60% ma 6 dni, więc schodzi 71%, nie 60%.
    assert world["board"][1] not in board
    assert world["board"][3] in board
    assert len(board) == 5


async def test_at_most_five_swaps_a_day_also_across_runs(tempo_on):
    world = await _seats([(10, 70 + i) for i in range(8)], newcomers=7)
    first = await _fill(world["job_id"], swap=True)
    assert len(first) == 5
    assert await _fill(world["job_id"], swap=True) == []
    assert len(await _board(world["job_id"])) == 8


async def test_swap_counts_against_the_tick_limit(tempo_on):
    world = await _seats(
        [(10, 70), (10, 71), (10, 72), (10, 73), (10, 74)], newcomers=4
    )
    added = await _fill(world["job_id"], swap=True, limit=2)
    assert len(added) == 2
    assert len(await _board(world["job_id"])) == 5


async def test_without_swap_flag_nobody_leaves(tempo_on):
    world = await _seats([(10, 70)] * 5, newcomers=1)
    assert await _fill(world["job_id"]) == []
    assert set(world["board"]) == await _board(world["job_id"])


async def test_touched_cards_never_leave(tempo_on):
    user = await _user()
    world = await _seats([(10, 70 + i) for i in range(6)], newcomers=5)
    job_id = world["job_id"]
    called, claimed, moved, noted, screened, untouched = world["board"]
    async with AsyncSessionLocal() as db:
        processes = {
            p.candidate_id: p
            for p in (
                await db.scalars(
                    select(RecruitmentProcess).where(
                        RecruitmentProcess.job_id == job_id
                    )
                )
            ).all()
        }
        processes[called].entry_meta = {"score": 70, "decided_at": "2026-11-09"}
        processes[claimed].claimed_by_user_id = user
        processes[claimed].claimed_until = datetime.now(timezone.utc) + timedelta(
            hours=6
        )
        db.add(
            Note(candidate_id=noted, job_id=job_id, content="Rozmowa", author_id=user)
        )
        stage = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id == screened,
            )
        )
        stage.rating = 4
        await db.commit()
    await _stage(moved, job_id, PipelineStage.new, user, _WORKDAY)
    added = await _fill(job_id, swap=True)
    # Dwie karty wzięte, więc jedna osoba wchodzi na wolne miejsce, druga za kartę.
    assert len(added) == 2
    board = await _board(job_id)
    assert untouched not in board
    assert {called, claimed, moved, noted, screened} <= board


async def test_no_fresh_person_means_no_withdrawal(tempo_on):
    world = await _seats([(10, 70)] * 5, newcomers=0)
    assert await _fill(world["job_id"], swap=True) == []
    assert await _removals(world["job_id"]) == []


async def test_swap_leaves_a_trace_and_the_card_can_come_back(tempo_on):
    world = await _seats(
        [(10, 70), (10, 80), (10, 81), (10, 82), (10, 83)], newcomers=1
    )
    job_id = world["job_id"]
    gone = world["board"][0]
    await _fill(job_id, swap=True)
    [removal] = await _removals(job_id)
    assert removal.reason == autofill_withdraw.FRESH_SEAT_REASON
    assert removal.removed_by is None
    async with AsyncSessionLocal() as db:
        entry = await db.scalar(
            select(Activity).where(
                Activity.entity_type == autofill_withdraw.ACTIVITY_ENTITY,
                Activity.entity_id == job_id,
                Activity.action == autofill_withdraw.ACTION,
            )
        )
        assert entry.details["count"] == 1
        assert entry.details["why"] == "fresh_seat"
        # Pula nocnego przeglądu też widzi ją jako wolną.
        assert gone not in await auto_full_review._in_job_ids(db, job_id)
    await _pool(job_id, {gone: 66})
    async with AsyncSessionLocal() as db:
        picks = await autofill.ranked_picks(db, job_id, limit=10)
    assert gone in {pick.candidate_id for pick in picks}


async def test_a_person_who_gave_way_does_not_come_back_as_new_in_base(tempo_on):
    world = await _seats([(10, 70)] * 5, newcomers=1)
    job_id = world["job_id"]
    gone = world["board"][0]
    await _new_in_base(gone, days=8)
    await _fill(job_id, swap=True)
    assert gone not in await _board(job_id)
    await _pool(job_id, {gone: 95})
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        picks = await autofill.new_in_base_picks(db, job, now=_WORKDAY)
    assert gone not in {pick.candidate_id for pick in picks}
    # Następnego ranka nie zabiera miejsca kolejnej karcie.
    assert await _fill(job_id, swap=True) == []
    assert len(await _removals(job_id)) == 1


async def test_batch_never_swaps_because_old_cards_take_no_place(tempo_on):
    recruiter = await _user()
    world = await _seats(
        [(1, 90)] * 5 + [(8, 70)] * 5, newcomers=5, recruiter_id=recruiter
    )
    job_id = world["job_id"]
    assert await _fill(job_id, batch=True, swap=True) == []
    assert await _removals(job_id) == []


async def test_other_removal_reasons_stay_excluded(tempo_on):
    world = await _world(2)
    job_id = world["job_id"]
    human, both = world["ids"]
    await _pool(job_id, {human: 90, both: 90})
    async with AsyncSessionLocal() as db:
        for cid, reason in (
            (human, "pomyłka"),
            (both, None),
            (both, autofill_withdraw.FRESH_SEAT_REASON),
        ):
            db.add(
                CandidateStageRemoval(
                    candidate_id=cid,
                    job_id=job_id,
                    reason=reason,
                    last_stage="new",
                    stage_count=1,
                    stages_snapshot=[],
                )
            )
        await db.commit()
        assert await autofill.ranked_picks(db, job_id, limit=10) == []
        assert {human, both} <= await auto_full_review._in_job_ids(db, job_id)


# ── Rytm ────────────────────────────────────────────────────────────────────


@pytest.fixture
def tempo_tick(tempo_on):
    tempo_on.setattr(autofill, "_state", autofill._State())
    tempo_on.setattr(settings, "NEW_COLUMN_AUTOFILL_ENABLED", True)
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", False)
    return tempo_on


async def _clear_day() -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, autofill.TEMPO_DAY_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()


def _only(monkeypatch, ids: list[int]) -> None:
    async def _in_work(_db):
        return ids

    async def _nothing(_db, **_kw):
        return []

    async def _no_moves(_db, _since):
        return []

    monkeypatch.setattr(autofill, "_jobs_in_work", _in_work)
    monkeypatch.setattr(autofill, "_jobs_without_batch", _nothing)
    monkeypatch.setattr(autofill, "_jobs_touched_since", _no_moves)


async def test_morning_pass_runs_once_and_survives_a_restart(tempo_tick):
    await _clear_day()
    world = await _world(12)
    job_id = world["job_id"]
    await _pool(job_id, {cid: 70 for cid in world["ids"]})
    _only(tempo_tick, [job_id])

    first = await autofill.tick(now=_WORKDAY)
    assert first["filled"] == {job_id: 5}
    async with AsyncSessionLocal() as db:
        state = (await db.get(AppSetting, autofill.TEMPO_DAY_KEY)).value
    assert state == {"day": business_today().isoformat(), "pending": []}

    # Restart: pamięć procesu pusta, a miejsce po decyzji nie dopełnia się.
    await _stage(world["ids"][0], job_id, PipelineStage.rejected, None, _WORKDAY)
    tempo_tick.setattr(autofill, "_state", autofill._State())
    second = await autofill.tick(now=_WORKDAY + timedelta(minutes=16))
    assert second["pass"] == "tempo"
    assert second["jobs"] == 0


async def test_morning_pass_resumes_after_the_budget_ran_out(tempo_tick):
    await _clear_day()
    tempo_tick.setattr(settings, "NEW_COLUMN_AUTOFILL_MAX_PER_TICK", 5)
    one = await _world(6)
    two = await _world(6)
    for world in (one, two):
        await _pool(world["job_id"], {cid: 70 for cid in world["ids"]})
    _only(tempo_tick, [one["job_id"], two["job_id"]])

    first = await autofill.tick(now=_WORKDAY)
    assert sum(first["filled"].values()) == 5
    assert first["pending"] > 0
    second = await autofill.tick(now=_WORKDAY + timedelta(minutes=1))
    assert sum(second["filled"].values()) == 5
    # Rekrutacja, na której skończył się limit, przechodzi jeszcze raz.
    assert second["pending"] == 1
    third = await autofill.tick(now=_WORKDAY + timedelta(minutes=2))
    assert third["filled"] == {}
    assert third["pending"] == 0


async def test_during_the_day_only_hot_jobs_refill_after_a_move(tempo_tick):
    user = await _user()
    await _clear_day()
    quiet = await _world(3)
    hot = await _world(14)
    for world in (quiet, hot):
        await _pool(world["job_id"], {cid: 70 for cid in world["ids"]})
    await _decisions(hot["job_id"], hot["ids"][:10], user)
    _only(tempo_tick, [])
    await autofill.tick(now=_WORKDAY)

    async def _touched(_db, _since):
        return [quiet["job_id"], hot["job_id"]]

    tempo_tick.setattr(autofill, "_jobs_touched_since", _touched)
    result = await autofill.tick(now=_WORKDAY + timedelta(minutes=1))
    assert list(result["filled"]) == [hot["job_id"]]


async def test_morning_swap_happens_in_the_tick_but_not_during_the_day(tempo_tick):
    await _clear_day()
    world = await _seats([(10, 70)] * 5, newcomers=2)
    job_id = world["job_id"]
    _only(tempo_tick, [job_id])
    result = await autofill.tick(now=_WORKDAY)
    assert result["filled"] == {job_id: 2}
    assert len(await _removals(job_id)) == 2

    # P0 dopełnia się w dzień, ale miejsce dla świeżych jest tylko rano.
    late = await _seats(
        [(10, 70)] * 20, newcomers=1, p0_until=_WORKDAY + timedelta(hours=20)
    )

    async def _touched(_db, _since):
        return [late["job_id"]]

    tempo_tick.setattr(autofill, "_jobs_touched_since", _touched)
    result = await autofill.tick(now=_WORKDAY + timedelta(minutes=1))
    assert result["filled"] == {}
    assert await _removals(late["job_id"]) == []


# ── „Dodaj 10 kolejnych” ────────────────────────────────────────────────────


async def _call(route, job_id: int, user_id: int):
    async with AsyncSessionLocal() as db:
        return await route(job_id, await db.get(User, user_id), db)


async def _refused(route, job_id: int, user_id: int) -> HTTPException:
    with pytest.raises(HTTPException) as refused:
        await _call(route, job_id, user_id)
    return refused.value


async def test_more_adds_ten_outside_the_batch_even_on_a_quiet_job(tempo_on):
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", False)
    user = await _user()
    world = await _world(15)
    await _pool(world["job_id"], {cid: 70 for cid in world["ids"]})
    assert len(await _fill(world["job_id"])) == 5
    assert await _call(batch_api.add_more, world["job_id"], user) == {"added": 10}
    assert len(await _board(world["job_id"])) == 15


async def test_more_refuses_a_user_without_edit_rights(tempo_on):
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", False)
    viewer = await _user(UserRole.user)
    world = await _world(1)
    refused = await _refused(batch_api.add_more, world["job_id"], viewer)
    assert refused.status_code == 403


async def test_more_refuses_a_job_out_of_work_and_a_missing_job(tempo_on):
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", False)
    user = await _user()
    world = await _world(1, work_state="client_silent")
    assert (
        await _refused(batch_api.add_more, world["job_id"], user)
    ).status_code == 409
    assert (await _refused(batch_api.add_more, 2_000_000_000, user)).status_code == 404


async def test_more_in_batch_waits_for_own_cards(tempo_on):
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", True)
    recruiter = await _user()
    world = await _world(20, recruiter_id=recruiter)
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    assert len(await _fill(world["job_id"], batch=True)) == 5
    refused = await _refused(batch_api.add_more, world["job_id"], recruiter)
    assert refused.status_code == 409


async def test_more_in_batch_for_an_editor_outside_the_team_adds_ten(tempo_on):
    tempo_on.setattr(settings, "REVIEW_BATCH_ENABLED", True)
    recruiter = await _user()
    lead = await _user(UserRole.admin)
    world = await _world(20, recruiter_id=recruiter)
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    assert await _call(batch_api.add_more, world["job_id"], lead) == {"added": 10}


async def test_flag_off_keeps_the_old_more_rules(monkeypatch):
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", False)
    monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", False)
    user = await _user()
    world = await _world(1)
    refused = await _refused(batch_api.add_more, world["job_id"], user)
    assert refused.status_code == 409
    assert refused.detail == "Porcja dnia jest wyłączona."


async def test_tempo_read_says_off_or_gives_the_target(monkeypatch):
    admin = await _user(UserRole.admin)
    world = await _world(0)
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", False)
    assert await _call(batch_api.job_tempo, world["job_id"], admin) == {
        "enabled": False
    }
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", True)
    out = await _call(batch_api.job_tempo, world["job_id"], admin)
    assert (out["target"], out["tier"], out["can_add_more"]) == (5, "quiet", True)


async def test_tempo_read_hides_the_button_from_people_who_cannot_edit(monkeypatch):
    monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", True)
    admin = await _user(UserRole.admin)
    world = await _world(0, work_state="client_silent")
    out = await _call(batch_api.job_tempo, world["job_id"], admin)
    assert out["can_add_more"] is False


async def test_batch_status_says_how_many_the_button_adds(monkeypatch):
    user = await _user()
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, user)
        monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", False)
        assert (await batch_api.my_batch(actor, db))["more_cards"] == rb.BATCH_SIZE
        monkeypatch.setattr(settings, "NEW_COLUMN_TEMPO_TARGET_ENABLED", True)
        assert (await batch_api.my_batch(actor, db))["more_cards"] == 10


async def test_pending_cards_mark_taken_ones():
    user = await _user()
    world = await _world(3)
    job_id = world["job_id"]
    free, called, claimed = world["ids"]
    for cid in world["ids"]:
        await _system_card(job_id, cid, 70, 1)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(RecruitmentProcess).where(RecruitmentProcess.job_id == job_id)
            )
        ).all()
        for process in rows:
            if process.candidate_id == called:
                process.entry_meta = {"score": 70, "decided_at": "2026-11-09"}
            if process.candidate_id == claimed:
                process.claimed_by_user_id = user
                process.claimed_until = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.commit()
        cards = await rb.pending_cards(db, job_ids=[job_id])
    assert {c.candidate_id: c.taken for c in cards} == {
        free: False,
        called: True,
        claimed: True,
    }
