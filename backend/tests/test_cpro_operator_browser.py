"""Human Cpro drafts use real NEXUS sessions and never delegate a run token."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cpro_bot import CproBotRun
from app.models.cv_document_version import CvDocumentVersion
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import cpro_sender
from app.services.cpro_bot import items as bot_items
from app.services.cpro_bot import runs
from app.services.cv_approved_docx import render_approved_docx
from app.services.cv_document_assets import default_template
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    restore_cpro_sender,
)

BASE = "/api/board-tasks/cpro/operator"
HTML = (
    '<h2 data-cv-section="why_points">WHY OUR CANDIDATE?</h2>'
    "<ul><li><p>Synthetic SQL experience for the operator test.</p></li></ul>"
)


def _keys(value):
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


@pytest_asyncio.fixture
async def browser_world(monkeypatch):
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    users = {}
    credentials = {}
    for key, role in (
        ("operator", UserRole.recruiter),
        ("other_operator", UserRole.recruiter),
        ("admin", UserRole.admin),
        ("other_admin", UserRole.admin),
        ("dl", UserRole.delivery_lead),
        ("read_only", UserRole.automation),
        ("external", UserRole.user),
    ):
        users[key], credentials[key] = await _seed_user(role)
    monkeypatch.setattr(settings, "CPRO_BOT_ENABLED", False)
    monkeypatch.setattr(settings, "CPRO_BOT_AUTO_DRAFT_ENABLED", False)
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_URL", "")
    monkeypatch.setattr(settings, "GROK_BOT_CPRO_WEBHOOK_KEY", "")
    monkeypatch.setattr(
        bot_items,
        "CPRO_ACCOUNTS",
        {users["dl"]: ("Synthetic DL", "Nordea Cpro – Marcin")},
    )
    webhook = AsyncMock(side_effect=AssertionError("Operator flow called webhook"))
    monkeypatch.setattr(runs, "start_run", webhook)
    docx = render_approved_docx(HTML, default_template())
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = users["dl"]
        job.client_reference = "99001"
        stage = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage=PipelineStage.new,
            stage_def_id=world["defs"]["cpro"],
            moved_by=users["dl"],
            moved_at=now,
        )
        db.add(stage)
        await db.flush()
        csv = CandidateStageCV(
            candidate_stage_id=stage.id,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            branded_status="finalized",
            branded_version=1,
            branded_finalized_at=now,
        )
        db.add(csv)
        await db.flush()
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                version=1,
                content_html=HTML,
                content_sha256=hashlib.sha256(HTML.encode()).hexdigest(),
                docx_content=docx,
                docx_sha256=hashlib.sha256(docx).hexdigest(),
                docx_filename="operator-approved.docx",
                approved_at=now,
            )
        )
        await db.commit()
        stage_id, csv_id = stage.id, csv.id

    item = bot_items.BotItem(
        stage_id=stage_id,
        candidate_id=world["candidate_id"],
        job_id=world["job_id"],
        candidate_name="Synthetic operator candidate",
        process_state_version=0,
        target_stage_def_id=world["defs"]["cv_sent"],
        blockers=(),
        payload={
            "ref": stage_id,
            "request_number": "99001",
            "request_title": "Synthetic request",
            "cpro_account": {
                "delivery_lead_id": users["dl"],
                "delivery_lead_name": "Synthetic DL",
                "vault_entry": "Nordea Cpro – Marcin",
            },
            "candidate": {
                "first_name": "Synthetic",
                "last_name": "Candidate",
                "citizenship": "Poland",
                "profile_title": "Synthetic engineer",
                "profile_description": "Synthetic description",
            },
            "offer": {
                "rate": "150",
                "motivation": "- Synthetic SQL experience",
                "available_from": now.date().isoformat(),
                "physical_location": "Warszawa",
                "former_employee": False,
                "former_consultant": False,
                "cv_file_name": "operator-approved.pdf",
                "cv_format": "pdf",
                "cv_version": 1,
            },
        },
        cv=bot_items.CvFile(
            candidate_stage_id=stage_id,
            version=1,
            filename="operator-approved.pdf",
            why_points=("Synthetic SQL experience",),
            job_id=world["job_id"],
        ),
    )
    state = SimpleNamespace(
        item=item,
        users=users,
        stage_id=stage_id,
        csv_id=csv_id,
        world=world,
        docx=docx,
        webhook=webhook,
        headers={},
        create_body={"delivery_lead_id": users["dl"], "request_number": "99001"},
    )

    async def load_ready(_db, *, stage_ids=None, **_kwargs):
        return [state.item] if stage_ids is None or stage_id in stage_ids else []

    monkeypatch.setattr(bot_items, "load_items", load_ready)
    try:
        async with restore_cpro_sender():
            async with AsyncSessionLocal() as db:
                await cpro_sender.set_sender(
                    db,
                    user_id=users["operator"],
                    until=None,
                    actor=await db.get(User, users["admin"]),
                )
                await db.commit()
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://testserver",
            ) as client:
                state.client = client
                for name, creds in credentials.items():
                    state.headers[name] = await _login(client, creds)
                yield state
                webhook.assert_not_called()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CproBotRun).where(
                    CproBotRun.requested_by_user_id.in_(users.values())
                )
            )
            await db.execute(
                delete(CvDocumentVersion).where(
                    CvDocumentVersion.candidate_stage_cv_id == csv_id
                )
            )
            await db.execute(
                delete(CandidateStageCV).where(CandidateStageCV.id == csv_id)
            )
            await db.commit()
        await _cleanup(world, list(users.values()))


async def _create(world, *, actor="operator", body=None):
    response = await world.client.post(
        f"{BASE}/stages/{world.stage_id}/draft",
        headers=world.headers[actor],
        json=world.create_body if body is None else body,
    )
    return response


async def _created(world, **kwargs):
    response = await _create(world, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


async def _confirm(world, run_id, *, actor="operator", **overrides):
    return await world.client.post(
        f"{BASE}/runs/{run_id}/confirm",
        headers=world.headers[actor],
        json={
            "offer_id": "990001",
            "confirmed_draft": True,
            "confirmed_pdf": True,
            **overrides,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["operator", "admin"])
async def test_browser_session_creates_one_draft_without_run_token(
    browser_world, actor
):
    world = browser_world
    run_id = await _created(world, actor=actor)
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.requested_by_user_id == world.users[actor]
        assert run.request["operator_browser"] is True
        assert run.stage_ids == [world.stage_id] and run.submit is False
        assert run.token_hash is None
        assert (
            datetime.now(UTC)
            < run.token_expires_at
            < datetime.now(UTC) + timedelta(hours=3)
        )
    view = await world.client.get(f"{BASE}/runs/{run_id}", headers=world.headers[actor])
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["run_id"] == run_id and body["stage_id"] == world.stage_id
    assert body["submit"] is False and body["mode"] == "operator_browser"
    assert body["allow_create"] is True and body["reconcile_only"] is False
    assert body["allow_close_absent"] is False
    assert body["request_number"] == "99001"
    assert body["cpro_account_name"] == "Marcin"
    assert not {
        "token",
        "token_hash",
        "callback_url",
        "vault_entry",
        "cv_url",
    }.intersection(_keys(body))
    # A run id is not a bearer credential for the bot routes.
    assert (
        await world.client.get(f"/api/integrations/cpro-bot/runs/{run_id}/task")
    ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["other_operator", "read_only", "external"])
async def test_browser_creation_enforces_real_operator_rbac(browser_world, actor):
    response = await _create(browser_world, actor=actor)
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_browser_routes_require_user_session_and_owner(browser_world):
    world = browser_world
    unauthenticated = await world.client.post(
        f"{BASE}/stages/{world.stage_id}/draft", json=world.create_body
    )
    assert unauthenticated.status_code == 401
    run_id = await _created(world)
    for path in (f"{BASE}/runs/{run_id}", f"{BASE}/runs/{run_id}/cv"):
        assert (await world.client.get(path)).status_code == 401
        denied = await world.client.get(path, headers=world.headers["other_admin"])
        assert denied.status_code in (403, 404), denied.text
    assert (await _confirm(world, run_id, actor="other_admin")).status_code in (
        403,
        404,
    )


@pytest.mark.asyncio
async def test_browser_confirm_is_idempotent_and_never_moves_stage(browser_world):
    world = browser_world
    run_id = await _created(world)
    first = await _confirm(world, run_id)
    assert first.status_code == 200, first.text
    again = await _confirm(world, run_id)
    assert again.status_code == 200 and again.json() == first.json()
    different = await _confirm(world, run_id, offer_id="990002")
    assert different.status_code == 409, different.text
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.status == "received" and run.submit is False
        assert run.report["counts"]["draft"] == 1
        assert run.report["counts"]["submitted"] == 0
        assert run.report["counts"].get("moved", 0) == 0
        entry = run.report["items"][str(world.stage_id)]
        assert entry["outcome"] == "draft" and entry["cpro_status"] == "DRAFT"
        stage = await db.get(CandidateStage, world.stage_id)
        assert stage.stage_def_id == world.world["defs"]["cpro"]
        assert (
            await db.scalar(
                select(func.count(CandidateStage.id)).where(
                    CandidateStage.candidate_id == world.world["candidate_id"],
                    CandidateStage.job_id == world.world["job_id"],
                )
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count(Activity.id)).where(
                    Activity.action == "cpro_bot_submitted",
                    Activity.entity_id == world.stage_id,
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_simultaneous_browser_creates_resume_same_single_handle(browser_world):
    world = browser_world
    responses = await asyncio.gather(_create(world), _create(world))
    assert [response.status_code for response in responses] == [200, 200]
    ids = {response.json()["run_id"] for response in responses}
    assert len(ids) == 1
    assert sorted(response.json()["created"] for response in responses) == [False, True]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(CproBotRun.id)).where(
                    CproBotRun.requested_by_user_id == world.users["operator"]
                )
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["started", "expired", "failed", "received"])
async def test_resume_never_grants_second_creation_capability(browser_world, status):
    world = browser_world
    run_id = await _created(world)
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        run.status = status
        if status == "expired":
            run.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    resumed = await _create(world)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json() == {"run_id": run_id, "created": False}
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(CproBotRun.id)).where(
                    CproBotRun.stage_ids.contains([world.stage_id])
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_expired_get_does_not_write_and_can_only_reconcile_existing_draft(
    browser_world,
):
    world = browser_world
    run_id = await _created(world)
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        run.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    view = await world.client.get(
        f"{BASE}/runs/{run_id}", headers=world.headers["operator"]
    )
    assert view.status_code == 200, view.text
    assert view.json()["allow_create"] is False
    assert view.json()["reconcile_only"] is True
    assert view.json()["allow_close_absent"] is True
    assert view.headers["cache-control"] == "private, no-store"
    async with AsyncSessionLocal() as db:
        assert (await db.get(CproBotRun, run_id)).status == "started"
    cv = await world.client.get(
        f"{BASE}/runs/{run_id}/cv", headers=world.headers["operator"]
    )
    assert cv.status_code == 409, cv.status_code
    confirmed = await _confirm(world, run_id)
    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("rate", "151"), ("cv_version", 2), ("cv_file_name", "changed.pdf")]
)
async def test_changed_offer_snapshot_requires_reconciliation(
    browser_world, field, value
):
    world = browser_world
    run_id = await _created(world)
    payload = copy.deepcopy(world.item.payload)
    payload["offer"][field] = value
    world.item = replace(world.item, payload=payload)
    view = await world.client.get(
        f"{BASE}/runs/{run_id}", headers=world.headers["operator"]
    )
    assert view.status_code == 200, view.text
    assert (
        view.json()["allow_create"] is False and view.json()["reconcile_only"] is True
    )
    cv = await world.client.get(
        f"{BASE}/runs/{run_id}/cv", headers=world.headers["operator"]
    )
    assert cv.status_code == 409, cv.status_code
    assert (await _create(world)).json() == {"run_id": run_id, "created": False}
    assert (await _confirm(world, run_id)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["blocked", "wrong_request", "wrong_dl"])
async def test_not_ready_or_mismatched_card_cannot_be_claimed(browser_world, change):
    world = browser_world
    if change == "blocked":
        world.item = replace(world.item, blockers=("synthetic blocker",))
        body = world.create_body
    else:
        body = {
            **world.create_body,
            **(
                {"request_number": "99002"}
                if change == "wrong_request"
                else {"delivery_lead_id": world.users["dl"] + 10000}
            ),
        }
    response = await _create(world, body=body)
    assert response.status_code == 409, response.text
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count(CproBotRun.id)).where(
                    CproBotRun.stage_ids.contains([world.stage_id])
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_confirm_requires_explicit_draft_pdf_and_numeric_offer_without_writes(
    browser_world,
):
    world = browser_world
    run_id = await _created(world)
    for invalid in (
        {"confirmed_draft": False},
        {"confirmed_draft": 1},
        {"confirmed_pdf": False},
        {"confirmed_pdf": 1},
        {"offer_id": "https://example.test/offer/123?token=synthetic"},
        {"offer_id": True},
        {"offer_id": "0"},
        {"offer_id": "١٢٣"},
        {"submit": True},
    ):
        response = await _confirm(world, run_id, **invalid)
        assert response.status_code == 422, response.text
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.status == "started" and run.report == {} and run.submit is False


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["operator", "admin"])
async def test_document_scope_denial_is_not_bypassed_even_by_admin(
    browser_world, monkeypatch, actor
):
    from fastapi import HTTPException

    from app.services.cpro_bot import operator_browser

    denied = AsyncMock(
        side_effect=HTTPException(403, "Synthetic source document denial")
    )
    monkeypatch.setattr(operator_browser, "_load_csv_for_stage", denied)
    response = await _create(browser_world, actor=actor)
    assert response.status_code == 403, response.text
    denied.assert_awaited_once()


@pytest.mark.asyncio
async def test_borrowed_data_is_denied_for_operator(browser_world):
    world = browser_world
    world.item = replace(world.item, data_from={"synthetic": "source"})
    response = await _create(world)
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_saved_offer_from_history_blocks_new_claim(browser_world):
    world = browser_world
    async with AsyncSessionLocal() as db:
        historic, _ = runs.new_run(
            [world.item.payload],
            now=datetime.now(UTC) - timedelta(days=90),
            submit=False,
        )
        historic.status = "received"
        historic.requested_by_user_id = world.users["admin"]
        historic.report = {
            "items": {str(world.stage_id): {"outcome": "draft", "cpro_status": "DRAFT"}}
        }
        db.add(historic)
        await db.commit()
    response = await _create(world)
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_other_active_execution_blocks_browser_claim(browser_world):
    world = browser_world
    async with AsyncSessionLocal() as db:
        active, _ = runs.new_run(
            [{"ref": world.stage_id + 100000}], now=datetime.now(UTC), submit=False
        )
        active.requested_by_user_id = world.users["admin"]
        db.add(active)
        await db.commit()
    response = await _create(world)
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_browser_cv_is_real_pdf_from_frozen_approved_version(browser_world):
    if not shutil.which("soffice"):
        pytest.skip("LibreOffice is unavailable")

    world = browser_world
    run_id = await _created(world)
    async with AsyncSessionLocal() as db:
        csv = await db.get(CandidateStageCV, world.csv_id)
        csv.branded_draft_html = (
            "<p>UNAPPROVED EDIT MUST NEVER REPLACE THE FROZEN PDF</p>"
        )
        await db.commit()
    response = await world.client.get(
        f"{BASE}/runs/{run_id}/cv", headers=world.headers["operator"]
    )
    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-cv-version"] == "1"
    assert response.headers["cache-control"] == "private, no-store"
    assert ".pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-") and not response.content.startswith(
        b"PK"
    )
    import pdfplumber

    with pdfplumber.open(io.BytesIO(response.content)) as reader:
        assert len(reader.pages) >= 1
        text = " ".join(page.extract_text() or "" for page in reader.pages)
        assert "Synthetic SQL" in text
        assert "UNAPPROVED EDIT" not in text
        assert sum(len(page.images) for page in reader.pages) >= 1


async def _close_absent(world, run_id, *, actor="operator", body=None):
    return await world.client.post(
        f"{BASE}/runs/{run_id}/close-absent",
        headers=world.headers[actor],
        json={"confirmed_absent": True} if body is None else body,
    )


@pytest.mark.asyncio
async def test_close_absent_releases_only_expired_empty_claim_without_restart(
    browser_world,
):
    world = browser_world
    run_id = await _created(world)
    assert (await _close_absent(world, run_id)).status_code == 409
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        run.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert (await _close_absent(world, run_id, actor="other_admin")).status_code in (
        403,
        404,
    )
    for invalid in (
        {"confirmed_absent": False},
        {"confirmed_absent": 1},
        {"confirmed_absent": True, "submit": True},
    ):
        assert (await _close_absent(world, run_id, body=invalid)).status_code == 422
    response = await _close_absent(world, run_id)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "run_id": run_id,
        "status": "closed_absent",
        "reservation_released": True,
    }
    assert (await _close_absent(world, run_id)).json() == response.json()
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.status == "failed" and run.submit is False and run.token_hash is None
        assert (
            run.request["operator_absent_confirmed_by_user_id"]
            == world.users["operator"]
        )
        assert (
            run.report["items"][str(world.stage_id)]["reason"]
            == "operator_confirmed_absent"
        )
        assert (
            await db.scalar(
                select(func.count(CproBotRun.id)).where(
                    CproBotRun.stage_ids.contains([world.stage_id])
                )
            )
            == 1
        )
        assert not await runs.operator_reserved_stage_ids(db, [world.stage_id])
        assert (
            await db.scalar(
                select(func.count(Activity.id)).where(
                    Activity.action == "cpro_operator_closed_absent",
                    Activity.entity_id == world.stage_id,
                    Activity.user_id == world.users["operator"],
                )
            )
            == 1
        )
    new_claim = await _create(world)
    assert new_claim.status_code == 200, new_claim.text
    assert new_claim.json()["created"] is True and new_claim.json()["run_id"] != run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("has_confirmed_offer", [False, True])
async def test_close_absent_cannot_erase_possible_or_confirmed_offer(
    browser_world, has_confirmed_offer
):
    world = browser_world
    run_id = await _created(world)
    if has_confirmed_offer:
        assert (await _confirm(world, run_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        run.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        if not has_confirmed_offer:
            run.report = {
                "items": {
                    str(world.stage_id): {"outcome": "failed", "reason": "uncertain"}
                }
            }
        before = copy.deepcopy(run.report)
        await db.commit()
    response = await _close_absent(world, run_id)
    assert response.status_code == 409, response.text
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.report == before and not run.request.get("operator_absent_confirmed")
        assert await runs.operator_reserved_stage_ids(db, [world.stage_id]) == {
            world.stage_id
        }


@pytest.mark.asyncio
async def test_queue_exposes_operator_action_only_to_authorized_owner_and_tracks_state(
    browser_world,
):
    world = browser_world

    async def queue_entry(actor):
        response = await world.client.get(
            "/api/board-tasks/cpro/queue", headers=world.headers[actor]
        )
        assert response.status_code == 200, response.text
        return next(
            item
            for group in response.json()["jobs"]
            for item in group["items"]
            if item["stage_id"] == world.stage_id
        )

    assert (await queue_entry("operator"))["operator_draft"]["state"] == "ready"
    assert (await queue_entry("other_operator"))["operator_draft"] is None
    run_id = await _created(world)
    started = (await queue_entry("operator"))["operator_draft"]
    assert started["state"] == "started" and started["run_id"] == run_id
    assert started["cpro_account_name"] == "Marcin"
    other = await queue_entry("other_admin")
    assert other["operator_draft"] is None
    assert other["operator_status"]["state"] == "working"
    assert other["operator_status"]["cpro_account_name"] == "Marcin"
    assert "run_id" not in other["operator_status"]
    assert (await queue_entry("other_operator"))["operator_status"] is None
    assert (await _confirm(world, run_id)).status_code == 200
    received = (await queue_entry("operator"))["operator_draft"]
    assert received["state"] == "received" and received["run_id"] == run_id
    other = (await queue_entry("other_admin"))["operator_status"]
    assert other["state"] == "draft" and other["offer_id"] == "990001"
    assert other["cpro_account_name"] == "Marcin"
    assert "run_id" not in other


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "expired"])
async def test_unresolved_old_execution_cannot_authorize_another_offer(
    browser_world, status
):
    world = browser_world
    async with AsyncSessionLocal() as db:
        old, _ = runs.new_run(
            [world.item.payload],
            now=datetime.now(UTC) - timedelta(days=90),
            submit=False,
        )
        old.status = status
        old.requested_by_user_id = world.users["admin"]
        old.report = {}
        db.add(old)
        await db.commit()
    response = await _create(world)
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["skipped", "failed"])
async def test_explicit_old_non_offer_result_is_not_ambiguous(browser_world, outcome):
    from app.services.cpro_bot import operator_browser

    world = browser_world
    async with AsyncSessionLocal() as db:
        old, _ = runs.new_run(
            [world.item.payload],
            now=datetime.now(UTC) - timedelta(days=90),
            submit=False,
        )
        old.status = "received"
        old.requested_by_user_id = world.users["admin"]
        old.report = {"items": {str(world.stage_id): {"outcome": outcome}}}
        db.add(old)
        await db.commit()
        assert not await operator_browser.unresolved_stage_ids(db, [world.stage_id])


@pytest.mark.asyncio
async def test_existing_offer_identifier_cannot_be_attached_to_another_card(
    browser_world,
):
    world = browser_world
    run_id = await _created(world)
    async with AsyncSessionLocal() as db:
        historical, _ = runs.new_run(
            [{"ref": world.stage_id + 100000}],
            now=datetime.now(UTC) - timedelta(days=90),
            submit=False,
        )
        historical.status = "received"
        historical.requested_by_user_id = world.users["admin"]
        historical.report = {
            "items": {
                str(world.stage_id + 100000): {
                    "outcome": "draft",
                    "cpro_status": "DRAFT",
                    "offer_url": "https://nordea.onevms.se/nordea/vendor/OfferController?action=view&id=990001",
                }
            }
        }
        db.add(historical)
        await db.commit()
    response = await _confirm(world, run_id)
    assert response.status_code == 409, response.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(CproBotRun, run_id)).report == {}


@pytest.mark.asyncio
async def test_document_scope_is_rechecked_for_every_owned_action(
    browser_world, monkeypatch
):
    from fastapi import HTTPException

    from app.services.cpro_bot import operator_browser

    world = browser_world
    run_id = await _created(world, actor="admin")
    denied = AsyncMock(
        side_effect=HTTPException(403, "Synthetic revoked document scope")
    )
    monkeypatch.setattr(operator_browser, "_load_csv_for_stage", denied)
    for suffix in ("", "/cv"):
        response = await world.client.get(
            f"{BASE}/runs/{run_id}{suffix}", headers=world.headers["admin"]
        )
        assert response.status_code == 403, response.text
    assert (await _confirm(world, run_id, actor="admin")).status_code == 403
    assert denied.await_count == 3


@pytest.mark.asyncio
async def test_changed_snapshot_during_pdf_render_returns_no_file(
    browser_world, monkeypatch
):
    from app.api import cpro_operator

    world = browser_world
    run_id = await _created(world)

    async def changed_after_render(_db, _version):
        payload = copy.deepcopy(world.item.payload)
        payload["offer"]["rate"] = "999"
        world.item = replace(world.item, payload=payload)
        return b"%PDF-1.7\nsynthetic-render", "classic"

    monkeypatch.setattr(cpro_operator, "render_approved_pdf", changed_after_render)
    response = await world.client.get(
        f"{BASE}/runs/{run_id}/cv", headers=world.headers["operator"]
    )
    assert response.status_code == 409, response.status_code
    assert "application/pdf" not in response.headers["content-type"]


@pytest.mark.asyncio
async def test_dominik_operator_uses_marcin_account_without_delegating_ownership(
    browser_world, monkeypatch
):
    world = browser_world
    real_lead = world.users["dl"]
    other_lead = world.users["other_admin"]
    # Syntetyczne FK użytkowników; produkcyjny allowlist 32 pokrywa unit test.
    monkeypatch.setattr(
        bot_items,
        "CPRO_ACCOUNTS",
        {
            real_lead: ("Dominik", "Nordea Cpro – Marcin"),
            other_lead: ("Marcin", "Nordea Cpro – Marcin"),
        },
    )
    payload = copy.deepcopy(world.item.payload)
    payload["cpro_account"] = {
        "delivery_lead_id": real_lead,
        "delivery_lead_name": "Dominik",
        "vault_entry": "Nordea Cpro – Marcin",
    }
    world.item = replace(world.item, payload=payload)
    response = await _create(world)
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert response.json()["created"] is True
    assert (await _create(world)).json() == {"run_id": run_id, "created": False}
    wrong_owner = await _create(
        world, body={**world.create_body, "delivery_lead_id": other_lead}
    )
    assert wrong_owner.status_code == 409
    view = await world.client.get(
        f"{BASE}/runs/{run_id}", headers=world.headers["operator"]
    )
    assert view.status_code == 200, view.text
    assert view.json()["delivery_lead_id"] == real_lead
    assert view.json()["cpro_account_name"] == "Marcin"
    assert view.json()["allow_create"] is True
    denied = await world.client.get(
        f"{BASE}/runs/{run_id}", headers=world.headers["other_admin"]
    )
    assert denied.status_code == 404
    queue = await world.client.get(
        "/api/board-tasks/cpro/queue", headers=world.headers["operator"]
    )
    row = next(
        row
        for group in queue.json()["jobs"]
        for row in group["items"]
        if row["stage_id"] == world.stage_id
    )
    assert row["operator_draft"]["delivery_lead_id"] == real_lead
    assert row["operator_draft"]["cpro_account_name"] == "Marcin"
    assert (await _confirm(world, run_id)).status_code == 200
    async with AsyncSessionLocal() as db:
        run = await db.get(CproBotRun, run_id)
        assert run.request["items"][0]["cpro_account"] == payload["cpro_account"]
        assert run.requested_by_user_id == world.users["operator"]
        assert run.token_hash is None and run.submit is False
        assert run.report["counts"]["draft"] == 1
        assert (
            await db.get(CandidateStage, world.stage_id)
        ).stage_def_id == world.world["defs"]["cpro"]
