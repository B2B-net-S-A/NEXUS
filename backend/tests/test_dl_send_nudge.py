"""„Przypomnij” — rekruter przypomina Delivery Leadowi o gotowym CV (13.10.2026).

`POST /api/board-tasks/dl-send/{stage_id}/nudge`. Pod ochroną:

1. Przypomnieć można tylko o CV, które naprawdę czeka na Delivery Leada: po
   zaliczeniu QC i po ``LATE_WORKDAYS`` dniach roboczych — wcześniej ruch ma
   rekruter albo jest po prostu za wcześnie.
2. Przypomina osoba, która przekazała kartę, albo rekruter kandydata.
3. Dzwonek jest zadaniem Delivery Leada (mail `dl_review`, nie „wróciło do
   poprawy”) i wychodzi najwyżej raz dziennie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import notification_delivery as delivery
from app.services.stage_handoff_recipients import (
    RETURNED_TITLE_PREFIXES,
    TITLE_DL_NUDGE,
)
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world
from tests.test_dl_send_queue import _add_qc_run, _put_in_qc, _set_job_lead

UTC = timezone.utc

GONE = "Ta osoba nie czeka już na wysyłkę do klienta."
NOT_READY = "CV nie przeszło jeszcze QC — ruch jest po Twojej stronie."
TOO_EARLY = "Przypomnieć można po 2 dniach roboczych czekania."
NOT_OWNER = "Przypomnieć może osoba, która przekazała CV, albo rekruter kandydata."
NO_LEAD = "Ta rekrutacja nie ma Delivery Leada — nie ma komu przypomnieć."


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


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_nudge_bell_mails_as_a_review_task_not_as_a_returned_cv() -> None:
    """Kolejka maili rozpoznaje „wróciło do poprawy” po początku tytułu —
    przypomnienie jest zadaniem Delivery Leada, więc nie może do nich należeć."""
    assert not TITLE_DL_NUDGE.startswith(RETURNED_TITLE_PREFIXES)
    assert (
        delivery.immediate_email_kind(
            NotificationType.board_task_waiting,
            title=f"{TITLE_DL_NUDGE} Jan Nowak",
            related_entity_type="candidate_stage",
        )
        == "dl_review"
    )


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _nudge(client: AsyncClient, headers: dict, stage_id: int):
    return await client.post(
        f"/api/board-tasks/dl-send/{stage_id}/nudge", headers=headers
    )


async def _ready_for_days(world: dict, *, moved_by: int | None, days: int = 10) -> int:
    """Karta w „QC CV” z zaliczonym QC sprzed ``days`` dni — gotowa i spóźniona."""
    now = datetime.now(UTC)
    stage_id = await _put_in_qc(
        world, moved_by=moved_by, moved_at=now - timedelta(days=days + 2)
    )
    await _add_qc_run(world, passed=True, created_at=now - timedelta(days=days))
    return stage_id


async def _bells(stage_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Notification).where(
                Notification.notification_type == NotificationType.board_task_waiting,
                Notification.related_entity_type == "candidate_stage",
                Notification.related_entity_id == stage_id,
            )
        )
        return list(rows.all())


async def _nudge_log(stage_id: int) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Activity).where(
                Activity.entity_type == "candidate_stage",
                Activity.entity_id == stage_id,
                Activity.action == "dl_send_nudge",
            )
        )
        return list(rows.all())


async def _forget(stage_ids: list[int]) -> None:
    if not stage_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(Notification).where(
                Notification.related_entity_type == "candidate_stage",
                Notification.related_entity_id.in_(stage_ids),
            )
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "candidate_stage",
                Activity.entity_id.in_(stage_ids),
                Activity.action == "dl_send_nudge",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_nudge_waits_for_qc_and_for_two_working_days(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    await _set_job_lead(world, dl_id)
    now = datetime.now(UTC)
    stage_id = await _put_in_qc(
        world, moved_by=rec_id, moved_at=now - timedelta(days=10)
    )
    try:
        # QC niesprawdzone, potem do poprawy: ruch ma rekruter.
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == NOT_READY
        await _add_qc_run(world, passed=False, created_at=now - timedelta(days=9))
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == NOT_READY

        # QC przeszło przed chwilą: Delivery Lead czeka od dziś, nie od 10 dni.
        await _add_qc_run(world, passed=True, created_at=now)
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == TOO_EARLY
        assert await _bells(stage_id) == []
        assert await _nudge_log(stage_id) == []
    finally:
        await _forget([stage_id])
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_nudge_is_gone_once_the_card_moved_on(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    await _set_job_lead(world, dl_id)
    stage_id = await _ready_for_days(world, moved_by=rec_id)
    try:
        # Delivery Lead wysłał CV — wiersz „QC CV” nie jest już najnowszy.
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage="cv_sent",
                    stage_def_id=world["defs"]["cv_sent"],
                    moved_by=dl_id,
                    moved_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await db.commit()
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == GONE

        # Etap, którego nie ma.
        resp = await _nudge(api_client, rec, 2_000_000_000)
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == GONE
        assert await _bells(stage_id) == []
    finally:
        await _forget([stage_id])
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_nudge_is_for_the_sender_and_the_candidates_recruiter(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    sender_id, _ = await _seed_user(UserRole.recruiter)
    recruiter_id, recruiter_creds = await _seed_user(UserRole.recruiter)
    stranger_id, stranger_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    recruiter = await _login(api_client, recruiter_creds)
    stranger = await _login(api_client, stranger_creds)
    dl = await _login(api_client, dl_creds)
    await _set_job_lead(world, dl_id)
    # Kartę przekazał ktoś inny; kandydata prowadzi rekruter rekrutacji.
    async with AsyncSessionLocal() as db:
        (await db.get(Job, world["job_id"])).recruiter_id = recruiter_id
        await db.commit()
    stage_id = await _ready_for_days(world, moved_by=sender_id)
    try:
        for headers in (stranger, dl):
            resp = await _nudge(api_client, headers, stage_id)
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"] == NOT_OWNER
        assert await _bells(stage_id) == []

        resp = await _nudge(api_client, recruiter, stage_id)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"sent": True, "recipients": 1}
        assert [b.user_id for b in await _bells(stage_id)] == [dl_id]
    finally:
        await _forget([stage_id])
        await _cleanup(world, [sender_id, recruiter_id, stranger_id, dl_id])


@pytest.mark.asyncio
async def test_nudge_needs_a_delivery_lead_to_ring(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rekrutacja bez Delivery Leada i klient bez portfela — nie ma komu."""
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    stage_id = await _ready_for_days(world, moved_by=rec_id)
    try:
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == NO_LEAD
        assert await _bells(stage_id) == []
        assert await _nudge_log(stage_id) == []
    finally:
        await _forget([stage_id])
        await _cleanup(world, [rec_id])


