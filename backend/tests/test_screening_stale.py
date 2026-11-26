"""Karty bez śladu wracają do „Nowych” (decyzja Artura z 23.11.2026).

Prawdziwy Postgres, baza wspólna i nieczyszczona — każdy test zakłada własny
świat i woła przebieg tylko dla swojej rekrutacji (``job_ids``). Daty są
stałe: listopad 2026, ślad w poniedziałek 16.11 wraca w czwartek 19.11.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.calendar_event import (
    BOOKED_CALL_LOCATION,
    CalendarEvent,
    EventStatus,
    EventType,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import candidate_claim, review_batch
from app.services import screening_stale as svc
from app.services.recruitment_process_commands import transition_process

pytestmark = pytest.mark.asyncio

WAW = ZoneInfo("Europe/Warsaw")
MONDAY = datetime(2026, 11, 16, 10, tzinfo=WAW)
WEDNESDAY_EVENING = datetime(2026, 11, 18, 20, tzinfo=WAW)
THURSDAY_MORNING = datetime(2026, 11, 19, 0, 30, tzinfo=WAW)
SATURDAY = datetime(2026, 11, 21, 9, tzinfo=WAW)


async def _user(name: str = "Rekruter") -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"stale-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!St"),
            name=f"{name} {unique}",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _world(*, status: JobStatus = JobStatus.published) -> dict:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Stale {unique}")
        cand = Candidate(
            name="Ola", lastname=f"Cisza{unique}", email=f"stale-{unique}@example.com"
        )
        tpl = PipelineTemplate(name=f"Stale template {unique}")
        db.add_all([cli, cand, tpl])
        await db.flush()
        defs = {}
        for order, (key, name, enum) in enumerate(
            [("new", "Nowi", "new"), ("screening", "Screening", "screening")]
        ):
            d = PipelineStageDef(
                template_id=tpl.id,
                name=name,
                order=order,
                category=StageCategoryEnum.internal,
                legacy_enum_value=enum,
            )
            db.add(d)
            defs[key] = d
        await db.flush()
        job = Job(
            title=f"Stale Java {unique}",
            location="Warszawa",
            status=status,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            pipeline_template_id=tpl.id,
        )
        db.add(job)
        await db.commit()
        return {
            "client_id": cli.id,
            "candidate_id": cand.id,
            "job_id": job.id,
            "template_id": tpl.id,
            "defs": {k: d.id for k, d in defs.items()},
        }


async def _cleanup(world: dict) -> None:
    cid, job_id = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CalendarEvent).where(CalendarEvent.candidate_id == cid))
        await db.execute(delete(Note).where(Note.candidate_id == cid))
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == cid)
        )
        await db.execute(
            delete(RecruitmentProcess).where(RecruitmentProcess.candidate_id == cid)
        )
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(
            delete(PipelineStageDef).where(
                PipelineStageDef.template_id == world["template_id"]
            )
        )
        await db.execute(
            delete(PipelineTemplate).where(PipelineTemplate.id == world["template_id"])
        )
        await db.execute(delete(Client).where(Client.id == world["client_id"]))
        await db.commit()


async def _move(
    world: dict,
    key: str,
    *,
    actor: int | None,
    at: datetime,
    entry_source: str | None = None,
    entry_meta: dict | None = None,
    claim_for: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        stage = await transition_process(
            db,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.new if key == "new" else PipelineStage.screening,
            stage_def_id=world["defs"][key],
            actor_user_id=actor,
            moved_at=at,
            entry_source=entry_source,
            entry_meta=entry_meta,
            claim_for_user_id=claim_for,
        )
        await db.commit()
        return stage.id


async def _in_screening(world: dict, recruiter: int, *, at: datetime = MONDAY) -> int:
    await _move(
        world,
        "new",
        actor=recruiter,
        at=at - timedelta(hours=1),
        entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
        claim_for=recruiter,
    )
    return await _move(world, "screening", actor=recruiter, at=at)


async def _claim(world: dict, user_id: int, stage_id: int, at: datetime) -> None:
    """„Biorę” tak, jak zapisuje je trasa ``/claim``."""
    async with AsyncSessionLocal() as db:
        process = await _process(db, world)
        candidate_claim.set_claim(process, user_id, at)
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=stage_id,
                action="candidate_claimed",
                user_id=user_id,
                details={
                    "candidate_id": world["candidate_id"],
                    "job_id": world["job_id"],
                },
                created_at=at,
            )
        )
        await db.commit()


async def _process(db, world: dict) -> RecruitmentProcess:
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == world["candidate_id"],
            RecruitmentProcess.job_id == world["job_id"],
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
    )
    assert process is not None
    return process


async def _sweep(world: dict, now: datetime) -> svc.SweepResult:
    async with AsyncSessionLocal() as db:
        result = await svc.run_sweep(
            db, now=now.astimezone(timezone.utc), job_ids=[world["job_id"]]
        )
        await db.commit()
        await svc.send_bells(db, result)
        await db.commit()
        return result


async def _latest_stage(world: dict) -> CandidateStage:
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == world["candidate_id"],
                CandidateStage.job_id == world["job_id"],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    assert stage is not None
    return stage


async def _bells(user_id: int, job_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.link == f"/jobs/{job_id}",
                        Notification.notification_type
                        == NotificationType.screening_cards_returned,
                    )
                )
            ).all()
        )


async def _note(world: dict, author: int | None, at: datetime, **kw) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Note(
                content="Rozmowa jutro",
                candidate_id=world["candidate_id"],
                author_id=author,
                created_at=at,
                **kw,
            )
        )
        await db.commit()


async def test_silent_screening_card_returns_to_new_for_everyone() -> None:
    rec = await _user()
    other = await _user("Kolega")
    world = await _world()
    try:
        await _in_screening(world, rec)
        # Środa wieczór: jeszcze nie.
        early = await _sweep(world, WEDNESDAY_EVENING)
        assert early.returned == 0
        assert (await _latest_stage(world)).stage == PipelineStage.screening

        result = await _sweep(world, THURSDAY_MORNING)
        assert result.returned == 1
        latest = await _latest_stage(world)
        assert latest.stage == PipelineStage.new
        assert latest.stage_def_id == world["defs"]["new"]
        assert latest.moved_by is None
        async with AsyncSessionLocal() as db:
            process = await _process(db, world)
            assert process.claimed_by_user_id is None
            assert process.claimed_until is None
            # Każdy z zespołu może ją teraz wziąć.
            other_user = await db.get(User, other)
            assert candidate_claim.can_take(
                process, other_user, datetime.now(timezone.utc)
            )
            acts = (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "pipeline",
                        Activity.entity_id == latest.id,
                    )
                )
            ).all()
            assert {"stage_changed", svc.ACTION_RETURNED} <= set(acts)
        (bell,) = await _bells(rec, world["job_id"])
        assert bell.title == "Wróciło do „Nowych”: 1 osoba"
        assert bell.related_entity_type == "user" and bell.related_entity_id == rec
        assert "bierze je każdy" in bell.message
        assert await _bells(other, world["job_id"]) == []
        # Drugi przebieg nic nie powtarza.
        again = await _sweep(world, THURSDAY_MORNING + timedelta(minutes=15))
        assert again.returned == 0 and again.released == 0
    finally:
        await _cleanup(world)


async def test_trace_in_the_last_hour_keeps_the_card() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec, at=MONDAY - timedelta(days=7))
        # Notatka godzinę przed przebiegiem (także „Nie odebrał” to notatka).
        await _note(
            world, rec, THURSDAY_MORNING - timedelta(hours=1), job_id=world["job_id"]
        )
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.returned == 0
        assert (await _latest_stage(world)).stage == PipelineStage.screening
    finally:
        await _cleanup(world)


async def test_note_from_another_recruitment_is_not_a_trace() -> None:
    rec = await _user()
    world = await _world()
    other = await _world()
    try:
        await _in_screening(world, rec)
        await _note(world, rec, WEDNESDAY_EVENING, job_id=other["job_id"])
        # Notatka bez autora (automat) też nie.
        await _note(world, None, WEDNESDAY_EVENING)
        assert (await _sweep(world, THURSDAY_MORNING)).returned == 1
    finally:
        await _cleanup(world)
        await _cleanup(other)


async def test_contact_attempt_without_job_moves_the_return() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        await _note(world, rec, MONDAY + timedelta(days=1), kind="contact_attempt")
        assert (await _sweep(world, THURSDAY_MORNING)).returned == 0
        friday = THURSDAY_MORNING + timedelta(days=1)
        assert (await _sweep(world, friday)).returned == 1
    finally:
        await _cleanup(world)


async def test_weekend_and_sweep_on_saturday() -> None:
    rec = await _user()
    world = await _world()
    try:
        thursday = datetime(2026, 11, 19, 15, tzinfo=WAW)
        await _in_screening(world, rec, at=thursday)
        # Sobota: przebieg w dzień wolny nic nie robi.
        assert (await _sweep(world, SATURDAY)).returned == 0
        monday = datetime(2026, 11, 23, 9, tzinfo=WAW)
        assert (await _sweep(world, monday)).returned == 0
        tuesday = datetime(2026, 11, 24, 0, 30, tzinfo=WAW)
        assert (await _sweep(world, tuesday)).returned == 1
    finally:
        await _cleanup(world)


async def test_booked_call_in_the_future_holds_the_card() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec, at=MONDAY - timedelta(days=14))
        async with AsyncSessionLocal() as db:
            db.add(
                CalendarEvent(
                    title="Telefon: Ola C.",
                    event_type=EventType.screening,
                    location=BOOKED_CALL_LOCATION,
                    start_time=datetime(2026, 11, 20, 9, tzinfo=WAW),
                    end_time=datetime(2026, 11, 20, 9, 15, tzinfo=WAW),
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    operational_owner_id=rec,
                    created_by=rec,
                    status=EventStatus.scheduled,
                    created_at=MONDAY - timedelta(days=13),
                )
            )
            await db.commit()
        assert (await _sweep(world, THURSDAY_MORNING)).returned == 0
        # Telefon w piątek 9:00 bez wyniku: od piątku dwa pełne dni robocze ciszy.
        assert (
            await _sweep(world, datetime(2026, 11, 24, 12, tzinfo=WAW))
        ).returned == 0
        assert (
            await _sweep(world, datetime(2026, 11, 25, 0, 30, tzinfo=WAW))
        ).returned == 1
    finally:
        await _cleanup(world)


async def test_closed_recruitment_is_left_alone() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, world["job_id"])
            job.status = JobStatus.closed
            await db.commit()
        assert (await _sweep(world, THURSDAY_MORNING)).returned == 0
        assert (await _latest_stage(world)).stage == PipelineStage.screening
    finally:
        await _cleanup(world)


async def test_bell_goes_to_who_holds_the_card_not_who_moved_it() -> None:
    mover = await _user("Przesunął")
    holder = await _user("Przejął")
    world = await _world()
    try:
        stage_id = await _in_screening(world, mover)
        # Ktoś inny przejął kartę w Screeningu — to też ślad (poniedziałek 12:00).
        await _claim(world, holder, stage_id, MONDAY + timedelta(hours=2))
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.returned == 1
        assert len(await _bells(holder, world["job_id"])) == 1
        assert await _bells(mover, world["job_id"]) == []
    finally:
        await _cleanup(world)


async def test_claim_in_new_without_trace_is_released() -> None:
    adder = await _user("Dodał")
    taker = await _user("Bierze")
    world = await _world()
    try:
        stage_id = await _move(
            world,
            "new",
            actor=adder,
            at=MONDAY - timedelta(hours=2),
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            claim_for=adder,
        )
        await _claim(world, taker, stage_id, MONDAY)
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.released == 1 and result.returned == 0
        latest = await _latest_stage(world)
        assert latest.id == stage_id  # karta nie rusza się z „Nowych”
        async with AsyncSessionLocal() as db:
            process = await _process(db, world)
            assert process.claimed_by_user_id is None
        assert len(await _bells(taker, world["job_id"])) == 1
        assert await _bells(adder, world["job_id"]) == []
    finally:
        await _cleanup(world)


async def test_handed_over_card_in_new_without_trace_is_released() -> None:
    """Oddanie (25.11.2026) to „Biorę” osoby, która dostała kartę: bez śladu
    przez 2 dni robocze karta wraca dla wszystkich, jak po zwykłym „Biorę”."""
    adder = await _user("Dodał")
    taker = await _user("Bierze")
    receiver = await _user("Dostała")
    world = await _world()
    try:
        stage_id = await _move(
            world,
            "new",
            actor=adder,
            at=MONDAY - timedelta(hours=2),
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            claim_for=adder,
        )
        await _claim(world, taker, stage_id, MONDAY - timedelta(hours=1))
        async with AsyncSessionLocal() as db:
            process = await _process(db, world)
            candidate_claim.set_claim(process, receiver, MONDAY)
            db.add(
                Activity(
                    entity_type="pipeline",
                    entity_id=stage_id,
                    action="candidate_claim_handed_over",
                    user_id=taker,
                    details={
                        "candidate_id": world["candidate_id"],
                        "job_id": world["job_id"],
                        "from_user_id": taker,
                        "to_user_id": receiver,
                    },
                    created_at=MONDAY,
                )
            )
            await db.commit()
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.released == 1
        assert len(await _bells(receiver, world["job_id"])) == 1
        assert await _bells(taker, world["job_id"]) == []
    finally:
        await _cleanup(world)


async def test_manual_add_in_new_stays_with_the_adder() -> None:
    adder = await _user("Dodał")
    world = await _world()
    try:
        await _move(
            world,
            "new",
            actor=adder,
            at=MONDAY - timedelta(days=10),
            entry_source=candidate_claim.ENTRY_ADDED_MANUAL,
            claim_for=adder,
        )
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.released == 0
        async with AsyncSessionLocal() as db:
            assert (await _process(db, world)).claimed_by_user_id == adder
    finally:
        await _cleanup(world)


async def test_system_card_after_return_leaves_the_portion_and_the_debt() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _move(
            world,
            "new",
            actor=None,
            at=MONDAY - timedelta(hours=3),
            entry_source=candidate_claim.ENTRY_SYSTEM,
            entry_meta={"kind": "autofill", "score": 88, "review_owner_id": rec},
        )
        await _move(world, "screening", actor=rec, at=MONDAY)
        thursday_utc = THURSDAY_MORNING.astimezone(timezone.utc)
        async with AsyncSessionLocal() as db:
            before = await review_batch._decisions(
                db, [rec], now=thursday_utc, since=MONDAY - timedelta(days=1)
            )
        assert [d.candidate_id for d in before[rec]] == [world["candidate_id"]]

        assert (await _sweep(world, THURSDAY_MORNING)).returned == 1
        async with AsyncSessionLocal() as db:
            process = await _process(db, world)
            meta = process.entry_meta
            assert svc.META_RETURNED_AT in meta and "review_owner_id" not in meta
            (card,) = [
                c
                for c in await review_batch.pending_cards(db, job_ids=[world["job_id"]])
                if c.candidate_id == world["candidate_id"]
            ]
            assert card.returned and card.owner_id is None
            assert not review_batch.in_batch(card, thursday_utc)
            after = await review_batch._decisions(
                db, [rec], now=thursday_utc, since=MONDAY - timedelta(days=1)
            )
        assert after[rec] == []

        # Inny rekruter bierze kartę do Screeningu — dawna decyzja nie wraca.
        other = await _user("Drugi")
        await _move(
            world, "screening", actor=other, at=thursday_utc + timedelta(hours=8)
        )
        async with AsyncSessionLocal() as db:
            again = await review_batch._decisions(
                db,
                [rec],
                now=thursday_utc + timedelta(hours=9),
                since=MONDAY - timedelta(days=1),
            )
        assert again[rec] == []
    finally:
        await _cleanup(world)


async def test_board_says_when_the_card_returns() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        async with AsyncSessionLocal() as db:
            days = await svc.return_days_for_jobs(db, [world["job_id"]])
        assert days[world["job_id"]][world["candidate_id"]].isoformat() == "2026-11-19"
    finally:
        await _cleanup(world)


async def _returned_bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.screening_cards_returned,
                    )
                )
            ).all()
        )


async def test_one_bell_a_day_lists_cards_from_every_run() -> None:
    """26.11.2026: przebiegi po 200 kart dawały osobne dzwonki, a dzienny dedup
    puszczał tylko pierwszy. Teraz drugi przebieg dopisuje karty do tego samego
    dzwonka i zostawia go nieprzeczytanym."""
    rec = await _user()
    first, second = await _world(), await _world()
    try:
        await _in_screening(first, rec)
        await _in_screening(second, rec)
        await _sweep(first, THURSDAY_MORNING)
        (bell,) = await _returned_bells(rec)
        assert bell.title == "Wróciło do „Nowych”: 1 osoba"
        first_at = bell.created_at
        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, bell.id)
            row.is_read = True
            await db.commit()

        await _sweep(second, THURSDAY_MORNING + timedelta(minutes=15))
        (bell,) = await _returned_bells(rec)
        assert bell.title == "Wróciło do „Nowych”: 2 osoby"
        assert bell.is_read is False
        assert bell.created_at >= first_at
        async with AsyncSessionLocal() as db:
            for world in (first, second):
                cand = await db.get(Candidate, world["candidate_id"])
                assert cand.lastname in bell.message
    finally:
        await _cleanup(first)
        await _cleanup(second)


async def test_claim_taken_bell_the_same_day_does_not_block_the_return_bell() -> None:
    from app.services.notification_triggers import emit

    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        async with AsyncSessionLocal() as db:
            await emit(
                db,
                user_id=rec,
                title="Ktoś przejął osobę",
                message="…",
                ntype=NotificationType.candidate_claim_taken,
                related_entity_type="job",
                related_entity_id=world["job_id"],
            )
            await db.commit()
        await _sweep(world, THURSDAY_MORNING)
        assert len(await _returned_bells(rec)) == 1
    finally:
        await _cleanup(world)


async def _soon_bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.screening_cards_return_soon,
                    )
                )
            ).all()
        )


async def test_morning_warning_the_day_before_the_return() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)  # ślad w poniedziałek → wraca w czwartek
        wednesday = datetime(2026, 11, 18, 9, tzinfo=WAW).astimezone(timezone.utc)
        tuesday = datetime(2026, 11, 17, 9, tzinfo=WAW).astimezone(timezone.utc)
        async with AsyncSessionLocal() as db:
            assert (
                await svc.send_soon_bells(db, now=tuesday, job_ids=[world["job_id"]])
                == 0
            )
            sent = await svc.send_soon_bells(
                db, now=wednesday, job_ids=[world["job_id"]]
            )
            await db.commit()
        assert sent == 1
        (bell,) = await _soon_bells(rec)
        assert bell.title == "Jutro wrócą do „Nowych”: 1 osoba"
        assert bell.link == f"/jobs/{world['job_id']}"
        assert "Nie odebrał" in bell.message
    finally:
        await _cleanup(world)


async def test_friday_warning_names_monday_and_weekend_sends_nothing() -> None:
    rec = await _user()
    world = await _world()
    try:
        # Ślad w środę 18.11 → wraca w poniedziałek 23.11.
        await _in_screening(world, rec, at=datetime(2026, 11, 18, 10, tzinfo=WAW))
        friday = datetime(2026, 11, 20, 9, tzinfo=WAW).astimezone(timezone.utc)
        saturday = SATURDAY.astimezone(timezone.utc)
        async with AsyncSessionLocal() as db:
            assert (
                await svc.send_soon_bells(db, now=saturday, job_ids=[world["job_id"]])
                == 0
            )
            await svc.send_soon_bells(db, now=friday, job_ids=[world["job_id"]])
            await db.commit()
        (bell,) = await _soon_bells(rec)
        assert bell.title == "W poniedziałek wrócą do „Nowych”: 1 osoba"
    finally:
        await _cleanup(world)


async def test_substitute_gets_one_updated_bell_for_the_absent_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Przegląd 26.11: przy zastępstwie `emit` zapisuje wiersz na zastępcę,
    więc dzisiejszy dzwonek trzeba szukać po osobie, której dotyczy
    (`related_entity`), a nie po odbiorcy — inaczej drugi przebieg nic nie
    dopisuje (dedup dzienny)."""
    from app.services import notification_triggers
    from app.services.notification_substitution import Route

    rec = await _user()
    sub = await _user("Zastępca")

    async def route(db, user_id, ntype):  # noqa: ANN001, ANN202
        return Route(sub, on_behalf_of=user_id) if user_id == rec else Route(user_id)

    monkeypatch.setattr(notification_triggers, "notification_route", route)
    first, second = await _world(), await _world()
    try:
        await _in_screening(first, rec)
        await _in_screening(second, rec)
        await _sweep(first, THURSDAY_MORNING)
        await _sweep(second, THURSDAY_MORNING + timedelta(minutes=15))
        assert await _returned_bells(rec) == []
        (bell,) = await _returned_bells(sub)
        assert bell.related_entity_id == rec
        assert bell.title == "Wróciło do „Nowych”: 2 osoby"
    finally:
        await _cleanup(first)
        await _cleanup(second)


