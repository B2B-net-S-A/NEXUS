"""Awarie automatów rekrutacji (decyzja właściciela, 21.09.2026).

- rekruter NIE dostaje powiadomienia o awarii — jest wpis (z polskim powodem)
  w „Pracy w tle" rekrutacji;
- TEN SAM automat 3 razy z rzędu (globalnie, licznik w ``app_settings``) =
  JEDNO powiadomienie na serię, wyłącznie dla adminów; pierwszy sukces zeruje
  licznik i odblokowuje następny alarm; serie różnych automatów się nie mieszają;
- księgowanie awarii nigdy nie rzuca.

Licznik jest globalny, a baza testowa wspólna: każdy test zaczyna od
wyzerowania własnego automatu i czyści po sobie dzwonki.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate_search_run import CandidateSearchRun
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import automation_failures as failures
from tests.test_job_proposals import _user, _world


async def _person(role: UserRole) -> int:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"streak-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Streak"),
            name=f"Streak {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def _alerts(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.automation_failing,
                    )
                )
            ).all()
        )


async def _state(kind: str) -> dict:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, failures.SETTING_KEY)
        return dict((row.value or {}).get(kind) or {}) if row else {}


async def _reset(kind: str) -> None:
    failures._known_clean.discard(kind)
    await failures.record_success(kind)
    async with AsyncSessionLocal() as db:
        # Dobowy dedup patrzy na (odbiorca, typ, encja): stare dzwonki z tego
        # samego dnia zdusiłyby alarm, który ten test ma zobaczyć.
        await db.execute(
            delete(Notification).where(
                Notification.notification_type == NotificationType.automation_failing
            )
        )
        await db.commit()


@pytest.fixture
async def clean_streaks():
    for kind in failures.KINDS:
        await _reset(kind)
    yield
    for kind in failures.KINDS:
        await _reset(kind)


async def test_third_consecutive_failure_alerts_admins_once(clean_streaks):
    admin_id = await _person(UserRole.admin)
    recruiter_id = await _person(UserRole.recruiter)
    kind = failures.KIND_FULL_REVIEW

    await failures.record_failure(kind, "TimeoutError", job_id=None)
    await failures.record_failure(kind, "TimeoutError", job_id=None)
    assert await _alerts(admin_id) == []
    assert (await _state(kind))["count"] == 2

    await failures.record_failure(kind, "ValueError", job_id=None)
    [alert] = await _alerts(admin_id)
    assert "Nocny przegląd bazy" in alert.title
    assert "ValueError" in alert.message and "3 nieudane" in alert.message
    assert alert.link == "/settings"
    # Rekruter nie dostaje NIC.
    assert await _alerts(recruiter_id) == []

    # Czwarta i piąta porażka tej samej serii nie dzwonią ponownie.
    await failures.record_failure(kind, "ValueError")
    await failures.record_failure(kind, "ValueError")
    assert len(await _alerts(admin_id)) == 1
    state = await _state(kind)
    assert state["count"] == 5 and state["notified"] is True
    assert state["last_error"] == "ValueError"


async def test_success_resets_the_streak_and_rearms_the_alert(clean_streaks):
    kind = failures.KIND_AUTO_CV
    await failures.record_failure(kind, "RuntimeError")
    await failures.record_failure(kind, "RuntimeError")
    await failures.record_success(kind)
    assert (await _state(kind))["count"] == 0
    # Dwie kolejne porażki to NOWA seria — do progu brakuje jednej.
    admin_id = await _person(UserRole.admin)
    await failures.record_failure(kind, "RuntimeError")
    await failures.record_failure(kind, "RuntimeError")
    assert await _alerts(admin_id) == []
    await failures.record_failure(kind, "RuntimeError", job_id=123)
    [alert] = await _alerts(admin_id)
    assert alert.link == "/jobs/123"
    # Sukces po alarmie odblokowuje następny.
    await failures.record_success(kind)
    state = await _state(kind)
    assert state["count"] == 0 and state["notified"] is False


async def test_streaks_are_per_automation_kind(clean_streaks):
    admin_id = await _person(UserRole.admin)
    await failures.record_failure(failures.KIND_FULL_REVIEW, "A")
    await failures.record_failure(failures.KIND_NEW_CV, "B")
    await failures.record_failure(failures.KIND_AUTO_CV, "C")
    # Trzy porażki, ale trzech RÓŻNYCH automatów — nikt nie padł 3 razy z rzędu.
    assert await _alerts(admin_id) == []
    # Sukces jednego nie zeruje pozostałych.
    await failures.record_success(failures.KIND_NEW_CV)
    assert (await _state(failures.KIND_FULL_REVIEW))["count"] == 1


async def test_success_without_an_open_streak_skips_the_database(monkeypatch):
    kind = failures.KIND_NEW_CV
    await _reset(kind)
    assert kind in failures._known_clean

    async def _boom(*args, **kwargs):
        raise AssertionError("sukces bez otwartej serii nie dotyka bazy")

    monkeypatch.setattr(failures, "_update", _boom)
    await failures.record_success(kind)  # auto-match woła to przy każdym CV


async def test_bookkeeping_never_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(failures, "_update", _boom)
    failures._known_clean.discard(failures.KIND_AUTO_CV)
    await failures.record_failure(failures.KIND_AUTO_CV, "X")
    await failures.record_success(failures.KIND_AUTO_CV)
    await failures.record_failure("unknown-kind", "X")


def test_polish_reasons():
    assert failures.reason_pl("stalled").startswith("Przegląd stanął")
    assert failures.reason_pl("KeyError") == "Błąd wewnętrzny (KeyError)."
    assert failures.reason_pl(None) == "Błąd wewnętrzny."
    assert failures.failure_details("stalled", run_id="r")["run_id"] == "r"


def test_alert_type_is_admin_only():
    from app.services import notification_access as na

    assert NotificationType.automation_failing in na.ADMIN_ONLY_NOTIFICATION_TYPES


async def test_failed_auto_review_is_a_feed_entry_not_a_bell(
    app_client: AsyncClient, monkeypatch
):
    from app.services.candidate_search_worker import _notify_search_finished

    streak: list[tuple] = []

    async def _streak(kind, code, *, job_id=None):
        streak.append((kind, code, job_id))

    monkeypatch.setattr(failures, "record_failure", _streak)
    owner_id, headers = await _user(UserRole.recruiter)
    world = await _world(people=0, recruiter_id=owner_id)
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSearchRun(
                id=run_id,
                created_by=owner_id,
                client_id=world["client_id"],
                job_id=world["job_id"],
                state="failed",
                error_code="stalled",
                request_fingerprint="f" * 64,
                request_context={},
                version_trace={"origin": "auto"},
                population_size=0,
                metrics={},
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        await _notify_search_finished(db, run_id, eligible=None, failed=True)
        await db.commit()
        assert (
            await db.scalar(
                select(Notification.id).where(Notification.user_id == owner_id)
            )
        ) is None
        [event] = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job_automation",
                    Activity.entity_id == world["job_id"],
                )
            )
        ).all()
        assert event.action == "auto_full_review_failed"
    assert streak == [(failures.KIND_FULL_REVIEW, "stalled", world["job_id"])]

    feed = await app_client.get(
        f"/api/jobs/{world['job_id']}/background-events", headers=headers
    )
    assert feed.status_code == 200, feed.text
    [item] = feed.json()["items"]
    assert item["kind"] == "auto_full_review_failed"
    assert item["reason"] == "stalled"
    assert item["message"].startswith("Przegląd stanął")


async def test_dead_auto_match_event_counts_and_lands_in_the_feed(monkeypatch):
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.tasks import candidate_auto_match as worker

    streak: list[tuple] = []

    async def _streak(kind, code, *, job_id=None):
        streak.append((kind, code, job_id))

    monkeypatch.setattr(failures, "record_failure", _streak)
    world = await _world(people=0)
    async with AsyncSessionLocal() as db:
        event = CandidateMatchOutbox(
            job_id=world["job_id"], trigger="job_publish", status="dead"
        )
        db.add(event)
        await db.commit()
        event_id = event.id
    await worker._record_dead_event(event_id, "ValueError")
    assert streak == [(failures.KIND_NEW_CV, "ValueError", world["job_id"])]
    async with AsyncSessionLocal() as db:
        [entry] = (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "job_automation",
                    Activity.entity_id == world["job_id"],
                )
            )
        ).all()
        assert entry.action == "auto_match_failed"
        assert entry.details["message"] == "Błąd wewnętrzny (ValueError)."