@pytest.mark.asyncio
async def test_nudge_rings_the_delivery_lead_once_a_day(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    await _set_job_lead(world, dl_id)
    cid, jid = world["candidate_id"], world["job_id"]
    stage_id = await _ready_for_days(world, moved_by=rec_id)
    try:
        resp = await _nudge(api_client, rec, stage_id)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"sent": True, "recipients": 1}

        bells = await _bells(stage_id)
        assert [b.user_id for b in bells] == [dl_id]
        bell = bells[0]
        assert bell.title.startswith(f"{TITLE_DL_NUDGE} Ewa BT")
        assert bell.link == f"/jobs/{jid}?candidate={cid}&review=1"
        assert "przypomina" in bell.message
        assert "dni roboczych" in bell.message
        # Mail idzie jako zadanie przeglądu, nie jako zwrot do poprawy.
        assert (
            delivery.immediate_email_kind(
                bell.notification_type,
                title=bell.title,
                related_entity_type=bell.related_entity_type,
            )
            == "dl_review"
        )
        log = await _nudge_log(stage_id)
        assert [(a.user_id, a.details) for a in log] == [
            (rec_id, {"candidate_id": cid, "job_id": jid, "recipients": [dl_id]})
        ]

        # Drugi raz tego samego dnia: nic nie wychodzi i nic się nie zapisuje.
        again = await _nudge(api_client, rec, stage_id)
        assert again.status_code == 200, again.text
        assert again.json() == {"sent": False, "reason": "already_today"}
        assert len(await _bells(stage_id)) == 1
        assert len(await _nudge_log(stage_id)) == 1
    finally:
        await _forget([stage_id])
        await _cleanup(world, [rec_id, dl_id])
