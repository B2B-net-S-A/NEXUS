"""Follow-up z kandydatem, gdy klient milczy (0371, decyzje Artura 24.09.2026).

Jedno zadanie na OSOBĘ: kandydat w trzech procesach u trzech rekruterów
dostaje jeden telefon od rekrutera procesu, który zaszedł najdalej; kontakt
kogokolwiek zeruje zegar; „nie odebrał” przypomina co 2 dni robocze bez
limitu; wchodzą tylko CV wysłane od dnia startu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_followup import CandidateFollowup
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.note import Note, NoteType
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.user import User, UserRole
from app.services import candidate_followups as svc

# ── Czysta reguła ────────────────────────────────────────────────────────────


def _at(days_ago: float, now: datetime) -> datetime:
    return now - timedelta(days=days_ago)


def _proc(
    job_id: int,
    *,
    owner: int | None,
    column: str = "cv_sent",
    silent_days: float,
    sent_days: float | None = None,
    now: datetime,
) -> svc.WaitingProcess:
    return svc.WaitingProcess(
        candidate_id=1,
        job_id=job_id,
        job_title=f"Rekrutacja {job_id}",
        client_id=None,
        client_name=f"Klient {job_id}",
        column=column,
        stage_name=None,
        sent_at=_at(sent_days if sent_days is not None else silent_days, now),
        silent_since=_at(silent_days, now),
        owner_id=owner,
    )


def _compute(processes, contact=None, logs=(), *, active=None, performer=None):
    active = active if active is not None else {10, 20, 30, 40}
    return svc.compute_followup(
        processes,
        contact,
        logs,
        days=14,
        retry_business_days=2,
        is_active=lambda uid: uid in active,
        performer=performer or (lambda uid: uid),
    )


def _now() -> datetime:
    # Czwartek 12:00 czasu polskiego — stała chwila, niezależna od zegara CI.
    return datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


def test_three_processes_three_recruiters_give_one_call_from_the_furthest() -> None:
    now = _now()
    f = _compute(
        [
            _proc(1, owner=10, silent_days=20, now=now),
            _proc(2, owner=20, column="client_interview", silent_days=16, now=now),
            _proc(3, owner=30, silent_days=15, now=now),
        ]
    )
    assert f is not None
    assert f.caller_id == 20 and f.caller_reason == "furthest"
    assert f.lead.job_id == 2
    assert f.owner_ids == frozenset({10, 20, 30})
    # Termin liczy się od NAJSTARSZEJ ciszy: 20 dni temu + 14 = 6 dni temu.
    today = svc.local_date(now)
    assert f.due_on == today - timedelta(days=6)
    assert f.state(today) == "overdue" and f.overdue_days(today) == 6


def test_contact_by_anyone_resets_the_clock() -> None:
    now = _now()
    contact = svc.Contact(at=_at(5, now), by=99, kind="note")
    f = _compute([_proc(1, owner=10, silent_days=20, now=now)], contact)
    assert f is not None
    assert f.due_on == svc.local_date(_at(5, now) + timedelta(days=14))
    assert f.state(svc.local_date(now)) == "scheduled"


def test_no_answer_retries_after_two_business_days_without_limit() -> None:
    now = _now()
    contact = svc.Contact(at=_at(30, now), by=10, kind="note")
    logs = [
        svc.LogEntry(
            user_id=10, outcome="no_answer", callback_on=None, created_at=_at(d, now)
        )
        for d in (9, 7, 5, 3, 1)
    ]
    f = _compute([_proc(1, owner=10, silent_days=30, now=now)], contact, logs)
    assert f is not None
    assert f.pending == "no_answer"
    assert f.no_answer_count == 5
    # Ostatnia próba w środę 14.10 → dwa dni robocze później: piątek 16.10.
    assert f.due_on == date(2026, 10, 16)
    # „Nie odebrał” nie jest kontaktem.
    assert f.last_contact == contact


def test_no_answer_skips_weekend() -> None:
    friday = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
    assert svc.add_business_days(friday, 2) == date(2026, 10, 20)


def test_callback_sets_the_chosen_day() -> None:
    now = _now()
    logs = [
        svc.LogEntry(
            user_id=10,
            outcome="callback",
            callback_on=date(2026, 10, 20),
            created_at=_at(1, now),
        )
    ]
    f = _compute([_proc(1, owner=10, silent_days=30, now=now)], None, logs)
    assert f is not None and f.pending == "callback"
    assert f.due_on == date(2026, 10, 20)


def test_connected_followup_is_a_contact() -> None:
    now = _now()
    logs = [
        svc.LogEntry(
            user_id=30, outcome="connected", callback_on=None, created_at=_at(2, now)
        )
    ]
    f = _compute([_proc(1, owner=10, silent_days=30, now=now)], None, logs)
    assert f is not None
    assert f.last_contact is not None and f.last_contact.by == 30
    assert f.due_on == svc.local_date(_at(2, now) + timedelta(days=14))


def test_claim_wins_the_current_round_only() -> None:
    now = _now()
    claim = svc.LogEntry(
        user_id=40, outcome="claim", callback_on=None, created_at=_at(1, now)
    )
    f = _compute([_proc(1, owner=10, silent_days=30, now=now)], None, [claim])
    assert f is not None and f.caller_id == 40 and f.caller_reason == "claim"
    # Kontakt po przejęciu kończy rundę — kolejna wraca do właściciela.
    later = svc.Contact(at=_at(0.5, now), by=40, kind="note")
    g = _compute([_proc(1, owner=10, silent_days=30, now=now)], later, [claim])
    assert g is not None and g.caller_id == 10


def test_substitute_takes_the_call_of_an_absent_owner() -> None:
    now = _now()
    f = _compute(
        [_proc(1, owner=10, silent_days=20, now=now)],
        performer=lambda uid: 40 if uid == 10 else uid,
    )
    assert f is not None and f.caller_id == 40 and f.caller_reason == "substitute"


def test_inactive_owner_passes_the_call_to_the_next_process() -> None:
    now = _now()
    f = _compute(
        [
            _proc(1, owner=10, column="client_interview", silent_days=20, now=now),
            _proc(2, owner=20, silent_days=18, now=now),
        ],
        active={20},
    )
    assert f is not None and f.caller_id == 20 and f.caller_reason == "next_process"


def test_tie_goes_to_the_owner_who_last_talked_to_the_candidate() -> None:
    now = _now()
    contact = svc.Contact(at=_at(16, now), by=20, kind="note")
    f = _compute(
        [
            _proc(1, owner=10, silent_days=20, now=now),
            _proc(2, owner=20, silent_days=18, now=now),
        ],
        contact,
    )
    assert f is not None and f.caller_id == 20 and f.caller_reason == "recent_contact"


def test_nobody_to_call_is_visible_to_oversight() -> None:
    now = _now()
    f = _compute([_proc(1, owner=None, silent_days=20, now=now)])
    assert f is not None and f.caller_id is None and f.caller_reason == "none"
    hor = User(id=5, role=UserRole.head_of_recruitment, roles=[])
    rec = User(id=6, role=UserRole.recruiter, roles=[])
    today = svc.local_date(now)
    assert svc.for_user({1: f}, hor, today=today) == [f]
    assert svc.for_user({1: f}, rec, today=today) == []


def test_for_user_shows_only_due_until_tomorrow() -> None:
    now = _now()
    today = svc.local_date(now)
    soon = _compute([_proc(1, owner=10, silent_days=13, now=now)])
    later = _compute([_proc(2, owner=10, silent_days=5, now=now)])
    assert soon is not None and later is not None
    later.candidate_id = 2
    rec = User(id=10, role=UserRole.recruiter, roles=[])
    assert svc.for_user({1: soon, 2: later}, rec, today=today) == [soon]
    other = User(id=20, role=UserRole.recruiter, roles=[])
    assert svc.for_user({1: soon}, other, today=today) == []


def test_digest_counts_due_and_overdue() -> None:
    now = _now()
    today = svc.local_date(now)
    overdue = _compute([_proc(1, owner=10, silent_days=20, now=now)])
    due_today = _compute([_proc(2, owner=10, silent_days=14, now=now)])
    assert overdue is not None and due_today is not None
    counts = svc.digest_counts({1: overdue, 2: due_today}, today=today)
    assert counts[10].due == 2 and counts[10].overdue == 1


def test_digest_message_names_followups() -> None:
    from app.services import board_tasks

    line = board_tasks.DigestLine(followups=3, followups_overdue=1)
    assert line.total == 3
    assert board_tasks.digest_message(line) == (
        "3 follow-upy z kandydatami do zrobienia (1 zaległy)"
    )


# ── Integracyjne: pulpit, Tablica, zapis wyniku ──────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole) -> tuple[int, dict[str, str]]:
    unique = uuid.uuid4().hex[:8]
    email = f"fu-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Fu"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"FU {role.value} {unique}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, {"email": email, "password": password}


async def _login(client: AsyncClient, creds: dict[str, str]) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_world(owners: list[int], now: datetime) -> dict:
    """Jeden kandydat w trzech procesach; proces 2 po rozmowie u klienta."""

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Jan", lastname=f"FU{unique}", email=f"fu-{unique}@example.com"
        )
        tpl = PipelineTemplate(name=f"FU template {unique}")
        db.add_all([cand, tpl])
        await db.flush()
        defs: dict[str, PipelineStageDef] = {}
        for order, (key, name, enum, category) in enumerate(
            [
                ("verified", "Zweryfikowany", "verified", StageCategoryEnum.internal),
                ("qc", "QC CV", "interview", StageCategoryEnum.internal),
                ("cv_sent", "CV Wysłane", "cv_sent", StageCategoryEnum.external),
                ("after", "Po Interview", "interview", StageCategoryEnum.external),
            ]
        ):
            d = PipelineStageDef(
                template_id=tpl.id,
                name=name,
                order=order,
                category=category,
                legacy_enum_value=enum,
            )
            db.add(d)
            defs[key] = d
        await db.flush()
        clients, jobs = [], []
        for i, owner in enumerate(owners):
            cli = Client(name=f"FU klient {i} {unique}")
            db.add(cli)
            await db.flush()
            job = Job(
                title=f"FU Java {i} {unique}",
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=cli.id,
                pipeline_template_id=tpl.id,
            )
            db.add(job)
            await db.flush()
            clients.append(cli.id)
            jobs.append(job.id)
            sent_days = 20 - 2 * i
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    stage_def_id=defs["verified"].id,
                    moved_at=now - timedelta(days=sent_days + 1),
                    moved_by=owner,
                    verification_status=VerificationStatus.active,
                )
            )
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    stage_def_id=defs["cv_sent"].id,
                    moved_at=now - timedelta(days=sent_days),
                    moved_by=owner,
                )
            )
            if i == 1:
                db.add(
                    CandidateStage(
                        candidate_id=cand.id,
                        job_id=job.id,
                        stage=PipelineStage.interview,
                        stage_def_id=defs["after"].id,
                        moved_at=now - timedelta(days=16),
                        moved_by=owner,
                    )
                )
        await db.commit()
        return {
            "candidate_id": cand.id,
            "template_id": tpl.id,
            "job_ids": jobs,
            "client_ids": clients,
        }


async def _cleanup(world: dict, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        cid = world["candidate_id"]
        await db.execute(
            delete(CandidateFollowup).where(CandidateFollowup.candidate_id == cid)
        )
        await db.execute(delete(Note).where(Note.candidate_id == cid))
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == cid)
        )
        await db.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.execute(delete(Job).where(Job.id.in_(world["job_ids"])))
        await db.execute(
            delete(PipelineStageDef).where(
                PipelineStageDef.template_id == world["template_id"]
            )
        )
        await db.execute(
            delete(PipelineTemplate).where(PipelineTemplate.id == world["template_id"])
        )
        await db.execute(delete(Client).where(Client.id.in_(world["client_ids"])))
        await db.commit()


def _mine(payload: dict, key: str, candidate_id: int) -> list[dict]:
    return [r for r in payload[key] if r["candidate_id"] == candidate_id]


@pytest.mark.asyncio
async def test_one_call_for_the_person_and_outcome_resets_everyone(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with AsyncSessionLocal() as db:
        now = (await db.execute(select(func_now()))).scalar_one()
    monkeypatch.setattr(
        settings, "CANDIDATE_FOLLOWUP_SINCE", svc.local_date(now - timedelta(days=60))
    )
    ids = [await _seed_user(UserRole.recruiter) for _ in range(3)]
    user_ids = [uid for uid, _ in ids]
    world = await _seed_world(user_ids, now)
    cid = world["candidate_id"]
    heads = [await _login(api_client, creds) for _, creds in ids]
    try:
        # Dzwoni właściciel procesu po rozmowie u klienta (drugi) — raz.
        first = (await api_client.get("/api/board-tasks", headers=heads[1])).json()
        rows = _mine(first, "followups", cid)
        assert len(rows) == 1, first
        assert rows[0]["caller_id"] == user_ids[1]
        assert rows[0]["state"] == "overdue"
        assert {p["job_id"] for p in rows[0]["processes"]} == set(world["job_ids"])
        for other in (heads[0], heads[2]):
            payload = (await api_client.get("/api/board-tasks", headers=other)).json()
            assert _mine(payload, "followups", cid) == []
            assert len(_mine(payload, "followups_by_others", cid)) == 1

        # Zwykła notatka (np. komentarz przy dodaniu do innej rekrutacji) to
        # nie rozmowa z kandydatem — przypomnienie zostaje.
        async with AsyncSessionLocal() as db:
            db.add(
                Note(
                    candidate_id=cid,
                    author_id=user_ids[0],
                    content="Dodany do kolejnej rekrutacji.",
                    note_type=NoteType.general,
                )
            )
            await db.commit()
        still = (await api_client.get("/api/board-tasks", headers=heads[1])).json()
        assert len(_mine(still, "followups", cid)) == 1

        # Karta na Tablicy procesu 1 wie, kto dzwoni.
        board = (
            await api_client.get(
                f"/api/pipeline/kanban/{world['job_ids'][0]}", headers=heads[0]
            )
        ).json()
        cards = [
            c
            for col in board["columns"]
            for c in col["items"]
            if c["candidate_id"] == cid
        ]
        assert cards and cards[0]["followup"]["caller_id"] == user_ids[1]

        # Dzwoni ktoś inny (pierwszy rekruter) — zegar zeruje się wszystkim.
        done = await api_client.post(
            f"/api/candidate-followups/candidates/{cid}/outcome",
            headers=heads[0],
            json={"outcome": "connected", "note": "Czeka, dostępny od 01.11."},
        )
        assert done.status_code == 200, done.text
        assert done.json()["followup"]["state"] == "scheduled"
        async with AsyncSessionLocal() as db:
            notes = (
                await db.scalars(select(Note).where(Note.candidate_id == cid))
            ).all()
        calls = [n for n in notes if n.note_type == NoteType.call]
        assert len(calls) == 1 and calls[0].job_id is None
        after = (await api_client.get("/api/board-tasks", headers=heads[1])).json()
        assert _mine(after, "followups", cid) == []

        # Zmiana: rezygnacja z procesu 3 → dzwonek tylko do jego właściciela.
        changed = await api_client.post(
            f"/api/candidate-followups/candidates/{cid}/outcome",
            headers=heads[1],
            json={
                "outcome": "changed",
                "note": "Ma inną ofertę, rezygnuje z procesu 3.",
                "processes": {str(world["job_ids"][2]): "withdrawing"},
            },
        )
        assert changed.status_code == 200, changed.text
        async with AsyncSessionLocal() as db:
            signals = (
                await db.scalars(
                    select(Notification).where(
                        Notification.notification_type
                        == NotificationType.candidate_followup_signal,
                        Notification.user_id.in_(user_ids),
                    )
                )
            ).all()
        assert [n.user_id for n in signals] == [user_ids[2]]
        assert signals[0].link == f"/jobs/{world['job_ids'][2]}?candidate={cid}"

        history = (
            await api_client.get(
                f"/api/candidate-followups/candidates/{cid}", headers=heads[2]
            )
        ).json()["history"]
        assert [h["outcome"] for h in history] == ["changed", "connected"]
    finally:
        await _cleanup(world, user_ids)


@pytest.mark.asyncio
async def test_cv_sent_before_the_start_date_gives_no_followup(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decyzja Artura: wchodzą tylko CV wysłane od dnia startu — bez historii."""

    async with AsyncSessionLocal() as db:
        now = (await db.execute(select(func_now()))).scalar_one()
    monkeypatch.setattr(
        settings, "CANDIDATE_FOLLOWUP_SINCE", svc.local_date(now + timedelta(days=1))
    )
    ids = [await _seed_user(UserRole.recruiter)]
    user_ids = [uid for uid, _ in ids]
    world = await _seed_world(user_ids, now)
    try:
        async with AsyncSessionLocal() as db:
            found = await svc.load_followups(
                db, now=now, candidate_ids=[world["candidate_id"]]
            )
        assert found == {}
        resp = await api_client.post(
            f"/api/candidate-followups/candidates/{world['candidate_id']}/claim",
            headers=await _login(api_client, ids[0][1]),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "FOLLOWUP_NOT_WAITING"
    finally:
        await _cleanup(world, user_ids)


def func_now():
    """Punkt odniesienia z bazy — etapy i notatki mają czas nadany przez nią."""

    from sqlalchemy import func

    return func.now()
