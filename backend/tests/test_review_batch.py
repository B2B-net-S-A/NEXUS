"""Porcja dnia (07.11.2026) — prawdziwy Postgres.

Kontrakty:

- porcja liczy tylko czekające karty od systemu (osoby dodane przez zespół
  się nie liczą) i bierze osoby od ``MIN_SCORE``;
- rekrutacja bez rekrutera nie dostaje porcji;
- od 10.11.2026 porcja jest na osobę: tyle kart, ile wynosi jej poziom
  (tu minimum 4), wspólna pula dzieli się na zmianę między przypisanych;
- decyzja dziś = ruch karty od systemu z „Nowych” przez tę osobę i nic nie
  dochodzi w jej miejsce;
- „Dodaj kolejnych” dokłada osoby klikającemu;
- dzienny przebieg: drugi tick tego samego dnia nie dokłada nikogo w miejsce
  osób, o których już zdecydowano.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import new_column_autofill as autofill
from app.services import review_batch as rb

_WARSAW = ZoneInfo("Europe/Warsaw")
# Poniedziałek 09.11.2026, 9:00 w Warszawie.
_WORKDAY = datetime(2026, 11, 9, 9, 0, tzinfo=_WARSAW).astimezone(timezone.utc)


async def _user(role: UserRole = UserRole.recruiter) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rb-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Batch"),
            name=f"RB {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(people: int, *, recruiters: list[int]) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RB client {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RB job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=recruiters[0] if recruiters else None,
        )
        candidates = [
            Candidate(name="Porcja", lastname=f"{i}-{tag}") for i in range(people)
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
                    run_id="run-rb",
                    evidence={"matched_must": ["Java"], "missing_must": []},
                )
                for cid, score in scores.items()
            ]
        )
        await db.commit()


async def _fill(job_id: int, **kw) -> list[int]:
    async with AsyncSessionLocal() as db:
        added = await autofill.fill_job(db, job_id, now=_WORKDAY, batch=True, **kw)
        await db.commit()
        return added


async def _owners(job_id: int) -> dict[int, int]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == job_id,
                    RecruitmentProcess.entry_source == "system",
                )
            )
        ).all()
        return {p.candidate_id: (p.entry_meta or {}).get(rb.OWNER_KEY) for p in rows}


@pytest.fixture
def small_batch(monkeypatch):
    """Porcja osoby = 4 (minimum z ustawień, bez zapisanych poziomów)."""

    async def _four(_db):
        return rb.BatchSettings(minimum=4)

    monkeypatch.setattr(rb, "BATCH_SIZE", 4)
    monkeypatch.setattr(rb, "read_settings", _four)
    monkeypatch.setattr(rb.settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    return monkeypatch


async def test_batch_fills_from_min_score_and_splits_between_recruiters(small_batch):
    a, b = await _user(), await _user()
    world = await _world(6, recruiters=[a, b])
    ids = world["ids"]
    await _pool(
        world["job_id"],
        {ids[0]: 80, ids[1]: 78, ids[2]: 75, ids[3]: 70, ids[4]: 66, ids[5]: 60},
    )

    added = await _fill(world["job_id"])

    # Dwie porcje po 4, a od progu jest tylko 5 osób: na zmianę 3 i 2.
    assert len(added) == 5 and ids[5] not in added  # 60 < 65
    owners = await _owners(world["job_id"])
    assert sorted(list(owners.values()).count(u) for u in (a, b)) == [2, 3]


async def test_team_cards_do_not_count_and_no_recruiter_no_batch(small_batch):
    a = await _user()
    world = await _world(6, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 80 - i for i, cid in enumerate(ids)})
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=ids[0],
                job_id=world["job_id"],
                stage=PipelineStage.new,
                moved_by=a,
            )
        )
        await db.commit()

    added = await _fill(world["job_id"])
    assert len(added) == 4 and ids[0] not in added

    lonely = await _world(3, recruiters=[])
    await _pool(lonely["job_id"], {cid: 90 for cid in lonely["ids"]})
    assert await _fill(lonely["job_id"]) == []


async def test_decision_counts_today_and_nothing_replaces_it(small_batch):
    a = await _user()
    world = await _world(8, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})
    first = await _fill(world["job_id"])
    assert len(first) == 4

    async with AsyncSessionLocal() as db:
        assert len(await rb.pending_cards(db, owner_id=a)) == 4
        db.add(
            CandidateStage(
                candidate_id=first[0],
                job_id=world["job_id"],
                stage=PipelineStage.rejected,
                moved_by=a,
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await rb.decided_today(db, a, now=_WORKDAY) >= 1
        assert len(await rb.pending_cards(db, owner_id=a)) == 3

    # Porcja to porcja dnia: w miejsce decyzji nic nie dochodzi (10.11.2026).
    assert await _fill(world["job_id"]) == []


async def test_add_more_goes_to_clicker(small_batch):
    a, b = await _user(), await _user()
    world = await _world(12, recruiters=[a, b])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})
    first = await _fill(world["job_id"])
    more = await _fill(world["job_id"], extra_for=b)
    assert len(more) == 4
    owners = await _owners(world["job_id"])
    assert {owners[c] for c in more} == {b}
    assert {owners[c] for c in first} == {a, b}


async def test_daily_tick_runs_once_per_day(small_batch):
    a = await _user()
    world = await _world(8, recruiters=[a])
    ids = world["ids"]
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(ids)})

    async def _only_mine(_db):
        return [world["job_id"]]

    async def _no_new(_db):
        return []

    small_batch.setattr(autofill, "_jobs_in_work", _only_mine)
    small_batch.setattr(autofill, "_jobs_without_batch", _no_new)
    small_batch.setattr(
        autofill.settings, "NEW_COLUMN_AUTOFILL_ENABLED", True, raising=False
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, autofill.BATCH_DAY_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()

    result = await autofill.tick(now=_WORKDAY)
    assert result["pass"] == "batch" and result["filled"] == {world["job_id"]: 4}

    async with AsyncSessionLocal() as db:
        [one] = (await rb.pending_cards(db, job_ids=[world["job_id"]]))[:1]
        db.add(
            CandidateStage(
                candidate_id=one.candidate_id,
                job_id=world["job_id"],
                stage=PipelineStage.rejected,
                moved_by=a,
            )
        )
        await db.commit()

    again = await autofill.tick(now=_WORKDAY)
    assert again["filled"] == {} and again["jobs"] == 0


async def test_new_job_gets_its_batch_the_same_day(small_batch):
    """Rekrutacja założona w ciągu dnia (po pierwszym przeglądzie) dostaje
    porcję od razu, a nie dopiero jutro o 7:00; bez rekrutera — nie."""
    a = await _user()
    world = await _world(5, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(world["ids"])})
    lonely = await _world(2, recruiters=[])
    await _pool(lonely["job_id"], {cid: 90 for cid in lonely["ids"]})
    async with AsyncSessionLocal() as db:
        ids = await autofill._jobs_without_batch(db)
    assert world["job_id"] in ids and lonely["job_id"] not in ids

    await _fill(world["job_id"])
    async with AsyncSessionLocal() as db:
        assert world["job_id"] not in await autofill._jobs_without_batch(db)


async def test_closed_job_cards_do_not_block(small_batch):
    a = await _user()
    world = await _world(3, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    await _fill(world["job_id"])
    async with AsyncSessionLocal() as db:
        assert len(await rb._own_cards(db, a, now=_WORKDAY)) == 3
        job = await db.get(Job, world["job_id"])
        job.status = JobStatus.closed
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await rb._own_cards(db, a, now=_WORKDAY) == []


async def test_batch_card_cannot_be_removed_instead_of_decided(small_batch):
    from fastapi import HTTPException

    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    [first, *_] = await _fill(world["job_id"])
    async with AsyncSessionLocal() as db:
        user = await db.get(User, a)
        with pytest.raises(HTTPException) as exc:
            await rb.assert_removal_allowed(
                db, user, candidate_id=first, job_id=world["job_id"]
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == rb.REMOVAL_CODE


async def test_card_readded_by_hand_is_not_the_old_owners(small_batch):
    a = await _user()
    world = await _world(1, recruiters=[a])
    await _pool(world["job_id"], {world["ids"][0]: 90})
    [cid] = await _fill(world["job_id"])
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=cid,
                job_id=world["job_id"],
                stage=PipelineStage.rejected,
                moved_by=a,
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        old = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == cid,
                )
            )
        ).one()
        # Odrzucenie zamyka proces — dopiero wtedy wolno otworzyć nowe podejście.
        from app.models.recruitment_process import ProcessStatus

        old.status = ProcessStatus.closed
        old.closed_at = datetime.now(timezone.utc)
        await db.flush()
        db.add(
            RecruitmentProcess(
                candidate_id=cid,
                job_id=world["job_id"],
                client_id=old.client_id,
                attempt_no=(old.attempt_no or 1) + 1,
                previous_process_id=old.id,
                entry_source="added_manual",
                opened_at=datetime.now(timezone.utc),
                status=ProcessStatus.open,
                origin_kind=old.origin_kind,
            )
        )
        db.add(
            CandidateStage(
                candidate_id=cid,
                job_id=world["job_id"],
                stage=PipelineStage.new,
                moved_by=a,
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await rb.pending_cards(db, owner_id=a) == []


async def test_stale_card_leaves_the_batch_and_the_reset_withdraws_it(small_batch):
    """08.11.2026: karta starsza niż 7 dni nie jest porcją — nie blokuje, nie
    zajmuje miejsca świeżej, a jednorazowe wycofanie zdejmuje ją z Tablicy."""
    from datetime import timedelta

    from app.services import autofill_withdraw

    a = await _user()
    world = await _world(6, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(world["ids"])})
    first = await _fill(world["job_id"])
    assert len(first) == 4
    stale = first[0]
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == stale,
                )
            )
        ).one()
        process.opened_at = _WORKDAY - timedelta(days=10)
        await db.commit()
    async with AsyncSessionLocal() as db:
        mine = {c.candidate_id for c in await rb._own_cards(db, a, now=_WORKDAY)}
    assert stale not in mine and len(mine) == 3
    # Świeża karta wchodzi w miejsce starej.
    assert len(await _fill(world["job_id"])) == 1

    async with AsyncSessionLocal() as db:
        planned = await autofill_withdraw.plan_batch_reset(
            db, now=_WORKDAY, job_ids=[world["job_id"]]
        )
        assert planned == [(stale, world["job_id"])]
        done = await autofill_withdraw.apply(
            db,
            planned,
            reason=autofill_withdraw.BATCH_RESET_REASON,
            check_batch_reset=True,
        )
        await db.commit()
    assert done == planned
    async with AsyncSessionLocal() as db:
        left = {
            c.candidate_id
            for c in await rb.pending_cards(db, job_ids=[world["job_id"]])
        }
    assert stale not in left and len(left) == 4


async def test_low_score_card_is_not_the_batch(small_batch):
    a = await _user()
    world = await _world(2, recruiters=[a])
    await _pool(world["job_id"], {cid: 90 for cid in world["ids"]})
    [first, *_] = await _fill(world["job_id"])
    async with AsyncSessionLocal() as db:
        process = (
            await db.scalars(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == world["job_id"],
                    RecruitmentProcess.candidate_id == first,
                )
            )
        ).one()
        process.entry_meta = {**(process.entry_meta or {}), "score": 50}
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, a)
        # Słaba karta nie blokuje usunięcia i nie liczy się do porcji.
        await rb.assert_removal_allowed(
            db, user, candidate_id=first, job_id=world["job_id"]
        )
        mine = {c.candidate_id for c in await rb._own_cards(db, a, now=_WORKDAY)}
    assert first not in mine


async def test_board_shows_for_only_people_still_assigned(small_batch):
    """10.11.2026: „Dla: …” na Tablicy tylko przy osobie dalej przypisanej. Karta
    osoby zdjętej z rekrutacji wyglądała jak jej porcja, choć nikogo nie blokuje."""
    from httpx import ASGITransport, AsyncClient

    from app.core.rate_limit import limiter
    from app.main import app

    tag = uuid.uuid4().hex[:8]
    email, password = f"rb-board-{tag}@example.com", f"T3st_{tag}!Board"
    async with AsyncSessionLocal() as db:
        owner = User(
            email=email,
            password_hash=hash_password(password),
            name=f"RB board {tag}",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(owner)
        await db.commit()
        a = owner.id
    b = await _user()
    world = await _world(8, recruiters=[a, b])
    await _pool(world["job_id"], {cid: 90 - i for i, cid in enumerate(world["ids"])})
    await _fill(world["job_id"])
    owners = await _owners(world["job_id"])
    gone = {cid for cid, uid in owners.items() if uid == b}
    assert gone
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobCollaborator).where(
                JobCollaborator.job_id == world["job_id"], JobCollaborator.user_id == b
            )
        )
        await db.commit()

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        login = await client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        board = await client.get(
            f"/api/pipeline/kanban/{world['job_id']}", headers=headers
        )
    assert board.status_code == 200, board.text
    shown = {
        item["candidate_id"]: (item.get("entry_autofill") or {}).get("review_owner")
        for column in board.json()["columns"]
        for item in column["items"]
    }
    assert all(shown[cid] is None for cid in gone)
    assert any((owner or {}).get("id") == a for owner in shown.values())
