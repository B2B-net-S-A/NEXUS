"""Kolejka „Czeka na Ciebie" (0348, Rekrutacja v5): Cpro i przegląd DL.

Decyzje Artura: u Nordei „CV wysłane" = wysłane do Cpro (22.09.2026); do Cpro
wysyła JEDNA osoba na firmę (23.09.2026); kolejki DZ nie ma — przegląd DL
obejmuje osoby w kolumnie „QC CV" (24.09.2026); rano jeden zbiorczy dzwonek.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.job_collaborator import JobCollaborator
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.services import board_tasks as svc
from app.services import cpro_sender

# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _def(id_: int, name: str, order: int, enum: str | None, terminal: bool = False):
    return SimpleNamespace(
        id=id_,
        name=name,
        order=order,
        legacy_enum_value=enum,
        is_terminal=terminal,
    )


@pytest.mark.parametrize("qc_name", ["QC CV", "Przepuszczony przez DZ"])
def test_name_stages_are_never_hosts_even_with_host_codes(qc_name: str) -> None:
    """„QC CV" ma kod interview, „NORDEA: Wysłać do Cpro" kod screening —
    kolejka i tak rozpoznaje je po nazwie (także starą nazwę DZ z Traffita)."""
    stages = svc.classify_template(
        [
            _def(1, "Screening", 1, "screening"),
            _def(2, "Kandydat Zweryfikowany", 2, "verified"),
            _def(3, qc_name, 3, "interview"),
            _def(4, "NORDEA: Wysłać do Cpro", 4, "screening"),
            _def(5, "Wysłany do Klienta", 5, "cv_sent"),
            _def(6, "Odrzucony", 9, "rejected", terminal=True),
        ]
    )
    assert stages.verified_ids == frozenset({2})
    assert stages.qc_id == 3 and stages.qc_ids == frozenset({3})
    assert stages.cpro_ids == frozenset({4})
    assert stages.cv_sent_id == 5


def _task(kind: str, **kw) -> svc.BoardTask:
    base = dict(
        stage_id=1,
        candidate_id=1,
        candidate_name="Anna Nowak",
        job_id=10,
        job_title="Java",
        client_id=7,
        client_name="Nordea",
        since=datetime.now(timezone.utc),
        process_state_version=1,
        target_stage_def_id=3,
    )
    base.update(kw)
    return svc.BoardTask(kind=kind, **base)


def _user(uid: int, *roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        has_any_role=lambda *wanted: any(r in roles for r in wanted),
        has_role=lambda r: r in roles,
    )


def test_there_is_no_dz_queue_any_more() -> None:
    assert not hasattr(svc, "KIND_DZ")
    mine = svc.tasks_for_user(
        svc.BoardTaskSnapshot(), _user(1, UserRole.admin), portfolio=frozenset()
    )
    assert set(mine) == {svc.KIND_CPRO_TO_SEND, svc.KIND_CPRO_SENT, svc.KIND_DL_REVIEW}


def test_recruiter_sees_only_own_cpro_tasks() -> None:
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=70),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=3, assignee_id=None),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=4, assignee_id=71),
            # Wysłane widzi osoba od Cpro, nie ten, kto przesunął kartę.
            _task(svc.KIND_CPRO_SENT, stage_id=5, assignee_id=70, moved_by=71),
            _task(svc.KIND_CPRO_SENT, stage_id=6, assignee_id=71, moved_by=70),
            _task(svc.KIND_DL_REVIEW, stage_id=7),
        ]
    )
    mine = svc.tasks_for_user(
        snap, _user(70, UserRole.recruiter), portfolio=frozenset()
    )
    assert [t.stage_id for t in mine[svc.KIND_CPRO_TO_SEND]] == [2]
    assert [t.stage_id for t in mine[svc.KIND_CPRO_SENT]] == [5]
    assert mine[svc.KIND_DL_REVIEW] == []


def test_hor_never_sees_the_queue_of_the_firm_sender() -> None:
    """Decyzja Artura 24.09.2026: kolejka Cpro jest wyłącznie osoby od Cpro."""
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=71),
            _task(svc.KIND_CPRO_SENT, stage_id=4, assignee_id=71),
        ],
        firm_sender_id=71,
    )
    for role in (UserRole.head_of_recruitment, UserRole.admin):
        mine = svc.tasks_for_user(snap, _user(60, role), portfolio=frozenset())
        assert mine[svc.KIND_CPRO_TO_SEND] == []
        assert mine[svc.KIND_CPRO_SENT] == []
    sender = svc.tasks_for_user(
        snap, _user(71, UserRole.recruiter), portfolio=frozenset()
    )
    assert [t.stage_id for t in sender[svc.KIND_CPRO_TO_SEND]] == [1]


def test_without_firm_sender_hor_sees_fallback_tasks_too() -> None:
    """Audyt 25.09.2026: bez osoby na firmę zadanie z osobą ZAPASOWĄ
    (`jobs.cpro_sender_id`) widzi ta osoba ORAZ admin i HoR — inaczej nikt,
    kto może ustawić osobę firmową, nie wiedział, że kolejka stoi."""
    old = datetime.now(timezone.utc) - timedelta(days=3)
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=71, since=old),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=None, since=old),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=3, assignee_id=60),
            _task(svc.KIND_CPRO_SENT, stage_id=4, assignee_id=71),
            _task(svc.KIND_CPRO_SENT, stage_id=5, assignee_id=None),
        ]
    )
    for role in (UserRole.head_of_recruitment, UserRole.admin):
        mine = svc.tasks_for_user(snap, _user(60, role), portfolio=frozenset())
        assert [t.stage_id for t in mine[svc.KIND_CPRO_TO_SEND]] == [3, 1, 2]
        assert mine[svc.KIND_CPRO_SENT] == []
    fallback = svc.tasks_for_user(
        snap, _user(71, UserRole.recruiter), portfolio=frozenset()
    )
    assert [t.stage_id for t in fallback[svc.KIND_CPRO_TO_SEND]] == [1]
    assert [t.stage_id for t in fallback[svc.KIND_CPRO_SENT]] == [4]


class _DigestDb:
    """Minimalna sesja dla `digest_counts`: lista aktywnych użytkowników."""

    def __init__(self, users: list) -> None:
        self._users = users

    async def scalars(self, _query):
        return SimpleNamespace(all=lambda: self._users)


@pytest.mark.asyncio
async def test_digest_counts_fallback_tasks_for_hor_without_firm_sender() -> None:
    """Poranny skrót liczy tak jak panel: bez osoby na firmę HoR dostaje
    także zadania z osobą zapasową, a zapasowa osoba — swoje, raz."""
    hor = _user(60, UserRole.head_of_recruitment)
    fallback_hor = _user(61, UserRole.head_of_recruitment)
    tasks = [
        _task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=70),
        _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=None),
        _task(svc.KIND_CPRO_TO_SEND, stage_id=3, assignee_id=61),
    ]
    counts = await svc.digest_counts(
        _DigestDb([hor, fallback_hor]), svc.BoardTaskSnapshot(tasks=tasks)
    )
    assert counts[70].cpro_mine == 1
    assert counts[60].cpro_unassigned == 3
    assert counts[61].cpro_mine == 1 and counts[61].cpro_unassigned == 2

    with_firm = await svc.digest_counts(
        _DigestDb([hor, fallback_hor]),
        svc.BoardTaskSnapshot(
            tasks=[_task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=70)],
            firm_sender_id=70,
        ),
    )
    assert with_firm[70].cpro_mine == 1
    assert 60 not in with_firm and 61 not in with_firm


def test_delivery_lead_never_sees_the_cpro_queue() -> None:
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=None, client_id=7),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=71, client_id=7),
            _task(svc.KIND_CPRO_SENT, stage_id=3, assignee_id=71, client_id=7),
        ]
    )
    mine = svc.tasks_for_user(
        snap, _user(50, UserRole.delivery_lead), portfolio=frozenset({7})
    )
    assert mine[svc.KIND_CPRO_TO_SEND] == [] and mine[svc.KIND_CPRO_SENT] == []


def test_classify_template_finds_the_rejected_terminal_stage() -> None:
    stages = svc.classify_template(
        [
            _def(2, "Zweryfikowany", 2, "verified"),
            _def(5, "CV Wysłane", 5, "cv_sent"),
            _def(8, "Zatrudniony", 8, "hired", terminal=True),
            _def(9, "Odrzucony", 9, "rejected", terminal=True),
        ]
    )
    assert stages.rejected_id == 9
    assert stages.cv_sent_id == 5
    assert stages.qc_id is None


def test_dl_review_belongs_only_to_the_recruitments_delivery_lead() -> None:
    """Decyzja Artura 24.09.2026: przegląd widzi wyłącznie DL rekrutacji —
    admin i HoR nie, nawet gdy rekrutacja nie ma żadnego DL-a."""
    snap = svc.BoardTaskSnapshot(
        tasks=[
            # Portfel DL 50, bez DL w rekrutacji.
            _task(svc.KIND_DL_REVIEW, stage_id=1, client_id=7),
            # Klient spoza portfela DL 50.
            _task(svc.KIND_DL_REVIEW, stage_id=2, client_id=8),
            # DL 50 wpisany w rekrutacji — spoza portfela.
            _task(svc.KIND_DL_REVIEW, stage_id=3, client_id=9, delivery_lead_id=50),
            # Klient z portfela DL 50, ale rekrutacja ma wpisanego innego DL.
            _task(svc.KIND_DL_REVIEW, stage_id=4, client_id=7, delivery_lead_id=51),
        ]
    )
    dl = _user(50, UserRole.delivery_lead)
    mine = svc.tasks_for_user(snap, dl, portfolio=frozenset({7}))
    assert [t.stage_id for t in mine[svc.KIND_DL_REVIEW]] == [1, 3]

    for role in (UserRole.head_of_recruitment, UserRole.admin, UserRole.recruiter):
        other = svc.tasks_for_user(snap, _user(60, role), portfolio=frozenset({7}))
        assert other[svc.KIND_DL_REVIEW] == []

    # HoR, który jest też DL, widzi swoje jako DL.
    hybrid = _user(51, UserRole.head_of_recruitment, UserRole.delivery_lead)
    assert [
        t.stage_id
        for t in svc.tasks_for_user(snap, hybrid, portfolio=frozenset())[
            svc.KIND_DL_REVIEW
        ]
    ] == [4]


def test_task_dict_carries_qc_and_return_stage() -> None:
    task = _task(
        svc.KIND_CPRO_TO_SEND,
        return_stage_def_id=41,
        qc_status="failed",
        qc_blocking_failed=2,
    )
    data = task.as_dict()
    assert data["return_stage_def_id"] == 41
    assert data["qc_status"] == "failed" and data["qc_blocking_failed"] == 2


@pytest.mark.parametrize(
    ("line", "text"),
    [
        (svc.DigestLine(dl_review=1), "1 osoba czeka na Twój przegląd"),
        (svc.DigestLine(dl_review=3), "3 osoby czekają na Twój przegląd"),
        (
            svc.DigestLine(dl_review=5, cpro_mine=2),
            "5 osób czeka na Twój przegląd · "
            "2 osoby w kolejce Cpro do wysłania przez Ciebie",
        ),
        (
            svc.DigestLine(cpro_mine=1),
            "1 osoba w kolejce Cpro do wysłania przez Ciebie",
        ),
        (
            svc.DigestLine(cpro_unassigned=12),
            "12 osób w kolejce Cpro — nikt nie jest ustawiony do wysyłki",
        ),
    ],
)
def test_digest_message_is_one_polish_sentence(line: svc.DigestLine, text: str) -> None:
    assert svc.digest_message(line) == text
    assert "DZ" not in svc.digest_message(line)


# ── Integracyjne: ruch, typowanie, lista ─────────────────────────────────────


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
    email = f"bt-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Bt"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"BT {role.value} {unique}",
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


async def _seed_world() -> dict:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Nordea BT {unique}")
        cand = Candidate(
            name="Ewa", lastname=f"BT{unique}", email=f"bt-{unique}@example.com"
        )
        tpl = PipelineTemplate(name=f"BT template {unique}")
        db.add_all([cli, cand, tpl])
        await db.flush()
        defs = {}
        for order, (key, name, enum, category) in enumerate(
            [
                ("screening", "Screening", "screening", StageCategoryEnum.internal),
                ("verified", "Zweryfikowany", "verified", StageCategoryEnum.internal),
                ("qc", "QC CV", "interview", StageCategoryEnum.internal),
                ("cpro", "Wysłać do Cpro", "new", StageCategoryEnum.internal),
                ("cv_sent", "CV Wysłane", "cv_sent", StageCategoryEnum.external),
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
        db.add(
            PipelineStageDef(
                template_id=tpl.id,
                name="Odrzucony",
                order=99,
                category=StageCategoryEnum.terminal,
                is_terminal=True,
                terminal_type=TerminalType.rejected,
                legacy_enum_value="rejected",
            )
        )
        await db.flush()
        job = Job(
            title=f"BT Java {unique}",
            location="Warszawa",
            status=JobStatus.published,
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


async def seed_entry_row(candidate_id: int, job_id: int) -> None:
    """Osoba jest już w rekrutacji („Nowi”) — dopiero wtedy `/move` przenosi
    ją dalej. Runda 9 (R9-N11-4): para BEZ wiersza wchodzi wyłącznie do
    „Nowych”/„Screeningu”, jak przy dodaniu przez bulk-add."""
    from app.models.recruitment_pipeline import PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        await db.commit()


async def _cleanup(world: dict, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(
                CandidateStage.candidate_id == world["candidate_id"]
            )
        )
        await db.execute(
            delete(JobCollaborator).where(JobCollaborator.job_id == world["job_id"])
        )
        await db.execute(delete(Candidate).where(Candidate.id == world["candidate_id"]))
        await db.execute(delete(Job).where(Job.id == world["job_id"]))
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


def _rows(payload: dict, kind: str, candidate_id: int) -> list[dict]:
    return [r for r in payload[kind] if r["candidate_id"] == candidate_id]


@contextlib.asynccontextmanager
async def restore_cpro_sender():
    """Osoba od Cpro jest JEDNA na bazę (`app_settings`) — test ją przywraca,
    bo baza testowa jest wspólna dla całego przebiegu."""

    async with AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == cpro_sender.SETTING_KEY)
        )
    try:
        yield
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(AppSetting).where(AppSetting.key == cpro_sender.SETTING_KEY)
            )
            if saved is not None:
                db.add(AppSetting(key=cpro_sender.SETTING_KEY, value=saved))
            await db.commit()


async def clear_cpro_sender() -> None:
    """Nikt nie wysyła do Cpro — bez trasy PUT, którą od 25.09.2026 woła
    wyłącznie admin albo DL Nordei (testy HoR czyszczą stan wprost)."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == cpro_sender.SETTING_KEY)
        )
        await db.commit()


