"""„Match” — DL wysyła osobę z przeglądu od razu do innych swoich rekrutacji.

Decyzja Artura 22.10.2026, warianty rekomendowane: portfel DL-a, połączone
rekrutacje tylko zaznaczone w przeglądzie, rekruter z A dostaje prośbę
o kontakt z kandydatem. Reguły: ``docs/claude/rekrutacja-tablica/dl-match-wyslij-tez-do.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.notification import Notification
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import dl_match
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world


@pytest_asyncio.fixture
async def api_client():
    from httpx import ASGITransport

    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def dl_skips_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VERIFIED_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "VERIFIED_MINIMUM_FIELDS_ENABLED", True)
    monkeypatch.setattr(settings, "DL_SKIPS_FILL_GATES", True)


# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _user(*roles: UserRole, uid: int = 7):
    return SimpleNamespace(
        id=uid, has_any_role=lambda *asked: bool(set(asked) & set(roles))
    )


def test_portfolio_is_own_jobs_and_portfolio_clients_for_a_delivery_lead() -> None:
    clause = dl_match.portfolio_clause(_user(UserRole.delivery_lead), [12, 3, 12])
    sql = str(clause.compile(compile_kwargs={"literal_binds": True}))
    assert "jobs.delivery_lead_id = 7" in sql
    assert "jobs.client_id IN (3, 12)" in sql
    only_own = dl_match.portfolio_clause(_user(UserRole.delivery_lead), [])
    assert "client_id" not in str(
        only_own.compile(compile_kwargs={"literal_binds": True})
    )


def test_admin_without_delivery_lead_role_is_not_narrowed() -> None:
    assert dl_match.portfolio_clause(_user(UserRole.admin), [1]) is None


def test_linked_jobs_first_then_by_score() -> None:
    jobs = [
        dl_match.MatchJob(
            job_id=3, title="C", client_name=None, client_reference=None, score=91
        ),
        dl_match.MatchJob(
            job_id=2,
            title="B",
            client_name=None,
            client_reference=None,
            score=None,
            linked=True,
        ),
        dl_match.MatchJob(
            job_id=1, title="A", client_name=None, client_reference=None, score=74
        ),
        dl_match.MatchJob(
            job_id=4, title="D", client_name=None, client_reference=None, score=91
        ),
    ]
    assert [j.job_id for j in dl_match.order_jobs(jobs)] == [2, 3, 4, 1]


def test_nordea_goes_to_the_cpro_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "55")
    assert dl_match.destination_for(55) == dl_match.DESTINATION_CPRO
    assert dl_match.destination_for(56) == dl_match.DESTINATION_CV_SENT
    stages = SimpleNamespace(cpro_id=10, cv_sent_id=11)
    assert dl_match.target_stage_id(stages, dl_match.DESTINATION_CPRO) == 10
    assert dl_match.target_stage_id(stages, dl_match.DESTINATION_CV_SENT) == 11
    assert dl_match.target_stage_id(None, dl_match.DESTINATION_CV_SENT) is None


def test_only_a_qc_refusal_triggers_the_override() -> None:
    from app.api.dl_match import _is_qc_failure

    assert _is_qc_failure(HTTPException(409, detail={"code": "CV_QC_FAILED"}))
    assert not _is_qc_failure(HTTPException(409, detail={"code": "OTHER"}))
    assert not _is_qc_failure(HTTPException(403, detail="Brak uprawnień"))


@pytest.mark.asyncio
async def test_month_match_handoffs_counts_processes_from_match() -> None:
    from app.services.kpi_panel import month_match_handoffs

    class _Db:
        params: dict = {}

        async def scalar(self, _sql, params):
            self.params = params
            return 4

    db = _Db()
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    assert await month_match_handoffs(db, user=SimpleNamespace(id=9), now=now) == 4
    assert db.params["uid"] == 9
    assert db.params["month_start"].day == 1


# ── Integracyjne ─────────────────────────────────────────────────────────────


async def _second_job(world: dict, *, delivery_lead_id: int | None) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"BT Java B {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=world["client_id"],
            pipeline_template_id=world["template_id"],
            delivery_lead_id=delivery_lead_id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _verified_in_a(world: dict, recruiter_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage=PipelineStage.verified,
                stage_def_id=world["defs"]["verified"],
                moved_by=recruiter_id,
                moved_at=datetime.now(timezone.utc) - timedelta(hours=1),
                expected_rate_value=150,
            )
        )
        await db.commit()


async def _drop(job_ids: list[int], user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await db.execute(
            delete(CandidateStage).where(CandidateStage.job_id.in_(job_ids))
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _send(client: AsyncClient, headers: dict, world: dict, job_b: int, rate=185):
    return await client.post(
        "/api/dl-match/send",
        headers=headers,
        json={
            "candidate_id": world["candidate_id"],
            "from_job_id": world["job_id"],
            "targets": [{"job_id": job_b, "client_rate_value": rate}],
        },
    )


async def _rows_in(job_id: int, candidate_id: int) -> list[CandidateStage]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CandidateStage)
                    .where(
                        CandidateStage.job_id == job_id,
                        CandidateStage.candidate_id == candidate_id,
                    )
                    .order_by(CandidateStage.moved_at, CandidateStage.id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_dl_sends_the_person_to_another_job_in_one_call(
    api_client: AsyncClient, dl_skips_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A → B: przepięcie z kopią źródła, „Zweryfikowany” DL-a, „CV wysłane”
    ze stawką; proces liczy się DL-owi, rekruter z A dostaje prośbę."""
    from app.models.recruitment_process import RecruitmentProcess

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=dl_id)
    try:
        await _verified_in_a(world, rec_id)
        resp = await _send(api_client, dl, world, job_b)
        assert resp.status_code == 200, resp.text
        [result] = resp.json()["results"]
        assert result["status"] == "sent", result
        assert result["destination"] == "cv_sent"

        rows = await _rows_in(job_b, world["candidate_id"])
        assert [r.stage for r in rows][-2:] == [
            PipelineStage.verified,
            PipelineStage.cv_sent,
        ]
        assert rows[-1].stage_def_id == world["defs"]["cv_sent"]
        assert float(rows[-1].client_rate_value) == 185.0
        assert all(r.moved_by == dl_id for r in rows[-2:])

        async with AsyncSessionLocal() as db:
            process = await db.scalar(
                select(RecruitmentProcess).where(
                    RecruitmentProcess.job_id == job_b,
                    RecruitmentProcess.candidate_id == world["candidate_id"],
                )
            )
            assert process.entry_source == "reassign"
            assert process.entry_meta["via"] == dl_match.MATCH_VIA
            assert process.entry_meta["from_job_id"] == world["job_id"]
            assert process.credit_user_id == dl_id
            ask = await db.scalar(
                select(Notification).where(Notification.user_id == rec_id)
            )
        assert ask is not None and ask.title.startswith("Daj znać")
    finally:
        await _drop([job_b], [rec_id, dl_id])
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_nordea_target_lands_in_the_cpro_queue(
    api_client: AsyncClient, dl_skips_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=dl_id)
    try:
        await _verified_in_a(world, rec_id)
        resp = await _send(api_client, dl, world, job_b, rate=172)
        assert resp.status_code == 200, resp.text
        [result] = resp.json()["results"]
        assert result["status"] == "sent", result
        assert result["destination"] == "cpro"
        rows = await _rows_in(job_b, world["candidate_id"])
        assert rows[-1].stage_def_id == world["defs"]["cpro"]
    finally:
        await _drop([job_b], [rec_id, dl_id])
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_job_outside_the_portfolio_is_refused_without_writes(
    api_client: AsyncClient, dl_skips_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    other_dl, _ = await _seed_user(UserRole.delivery_lead)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=other_dl)
    try:
        await _verified_in_a(world, rec_id)
        resp = await _send(api_client, dl, world, job_b)
        assert resp.status_code == 200, resp.text
        [result] = resp.json()["results"]
        assert result["status"] == "failed"
        assert "portfelu" in result["detail"]
        assert await _rows_in(job_b, world["candidate_id"]) == []
    finally:
        await _drop([job_b], [rec_id, dl_id, other_dl])
        await _cleanup(world, [rec_id, dl_id, other_dl])


