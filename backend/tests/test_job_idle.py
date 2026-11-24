"""Rekrutacje bez ruchu: 14 dni → DL, 21 → także HoR, 28 → NEXUS zamyka (28.10.2026).

Czyste reguły bez bazy (licznik, etapy, treść dzwonka, powód tylko dla
automatu) i przebieg z bazą: znaczniki etapów, zamknięcie dopiero po
ostrzeżeniu Head of Recruitment, „Jeszcze trwa” liczy od nowa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.models.job import JobCloseReason
from app.services import job_idle
from app.services.hit_ratio_scope import close_reason_group
from app.services.job_close_choice import validate_close_choice
from app.services.job_idle import IdleFacts, idle_state, notice_text, stage_for

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
START = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def _facts(**kw) -> IdleFacts:
    base = dict(
        job_id=1,
        opened_at=None,
        last_move_at=None,
        last_move_kind=None,
        snoozed_at=None,
    )
    base.update(kw)
    return IdleFacts(**base)


# ── Bez bazy ──────────────────────────────────────────────────────────────


def test_stages_at_14_21_28_days() -> None:
    assert [stage_for(d) for d in (0, 13, 14, 20, 21, 27, 28, 99)] == [
        None,
        None,
        "remind",
        "remind",
        "hor",
        "hor",
        "close",
        "close",
    ]


def test_backlog_is_reminded_on_the_first_day_of_the_rule() -> None:
    """Rekrutacja otwarta pół roku temu nie zamyka się w dniu włączenia."""
    old = _facts(opened_at=START - timedelta(days=180))
    state = idle_state(old, started_at=START, now=START)
    assert (state.days, state.stage) == (14, "remind")
    # Ludzie widzą prawdziwą ciszę, nie dzień cyklu.
    assert state.quiet_days == 180
    # Zaległe mają 28 dni (decyzja Artura 29.10.2026): HoR po 21, zamknięcie po 28.
    assert state.hor_on.isoformat() == "2026-11-19"
    assert state.close_on.isoformat() == "2026-11-26"
    assert (
        idle_state(old, started_at=START, now=START + timedelta(days=20)).stage
        == "remind"
    )
    assert (
        idle_state(old, started_at=START, now=START + timedelta(days=21)).stage == "hor"
    )
    assert (
        idle_state(old, started_at=START, now=START + timedelta(days=28)).stage
        == "close"
    )


def test_new_silence_after_the_start_keeps_14_21_28() -> None:
    moved = START + timedelta(days=3)
    facts = _facts(last_move_at=moved, last_move_kind="cv")
    state = idle_state(facts, started_at=START, now=moved + timedelta(days=21))
    assert (state.days, state.stage) == (21, "hor")
    assert (state.close_on - state.hor_on).days == 7


def test_cv_to_the_client_restarts_the_count() -> None:
    state = idle_state(
        _facts(
            opened_at=START - timedelta(days=90),
            last_move_at=NOW - timedelta(days=3),
            last_move_kind="cv",
        ),
        started_at=START,
        now=NOW,
    )
    assert (state.days, state.stage) == (3, None)


def test_still_going_restarts_the_count() -> None:
    state = idle_state(
        _facts(
            opened_at=START - timedelta(days=90), snoozed_at=NOW - timedelta(days=1)
        ),
        started_at=START,
        now=NOW,
    )
    assert (state.days, state.stage) == (1, None)


def test_days_follow_the_company_calendar() -> None:
    """23:30 UTC 31.10 to już 01.11 w Warszawie — dzień liczy się od 01.11."""
    moved = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    state = idle_state(
        _facts(last_move_at=moved, last_move_kind="client"),
        started_at=moved - timedelta(days=60),
        now=datetime(2026, 11, 15, 7, 0, tzinfo=timezone.utc),
    )
    assert state.days == 14
    assert state.remind_on.isoformat() == "2026-11-15"


def test_no_activity_is_a_loss_in_hit_ratio() -> None:
    assert close_reason_group(JobCloseReason.no_activity) == "lost"
    assert close_reason_group("no_activity") == "lost"


@pytest.mark.asyncio
async def test_people_cannot_pick_the_system_reason() -> None:
    with pytest.raises(HTTPException) as err:
        await validate_close_choice(
            None,  # type: ignore[arg-type] — odmowa przed pierwszym zapytaniem
            object(),  # type: ignore[arg-type]
            reason=JobCloseReason.no_activity,
            notes=None,
            duplicate_of_job_id=None,
        )
    assert err.value.status_code == 422
    assert err.value.detail["code"] == "close_reason_system_only"


def _line(job_id: int, days: int, lead_id: int = 7) -> job_idle._Line:
    return job_idle._Line(
        job_id=job_id,
        title=f"Rekrutacja {job_id}",
        client="Klient",
        lead_id=lead_id,
        days=days,
        detail="ostatnie CV do klienta 15.07, bez odpowiedzi",
    )


def test_lead_notice_lists_jobs_and_links_the_oldest() -> None:
    title, message, link = notice_text(
        {"mine": [_line(2, 15), _line(3, 99)]}, names={}, uid=7
    )
    assert title == "2 rekrutacje bez ruchu"
    assert link == "/jobs/3"
    assert message.index("Rekrutacja 3") < message.index("Rekrutacja 2")
    assert "Jeszcze trwa" in message and "przegrane" in message


def test_head_of_recruitment_sees_counts_per_delivery_lead() -> None:
    title, message, _ = notice_text(
        {"team": [_line(1, 21, 7), _line(2, 22, 7), _line(3, 23, 8)]},
        names={7: "Igor", 8: "Marta"},
        uid=50,
    )
    assert title == "3 rekrutacje bez ruchu"
    assert "Igor: 2, Marta: 1" in message


def test_closed_notice_title_and_many_jobs_are_trimmed() -> None:
    lines = [_line(i, 28 + i) for i in range(1, 11)]
    title, message, _ = notice_text({"closed": lines}, names={}, uid=7)
    assert title == "NEXUS zamknął 10 rekrutacji bez ruchu"
    assert message.count("Rekrutacja ") == job_idle.TITLES_MAX
    assert "i 2 innych" in message


def _row(job_id: int, *, work_state="searching", champion=None, deadline=None):
    """Wiersz przebiegu: id, tytuł, tytuł roboczy, DL, klient, priorytet,
    stan pracy, champion, termin."""
    return (
        job_id,
        f"Rekrutacja {job_id}",
        None,
        7,
        "Klient",
        None,
        work_state,
        champion,
        deadline,
    )


def test_overdue_starts_the_day_after_the_deadline() -> None:
    """24.11.2026: „Szukamy” po terminie czeka na decyzję DL — dzwonek."""
    today = datetime(2026, 11, 24).date()
    info = {
        1: _row(1, deadline=today - timedelta(days=1)),
        2: _row(2, deadline=today),
        3: _row(3, deadline=None),
        4: _row(4, deadline=today - timedelta(days=5), champion=NOW),
        5: _row(5, deadline=today - timedelta(days=5), work_state="client_silent"),
        6: _row(6, deadline=today - timedelta(days=40)),
    }
    assert job_idle.overdue_jobs(info, today=today) == {
        1: (1, today - timedelta(days=1)),
        6: (40, today - timedelta(days=40)),
    }


def test_overdue_notice_names_the_three_decisions() -> None:
    title, message, link = job_idle.overdue_notice_text([_line(2, 3), _line(3, 40)])
    assert title == "Po terminie: 2 rekrutacje"
    assert message.index("Rekrutacja 3") < message.index("Rekrutacja 2")
    assert "nowy termin" in message and "Klient milczy" in message
    assert link == "/jobs?stage=overdue"
    _t, _m, one = job_idle.overdue_notice_text([_line(9, 1)])
    assert one == "/jobs/9"


def test_send_window_is_business_hours_on_working_days() -> None:
    # 12.11.2026 to czwartek; 9:00 UTC = 10:00 w Warszawie.
    assert job_idle.in_send_window(NOW)
    assert not job_idle.in_send_window(NOW.replace(hour=19))
    # 11.11 — Święto Niepodległości.
    assert not job_idle.in_send_window(NOW - timedelta(days=1))


# ── Z bazą ────────────────────────────────────────────────────────────────


async def _seed(*, opened_days_ago: int, start_days_ago: int) -> tuple[int, int, int]:
    """Rekrutacja z DL-em i Head of Recruitment; start reguły w przeszłości."""
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.app_setting import AppSetting
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        lead = User(
            email=f"idle-dl-{suffix}@example.com",
            password_hash=hash_password("P@ssw0rd"),
            name=f"DL {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        hor = User(
            email=f"idle-hor-{suffix}@example.com",
            password_hash=hash_password("P@ssw0rd"),
            name=f"HoR {suffix}",
            role=UserRole.head_of_recruitment,
            roles=[UserRole.head_of_recruitment.value],
            is_active=True,
        )
        client = Client(name=f"IdleClient-{suffix}")
        db.add_all([lead, hor, client])
        await db.flush()
        job = Job(
            title=f"pytest-idle-{suffix}",
            client_id=client.id,
            status=JobStatus.published,
            delivery_lead_id=lead.id,
            opened_at=now - timedelta(days=opened_days_ago),
        )
        db.add(job)
        await db.execute(
            delete(AppSetting).where(AppSetting.key == job_idle.STARTED_KEY)
        )
        db.add(
            AppSetting(
                key=job_idle.STARTED_KEY,
                value={"at": (now - timedelta(days=start_days_ago)).isoformat()},
            )
        )
        await db.commit()
        return job.id, lead.id, hor.id


async def _sweep(job_id: int, *, days_ahead: int = 0) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services.job_lifecycle import PostCommit

    async with AsyncSessionLocal() as db:
        counts = await job_idle.run_idle_sweep(
            db,
            PostCommit(),
            now=datetime.now(timezone.utc) + timedelta(days=days_ahead),
            only_job_ids=[job_id],
        )
        await db.commit()
        return counts


async def _notices(user_id: int) -> list[str]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification.message).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.job_idle_reminder,
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_sweep_reminds_escalates_and_closes_after_the_warning(
    app_client: AsyncClient,
) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    job_id, lead_id, hor_id = await _seed(opened_days_ago=16, start_days_ago=30)

    first = await _sweep(job_id)
    assert first["remind"] == 1
    assert any("pytest-idle" in m for m in await _notices(lead_id))
    assert await _notices(hor_id) == []
    # Drugi przebieg tego samego dnia niczego nie powtarza.
    assert (await _sweep(job_id))["remind"] == 0

    escalated = await _sweep(job_id, days_ahead=6)
    assert escalated["hor"] == 1
    assert any("Bez ruchu od 3 tygodni" in m for m in await _notices(hor_id))

    # Dzień 28, ale ostrzeżenie HoR padło „przed chwilą” — jeszcze nie zamyka.
    assert (await _sweep(job_id, days_ahead=12))["closed"] == 0
    closed = await _sweep(job_id, days_ahead=14)
    assert closed["closed"] == 1
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        assert job.status == JobStatus.closed
        assert job.close_reason.value == "no_activity"
        assert job.close_notes == job_idle.CLOSE_NOTE


@pytest.mark.asyncio
async def test_still_going_hides_the_bar_and_counts_snoozes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id, _lead, _hor = await _seed(opened_days_ago=40, start_days_ago=30)

    idle = await app_client.get(f"/api/jobs/{job_id}/idle", headers=app_auth_headers)
    assert idle.status_code == 200, idle.text
    body = idle.json()
    # Dni liczy kalendarz firmy — zmiana czasu potrafi przesunąć o jeden.
    assert body["stage"] == "close" and 39 <= body["days"] <= 41
    assert body["last_move_at"] is None

    snoozed = await app_client.post(
        f"/api/jobs/{job_id}/idle/snooze", headers=app_auth_headers
    )
    assert snoozed.status_code == 200, snoozed.text
    after = snoozed.json()
    assert (after["stage"], after["days"], after["snooze_count"]) == (None, 0, 1)


@pytest.mark.asyncio
async def test_snooze_needs_an_open_job(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    job_id, _lead, _hor = await _seed(opened_days_ago=20, start_days_ago=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await db.commit()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/idle/snooze", headers=app_auth_headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "job_not_open"
    idle = await app_client.get(f"/api/jobs/{job_id}/idle", headers=app_auth_headers)
    assert idle.json()["stage"] is None


@pytest.mark.asyncio
async def test_recruiter_without_close_permission_gets_403(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    job_id, _lead, _hor = await _seed(opened_days_ago=20, start_days_ago=30)
    suffix = uuid.uuid4().hex[:8]
    email = f"idle-rec-{suffix}@example.com"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password("P@ssw0rd"),
                name=f"Rek {suffix}",
                role=UserRole.recruiter,
                is_active=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": "P@ssw0rd"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await app_client.post(f"/api/jobs/{job_id}/idle/snooze", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sweep_rings_the_lead_once_per_deadline_when_searching_is_overdue(
    app_client: AsyncClient,
) -> None:
    """24.11.2026: „Szukamy” po terminie → jeden dzwonek do DL na termin."""
    from sqlalchemy import delete, select, update

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.job import Job
    from app.models.notification import Notification, NotificationType

    job_id, lead_id, hor_id = await _seed(opened_days_ago=2, start_days_ago=0)

    async def set_deadline(days_ago: int) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    work_state="searching",
                    deadline=business_today() - timedelta(days=days_ago),
                )
            )
            await db.commit()

    await set_deadline(3)
    first = await _sweep(job_id)
    assert first[job_idle.OVERDUE_STAGE] == 1
    async with AsyncSessionLocal() as db:
        bells = (
            await db.scalars(
                select(Notification.message).where(
                    Notification.user_id == lead_id,
                    Notification.notification_type
                    == NotificationType.request_review_needed,
                )
            )
        ).all()
    assert any("pytest-idle" in m and "Termin minął" in m for m in bells)
    assert (await _sweep(job_id))[job_idle.OVERDUE_STAGE] == 0

    # Nowy termin, który też minął = nowy cykl. Dzwonek z poprzedniego cyklu
    # usuwamy, bo dobowy dedup `emit` (ta sama osoba, typ i rekrutacja)
    # zjadłby drugi wpis tego samego dnia — w pracy nowy cykl to inny dzień.
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.user_id == lead_id,
                Notification.notification_type
                == NotificationType.request_review_needed,
            )
        )
        await db.commit()
    await set_deadline(1)
    assert (await _sweep(job_id))[job_idle.OVERDUE_STAGE] == 1


@pytest.mark.asyncio
async def test_overdue_bell_skips_jobs_the_list_shows_as_contract(
    app_client: AsyncClient,
) -> None:
    """Lista mówi „Umowa” (pierwszeństwo przed „Po terminie”) — bez dzwonka."""
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from tests.test_pipeline_membership_gate import _seed_candidate

    job_id, _lead_id, _hor_id = await _seed(opened_days_ago=2, start_days_ago=0)
    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                work_state="searching", deadline=business_today() - timedelta(days=3)
            )
        )
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.negotiation,
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    assert (await _sweep(job_id))[job_idle.OVERDUE_STAGE] == 0


@pytest.mark.asyncio
async def test_overdue_bell_eaten_by_daily_dedup_is_retried(
    app_client: AsyncClient,
) -> None:
    """Dzwonek „P1 bez CV” o tej samej rekrutacji tego dnia blokuje wpis
    (dedup dobowy `emit`) — znacznik nie powstaje, więc dzwonek wraca."""
    from sqlalchemy import delete, update

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.job import Job
    from app.models.notification import Notification, NotificationType

    job_id, lead_id, _hor_id = await _seed(opened_days_ago=2, start_days_ago=0)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                work_state="searching", deadline=business_today() - timedelta(days=3)
            )
        )
        earlier = Notification(
            user_id=lead_id,
            title="P1 bez CV: 1 rekrutacja",
            message="pytest",
            notification_type=NotificationType.request_review_needed,
            related_entity_type="job",
            related_entity_id=job_id,
        )
        db.add(earlier)
        await db.commit()
        earlier_id = earlier.id

    assert (await _sweep(job_id))[job_idle.OVERDUE_STAGE] == 0
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.id == earlier_id))
        await db.commit()
    assert (await _sweep(job_id))[job_idle.OVERDUE_STAGE] == 1
