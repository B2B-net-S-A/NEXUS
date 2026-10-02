"""Dzwonek przy przekazaniu karty na Tablicy (0408, zgłoszenie 02.10.2026).

„Przekaż Delivery Leadowi" przesuwało kartę do „QC CV" bez powiadomienia:
Delivery Lead nie wiedział, że ma kogoś do sprawdzenia, a osoba, która kartę
przekazała, nie wiedziała, że DL wysłał CV do klienta. To samo w kolejce Cpro.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    restore_cpro_sender,
    seed_entry_row,
)

_BACKEND = Path(__file__).resolve().parents[1]


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


async def _bells(user_id: int) -> list[Notification]:
    """Dzwonki przekazania tej osoby — inne typy (np. ustawienie osoby od
    Cpro) nie należą do tego testu."""
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.notification_type.in_(
                            (
                                NotificationType.board_task_waiting,
                                NotificationType.stage_rule,
                            )
                        ),
                    )
                    .order_by(Notification.id)
                )
            ).all()
        )


async def _latest_stage_id(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage.id)
            .where(
                CandidateStage.candidate_id == world["candidate_id"],
                CandidateStage.job_id == world["job_id"],
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )


async def _set_job_dl(job_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.delivery_lead_id = user_id
        await db.commit()


def test_migration_and_entrypoint_add_the_notification_type() -> None:
    statement = (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'board_task_waiting'"
    )
    migration = (
        _BACKEND / "alembic" / "versions" / "0408_board_task_waiting_notif.py"
    ).read_text(encoding="utf-8")
    entrypoint = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert statement in " ".join(migration.split())
    assert statement in entrypoint
    assert NotificationType.board_task_waiting.value == "board_task_waiting"


@pytest.mark.asyncio
async def test_handing_over_rings_the_delivery_lead_and_sending_rings_back(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenariusz ze zgłoszenia: rekruter → „QC CV" → DL → „CV wysłane"."""

    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    other_dl_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    await _set_job_dl(jid, dl_id)
    try:
        await _move(api_client, rec, world, "verified")
        assert await _bells(dl_id) == []

        await _move(api_client, rec, world, "qc")
        qc_stage_id = await _latest_stage_id(world)
        bells = await _bells(dl_id)
        assert len(bells) == 1
        bell = bells[0]
        assert bell.notification_type == NotificationType.board_task_waiting
        assert bell.title.startswith("Do przeglądu: Ewa")
        assert "BT recruiter" in bell.message
        assert (bell.related_entity_type, bell.related_entity_id) == (
            "candidate_stage",
            qc_stage_id,
        )
        assert bell.link == f"/jobs/{jid}?candidate={cid}"
        # Rekruter nie powiadamia siebie, a DL spoza rekrutacji nic nie dostaje.
        assert await _bells(rec_id) == []
        assert await _bells(other_dl_id) == []

        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="180",
            client_rate_unit="hourly",
        )
        sent_stage_id = await _latest_stage_id(world)
        back = await _bells(rec_id)
        assert len(back) == 1
        assert back[0].notification_type == NotificationType.stage_rule
        assert back[0].title.startswith("CV wysłane do klienta: Ewa")
        assert "BT delivery_lead" in back[0].message
        assert back[0].related_entity_id == sent_stage_id
        assert back[0].link == f"/jobs/{jid}?candidate={cid}"
        # DL wysłał sam — nie dostaje dzwonka o własnym ruchu.
        assert len(await _bells(dl_id)) == 1
    finally:
        await _cleanup(world, [rec_id, dl_id, other_dl_id])


@pytest.mark.asyncio
async def test_rejection_after_review_rings_the_person_who_handed_over(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    await _set_job_dl(world["job_id"], dl_id)
    async with AsyncSessionLocal() as db:
        rejected_id = await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == world["template_id"],
                PipelineStageDef.is_terminal.is_(True),
            )
        )
    try:
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": rejected_id,
                "rejection_reason": "Za mało doświadczenia w bankowości",
            },
        )
        assert resp.status_code == 200, resp.text
        back = await _bells(rec_id)
        assert len(back) == 1
        assert back[0].title.startswith("Po przeglądzie: Ewa")
        assert back[0].title.endswith("→ Odrzucony")
    finally:
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_inactive_job_dl_sends_the_review_to_the_client_portfolio(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nieaktywny DL rekrutacji = brak DL-a (jak kolejka „Czeka na Ciebie")."""

    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    gone_dl_id, _ = await _seed_user(UserRole.delivery_lead)
    portfolio_dl_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    async with AsyncSessionLocal() as db:
        (await db.get(User, gone_dl_id)).is_active = False
        (await db.get(Job, world["job_id"])).delivery_lead_id = gone_dl_id
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=portfolio_dl_id, client_id=world["client_id"]
            )
        )
        await db.commit()
    try:
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        assert await _bells(gone_dl_id) == []
        bells = await _bells(portfolio_dl_id)
        assert [b.notification_type for b in bells] == [
            NotificationType.board_task_waiting
        ]
    finally:
        await _cleanup(world, [rec_id, gone_dl_id, portfolio_dl_id])


@pytest.mark.asyncio
async def test_cpro_queue_rings_the_sender_and_the_result_rings_back(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nordea: „Przekaż do Cpro" → osoba od Cpro; „✓ Wrzucone" i zwrot → rekruter."""

    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    sender_id, sender_creds = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    _admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec = await _login(api_client, rec_creds)
    sender = await _login(api_client, sender_creds)
    admin = await _login(api_client, admin_creds)
    await _set_job_dl(world["job_id"], dl_id)
    try:
        async with restore_cpro_sender():
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": sender_id, "until": None},
            )
            assert put.status_code == 200, put.text

            await _move(api_client, rec, world, "verified")
            await _move(api_client, rec, world, "qc")
            # U Nordei „QC CV" to praca rekrutera, nie przegląd DL.
            assert await _bells(dl_id) == []
            assert await _bells(sender_id) == []

            await _move(api_client, rec, world, "cpro")
            queued = await _bells(sender_id)
            assert len(queued) == 1
            assert queued[0].notification_type == NotificationType.board_task_waiting
            assert queued[0].title.startswith("Do wrzucenia do Cpro: Ewa")
            assert queued[0].link == "/dashboard#czeka-na-ciebie"

            # Zwrot do rekrutera: wraca do osoby, która przekazała kartę.
            await _move(api_client, sender, world, "qc")
            returned = await _bells(rec_id)
            assert len(returned) == 1
            assert returned[0].notification_type == NotificationType.board_task_waiting
            assert returned[0].title.startswith("Wrócił z kolejki Cpro: Ewa")

            await _move(api_client, rec, world, "cpro")
            await _move(api_client, sender, world, "cv_sent")
            done = await _bells(rec_id)
            assert len(done) == 2
            assert done[1].notification_type == NotificationType.stage_rule
            assert done[1].title.startswith("Wysłane do Cpro: Ewa")
    finally:
        await _cleanup(world, [rec_id, sender_id, dl_id])