@pytest.mark.asyncio
async def test_person_not_verified_in_the_source_job_is_refused(
    api_client: AsyncClient, dl_skips_on
) -> None:
    world = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=dl_id)
    try:
        resp = await _send(api_client, dl, world, job_b)
        assert resp.status_code == 422, resp.text
    finally:
        await _drop([job_b], [dl_id])
        await _cleanup(world, [dl_id])


@pytest.mark.asyncio
async def test_recruiter_cannot_use_match(api_client: AsyncClient) -> None:
    world = await _seed_world()
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    try:
        resp = await _send(api_client, rec, world, world["job_id"])
        assert resp.status_code == 403, resp.text
        listing = await api_client.get(
            f"/api/dl-match/candidates/{world['candidate_id']}",
            headers=rec,
            params={"from_job_id": world["job_id"]},
        )
        assert listing.status_code == 403, listing.text
    finally:
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_linked_job_is_listed_and_marked_even_without_a_score(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Połączona z A rekrutacja jest na liście i zaznaczona (wariant
    „Wysyłaj razem = zaznacza w przeglądzie”), także gdy ocena wektorowa nie
    działa (w testach Qdranta nie ma)."""
    from app.models.job_similar_link import JobSimilarLink

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=dl_id)
    job_c = await _second_job(world, delivery_lead_id=dl_id)
    try:
        await _verified_in_a(world, rec_id)
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    JobSimilarLink(job_id=world["job_id"], similar_job_id=job_b),
                    JobSimilarLink(job_id=job_b, similar_job_id=world["job_id"]),
                ]
            )
            db.add(
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=job_c,
                    stage=PipelineStage.screening,
                    stage_def_id=world["defs"]["screening"],
                    moved_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        resp = await api_client.get(
            f"/api/dl-match/candidates/{world['candidate_id']}",
            headers=dl,
            params={"from_job_id": world["job_id"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        linked = [j for j in body["jobs"] if j["job_id"] == job_b]
        assert linked and linked[0]["linked"] is True
        assert linked[0]["sendable"] is True
        assert linked[0]["destination"] == "cv_sent"
        assert [a["job_id"] for a in body["already_in"]] == [job_c]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(JobSimilarLink).where(
                    JobSimilarLink.job_id.in_([world["job_id"], job_b])
                )
            )
            await db.commit()
        await _drop([job_b, job_c], [rec_id, dl_id])
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_qc_refusal_is_overridden_like_send_anyway(
    api_client: AsyncClient, dl_skips_on, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Z włączonym QC: osoba bez CV firmowego w B nie przechodzi QC, DL wysyła
    mimo to (obejście zapisane jak „Wyślij mimo to”) — a QC liczone we własnej
    sesji nie czeka na blokady dodania."""
    from app.models.cv_qc_run import CvQcRun

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    job_b = await _second_job(world, delivery_lead_id=dl_id)
    try:
        await _verified_in_a(world, rec_id)
        resp = await _send(api_client, dl, world, job_b)
        assert resp.status_code == 200, resp.text
        [result] = resp.json()["results"]
        assert result["status"] == "sent", result
        assert result["qc"] in ("passed", "overridden")
        if result["qc"] == "overridden":
            async with AsyncSessionLocal() as db:
                runs = (
                    await db.scalars(select(CvQcRun).where(CvQcRun.job_id == job_b))
                ).all()
            assert runs
    finally:
        from app.models.cv_qc_run import CvQcRun

        async with AsyncSessionLocal() as db:
            await db.execute(delete(CvQcRun).where(CvQcRun.job_id == job_b))
            await db.commit()
        await _drop([job_b], [rec_id, dl_id])
        await _cleanup(world, [rec_id, dl_id])
