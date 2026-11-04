"""Przypomnienie osobie od Cpro o kolejce Cpro prowadzonej w Traffit (08.10.2026).

Zgłoszenie: osoba od Cpro nie dostała ani jednego powiadomienia, bo karty
Nordei wchodzą do kolejki Cpro w Traffit, a import nikogo nie powiadamiał.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import cpro_queue_reminder as reminder
from app.services import cpro_sender
from app.services.notification_delivery import immediate_email_kind
from app.tasks import traffit_sync
from tests.test_board_tasks import (
    _cleanup,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
)

# ── Jednostkowe: treść przypomnienia ─────────────────────────────────────────


def _card(n: int, *, since: datetime) -> reminder.WaitingCard:
    return reminder.WaitingCard(
        stage_id=100 + n,
        candidate_id=10 + n,
        job_id=7,
        candidate_name=f"Jan Testowy{n}",
        job_title="Java · Spring",
        waiting_since=since,
    )


def test_one_waiting_card_is_named_in_the_title_and_opens_its_board_card() -> None:
    since = datetime(2026, 10, 7, 14, 5, tzinfo=timezone.utc)
    title, message, link = reminder.build_notice(
        [_card(1, since=since)], tz="Europe/Warsaw"
    )
    assert title == "Do wrzucenia do Cpro: Jan Testowy1"
    # Godzina w czasie firmy, nie w UTC.
    assert "Jan Testowy1 — „Java · Spring” (od 07.10, 16:05)" in message
    assert link == "/jobs/7?candidate=11"


def test_several_cards_are_counted_and_the_list_is_capped() -> None:
    since = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    cards = [_card(n, since=since) for n in range(1, reminder.MAX_LISTED + 4)]
    title, message, link = reminder.build_notice(cards, tz="Europe/Warsaw")
    assert title == f"Do wrzucenia do Cpro: {len(cards)} kandydatów"
    assert f"czeka {len(cards)} kandydatów" in message
    assert f"Jan Testowy{reminder.MAX_LISTED}" in message
    assert f"Jan Testowy{reminder.MAX_LISTED + 1} " not in message
    assert "oraz 3 kolejnych" in message
    # Link otwiera kartę, która czeka najdłużej (pierwszą na liście).
    assert link == "/jobs/7?candidate=11"


def test_long_traffit_job_titles_are_cut_in_the_bell() -> None:
    card = reminder.WaitingCard(
        stage_id=1,
        candidate_id=2,
        job_id=3,
        candidate_name="Jan Testowy",
        job_title="Senior Java Developer " * 6,
        waiting_since=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc),
    )
    _, message, _ = reminder.build_notice([card], tz="Europe/Warsaw")
    quoted = message.split("„")[1].split("”")[0]
    assert len(quoted) == reminder.MAX_JOB_TITLE
    assert quoted.endswith("…")


def test_the_reminder_bell_goes_out_by_mail_right_away() -> None:
    title, _, _ = reminder.build_notice(
        [_card(1, since=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc))],
        tz="Europe/Warsaw",
    )
    assert (
        immediate_email_kind(
            NotificationType.board_task_waiting,
            title=title,
            related_entity_type="user",
        )
        == "dl_review"
    )


# ── Faza importu: przypomnienie po ruchach, nigdy kosztem fazy ───────────────


@pytest.mark.asyncio
async def test_pipelines_phase_reminds_after_the_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    async def _import_pipelines(since=None):
        order.append("import")
        return "progress"

    async def _remind(db, *, now=None) -> int:
        order.append("remind")
        return 2

    monkeypatch.setattr(reminder, "remind", _remind)
    importer = SimpleNamespace(import_pipelines=_import_pipelines)
    assert await traffit_sync._pipelines_phase(importer, None) == "progress"
    assert order == ["import", "remind"]


@pytest.mark.asyncio
async def test_a_failing_reminder_does_not_fail_the_pipelines_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _import_pipelines(since=None):
        return "progress"

    async def _boom(db, *, now=None) -> int:
        raise RuntimeError("smtp down")

    monkeypatch.setattr(reminder, "remind", _boom)
    importer = SimpleNamespace(import_pipelines=_import_pipelines)
    assert await traffit_sync._pipelines_phase(importer, None) == "progress"


@pytest.mark.asyncio
async def test_a_crashed_import_sends_no_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def _import_pipelines(since=None):
        raise RuntimeError("traffit 500")

    async def _remind(db, *, now=None) -> int:
        called.append("remind")
        return 0

    monkeypatch.setattr(reminder, "remind", _remind)
    importer = SimpleNamespace(import_pipelines=_import_pipelines)
    with pytest.raises(RuntimeError):
        await traffit_sync._pipelines_phase(importer, None)
    assert called == []


# ── Integracyjne: stan kolejki z zaimportowanych wierszy ─────────────────────


async def _seed_candidate(tag: str) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=tag, lastname=f"CQ{unique}", email=f"cq-{unique}@example.com"
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _stage(
    candidate_id: int,
    world: dict,
    key: str,
    *,
    ago: timedelta,
    source: str | None = reminder.TRAFFIT_SOURCE,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=world["job_id"],
                stage="cv_sent" if key == "cv_sent" else "screening",
                stage_def_id=world["defs"][key],
                moved_at=datetime.now(timezone.utc) - ago,
                external_source=source,
                external_id=uuid.uuid4().hex if source else None,
            )
        )
        await db.commit()


async def _set_sender(sender_id: int, actor_id: int) -> None:
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, actor_id)
        await cpro_sender.set_sender(db, user_id=sender_id, until=None, actor=actor)
        await db.commit()


async def _remind() -> int:
    async with AsyncSessionLocal() as db:
        listed = await reminder.remind(db)
        await db.commit()
        return listed


async def _bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.board_task_waiting,
                Notification.related_entity_type == "user",
            )
            .order_by(Notification.id)
        )
        return list(rows.all())


async def _lastname(candidate_id: int) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.get(Candidate, candidate_id)).lastname


async def _drop_candidates(candidate_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(candidate_ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_sender_gets_one_bell_listing_only_cards_still_in_the_traffit_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    monkeypatch.setattr(reminder, "is_business_day", lambda *_a, **_k: True)
    admin_id, _ = await _seed_user(UserRole.admin)
    sender_id, _ = await _seed_user(UserRole.recruiter)
    waiting = world["candidate_id"]
    sent = await _seed_candidate("Wyslany")
    in_nexus = await _seed_candidate("WNexusie")
    stale = await _seed_candidate("Dawny")
    try:
        async with restore_cpro_sender():
            await _set_sender(sender_id, admin_id)
            await _stage(waiting, world, "cpro", ago=timedelta(hours=14))
            # Wysłany tego samego dnia — późniejszy wiersz zdejmuje go z kolejki.
            await _stage(sent, world, "cpro", ago=timedelta(hours=20))
            await _stage(sent, world, "cv_sent", ago=timedelta(hours=19))
            # Ruch w NEXUSIE ma własny dzwonek przy przesunięciu karty.
            await _stage(in_nexus, world, "cpro", ago=timedelta(hours=3), source=None)
            await _stage(
                stale,
                world,
                "cpro",
                ago=timedelta(days=settings.TRAFFIT_CPRO_REMINDER_WINDOW_DAYS + 2),
            )

            assert await _remind() == 1
            bells = await _bells(sender_id)
            assert len(bells) == 1
            assert (
                bells[0].title
                == f"Do wrzucenia do Cpro: Ewa {await _lastname(waiting)}"
            )
            assert bells[0].link == f"/jobs/{world['job_id']}?candidate={waiting}"
            for other in (sent, in_nexus, stale):
                assert await _lastname(other) not in bells[0].message

            # Drugi import tego samego dnia nie dokłada drugiego dzwonka.
            assert await _remind() == 0
            assert len(await _bells(sender_id)) == 1
    finally:
        await _drop_candidates([sent, in_nexus, stale])
        await _cleanup(world, [admin_id, sender_id])


@pytest.mark.asyncio
async def test_no_reminder_on_a_day_off_without_a_sender_or_when_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    admin_id, _ = await _seed_user(UserRole.admin)
    sender_id, _ = await _seed_user(UserRole.recruiter)
    try:
        async with restore_cpro_sender():
            await _stage(world["candidate_id"], world, "cpro", ago=timedelta(hours=5))

            await _set_sender(sender_id, admin_id)
            monkeypatch.setattr(reminder, "is_business_day", lambda *_a, **_k: False)
            assert await _remind() == 0

            monkeypatch.setattr(reminder, "is_business_day", lambda *_a, **_k: True)
            monkeypatch.setattr(settings, "TRAFFIT_CPRO_REMINDER_ENABLED", False)
            assert await _remind() == 0

            monkeypatch.setattr(settings, "TRAFFIT_CPRO_REMINDER_ENABLED", True)
            await clear_cpro_sender()
            assert await _remind() == 0
            assert await _bells(sender_id) == []
    finally:
        await _cleanup(world, [admin_id, sender_id])


@pytest.mark.asyncio
async def test_clients_without_a_cpro_queue_are_not_reminded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    monkeypatch.setattr(reminder, "is_business_day", lambda *_a, **_k: True)
    admin_id, _ = await _seed_user(UserRole.admin)
    sender_id, _ = await _seed_user(UserRole.recruiter)
    try:
        async with restore_cpro_sender():
            await _set_sender(sender_id, admin_id)
            await _stage(world["candidate_id"], world, "cpro", ago=timedelta(hours=5))
            async with AsyncSessionLocal() as db:
                cards = await reminder.waiting_cards(db, now=datetime.now(timezone.utc))
            assert [c for c in cards if c.job_id == world["job_id"]] == []
    finally:
        await _cleanup(world, [admin_id, sender_id])
