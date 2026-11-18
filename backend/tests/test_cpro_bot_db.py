"""Bot Cpro na bazie: kolejka → zlecenie → CV na token → raport → karta wysłana.

Reguła: ``docs/claude/integracje/cpro-bot-grok.md``. Karta przechodzi drogę
z produkcji: Delivery Lead akceptuje ze stawką do Cpro, bot dostaje dane
z Warunków (narodowość i „pracował u klienta” z karty tej osoby w drugiej
rekrutacji Nordei — przypadek osoby wrzuconej na kilka requestów bez
screeningu), raport „submitted” przesuwa kartę jak „✓ Wrzucone”.
Wymaga Postgresa (CI).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cpro_bot import CproBotRun
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job, JobStatus
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services.cpro_bot import flow, runs
from tests.test_board_tasks import (
    CPRO_RATE,
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
    seed_entry_row,
)

WHY_HTML = (
    '<h2 data-cv-section="why_points">WHY OUR CANDIDATE?</h2>'
    "<ul><li><p>Over 6 years at Nordea Bank</p></li>"
    "<li><p>Practical SQL skills</p></li></ul>"
)


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


async def _latest(candidate_id: int, job_id: int) -> CandidateStage:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )


@pytest.mark.asyncio
async def test_bot_sends_queued_card_and_moves_it_like_wrzucone(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
    monkeypatch.setattr(
        settings, "GROK_BOT_CPRO_WEBHOOK_URL", "https://bot.example/cpro"
    )
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_KEY", "test-key")
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    users = [hor_id, rec_id, dl_id, admin_id]
    cid, job_id = world["candidate_id"], world["job_id"]
    unique = uuid.uuid4().hex[:6]
    other_job_id = None
    run_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                client_reference="42511",
                location="Gdynia, Gdańsk lub Warszawa",
                onsite_days_per_week=3,
            )
        )
        other = Job(
            title=f"KYC drugi {unique}",
            location="Gdańsk",
            status=JobStatus.published,
            client_id=world["client_id"],
            pipeline_template_id=world["template_id"],
            client_reference="42480",
        )
        db.add(other)
        await db.flush()
        other_job_id = other.id
        at = datetime.now(timezone.utc).isoformat()
        db.add_all(
            [
                RecommendationCard(
                    candidate_id=cid,
                    job_id=job_id,
                    fields_manual={"location": {"raw": "Gdynia", "at": at}},
                ),
                RecommendationCard(
                    candidate_id=cid,
                    job_id=other_job_id,
                    fields_manual={
                        "nationality": {"raw": "Austria", "at": at},
                        "worked_at_client": {"raw": "UoP", "value": "uop", "at": at},
                    },
                ),
            ]
        )
        await db.commit()
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    rec = await _login(api_client, rec_creds)
    admin = await _login(api_client, admin_creds)
    try:
        async with restore_cpro_sender():
            await _move(api_client, hor, world, "verified")
            await _move(api_client, hor, world, "qc")
            await _move(api_client, dl, world, "cpro", **CPRO_RATE)
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": rec_id, "until": None},
            )
            assert put.status_code == 200, put.text
            queued = await _latest(cid, job_id)

            # Bez CV firmowego bot czeka i mówi dlaczego.
            view = (
                await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
            ).json()
            group = next(g for g in view["jobs"] if g["job_id"] == job_id)
            item = next(i for i in group["items"] if i["candidate_id"] == cid)
            assert item["bot"]["state"] == "blocked"
            assert "Brak zatwierdzonego CV firmowego" in item["bot"]["blockers"]
            assert view["bot"]["configured"] is True

            async with AsyncSessionLocal() as db:
                csv = await db.scalar(
                    select(CandidateStageCV).where(
                        CandidateStageCV.candidate_stage_id == queued.id
                    )
                )
                if csv is None:
                    csv = CandidateStageCV(
                        candidate_stage_id=queued.id, candidate_id=cid, job_id=job_id
                    )
                    db.add(csv)
                csv.branded_status = "finalized"
                csv.branded_version = 1
                csv.branded_finalized_at = datetime.now(timezone.utc)
                await db.flush()
                db.add(
                    CvDocumentVersion(
                        candidate_stage_cv_id=csv.id,
                        version=1,
                        content_html=WHY_HTML,
                        content_sha256="0" * 64,
                        docx_content=b"PK-docx-bytes",
                        docx_sha256="1" * 64,
                        docx_filename="B2B_#KYC_Ewa.docx",
                        approved_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

            sent: list[dict] = []

            def bot(request: httpx.Request) -> httpx.Response:
                assert request.headers["authorization"] == "Bearer test-key"
                sent.append(json.loads(request.content))
                return httpx.Response(200)

            client = httpx.AsyncClient(transport=httpx.MockTransport(bot))
            started = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                due = await flow.due_items(db, now=now, today=business_date(now))
                mine = [i for i in due if i.stage_id == queued.id]
                assert len(mine) == 1 and mine[0].payload is not None
                run = await flow.start_for(db, mine, now=now, client=client)
                assert run is not None and run.status == "started"
                run_id = run.id
                run_ids.append(run_id)
            body = sent[0]
            token = body["token"]
            offer = body["items"][0]["offer"]
            assert body["items"][0]["request_number"] == "42511"
            assert body["items"][0]["candidate"]["citizenship"] == "Austria"
            assert body["items"][0]["data_from"] == ["42480"]
            assert offer["rate"] == "158"
            assert offer["physical_location"] == (
                "Gdynia, willing to come to the Nordea office in Gdynia 3x/week, "
                "available ASAP, a former employee at Nordea"
            )
            assert (
                offer["motivation"]
                == "- Over 6 years at Nordea Bank\n- Practical SQL skills"
            )
            assert offer["cv_file_name"] == "B2B_KYC_Ewa.docx"
            assert "cards" not in body

            view = (
                await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
            ).json()
            group = next(g for g in view["jobs"] if g["job_id"] == job_id)
            item = next(i for i in group["items"] if i["candidate_id"] == cid)
            assert item["bot"]["state"] == "working"
            assert view["bot"]["working"] is True

            cv_url = f"/api/integrations/cpro-bot/runs/{run_id}/cv/{queued.id}"
            assert (await api_client.get(cv_url)).status_code == 401
            assert (
                await api_client.get(cv_url, headers={"X-Run-Token": "zly"})
            ).status_code == 401
            other_stage = await api_client.get(
                f"/api/integrations/cpro-bot/runs/{run_id}/cv/{queued.id + 999999}",
                headers={"X-Run-Token": token},
            )
            assert other_stage.status_code == 404
            cv = await api_client.get(cv_url, headers={"X-Run-Token": token})
            assert cv.status_code == 200, cv.text
            assert cv.content == b"PK-docx-bytes"
            assert "B2B_KYC_Ewa.docx" in cv.headers["content-disposition"]
            # Wydanie CV botowi zostawia ślad jak API v1: dziennik i audyt osoby.
            async with AsyncSessionLocal() as db:
                traces = (
                    await db.scalars(
                        select(Activity.action).where(
                            Activity.action.in_(
                                ("cv_file_downloaded", "cv_downloaded")
                            ),
                            Activity.created_at >= started,
                        )
                    )
                ).all()
            assert {"cv_file_downloaded", "cv_downloaded"} <= set(traces)

            report = await api_client.post(
                f"/api/integrations/cpro-bot/runs/{run_id}",
                headers={"X-Run-Token": token},
                json={
                    "items": [
                        {
                            "ref": queued.id,
                            "outcome": "submitted",
                            "cpro_status": "SELECTION",
                            "offer_url": "https://nordea.onevms.se/nordea/vendor/OfferController?action=view&id=1",
                        }
                    ]
                },
            )
            assert report.status_code == 200, report.text
            assert report.json()["submitted"] == 1 and report.json()["moved"] == 1
            latest = await _latest(cid, job_id)
            assert latest.stage_def_id == world["defs"]["cv_sent"]
            again = await api_client.post(
                f"/api/integrations/cpro-bot/runs/{run_id}",
                headers={"X-Run-Token": token},
                json={"items": []},
            )
            assert again.status_code == 401

            async with AsyncSessionLocal() as db:
                stored = await db.get(CproBotRun, run_id)
                assert stored.status == "received" and stored.token_hash is None
                assert stored.report["items"][str(queued.id)]["moved"] is True
                states = await runs.item_states(
                    db, [queued.id], now=datetime.now(timezone.utc)
                )
                assert states[queued.id].state == "submitted"
                assert not runs.due_for_bot(
                    states[queued.id], now=datetime.now(timezone.utc)
                )
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id.in_(run_ids)))
            csv_ids = select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_id == cid
            )
            await db.execute(
                delete(CvDocumentVersion).where(
                    CvDocumentVersion.candidate_stage_cv_id.in_(csv_ids)
                )
            )
            await db.execute(
                delete(CandidateStageCV).where(CandidateStageCV.candidate_id == cid)
            )
            await db.execute(
                delete(RecommendationCard).where(RecommendationCard.candidate_id == cid)
            )
            if other_job_id is not None:
                await db.execute(delete(Job).where(Job.id == other_job_id))
            await db.commit()
        await _cleanup(world, users)


@pytest.mark.asyncio
async def test_retry_route_refuses_blocked_card_and_disabled_bot(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    try:
        monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", False)
        off = await api_client.post("/api/board-tasks/cpro/bot/1/retry", headers=hor)
        assert off.status_code == 409 and "wyłączony" in off.json()["detail"]
        monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", True)
        async with restore_cpro_sender():
            await clear_cpro_sender()
            refused = await api_client.post(
                "/api/board-tasks/cpro/bot/1/retry", headers=rec
            )
            assert refused.status_code == 403
            gone = await api_client.post(
                "/api/board-tasks/cpro/bot/1/retry", headers=hor
            )
            assert gone.status_code == 409
            assert "nie ma już w kolejce" in gone.json()["detail"]
    finally:
        await _cleanup_users([hor_id, rec_id])


async def _cleanup_users(user_ids: list[int]) -> None:
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()
