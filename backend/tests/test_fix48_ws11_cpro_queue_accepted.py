"""Kolejka Cpro: „✓ Zaakceptował(a)” z uprawnień w bazie (audyt 48 h, 13.10.2026).

Reguła: `docs/claude/rekrutacja-tablica/nordea-akceptacja-dl-przed-cpro.md`.
Akceptacja do kolejki Cpro to prawo wysyłki (`recruitment_manage`), które
admin nadaje i odbiera w „Osoby i role”. Kolejka czytała je z domyślnych ról:
osoba z nadanym prawem wychodziła „Bez akceptacji DL”, a Delivery Lead
z odebranym — „✓ Zaakceptował(a)”. Wymaga Postgresa (CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.section_permission import UserActionOverride
from app.models.user import UserRole
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
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


@pytest.mark.asyncio
async def test_cpro_queue_reads_acceptance_from_permissions_in_the_db(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    granted_id, _ = await _seed_user(UserRole.recruiter)
    revoked_id, _ = await _seed_user(UserRole.delivery_lead)
    users = [hor_id, granted_id, revoked_id]
    unique = uuid.uuid4().hex[:8]
    at = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        second = Candidate(
            name="Olga", lastname=f"CQ{unique}", email=f"cq-{unique}@example.com"
        )
        db.add_all(
            [
                second,
                UserActionOverride(
                    user_id=granted_id, action="recruitment_manage", access="manage"
                ),
                UserActionOverride(
                    user_id=revoked_id, action="recruitment_manage", access="none"
                ),
            ]
        )
        await db.flush()
        second_id = second.id
        for candidate_id, mover in (
            (world["candidate_id"], granted_id),
            (second_id, revoked_id),
        ):
            db.add(
                CandidateStage(
                    candidate_id=candidate_id,
                    job_id=world["job_id"],
                    stage=PipelineStage.new,
                    stage_def_id=world["defs"]["cpro"],
                    moved_at=at,
                    moved_by=mover,
                )
            )
        await db.commit()
    hor = await _login(api_client, hor_creds)
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            resp = await api_client.get("/api/board-tasks/cpro/queue", headers=hor)
        assert resp.status_code == 200, resp.text
        group = next(g for g in resp.json()["jobs"] if g["job_id"] == world["job_id"])
        accepted = {i["candidate_id"]: i["accepted"] for i in group["items"]}
        assert accepted == {world["candidate_id"]: True, second_id: False}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == second_id)
            )
            await db.execute(delete(Candidate).where(Candidate.id == second_id))
            await db.execute(
                delete(UserActionOverride).where(UserActionOverride.user_id.in_(users))
            )
            await db.commit()
        await _cleanup(world, users)