async def test_second_warning_the_same_day_leaves_the_morning_bell_alone() -> None:
    """Przegląd 26.11: wdrożenie po 18:00 restartuje pętlę; ostrzeżenie nie
    może wtedy wrócić jako nieprzeczytane z inną liczbą."""
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        morning = datetime(2026, 11, 18, 9, tzinfo=WAW).astimezone(timezone.utc)
        evening = datetime(2026, 11, 18, 18, 30, tzinfo=WAW).astimezone(timezone.utc)
        async with AsyncSessionLocal() as db:
            assert (
                await svc.send_soon_bells(db, now=morning, job_ids=[world["job_id"]])
                == 1
            )
            await db.commit()
        (bell,) = await _soon_bells(rec)
        async with AsyncSessionLocal() as db:
            row = await db.get(Notification, bell.id)
            row.is_read = True
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (
                await svc.send_soon_bells(db, now=evening, job_ids=[world["job_id"]])
                == 0
            )
            await db.commit()
        (bell,) = await _soon_bells(rec)
        assert bell.is_read is True
    finally:
        await _cleanup(world)


async def test_returned_card_stays_visible_to_the_holder_until_someone_moves_it() -> (
    None
):
    """26.11.2026: grupa „Wróciły od Ciebie” — kto trzymał kartę, od kiedy
    stała w „Screeningu”; po ponownym ruchu karta znika z grupy."""
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        await _sweep(world, THURSDAY_MORNING)
        async with AsyncSessionLocal() as db:
            cards = await svc.returned_cards_for_jobs(db, [world["job_id"]])
        card = cards[world["job_id"]][world["candidate_id"]]
        assert card.holder_id == rec
        assert card.screening_since == MONDAY.astimezone(timezone.utc)

        # Ktoś bierze ją z powrotem do „Screeningu” — już nie „wróciła”.
        await _move(world, "screening", actor=rec, at=datetime.now(timezone.utc))
        async with AsyncSessionLocal() as db:
            cards = await svc.returned_cards_for_jobs(db, [world["job_id"]])
        assert cards[world["job_id"]] == {}
    finally:
        await _cleanup(world)


async def test_returned_card_leaves_the_group_after_five_workdays() -> None:
    rec = await _user()
    world = await _world()
    try:
        await _in_screening(world, rec)
        await _sweep(world, THURSDAY_MORNING)
        # Wpis powrotu ma czas zapisu; trzy tygodnie później okno już minęło.
        later = datetime.now(timezone.utc) + timedelta(days=21)
        async with AsyncSessionLocal() as db:
            cards = await svc.returned_cards_for_jobs(db, [world["job_id"]], now=later)
        assert cards[world["job_id"]] == {}
    finally:
        await _cleanup(world)


async def test_expired_claim_in_new_is_not_a_return_from_screening() -> None:
    rec = await _user()
    world = await _world()
    try:
        stage_id = await _move(
            world,
            "new",
            actor=rec,
            at=MONDAY - timedelta(hours=1),
            entry_source=candidate_claim.ENTRY_SYSTEM,
        )
        await _claim(world, rec, stage_id, MONDAY)
        result = await _sweep(world, THURSDAY_MORNING)
        assert result.released == 1
        async with AsyncSessionLocal() as db:
            cards = await svc.returned_cards_for_jobs(db, [world["job_id"]])
        assert cards[world["job_id"]] == {}
    finally:
        await _cleanup(world)