async def _move(client: AsyncClient, headers: dict, world: dict, key: str, **extra):
    resp = await client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["job_id"],
            "stage_def_id": world["defs"][key],
            **extra,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp


@pytest.mark.asyncio
async def test_nordea_cpro_queue_with_one_sender_for_the_company(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    other_id, other_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    cid, defs = world["candidate_id"], world["defs"]
    try:
        async with restore_cpro_sender():
            # Nikt nie wysyła — zadanie jest nieprzypisane, HoR je widzi.
            await clear_cpro_sender()

            await _move(api_client, hor, world, "verified")
            await _move(api_client, hor, world, "qc")
            queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
            # U Nordei osoba w QC CV nie czeka na przegląd DL.
            assert _rows(queue, "dl_review", cid) == []
            assert "dz" not in queue and "can_approve_dz" not in queue

            await _move(api_client, rec, world, "cpro")
            queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
            todo = _rows(queue, "cpro_to_send", cid)
            assert len(todo) == 1 and todo[0]["assignee_id"] is None
            assert todo[0]["target_stage_def_id"] == defs["cv_sent"]
            assert todo[0]["return_stage_def_id"] == defs["qc"]
            assert todo[0]["qc_status"] == "unchecked"
            rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
            assert _rows(rec_queue, "cpro_to_send", cid) == []

            # Rekruter nie ustawia siebie (decyzja 25.09.2026 — osoba od Cpro
            # widzi stawki do klienta); ustawia go admin, dla całej firmy.
            self_set = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=rec,
                json={"user_id": rec_id, "until": None},
            )
            assert self_set.status_code == 403, self_set.text
            _admin_id, admin_creds = await _seed_user(UserRole.admin)
            admin = await _login(api_client, admin_creds)
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": rec_id, "until": None},
            )
            assert put.status_code == 200, put.text
            rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
            todo = _rows(rec_queue, "cpro_to_send", cid)
            assert len(todo) == 1 and todo[0]["assignee_id"] == rec_id
            # Od teraz kolejka jest tylko osoby od Cpro — HoR jej nie widzi.
            hor_queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
            assert _rows(hor_queue, "cpro_to_send", cid) == []

            # Kolejka firmowa widzi każdy — pogrupowana po rekrutacji.
            cpro = (
                await api_client.get("/api/board-tasks/cpro/queue", headers=hor)
            ).json()
            assert cpro["sender"]["user_id"] == rec_id
            group = next(g for g in cpro["jobs"] if g["job_id"] == world["job_id"])
            item = next(i for i in group["items"] if i["candidate_id"] == cid)
            assert item["target_stage_def_id"] == defs["cv_sent"]
            assert item["return_stage_def_id"] == defs["qc"]
            assert item["qc_status"] == "unchecked"
            assert item["cv"] is None
            assert item["client_rate_value"] is None
            before_sent = cpro["sent_today"]

            # Stawkę do klienta widzi HoR i osoba od Cpro, inny rekruter nie
            # (decyzja 23.09.2026 — rekruter nie widzi stawki do klienta).
            async with AsyncSessionLocal() as session:
                row = await session.scalar(
                    select(CandidateStage)
                    .where(
                        CandidateStage.candidate_id == cid,
                        CandidateStage.job_id == world["job_id"],
                    )
                    .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                    .limit(1)
                )
                row.client_rate_value = 158
                await session.commit()
            other = await _login(api_client, other_creds)
            for headers, expected in ((hor, 158.0), (rec, 158.0), (other, None)):
                queue_view = (
                    await api_client.get("/api/board-tasks/cpro/queue", headers=headers)
                ).json()
                group = next(
                    g for g in queue_view["jobs"] if g["job_id"] == world["job_id"]
                )
                item = next(i for i in group["items"] if i["candidate_id"] == cid)
                assert item["client_rate_value"] == expected

            # „✓ Wrzucone” = zwykły ruch na „CV wysłane” (u Nordei = Cpro).
            await _move(api_client, rec, world, "cv_sent")
            rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
            assert _rows(rec_queue, "cpro_to_send", cid) == []
            assert len(_rows(rec_queue, "cpro_sent", cid)) == 1
            cpro = (
                await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
            ).json()
            assert cpro["sent_today"] == before_sent + 1
    finally:
        await _cleanup(world, [hor_id, rec_id, other_id])


