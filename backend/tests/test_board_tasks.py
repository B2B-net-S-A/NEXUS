"""Kolejka „Czeka na Ciebie" (0348): DZ, do wysłania do Cpro, wysłane do Cpro.

Decyzje Artura 22.09.2026: DZ zatwierdza każdy DL i Dominik (Head of
Recruitment); u Nordei „CV wysłane" = wysłane do Cpro; osobę, która wysyła do
Cpro, typujemy za każdym razem; rano jeden zbiorczy dzwonek.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
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

# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _def(id_: int, name: str, order: int, enum: str | None, terminal: bool = False):
    return SimpleNamespace(
        id=id_,
        name=name,
        order=order,
        legacy_enum_value=enum,
        is_terminal=terminal,
    )


def test_badge_stages_are_never_hosts_even_with_host_codes() -> None:
    """„Przepuszczony przez DZ" ma kod interview, „NORDEA: Wysłać do Cpro"
    kod screening — kolejka i tak rozpoznaje je po nazwie."""
    stages = svc.classify_template(
        [
            _def(1, "Screening", 1, "screening"),
            _def(2, "Kandydat Zweryfikowany", 2, "verified"),
            _def(3, "Przepuszczony przez DZ", 3, "interview"),
            _def(4, "NORDEA: Wysłać do Cpro", 4, "screening"),
            _def(5, "Wysłany do Klienta", 5, "cv_sent"),
            _def(6, "Odrzucony", 9, "rejected", terminal=True),
        ]
    )
    assert stages.verified_ids == frozenset({2})
    assert stages.dz_id == 3
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


def test_delivery_lead_sees_dz_only_in_own_portfolio() -> None:
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_DZ, stage_id=1, client_id=7),
            _task(svc.KIND_DZ, stage_id=2, client_id=8),
            _task(svc.KIND_DZ, stage_id=3, client_id=9, delivery_lead_id=50),
        ]
    )
    dl = _user(50, UserRole.delivery_lead)
    mine = svc.tasks_for_user(snap, dl, portfolio=frozenset({7}))
    assert [t.stage_id for t in mine[svc.KIND_DZ]] == [1, 3]

    hor = _user(60, UserRole.head_of_recruitment)
    assert len(svc.tasks_for_user(snap, hor, portfolio=frozenset())[svc.KIND_DZ]) == 3


def test_recruiter_sees_only_own_cpro_tasks_and_no_dz() -> None:
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_DZ, stage_id=1),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=70),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=3, assignee_id=None),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=4, assignee_id=71),
            _task(svc.KIND_CPRO_SENT, stage_id=5, moved_by=70),
            _task(svc.KIND_CPRO_SENT, stage_id=6, moved_by=71),
        ]
    )
    mine = svc.tasks_for_user(
        snap, _user(70, UserRole.recruiter), portfolio=frozenset()
    )
    assert mine[svc.KIND_DZ] == []
    assert [t.stage_id for t in mine[svc.KIND_CPRO_TO_SEND]] == [2]
    assert [t.stage_id for t in mine[svc.KIND_CPRO_SENT]] == [5]


def test_hor_sees_own_cpro_first_then_unassigned_then_others() -> None:
    old = datetime.now(timezone.utc) - timedelta(days=3)
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_CPRO_TO_SEND, stage_id=1, assignee_id=71, since=old),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=2, assignee_id=None, since=old),
            _task(svc.KIND_CPRO_TO_SEND, stage_id=3, assignee_id=60),
        ]
    )
    mine = svc.tasks_for_user(
        snap, _user(60, UserRole.head_of_recruitment), portfolio=frozenset()
    )
    assert [t.stage_id for t in mine[svc.KIND_CPRO_TO_SEND]] == [3, 2, 1]


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


def test_dl_review_is_visible_like_dz_and_never_to_recruiters() -> None:
    snap = svc.BoardTaskSnapshot(
        tasks=[
            _task(svc.KIND_DL_REVIEW, stage_id=1, client_id=7),
            _task(svc.KIND_DL_REVIEW, stage_id=2, client_id=8),
            _task(svc.KIND_DL_REVIEW, stage_id=3, client_id=9, delivery_lead_id=50),
        ]
    )
    dl = _user(50, UserRole.delivery_lead)
    mine = svc.tasks_for_user(snap, dl, portfolio=frozenset({7}))
    assert [t.stage_id for t in mine[svc.KIND_DL_REVIEW]] == [1, 3]
    assert mine[svc.KIND_DZ] == []

    hor = _user(60, UserRole.head_of_recruitment)
    assert (
        len(svc.tasks_for_user(snap, hor, portfolio=frozenset())[svc.KIND_DL_REVIEW])
        == 3
    )
    rec = _user(70, UserRole.recruiter)
    assert (
        svc.tasks_for_user(snap, rec, portfolio=frozenset({7}))[svc.KIND_DL_REVIEW]
        == []
    )


@pytest.mark.parametrize(
    ("line", "text"),
    [
        (svc.DigestLine(dl_review=1), "1 osoba czeka na Twój przegląd"),
        (
            svc.DigestLine(dl_review=5, dz=2),
            "5 osób czeka na Twój przegląd · 2 osoby czekają na DZ",
        ),
        (svc.DigestLine(dz=1), "1 osoba czeka na DZ"),
        (svc.DigestLine(dz=3), "3 osoby czekają na DZ"),
        (
            svc.DigestLine(dz=12, cpro_mine=2),
            "12 osób czeka na DZ · 2 do wysłania przez Ciebie do Cpro",
        ),
        (svc.DigestLine(cpro_unassigned=1), "1 do Cpro bez wytypowanej osoby"),
    ],
)
def test_digest_message_is_one_polish_sentence(line: svc.DigestLine, text: str) -> None:
    assert svc.digest_message(line) == text


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
                (
                    "dz",
                    "Przepuszczony przez DZ",
                    "interview",
                    StageCategoryEnum.internal,
                ),
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


@pytest.mark.asyncio
async def test_dz_then_cpro_assignment_then_sent_flows_through_the_queue(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    try:
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={"candidate_id": cid, "job_id": jid, "stage_def_id": defs["verified"]},
        )
        assert moved.status_code == 200, moved.text

        # 1. Czeka na DZ — HoR widzi, rekruter nie.
        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        dz = _rows(queue, "dz", cid)
        assert len(dz) == 1 and dz[0]["target_stage_def_id"] == defs["dz"]
        assert queue["can_approve_dz"] is True
        rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
        assert _rows(rec_queue, "dz", cid) == []

        # Osoba wysyłająca dozwolona wyłącznie przy „Gotowy do Cpro”.
        wrong = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["dz"],
                "task_assignee_id": rec_id,
                "expected_state_version": dz[0]["process_state_version"],
            },
        )
        assert wrong.status_code == 422, wrong.text

        approved = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["dz"],
                "expected_state_version": dz[0]["process_state_version"],
            },
        )
        assert approved.status_code == 200, approved.text
        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert _rows(queue, "dz", cid) == []

        # 2. Gotowy do Cpro z wytypowanym rekruterem spoza zespołu.
        ready = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["cpro"],
                "task_assignee_id": rec_id,
            },
        )
        assert ready.status_code == 200, ready.text
        assert ready.json()["task_assignee_id"] == rec_id
        async with AsyncSessionLocal() as db:
            collab = await db.scalar(
                select(JobCollaborator.id).where(
                    JobCollaborator.job_id == jid, JobCollaborator.user_id == rec_id
                )
            )
        assert collab is not None, "wytypowany rekruter musi móc przesunąć kartę"

        rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
        todo = _rows(rec_queue, "cpro_to_send", cid)
        assert len(todo) == 1
        assert todo[0]["assignee_id"] == rec_id
        assert todo[0]["target_stage_def_id"] == defs["cv_sent"]

        kanban = (
            await api_client.get(f"/api/pipeline/kanban/{jid}", headers=hor)
        ).json()
        cards = [
            i for c in kanban["columns"] for i in c["items"] if i["candidate_id"] == cid
        ]
        assert cards[0]["task_assignee_id"] == rec_id
        assert cards[0]["task_assignee_name"]

        # Rekruter z zespołu nie może wprowadzić do rekrutacji osoby spoza niej
        # (zespół zmienia admin / DL / HoR) — 422, bez zmian.
        outsider_id, _ = await _seed_user(UserRole.sourcer)
        refused = await api_client.patch(
            f"/api/board-tasks/cpro/{todo[0]['stage_id']}/assignee",
            headers=rec,
            json={"assignee_id": outsider_id},
        )
        assert refused.status_code == 422, refused.text
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(JobCollaborator.id).where(
                        JobCollaborator.job_id == jid,
                        JobCollaborator.user_id == outsider_id,
                    )
                )
                is None
            )

        # Zmiana osoby — HoR przejmuje.
        swap = await api_client.patch(
            f"/api/board-tasks/cpro/{todo[0]['stage_id']}/assignee",
            headers=hor,
            json={"assignee_id": hor_id},
        )
        assert swap.status_code == 200, swap.text
        rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
        assert _rows(rec_queue, "cpro_to_send", cid) == []

        # 3. Wysłane do Cpro = „CV wysłane" u Nordei.
        sent = await api_client.post(
            "/api/pipeline/move",
            headers=rec,
            json={"candidate_id": cid, "job_id": jid, "stage_def_id": defs["cv_sent"]},
        )
        assert sent.status_code == 200, sent.text
        rec_queue = (await api_client.get("/api/board-tasks", headers=rec)).json()
        assert len(_rows(rec_queue, "cpro_sent", cid)) == 1

        # Zmiana osoby na nieaktualnym wierszu → 409.
        stale = await api_client.patch(
            f"/api/board-tasks/cpro/{todo[0]['stage_id']}/assignee",
            headers=hor,
            json={"assignee_id": rec_id},
        )
        assert stale.status_code == 409, stale.text
    finally:
        await _cleanup(world, [hor_id, rec_id])


@pytest.mark.asyncio
async def test_cpro_queue_ignores_non_nordea_clients(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    try:
        # Poza Nordeą „CV wysłane" to ruch Delivery Leada ze stawką do klienta.
        for headers, key, extra in (
            (hor, "verified", {}),
            (
                dl,
                "cv_sent",
                {
                    "client_rate_value": "180",
                    "client_rate_unit": "hourly",
                    "client_rate_currency": "PLN",
                },
            ),
        ):
            r = await api_client.post(
                "/api/pipeline/move",
                headers=headers,
                json={
                    "candidate_id": cid,
                    "job_id": jid,
                    "stage_def_id": defs[key],
                    **extra,
                },
            )
            assert r.status_code == 200, r.text
        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert _rows(queue, "cpro_sent", cid) == []
        # Wysłany do klienta nie czeka już na przegląd DL.
        assert _rows(queue, "dl_review", cid) == []
    finally:
        await _cleanup(world, [hor_id, dl_id])


@pytest.mark.asyncio
async def test_dl_review_queue_for_clients_other_than_nordea(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline v4: poza Nordeą zweryfikowany czeka na przegląd DL (nie na DZ).

    Wiersz niesie cel „CV wysłane", etap „Odrzucony", kto zweryfikował i
    migawkę stawki z wiersza weryfikacji — także wtedy, gdy najnowszym
    wierszem jest już etap DZ (odznaka w tej samej kolumnie).
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
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": defs["verified"],
                "expected_rate_value": "140",
                "expected_rate_unit": "hourly",
                "expected_rate_currency": "PLN",
            },
        )
        assert moved.status_code == 200, moved.text

        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert _rows(queue, "dz", cid) == []
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
        assert queue["can_send_to_client"] is False
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

        # Etap DZ to odznaka tej samej kolumny — osoba dalej czeka na przegląd,
        # a weryfikacja i stawka idą z wiersza „Zweryfikowany".
        dz = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={"candidate_id": cid, "job_id": jid, "stage_def_id": defs["dz"]},
        )
        assert dz.status_code == 200, dz.text
        after_dz = _rows(
            (await api_client.get("/api/board-tasks", headers=hor)).json(),
            "dl_review",
            cid,
        )
        assert len(after_dz) == 1
        assert after_dz[0]["stage_id"] != row["stage_id"]
        assert after_dz[0]["verified_by_id"] == hor_id
        assert after_dz[0]["expected_rate_value"] == 140.0

        # Poranny skrót liczy przegląd DL.
        async with AsyncSessionLocal() as db:
            snapshot = await svc.load_snapshot(db)
            counts = await svc.digest_counts(db, snapshot)
        assert counts[dl_in_id].dl_review >= 1
        assert dl_out_id not in counts
    finally:
        await _cleanup(world, [hor_id, rec_id, dl_in_id, dl_out_id])


@pytest.mark.asyncio
async def test_nordea_keeps_dz_and_has_no_dl_review(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    cid, jid, defs = world["candidate_id"], world["job_id"], world["defs"]
    try:
        r = await api_client.post(
            "/api/pipeline/move",
            headers=hor,
            json={"candidate_id": cid, "job_id": jid, "stage_def_id": defs["verified"]},
        )
        assert r.status_code == 200, r.text
        queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
        assert len(_rows(queue, "dz", cid)) == 1
        assert _rows(queue, "dl_review", cid) == []
    finally:
        await _cleanup(world, [hor_id])
