"""„Twoje CV w drodze” — lista rekrutera w panelu „Czeka na Ciebie” (02.10.2026).

Po przekazaniu CV do QC rekruter nie widział na pulpicie nic: panel pokazywał
przegląd tylko Delivery Leadowi, a kolejkę tylko osobie od Cpro. Lista jest
liczona przy odczycie z najnowszego wiersza pary i trafia do rekrutera
kandydata albo osoby, która przekazała kartę dalej.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import cv_in_transit as svc
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
    seed_entry_row,
)

# ── Jednostkowe: rodzaj wpisu z kolumn Tablicy ───────────────────────────────


def _kind(**over) -> str | None:
    args = dict(
        column="verified",
        badge=None,
        prev_column=None,
        prev_badge=None,
        nordea=False,
        ended_by=None,
    )
    args.update(over)
    return svc.classify(**args)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (dict(column="cv_sent"), svc.KIND_SENT),
        (dict(column="cv_qc", badge="qc"), svc.KIND_IN_REVIEW),
        # U Nordei „QC CV” to praca rekrutera, nie przegląd u DL.
        (dict(column="cv_qc", badge="qc", nordea=True), None),
        (dict(column="cv_qc", badge="cpro", nordea=True), svc.KIND_CPRO_QUEUE),
        (dict(column="cv_qc", badge="cpro"), None),
        (
            dict(
                column="cv_qc",
                badge="qc",
                nordea=True,
                prev_column="cv_qc",
                prev_badge="cpro",
            ),
            svc.KIND_CPRO_RETURNED,
        ),
        (dict(column="closed", ended_by="delivery_lead"), svc.KIND_REJECTED_BY_DL),
        (dict(column="closed", ended_by="recruiter"), None),
        (dict(column="closed", ended_by="candidate"), None),
        (dict(column="verified", prev_column="cv_qc"), svc.KIND_SENT_BACK),
        (dict(column="screening", prev_column="cv_qc"), svc.KIND_SENT_BACK),
        # Zwykły ruch w przód i etap spoza szablonu nie są wpisem.
        (dict(column="verified", prev_column="screening"), None),
        (dict(column="client_interview", prev_column="cv_sent"), None),
        (dict(column=None), None),
    ],
)
def test_classify(args: dict, expected: str | None) -> None:
    assert _kind(**args) == expected


def test_transit_row_carries_the_fix_list() -> None:
    """D6 (08.10.2026): wiersz „wróciło” niesie pola wskazane przez DL."""
    row = svc.TransitRow(
        kind=svc.KIND_SENT_BACK,
        stage_id=1,
        candidate_id=2,
        candidate_name="Jan",
        job_id=3,
        job_title="Java",
        job_working_title=None,
        client_name=None,
        since=datetime.now(timezone.utc),
        fix_labels=("CV firmowe",),
    )
    assert row.fix_labels == ("CV firmowe",)
    from app.api.board_tasks import CvTransitRow
    from dataclasses import asdict

    assert CvTransitRow(**asdict(row)).fix_labels == ["CV firmowe"]


def test_rejection_reason_comes_from_the_dictionary_or_the_note() -> None:
    assert (
        svc.rejection_reason_text("salary_mismatch", "cokolwiek")
        == "Rozbieżność oczekiwań finansowych"
    )
    assert (
        svc.rejection_reason_text(None, "Powód (rejected): stawka ponad budżet\nreszta")
        == "stawka ponad budżet"
    )
    # Zwykła notatka nie udaje powodu odrzucenia.
    assert svc.rejection_reason_text(None, "Zadzwonić w piątek") is None
    assert svc.rejection_reason_text(None, None) is None


# ── Integracyjne: prawdziwe ruchy i odczyt panelu ────────────────────────────


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


async def _transit(client: AsyncClient, headers: dict) -> dict | None:
    resp = await client.get("/api/board-tasks", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["cv_in_transit"]


def _mine(block: dict | None, group: str, candidate_id: int) -> list[dict]:
    assert block is not None
    return [r for r in block[group] if r["candidate_id"] == candidate_id]


async def _seed_screening(world: dict, moved_by: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage="screening",
                stage_def_id=world["defs"]["screening"],
                moved_by=moved_by,
                moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        await db.commit()


async def _rejected_def_id(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == world["template_id"],
                PipelineStageDef.is_terminal.is_(True),
            )
        )


async def _non_nordea_world(monkeypatch: pytest.MonkeyPatch):
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    other_id, other_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        (await db.get(Job, world["job_id"])).delivery_lead_id = dl_id
        await db.commit()
    return world, (rec_id, rec_creds), (other_id, other_creds), (dl_id, dl_creds)


@pytest.mark.asyncio
async def test_recruiter_follows_the_cv_from_review_to_the_client(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, other_creds),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    other = await _login(api_client, other_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        # Zweryfikowany to jeszcze praca rekrutera — nic nie jest „w drodze”.
        block = await _transit(api_client, rec)
        assert block is not None
        assert not any(_mine(block, g, cid) for g in ("returned", "in_review", "sent"))

        await _move(api_client, rec, world, "qc")
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert [r["kind"] for r in review] == ["in_review"]
        assert review[0]["holder_name"].startswith("BT delivery_lead")
        assert review[0]["job_id"] == world["job_id"]
        # Inny rekruter nie widzi cudzego CV, a DL ma je w swoim przeglądzie.
        assert _mine(await _transit(api_client, other), "in_review", cid) == []
        dl_payload = (await api_client.get("/api/board-tasks", headers=dl)).json()
        assert [r["candidate_id"] for r in dl_payload["dl_review"]].count(cid) == 1
        assert _mine(dl_payload["cv_in_transit"], "in_review", cid) == []

        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        block = await _transit(api_client, rec)
        sent = _mine(block, "sent", cid)
        assert [r["kind"] for r in sent] == ["sent"]
        assert sent[0]["actor_name"].startswith("BT delivery_lead")
        assert _mine(block, "in_review", cid) == []
        assert block["sent_total"] >= 1
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_card_edited_by_the_delivery_lead_shows_who_and_what(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 (04.10.2026): DL poprawia kartę w przeglądzie, a rekruter widzi
    w „Twoje CV w drodze”, kto i które pola zmienił. Własne zapisy rekrutera
    nie są śladem."""
    (
        world,
        (rec_id, rec_creds),
        (other_id, _other_creds),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        own = await api_client.put(
            "/api/recommendation-cards",
            headers=rec,
            json={"candidate_id": cid, "job_id": jid, "fields": {"english": "B2"}},
        )
        assert own.status_code == 200, own.text
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["card_edited_by"] is None

        edited = await api_client.put(
            "/api/recommendation-cards",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "fields": {"motivation": "Chce wrócić do bankowości"},
            },
        )
        assert edited.status_code == 200, edited.text
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["card_edited_by"].startswith("BT delivery_lead")
        assert review[0]["card_edited_fields"] == ["Motywacja"]
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_rejection_by_the_delivery_lead_comes_back_with_the_reason(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": world["job_id"],
                "stage_def_id": await _rejected_def_id(world),
                "ended_by": "delivery_lead",
                "rejection_reason": "stawka ponad budżet",
            },
        )
        assert resp.status_code == 200, resp.text

        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert [r["kind"] for r in returned] == ["rejected_by_dl"]
        assert returned[0]["reason"] == "stawka ponad budżet"
        assert returned[0]["actor_name"].startswith("BT delivery_lead")
        # Delivery Lead nie dostaje wiadomości o własnej decyzji.
        assert _mine(await _transit(api_client, dl), "returned", cid) == []
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_card_sent_back_from_qc_disappears_after_the_next_move(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        await _move(api_client, dl, world, "verified")

        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert [r["kind"] for r in returned] == ["sent_back"]
        assert returned[0]["actor_name"].startswith("BT delivery_lead")

        # Rekruter poprawia i przekazuje ponownie — wpis „wróciło” znika.
        await _move(api_client, rec, world, "qc")
        block = await _transit(api_client, rec)
        assert _mine(block, "returned", cid) == []
        assert [r["kind"] for r in _mine(block, "in_review", cid)] == ["in_review"]

        # Własne cofnięcie karty nie jest wiadomością.
        await _move(api_client, rec, world, "verified")
        assert _mine(await _transit(api_client, rec), "returned", cid) == []
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_nordea_cpro_queue_and_return(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    sender_id, sender_creds = await _seed_user(UserRole.recruiter)
    admin = await _login(api_client, admin_creds)
    rec = await _login(api_client, rec_creds)
    sender = await _login(api_client, sender_creds)
    cid = world["candidate_id"]
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": sender_id, "until": None},
            )
            assert put.status_code == 200, put.text

            await _move(api_client, rec, world, "verified")
            await _move(api_client, rec, world, "qc")
            # U Nordei QC CV to praca rekrutera — jeszcze nic nie czeka u innych.
            assert _mine(await _transit(api_client, rec), "in_review", cid) == []

            await _move(api_client, rec, world, "cpro")
            review = _mine(await _transit(api_client, rec), "in_review", cid)
            assert [r["kind"] for r in review] == ["cpro_queue"]
            assert review[0]["holder_name"].startswith("BT recruiter")

            resp = await api_client.post(
                "/api/pipeline/move",
                headers=sender,
                json={
                    "candidate_id": cid,
                    "job_id": world["job_id"],
                    "stage_def_id": world["defs"]["qc"],
                    "notes": "Brak numeru projektu w CV",
                },
            )
            assert resp.status_code == 200, resp.text
            block = await _transit(api_client, rec)
            returned = _mine(block, "returned", cid)
            assert [r["kind"] for r in returned] == ["cpro_returned"]
            assert returned[0]["reason"] == "Brak numeru projektu w CV"
            assert _mine(block, "in_review", cid) == []
    finally:
        await _cleanup(world, [admin_id, rec_id, sender_id])


@pytest.mark.asyncio
async def test_removed_from_the_dashboard_means_no_list_until_restored(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, (rec_id, rec_creds), (other_id, _), (dl_id, _) = await _non_nordea_world(
        monkeypatch
    )
    rec = await _login(api_client, rec_creds)
    cid = world["candidate_id"]
    url = "/api/users/me/dashboard/panels/cv_in_transit"
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        assert _mine(await _transit(api_client, rec), "in_review", cid)

        hide = await api_client.put(url, headers=rec, json={"hidden": True})
        assert hide.status_code == 200, hide.text
        assert hide.json()["hidden_panels"] == ["cv_in_transit"]
        assert await _transit(api_client, rec) is None

        restore = await api_client.put(url, headers=rec, json={"hidden": False})
        assert restore.json()["hidden_panels"] == []
        assert _mine(await _transit(api_client, rec), "in_review", cid)
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])
