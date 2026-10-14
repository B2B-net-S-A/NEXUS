"""Stan QC pary na bazie: obejście doradcze, pominięcia i zwrot karty
(audyt 48 h, 13.10.2026). Wymaga Postgresa (CI).

Reguły: `docs/claude/rekrutacja-tablica/qc-cv-tryb-doradczy-role-z-odczytu-potwierdzenie.md`
i `qc-to-nieprawda-i-jakosc-qc.md`. Logika bez bazy:
`test_fix48_ws11_qc_override_rule.py`, `test_fix48_ws11_card_return.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_finding_dismissal import CvFindingDismissal
from app.models.cv_qc_run import CvQcRun
from app.models.section_permission import UserActionOverride
from app.models.user import UserRole
from app.services import cv_finding_dismissals as dismissals
from app.services import cv_qc as qc
from tests.taxonomy_fixture import hydrated_taxonomy
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world
from tests.test_cv_qc import _assign_job, _cleanup_advisory, _mark_critical
from tests.test_dz_review import BRANDED_HTML, _seed_review


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


async def _status(world: dict) -> dict:
    pair = (world["candidate_id"], world["job_id"])
    async with AsyncSessionLocal() as db:
        return (await qc.pair_statuses(db, [pair]))[pair]


def _send(world: dict) -> dict:
    return {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "stage_def_id": world["defs"]["cv_sent"],
        "client_rate_value": "180",
        "client_rate_unit": "hourly",
        "client_rate_currency": "PLN",
    }


async def _advisory_world(api_client: AsyncClient, monkeypatch) -> dict:
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    monkeypatch.setattr(settings, "CV_QC_ADVISORY", True)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    world["users"] = [hor_id, dl_id, rec_id]
    world["hor"] = await _login(api_client, hor_creds)
    world["dl"] = await _login(api_client, dl_creds)
    world["rec"] = await _login(api_client, rec_creds)
    world["stage_id"] = await _seed_review(world, world["hor"], api_client)
    await _mark_critical(world, "Java", "Kubernetes")
    await _assign_job(world, delivery_lead_id=dl_id)
    world["qc_url"] = f"/api/pipeline/stages/{world['stage_id']}/qc"
    return world


async def _override(api_client: AsyncClient, world: dict, who: str) -> None:
    with hydrated_taxonomy():
        resp = await api_client.post(
            f"{world['qc_url']}/override",
            headers=world[who],
            json={"reason_code": "client_short_cv"},
        )
    assert resp.status_code == 200, resp.text


async def _move(api_client: AsyncClient, world: dict, who: str):
    with hydrated_taxonomy():
        return await api_client.post(
            "/api/pipeline/move", headers=world[who], json=_send(world)
        )


@pytest.mark.asyncio
async def test_advisory_override_is_for_the_cv_it_was_made_on(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _advisory_world(api_client, monkeypatch)
    try:
        await _override(api_client, world, "rec")
        assert (await _status(world))["status"] == "overridden"

        # Po obejściu ktoś zmienia CV — krytyczne dalej są do poprawy.
        async with AsyncSessionLocal() as db:
            csv = await db.scalar(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == world["stage_id"]
                )
            )
            csv.branded_draft_html = BRANDED_HTML.replace(
                "Rozwój usług w <b>Java</b> i Spring.",
                "Rozwój usług w <b>Java</b>, Spring i Kafka.",
            )
            await db.commit()

        refused = await _move(api_client, world, "dl")
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "CV_QC_FAILED"
        # Bramka zapisała przebieg nowego CV — plakietka mówi to samo.
        assert (await _status(world))["status"] == "failed"
        with hydrated_taxonomy():
            body = (await api_client.get(world["qc_url"], headers=world["rec"])).json()
        assert body["override"] is None

        # Nowe obejście — przy tym CV — znów przepuszcza.
        await _override(api_client, world, "rec")
        moved = await _move(api_client, world, "dl")
        assert moved.status_code == 200, moved.text
    finally:
        await _cleanup_advisory(world, world["stage_id"], world["users"])


@pytest.mark.asyncio
async def test_switching_advisory_mode_off_ends_recruiter_overrides(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _advisory_world(api_client, monkeypatch)
    try:
        await _override(api_client, world, "rec")
        assert (await _status(world))["status"] == "overridden"

        # Powrót do blokady = jedna wartość; stare obejścia rekruterów nie
        # przepuszczają dalej.
        monkeypatch.setattr(settings, "CV_QC_ADVISORY", False)
        assert (await _status(world))["status"] == "failed"
        refused = await _move(api_client, world, "dl")
        assert refused.status_code == 409, refused.text

        # Obejście osoby od wysyłki działa jak dotąd.
        await _override(api_client, world, "dl")
        assert (await _status(world))["status"] == "overridden"
        moved = await _move(api_client, world, "dl")
        assert moved.status_code == 200, moved.text
    finally:
        await _cleanup_advisory(world, world["stage_id"], world["users"])


@pytest.mark.asyncio
async def test_card_return_ends_pass_through_dismissals_of_people_without_send_right() -> (
    None
):
    """Zapisany przebieg zaliczony dzięki pominięciom; zwrot karty przywraca
    pominięcia osób bez prawa wysyłki — według uprawnień z bazy."""
    world = await _seed_world()
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    granted_id, _ = await _seed_user(UserRole.recruiter)
    revoked_id, _ = await _seed_user(UserRole.delivery_lead)
    users = [rec_id, dl_id, granted_id, revoked_id]
    cid, jid = world["candidate_id"], world["job_id"]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                UserActionOverride(
                    user_id=granted_id, action="recruitment_manage", access="manage"
                ),
                UserActionOverride(
                    user_id=revoked_id, action="recruitment_manage", access="none"
                ),
                CvQcRun(
                    candidate_id=cid,
                    job_id=jid,
                    passed=True,
                    blocking_failed=0,
                    warnings_count=0,
                    result={"checks": [], "dismissed_blocking": 4},
                    created_at=now,
                ),
            ]
        )
        for user_id in users:
            db.add(
                dismissals.new_row(
                    candidate_id=cid,
                    job_id=jid,
                    stage_id=None,
                    source="qc",
                    check_key="critical_skills",
                    key=f"critical_skills|java|rola-{user_id}",
                    label="Java",
                    reason="in_cv",
                    note=None,
                    quote=None,
                    blocking=True,
                    user_id=user_id,
                )
            )
        await db.commit()
    try:
        assert await _status(world) == {
            "status": "overridden",
            "blocking_failed": 0,
            "ok_at": now,
            "dismissed_blocking": 4,
        }
        async with AsyncSessionLocal() as db:
            spent = await dismissals.restore_on_card_return(db, cid, jid)
            await db.commit()
        assert spent == 2
        async with AsyncSessionLocal() as db:
            restored = set(
                (
                    await db.scalars(
                        select(CvFindingDismissal.dismissed_by_user_id).where(
                            CvFindingDismissal.candidate_id == cid,
                            CvFindingDismissal.restored_reason == "card_returned",
                        )
                    )
                ).all()
            )
        assert restored == {rec_id, revoked_id}
        # Plakietka i przegląd DL nie mówią już „przepuszczone”.
        assert await _status(world) == {
            "status": "failed",
            "blocking_failed": 2,
            "ok_at": None,
            "dismissed_blocking": 0,
        }
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvFindingDismissal).where(CvFindingDismissal.candidate_id == cid)
            )
            await db.execute(delete(CvQcRun).where(CvQcRun.candidate_id == cid))
            await db.execute(
                delete(UserActionOverride).where(UserActionOverride.user_id.in_(users))
            )
            await db.commit()
        await _cleanup(world, users)
