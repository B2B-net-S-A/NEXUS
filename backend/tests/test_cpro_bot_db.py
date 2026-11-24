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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
from app.services.cpro_bot import items as bot_items
from app.services.cv_approved_docx import render_approved_docx
from app.services.cv_document_assets import default_template
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
@pytest.mark.parametrize(
    "account_id", [14, 27, 32], ids=["igor", "marcin", "dominik-via-marcin"]
)
async def test_bot_sends_queued_card_and_moves_it_like_wrzucone(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, account_id: int
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
    other_dl_id, _ = await _seed_user(UserRole.delivery_lead)
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    users = [hor_id, rec_id, dl_id, other_dl_id, admin_id]
    account_name, vault_entry = bot_items.CPRO_ACCOUNTS[account_id]
    other_account = bot_items.CPRO_ACCOUNTS[27 if account_id == 14 else 14]
    monkeypatch.setattr(
        bot_items,
        "CPRO_ACCOUNTS",
        {dl_id: (account_name, vault_entry), other_dl_id: other_account},
    )
    cid, job_id = world["candidate_id"], world["job_id"]
    unique = uuid.uuid4().hex[:6]
    other_job_id = None
    run_ids: list[int] = []
    frozen_docx = render_approved_docx(WHY_HTML, default_template())
    pdf_bytes = b"%PDF-1.7\nroute transport fixture"
    converter = AsyncMock(return_value=pdf_bytes)
    monkeypatch.setattr("app.api.integrations_cpro_bot.pdf_from_docx", converter)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                client_reference="42511",
                location="Gdynia, Gdańsk lub Warszawa",
                onsite_days_per_week=3,
                delivery_lead_id=dl_id,
            )
        )
        other = Job(
            title=f"KYC drugi {unique}",
            location="Gdańsk",
            status=JobStatus.published,
            client_id=world["client_id"],
            pipeline_template_id=world["template_id"],
            client_reference="42480",
            delivery_lead_id=other_dl_id,
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
                        docx_content=frozen_docx,
                        docx_sha256="1" * 64,
                        docx_filename="B2B_#KYC_Ewa.docx",
                        approved_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

            # Nawet kompletna karta z danymi od innego DL-a nie może dostać
            # jego konta, gdy rekrutacja docelowa nie ma znanego DL-a.
            for missing_owner in (None, admin_id):
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Job)
                        .where(Job.id == job_id)
                        .values(delivery_lead_id=missing_owner)
                    )
                    await db.commit()
                    now = datetime.now(timezone.utc)
                    blocked = await bot_items.load_items(
                        db, now=now, today=business_date(now), stage_ids=[queued.id]
                    )
                    assert len(blocked) == 1
                    assert blocked[0].payload is None
                    assert bot_items.BLOCK_NO_CPRO_ACCOUNT in blocked[0].blockers
                    with pytest.raises(flow.NotReady, match="Delivery Lead"):
                        await flow.start_chosen(
                            db,
                            [queued.id],
                            now=now,
                            today=business_date(now),
                            submit=False,
                        )
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Job).where(Job.id == job_id).values(delivery_lead_id=dl_id)
                )
                await db.commit()

            # Automatyczne szkice są widoczne i można je bezpiecznie zlecać,
            # mimo że dawna flaga wysyłki pozostaje wyłączona.
            with monkeypatch.context() as auto:
                auto.setattr(settings, "CPRO_BOT_ENABLED", False)
                auto.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", True)
                draft_view = (
                    await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
                ).json()
                draft_group = next(
                    g for g in draft_view["jobs"] if g["job_id"] == job_id
                )
                draft_item = next(
                    i for i in draft_group["items"] if i["candidate_id"] == cid
                )
                assert draft_view["bot"]["mode"] == "draft"
                assert draft_view["bot"]["drafts_today"] == 0
                assert draft_view["bot"]["awaiting_review"] == 0
                assert draft_item["bot"]["mode"] == "draft"
                retry = AsyncMock(
                    return_value=SimpleNamespace(id=999, status="started")
                )
                auto.setattr(flow, "start_chosen", retry)
                response = await api_client.post(
                    f"/api/board-tasks/cpro/bot/{queued.id}/retry", headers=rec
                )
                assert response.status_code == 200, response.text
                assert retry.await_args.kwargs["submit"] is False

            with monkeypatch.context() as auto:
                auto.setattr(settings, "CPRO_BOT_ENABLED", False)
                auto.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", True)
                now = datetime.now(timezone.utc)
                async with AsyncSessionLocal() as db:
                    receipt, _ = runs.new_run(
                        [{"ref": queued.id, "offer": {}}], now=now, submit=False
                    )
                    receipt.status, receipt.token_hash, receipt.received_at = (
                        "received",
                        None,
                        now,
                    )
                    receipt.report = {
                        "items": {
                            str(queued.id): {
                                "outcome": "draft",
                                "cpro_status": "DRAFT",
                                "offer_url": "https://nordea.onevms.se/offer/42",
                            }
                        },
                        "counts": {"draft": 1},
                    }
                    db.add(receipt)
                    await db.commit()
                    run_ids.append(receipt.id)
                review_view = (
                    await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
                ).json()
                review_group = next(
                    g for g in review_view["jobs"] if g["job_id"] == job_id
                )
                review_item = next(
                    i for i in review_group["items"] if i["candidate_id"] == cid
                )
                assert review_view["bot"]["mode"] == "draft"
                assert review_view["bot"]["drafts_today"] == 1
                assert review_view["bot"]["awaiting_review"] == 1
                assert review_item["bot"]["state"] == "draft"
                assert (
                    review_item["bot"]["offer_url"]
                    == "https://nordea.onevms.se/offer/42"
                )
                assert review_item["bot"]["retry_allowed"] is False
                refused = await api_client.post(
                    f"/api/board-tasks/cpro/bot/{queued.id}/retry", headers=rec
                )
                assert refused.status_code == 409
                for reason in ("draft_unconfirmed", "submit_disallowed"):
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(CproBotRun)
                            .where(CproBotRun.id == receipt.id)
                            .values(
                                report={
                                    "items": {
                                        str(queued.id): {
                                            "outcome": "failed",
                                            "reason": reason,
                                        }
                                    }
                                }
                            )
                        )
                        await db.commit()
                    uncertain_view = (
                        await api_client.get("/api/board-tasks/cpro/queue", headers=rec)
                    ).json()
                    uncertain_group = next(
                        g for g in uncertain_view["jobs"] if g["job_id"] == job_id
                    )
                    uncertain_item = next(
                        i for i in uncertain_group["items"] if i["candidate_id"] == cid
                    )
                    assert uncertain_item["bot"]["state"] == "failed"
                    assert uncertain_item["bot"]["retry_allowed"] is False
                    assert uncertain_item["bot"]["message"]
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        delete(CproBotRun).where(CproBotRun.id == receipt.id)
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
            envelope = sent[0]
            assert set(envelope) == {
                "run_id",
                "kind",
                "token",
                "task_url",
                "schema_version",
            }
            assert envelope["schema_version"] == 2
            assert envelope["run_id"] == run_id
            assert len(json.dumps(envelope).encode("utf-8")) < 512
            token = envelope["token"]
            task_url = f"/api/integrations/cpro-bot/runs/{run_id}/task"
            assert envelope["task_url"].endswith(task_url)
            assert (await api_client.get(task_url)).status_code == 401
            assert (
                await api_client.get(task_url, headers={"X-Run-Token": "zly"})
            ).status_code == 401
            task = await api_client.get(task_url, headers={"X-Run-Token": token})
            assert task.status_code == 200, task.text
            assert task.headers["cache-control"] == "private, no-store"
            body = task.json()
            assert body["schema_version"] == 2 and body["run_id"] == run_id
            assert body["submit"] is True
            assert "token" not in body
            offer = body["items"][0]["offer"]
            # Warunki pochodzą z drugiej rekrutacji, ale konto zawsze z DL-a
            # rekrutacji docelowej, a nie DL-a źródła ani osoby od Cpro.
            assert body["items"][0]["cpro_account"] == {
                "delivery_lead_id": dl_id,
                "delivery_lead_name": account_name,
                "vault_entry": vault_entry,
            }
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
            assert offer["cv_file_name"] == "B2B_KYC_Ewa.pdf"
            assert offer["cv_format"] == "pdf" and offer["cv_version"] == 1
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
            assert cv.content == pdf_bytes
            assert cv.headers["content-type"] == "application/pdf"
            assert "B2B_KYC_Ewa.pdf" in cv.headers["content-disposition"]
            assert cv.headers["x-cv-version"] == "1"
            converter.assert_awaited_once_with(frozen_docx)
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
            assert (
                await api_client.get(task_url, headers={"X-Run-Token": token})
            ).status_code == 401

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


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "used"])
async def test_task_rejects_expired_or_used_run_token(
    api_client: AsyncClient, state: str
) -> None:
    now = datetime.now(timezone.utc)
    run, token = runs.new_run(
        [{"ref": 101, "offer": {}}],
        now=now - runs.TOKEN_TTL - timedelta(minutes=1) if state == "expired" else now,
        submit=False,
    )
    if state == "used":
        run.status = "received"
        run.token_hash = None
    async with AsyncSessionLocal() as db:
        db.add(run)
        await db.commit()
        run_id = run.id
    try:
        response = await api_client.get(
            f"/api/integrations/cpro-bot/runs/{run_id}/task",
            headers={"X-Run-Token": token},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": runs.INVALID_TOKEN_DETAIL}
        assert "items" not in response.json()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CproBotRun).where(CproBotRun.id == run_id))
            await db.commit()