def test_removed_dz_routes_are_gone() -> None:
    from app.main import app
    from tests._route_introspection import iter_api_routes

    paths = {path for path, _ in iter_api_routes(app)}
    assert "/api/board-tasks/dz/{stage_id}/review" not in paths
    assert "/api/board-tasks/dz/{stage_id}/hints" not in paths
    assert "/api/board-tasks/cpro/jobs/{job_id}/sender" not in paths
    assert "/api/board-tasks/cpro/sender" in paths
    assert "/api/board-tasks/cpro/queue" in paths


@pytest.mark.asyncio
async def test_cpro_queue_ignores_non_nordea_clients(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _move(api_client, hor, world, "verified")
        # Poza Nordeą „CV wysłane" to ruch Delivery Leada ze stawką do klienta.
        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="180",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert _rows(queue, "cpro_sent", cid) == []
        # Wysłany do klienta nie czeka już na przegląd DL.
        assert _rows(queue, "dl_review", cid) == []
        cpro = (await api_client.get("/api/board-tasks/cpro/queue", headers=hor)).json()
        assert all(g["job_id"] != world["job_id"] for g in cpro["jobs"])
    finally:
        await _cleanup(world, [hor_id, dl_id])


@pytest.mark.asyncio
async def test_dl_review_lists_people_in_the_qc_column_not_in_verified(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rekrutacja v5: poza Nordeą przegląd DL = osoby w kolumnie „QC CV”.

    Wiersz niesie cel „CV wysłane", etap „Odrzucony", kto zweryfikował,
    migawkę stawki z wiersza weryfikacji i wynik QC CV pary.
    """

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_in_id, dl_in_creds = await _seed_user(UserRole.delivery_lead)
    dl_out_id, dl_out_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    dl_in = await _login(api_client, dl_in_creds)
    dl_out = await _login(api_client, dl_out_creds)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.delivery_lead_id = dl_in_id
        rejected_id = await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == world["template_id"],
                PipelineStageDef.is_terminal.is_(True),
            )
        )
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cid,
                    job_id=jid,
                    stage="screening",
                    stage_def_id=defs["screening"],
                    moved_by=rec_id,
                    screening_answers={"answers": [], "overall_fit": "fit"},
                    moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
                )
            )
            await db.commit()
        await _move(
            api_client,
            hor,
            world,
            "verified",
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        # Zweryfikowany NIE jest jeszcze w przeglądzie DL — CV nie przeszło QC.
        queue = (await api_client.get("/api/board-tasks", headers=dl_in)).json()
        assert _rows(queue, "dl_review", cid) == []

        # Każdy, kto rusza kartą, przesuwa na „QC CV” (bez roli DZ).
        await _move(api_client, rec, world, "qc")
        # Rekrutacja ma swojego DL — HoR jej przeglądu nie widzi.
        hor_queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert _rows(hor_queue, "dl_review", cid) == []
        assert hor_queue["can_send_to_client"] is False
        queue = (await api_client.get("/api/board-tasks", headers=dl_in)).json()
        review = _rows(queue, "dl_review", cid)
        assert len(review) == 1
        row = review[0]
        assert row["kind"] == "dl_review"
        assert row["target_stage_def_id"] == defs["cv_sent"]
        assert row["rejected_stage_def_id"] == rejected_id
        assert row["verified_by_id"] == hor_id
        assert row["verified_by_name"].startswith("BT head_of_recruitment")
        assert row["expected_rate_value"] == 140.0
        assert row["expected_rate_unit"] == "hourly"
        assert row["expected_rate_currency"] == "PLN"
        assert row["screening_stage_id"] is not None
        assert row["screening_stage_id"] != row["stage_id"]
        assert row["qc_status"] == "unchecked"
        assert queue["dl_review_window_days"] == svc.DL_REVIEW_WINDOW_DAYS

        assert (
            _rows(
                (await api_client.get("/api/board-tasks", headers=rec)).json(),
                "dl_review",
                cid,
            )
            == []
        )
        assert (
            _rows(
                (await api_client.get("/api/board-tasks", headers=dl_out)).json(),
                "dl_review",
                cid,
            )
            == []
        )
        dl_queue = (await api_client.get("/api/board-tasks", headers=dl_in)).json()
        assert len(_rows(dl_queue, "dl_review", cid)) == 1
        assert dl_queue["can_send_to_client"] is True

        # Poranny skrót liczy przegląd DL.
        async with AsyncSessionLocal() as db:
            snapshot = await svc.load_snapshot(db)
            counts = await svc.digest_counts(db, snapshot)
        assert counts[dl_in_id].dl_review >= 1
        assert dl_out_id not in counts
    finally:
        await _cleanup(world, [hor_id, rec_id, dl_in_id, dl_out_id])


@pytest.mark.asyncio
async def test_dl_review_row_for_one_pair_matches_the_dashboard_row(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Przegląd otwierany z Tablicy i z dzwonka bierze wiersz z serwera.

    Do 04.10.2026 Tablica składała wiersz w przeglądarce — bez etapu CV po
    QC, osoby weryfikującej i stanu karty. `/dl-review-row` to ta sama
    reguła co lista na pulpicie, bez okna czasu (karta w „QC CV” dłużej niż
    okno pulpitu też się otwiera). Rekruter dostaje 403, osoba poza „QC CV” 404.
    """

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.delivery_lead_id = dl_id
        await db.commit()
    url = f"/api/board-tasks/dl-review-row?candidate_id={cid}&job_id={jid}"
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=cid,
                    job_id=jid,
                    stage="screening",
                    stage_def_id=defs["screening"],
                    moved_by=rec_id,
                    screening_answers={"answers": [], "overall_fit": "fit"},
                    moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
                )
            )
            await db.commit()
        await _move(
            api_client,
            rec,
            world,
            "verified",
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        not_yet = await api_client.get(url, headers=dl)
        assert not_yet.status_code == 404, not_yet.text

        await _move(api_client, rec, world, "qc")
        denied = await api_client.get(url, headers=rec)
        assert denied.status_code == 403, denied.text

        got = await api_client.get(url, headers=dl)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["can_send_to_client"] is True
        row = body["row"]
        dashboard = _rows(
            (await api_client.get("/api/board-tasks", headers=dl)).json(),
            "dl_review",
            cid,
        )
        assert dashboard == [row]
        assert row["verified_by_id"] == rec_id
        assert row["screening_stage_id"] is not None

        # Karta stoi w „QC CV” dłużej niż okno pulpitu — przegląd i tak się otwiera.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CandidateStage)
                .where(CandidateStage.candidate_id == cid)
                .values(
                    moved_at=datetime.now(timezone.utc)
                    - timedelta(days=svc.DL_REVIEW_WINDOW_DAYS + 10)
                )
            )
            await db.commit()
        old = await api_client.get(url, headers=dl)
        assert old.status_code == 200, old.text
        assert old.json()["row"]["stage_id"] == row["stage_id"]
    finally:
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_assignee_on_ready_move_still_sets_the_job_fallback(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pole ruchu z 0348 zostaje zgodne wstecz: ustawia zapas dla rekrutacji
    (`jobs.cpro_sender_id`), który obowiązuje, gdy nikt nie wysyła na firmę."""

    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    admin = await _login(api_client, admin_creds)
    rec = await _login(api_client, rec_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            # Wskazanie osoby przy ruchu = ustawienie osoby od Cpro rekrutacji —
            # tylko admin albo DL Nordei (przegląd PR #1844). Rekruter nie może
            # wskazać sam siebie (widziałby stawki do klienta), HoR też nie.
            for headers in (rec, hor):
                refused = await api_client.post(
                    "/api/pipeline/move",
                    headers=headers,
                    json={
                        "candidate_id": cid,
                        "job_id": jid,
                        "stage_def_id": world["defs"]["cpro"],
                        "task_assignee_id": rec_id,
                    },
                )
                assert refused.status_code == 403, refused.text
            async with AsyncSessionLocal() as db:
                assert (await db.get(Job, jid)).cpro_sender_id is None
            await _move(api_client, admin, world, "cpro", task_assignee_id=rec_id)
            async with AsyncSessionLocal() as db:
                assert (await db.get(Job, jid)).cpro_sender_id == rec_id
            async with AsyncSessionLocal() as db:
                snapshot = await svc.load_snapshot(db)
            todo = [
                t
                for t in snapshot.tasks
                if t.kind == svc.KIND_CPRO_TO_SEND and t.candidate_id == cid
            ]
            assert todo[0].assignee_id == rec_id
    finally:
        await _cleanup(world, [hor_id, admin_id, rec_id])


async def test_open_recruitment_without_dl_gets_the_clients_head_dl() -> None:
    """Rekrutacja bez DL-a dostaje głównego DL-a klienta (24.09.2026) —
    otwarta tak, zamknięta nie, a wpisany DL nigdy nie jest nadpisywany."""

    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.services.job_delivery_lead_fill import fill_missing_job_delivery_leads

    world = await _seed_world()
    head_id, _ = await _seed_user(UserRole.delivery_lead)
    other_id, _ = await _seed_user(UserRole.delivery_lead)
    unique = uuid.uuid4().hex[:8]
    extra_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=head_id,
                    client_id=world["client_id"],
                    is_head=True,
                )
            )
            closed = Job(
                title=f"BT closed {unique}",
                location="Warszawa",
                client_id=world["client_id"],
                status=JobStatus.closed,
                remote_policy=RemotePolicy.remote,
            )
            owned = Job(
                title=f"BT owned {unique}",
                location="Warszawa",
                client_id=world["client_id"],
                status=JobStatus.published,
                remote_policy=RemotePolicy.remote,
                delivery_lead_id=other_id,
            )
            db.add_all([closed, owned])
            await db.commit()
            extra_ids = [closed.id, owned.id]

        async with AsyncSessionLocal() as db:
            filled = await fill_missing_job_delivery_leads(db, [world["client_id"]])
            await db.commit()
        assert filled == 1

        async with AsyncSessionLocal() as db:
            assert (await db.get(Job, world["job_id"])).delivery_lead_id == head_id
            assert (await db.get(Job, extra_ids[0])).delivery_lead_id is None
            assert (await db.get(Job, extra_ids[1])).delivery_lead_id == other_id
            # Drugie wywołanie niczego już nie zmienia.
            assert await fill_missing_job_delivery_leads(db, [world["client_id"]]) == 0
            await db.rollback()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Job).where(Job.id.in_(extra_ids)))
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == world["client_id"]
                )
            )
            await db.commit()
        await _cleanup(world, [head_id, other_id])


# ── Propozycje automatu przydziału w „Czeka na Ciebie” (02.10.2026) ─────────


async def _seed_allocation_proposal(user_id: int, lead_id: int) -> dict:
    from app.models.job import JobPriority
    from app.models.job_work_assignment import JobWorkAssignment

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"BT alloc {unique}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"BT alloc {unique}",
            status=JobStatus.published,
            work_state="searching",
            client_id=cli.id,
            delivery_lead_id=lead_id,
            priority=JobPriority.urgent,
        )
        db.add(job)
        await db.flush()
        db.add(
            JobWorkAssignment(
                job_id=job.id,
                user_id=user_id,
                role="recruiter",
                source="auto",
                state="proposed",
                assigned_at=datetime.now(timezone.utc) - timedelta(minutes=3),
            )
        )
        await db.commit()
        return {"job_id": job.id, "client_id": cli.id, "client_name": cli.name}


async def _drop_allocation_proposal(seeded: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Job).where(Job.id == seeded["job_id"]))
        await db.execute(delete(Client).where(Client.id == seeded["client_id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_allocation_proposals_reach_only_those_who_decide(
    api_client: AsyncClient,
) -> None:
    """Propozycje automatu akceptuje Head of Recruitment (i admin) — tylko oni
    dostają wiersze. Delivery Lead i rekruter widzą pustą listę: propozycja
    nikogo jeszcze do niczego nie zobowiązuje."""

    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    seeded = await _seed_allocation_proposal(rec_id, dl_id)
    try:
        hor = await _login(api_client, hor_creds)
        resp = await api_client.get("/api/board-tasks", headers=hor)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["can_decide_proposals"] is True
        # Compass jest w testach wyłączony — urlopów nie znamy.
        assert body["allocation_leave_known"] is False
        (row,) = [
            r for r in body["allocation_proposals"] if r["job_id"] == seeded["job_id"]
        ]
        async with AsyncSessionLocal() as db:
            rec_name = await db.scalar(select(User.name).where(User.id == rec_id))
            dl_name = await db.scalar(select(User.name).where(User.id == dl_id))
        assert row["title"].startswith("BT alloc ")
        assert row["client_name"] == seeded["client_name"]
        assert (row["user_id"], row["user_name"], row["role"]) == (
            rec_id,
            rec_name,
            "recruiter",
        )
        assert row["delivery_lead_name"] == dl_name
        assert row["priority_level"] == "p1"
        assert row["fit"] == "other"
        assert (row["load"], row["sent"]) == (0, 0)
        assert row["leave_until"] is None and row["base_matches"] is None
        assert row["category_id"] is None and row["deadline"] is None
        assert row["proposed_at"] is not None

        for creds in (dl_creds, rec_creds):
            headers = await _login(api_client, creds)
            other = (await api_client.get("/api/board-tasks", headers=headers)).json()
            assert other["can_decide_proposals"] is False
            assert other["allocation_proposals"] == []
            assert other["allocation_leave_known"] is False
    finally:
        await _drop_allocation_proposal(seeded)


@pytest.mark.asyncio
async def test_board_tasks_survive_a_failure_while_loading_proposals(
    api_client: AsyncClient, monkeypatch
) -> None:
    """``GET /api/board-tasks`` zasila każdy pulpit — padnięte zapytanie
    o propozycje daje pustą listę, a nie 500 całej kolejki."""

    from app.services import request_allocation_proposals

    async def boom(_db):
        raise RuntimeError("proposals down")

    monkeypatch.setattr(request_allocation_proposals, "load_pending", boom)
    _, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    resp = await api_client.get("/api/board-tasks", headers=hor)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allocation_proposals"] == []
    assert body["can_decide_proposals"] is True
    # Reszta kolejki liczy się normalnie.
    assert isinstance(body["cpro_to_send"], list)


# ── „Kto prowadzi nowe rekrutacje” dla Head of Recruitment ──────────────────


async def _seed_job_leads(hor_id: int, dl_id: int) -> dict:
    """Rekrutacje przekazane do searchu przed chwilą: z prowadzącym automatu,
    z prowadzącym wskazanym przez człowieka, z samą propozycją i bez nikogo."""
    from app.models.competence_category import CompetenceCategory
    from app.models.job import JobPriority
    from app.models.job_collaborator import JobCollaboratorSource
    from app.models.job_work_assignment import JobWorkAssignment

    unique = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    people = {}
    for key, role in (
        ("auto", UserRole.recruiter),
        ("manual", UserRole.recruiter),
        ("owner", UserRole.recruiter),
        ("proposed", UserRole.recruiter),
        ("participant", UserRole.recruiter),
        ("removed", UserRole.recruiter),
    ):
        people[key], _ = await _seed_user(role)
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"BT leads {unique}")
        category = CompetenceCategory(
            slug=f"bt-leads-{unique}",
            name_pl=f"Kategoria {unique}",
            name_en=f"Category {unique}",
            description="kategoria testowa listy prowadzących",
        )
        db.add_all([cli, category])
        await db.flush()

        def job(key: str, *, handed_off: timedelta, **fields) -> Job:
            row = Job(
                title=f"BT leads {key} {unique}",
                status=fields.pop("status", JobStatus.published),
                work_state=fields.pop("work_state", "searching"),
                work_state_changed_at=now - handed_off,
                # Przekazanie do searchu stawia `is_open` (audyt 06.10.2026, H7:
                # opublikowana bez przekazania ma własny wiersz w kolejce).
                is_open=fields.pop("is_open", True),
                client_id=cli.id,
                delivery_lead_id=dl_id,
                **fields,
            )
            db.add(row)
            return row

        fresh = timedelta(seconds=20)
        jobs = {
            "auto": job(
                "auto",
                handed_off=fresh,
                recruiter_id=people["auto"],
                competence_category_id=category.id,
                working_title=f"BT leads tytuł roboczy {unique}",
                priority=JobPriority.urgent,
            ),
            "manual": job("manual", handed_off=fresh),
            "owner": job("owner", handed_off=fresh, recruiter_id=people["owner"]),
            "proposed": job("proposed", handed_off=fresh),
            "passive": job("passive", handed_off=fresh, priority=JobPriority.low),
            "fresh_empty": job("fresh-empty", handed_off=fresh),
            "stale_empty": job("stale-empty", handed_off=timedelta(minutes=5)),
            # Poza listą: przekazana dawno, nieprzekazana, zamknięta.
            "old": job("old", handed_off=timedelta(days=8)),
            "to_review": job("to-review", handed_off=fresh, work_state="to_review"),
            "closed": job("closed", handed_off=fresh, status=JobStatus.closed),
            "not_handed_off": job(
                "not-handed-off",
                handed_off=timedelta(days=20),
                work_state="to_review",
                is_open=False,
            ),
        }
        await db.flush()
        db.add_all(
            [
                JobWorkAssignment(
                    job_id=jobs["auto"].id,
                    user_id=people["auto"],
                    role="recruiter",
                    source="auto",
                    state="active",
                    assigned_at=now,
                ),
                JobWorkAssignment(
                    job_id=jobs["manual"].id,
                    user_id=people["manual"],
                    role="recruiter",
                    source="manual",
                    state="active",
                    assigned_at=now,
                    assigned_by=hor_id,
                ),
                JobWorkAssignment(
                    job_id=jobs["proposed"].id,
                    user_id=people["proposed"],
                    role="recruiter",
                    source="auto",
                    state="proposed",
                    assigned_at=now,
                ),
                JobCollaborator(
                    job_id=jobs["auto"].id,
                    user_id=people["participant"],
                    source=JobCollaboratorSource.auto_cc,
                ),
                JobCollaborator(
                    job_id=jobs["auto"].id,
                    user_id=people["auto"],
                    source=JobCollaboratorSource.auto_cc,
                ),
                # Zdjęty z rekrutacji i dopisany ręcznie nie są „z kategorii”.
                JobCollaborator(
                    job_id=jobs["auto"].id,
                    user_id=people["removed"],
                    source=JobCollaboratorSource.auto_cc,
                    removed_from_auto_cc=True,
                ),
                JobCollaborator(
                    job_id=jobs["auto"].id,
                    user_id=people["manual"],
                    source=JobCollaboratorSource.manual,
                ),
            ]
        )
        await db.commit()
        return {
            "unique": unique,
            "people": people,
            "jobs": {key: row.id for key, row in jobs.items()},
            "client_id": cli.id,
            "client_name": cli.name,
            "category_id": category.id,
            "category_name": category.name_pl,
            "category_slug": category.slug,
        }


async def _drop_job_leads(seeded: dict) -> None:
    from app.models.competence_category import CompetenceCategory

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Job).where(Job.id.in_(seeded["jobs"].values())))
        await db.execute(delete(Client).where(Client.id == seeded["client_id"]))
        await db.execute(
            delete(CompetenceCategory).where(
                CompetenceCategory.id == seeded["category_id"]
            )
        )
        await db.commit()


def _patch_job_leads(monkeypatch, *, mode: str) -> None:
    """Wspólna baza testowa: lista bez limitu wierszy (cudze świeże rekrutacje
    nie wypchną naszych) i z trybem automatu ustawionym przez test."""
    from app.services import new_job_leads, recruitment_allocation

    async def fixed_mode(_db) -> str:
        return mode

    monkeypatch.setattr(new_job_leads, "MAX_ROWS", 100_000)
    monkeypatch.setattr(recruitment_allocation, "effective_allocation_mode", fixed_mode)


@pytest.mark.asyncio
async def test_new_job_leads_show_who_leads_fresh_handoffs(
    api_client: AsyncClient, monkeypatch
) -> None:
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    seeded = await _seed_job_leads(hor_id, dl_id)
    jobs, people = seeded["jobs"], seeded["people"]
    try:
        _patch_job_leads(monkeypatch, mode="auto")
        hor = await _login(api_client, hor_creds)
        resp = await api_client.get("/api/board-tasks", headers=hor)
        assert resp.status_code == 200, resp.text
        listed = resp.json()["new_job_leads"]
        mine = {row["job_id"]: row for row in listed if row["job_id"] in jobs.values()}
        # Przekazane dawniej niż 7 dni, „Do przejrzenia” i zamknięte nie wchodzą.
        # Opublikowana bez przekazania wchodzi zawsze (H7, audyt 06.10.2026).
        assert set(mine) == {
            jobs[key]
            for key in (
                "auto",
                "manual",
                "owner",
                "proposed",
                "passive",
                "fresh_empty",
                "stale_empty",
                "not_handed_off",
            )
        }
        assert mine[jobs["not_handed_off"]]["pending_reason"] == "not_handed_off"
        assert mine[jobs["not_handed_off"]]["lead_user_id"] is None
        # Od najnowszego przekazania; nieprzekazane na końcu.
        handed = [r for r in listed if r["pending_reason"] != "not_handed_off"]
        handed_off = [datetime.fromisoformat(row["handed_off_at"]) for row in handed]
        assert handed_off == sorted(handed_off, reverse=True)
        assert listed[len(handed) :] == [
            r for r in listed if r["pending_reason"] == "not_handed_off"
        ]

        async with AsyncSessionLocal() as db:
            names = dict(
                (
                    await db.execute(
                        select(User.id, User.name).where(
                            User.id.in_([hor_id, dl_id, *people.values()])
                        )
                    )
                ).all()
            )

        auto = mine[jobs["auto"]]
        assert auto["title"] == f"BT leads tytuł roboczy {seeded['unique']}"
        assert auto["client_name"] == seeded["client_name"]
        assert (
            auto["category_id"],
            auto["category_name"],
            auto["category_slug"],
        ) == (
            seeded["category_id"],
            seeded["category_name"],
            seeded["category_slug"],
        )
        assert auto["participants"] == 2
        assert auto["priority_level"] == "p1"
        assert auto["delivery_lead_name"] == names[dl_id]
        assert auto["handed_off_at"] is not None
        assert (auto["lead_user_id"], auto["lead_name"], auto["lead_role"]) == (
            people["auto"],
            names[people["auto"]],
            "recruiter",
        )
        assert auto["lead_source"] == "auto"
        assert auto["assigned_by_name"] is None
        assert auto["proposed"] is False and auto["pending_reason"] is None

        manual = mine[jobs["manual"]]
        assert manual["title"] == f"BT leads manual {seeded['unique']}"
        assert (manual["lead_user_id"], manual["lead_role"]) == (
            people["manual"],
            "recruiter",
        )
        assert manual["lead_source"] == "manual"
        assert manual["assigned_by_name"] == names[hor_id]
        assert manual["participants"] == 0 and manual["category_id"] is None
        assert manual["priority_level"] == "p2"

        # Prowadzący wpisany ręcznie, bez wiersza przypisania.
        owner = mine[jobs["owner"]]
        assert (owner["lead_user_id"], owner["lead_source"]) == (
            people["owner"],
            "manual",
        )
        assert owner["proposed"] is False and owner["pending_reason"] is None

        # Sama propozycja automatu: pola opisują osobę proponowaną.
        proposed = mine[jobs["proposed"]]
        assert (proposed["lead_user_id"], proposed["lead_name"]) == (
            people["proposed"],
            names[people["proposed"]],
        )
        assert proposed["proposed"] is True
        assert proposed["lead_source"] == "auto"
        assert proposed["pending_reason"] is None

        # Nikt nie prowadzi — trzy różne powody.
        passive = mine[jobs["passive"]]
        assert passive["priority_level"] == "accepting"
        assert passive["pending_reason"] == "passive"
        assert mine[jobs["fresh_empty"]]["pending_reason"] == "assigning"
        assert mine[jobs["stale_empty"]]["pending_reason"] == "none"
        for key in ("passive", "fresh_empty", "stale_empty"):
            row = mine[jobs[key]]
            assert row["lead_user_id"] is None and row["lead_name"] is None
            assert row["lead_source"] is None and row["proposed"] is False

        # Automat tylko proponuje (albo jest wyłączony): świeżo przekazana
        # rekrutacja bez nikogo nie jest „w trakcie przydziału”.
        _patch_job_leads(monkeypatch, mode="shadow")
        resp = await api_client.get("/api/board-tasks", headers=hor)
        again = {row["job_id"]: row for row in resp.json()["new_job_leads"]}
        assert again[jobs["fresh_empty"]]["pending_reason"] == "none"
    finally:
        await _drop_job_leads(seeded)


@pytest.mark.asyncio
async def test_new_job_leads_reach_only_admin_and_head_of_recruitment(
    api_client: AsyncClient, monkeypatch
) -> None:
    hor_id, _ = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    _, rec_creds = await _seed_user(UserRole.recruiter)
    _, admin_creds = await _seed_user(UserRole.admin)
    seeded = await _seed_job_leads(hor_id, dl_id)
    try:
        _patch_job_leads(monkeypatch, mode="shadow")
        for creds in (dl_creds, rec_creds):
            headers = await _login(api_client, creds)
            resp = await api_client.get("/api/board-tasks", headers=headers)
            assert resp.status_code == 200, resp.text
            assert resp.json()["new_job_leads"] == []

        admin = await _login(api_client, admin_creds)
        resp = await api_client.get("/api/board-tasks", headers=admin)
        assert resp.status_code == 200, resp.text
        assert seeded["jobs"]["auto"] in {
            row["job_id"] for row in resp.json()["new_job_leads"]
        }
    finally:
        await _drop_job_leads(seeded)


@pytest.mark.asyncio
async def test_board_tasks_survive_a_failure_while_loading_job_leads(
    api_client: AsyncClient, monkeypatch
) -> None:
    from app.services import new_job_leads

    async def boom(_db, *, now):
        raise RuntimeError("job leads down")

    monkeypatch.setattr(new_job_leads, "load_new_job_leads", boom)
    _, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    resp = await api_client.get("/api/board-tasks", headers=hor)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_job_leads"] == []
    # Reszta kolejki liczy się normalnie.
    assert isinstance(body["cpro_to_send"], list)
