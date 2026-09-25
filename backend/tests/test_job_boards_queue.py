"""Kolejka publikacji na RocketJobs / JustJoin.IT (0381) — z bazą, bez sieci.

Portal podmieniony na atrapę adaptera (dziedziczy prawdziwą walidację
ustawień). Pilnuje:

- publikacja zapisuje ustawienia ogłoszenia, braki = 422 z listą po polsku;
- worker publikuje z naszym ``externalId`` i czyści ``pending_action``;
- zmiana ustawień i nowa zatwierdzona treść → ``update``;
- rekrutacja nieopublikowana → ogłoszenie do zamknięcia (siatka workera);
- usunięcie rekrutacji z żywym ogłoszeniem jest blokowane;
- ponowienie z backoffem, konto do ponownego połączenia nie pali prób;
- synchronizacja stanu: wygasłe na portalu = ``expired``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.services import job_portals
from app.services.job_portals import jjit_connection
from app.services.job_portals.base import (
    PortalError,
    PortalReconnectRequired,
    PortalResult,
)
from app.services.job_portals.jjit import RocketJobsAdapter
from app.services.job_portals.service import (
    claim_batch,
    close_postings_of_closed_jobs,
    has_live_postings,
    external_ref_for,
    process_one,
    queue_content_update,
    sync_remote_states,
)
from tests.test_career_links_api import (
    _approve,
    _create_job_link,
    _login,
    _seed_job,
    _seed_user,
)

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parents[1]

OPTIONS = {
    "category": "java",
    "experience_level": "senior",
    "working_time": "full_time",
    "workplace_type": "hybrid",
    "office_days": 2,
    "city": "Warszawa",
    "salary": {"from": 150, "to": 190, "unit": "hour"},
}


class FakeRocket(RocketJobsAdapter):
    calls: list[tuple[str, object]] = []
    fail_with: list[Exception] = []
    remote_state = "published"

    async def publish(self, content):
        FakeRocket.calls.append(("publish", content.external_ref))
        if FakeRocket.fail_with:
            raise FakeRocket.fail_with.pop(0)
        return PortalResult(
            external_id="ad-1", url="https://rocketjobs.pl/oferta-pracy/x"
        )

    async def update(self, external_id, content):
        FakeRocket.calls.append(("update", external_id))
        return PortalResult(external_id=external_id)

    async def unpublish(self, external_id, *, external_ref=None):
        FakeRocket.calls.append(("close", external_id or external_ref))

    async def status(self, external_id):
        return {"state": FakeRocket.remote_state}


@pytest.fixture
def rocket_ready(monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ENABLED", True)
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        settings,
        "JJIT_OAUTH_REDIRECT_URI",
        "https://api.test/api/job-boards/jjit/callback",
    )

    async def connected(_db):
        return True

    monkeypatch.setattr(jjit_connection, "is_connected", connected)
    monkeypatch.setitem(job_portals.ADAPTERS, Portal.rocketjobs, FakeRocket)
    FakeRocket.calls = []
    FakeRocket.fail_with = []
    FakeRocket.remote_state = "published"


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


async def _ready_job(api):
    uid, email, password = await _seed_user("boards")
    headers = await _login(api, email, password)
    job_id = await _seed_job(uid)
    await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    return headers, job_id


async def _posting(job_id: int) -> JobPosting:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(JobPosting)
            .where(JobPosting.job_id == job_id)
            .order_by(JobPosting.id.desc())
        )


async def _process(job_id: int) -> None:
    """Przetwarza WYŁĄCZNIE wiersz tego testu (baza jest wspólna)."""
    await process_one((await _posting(job_id)).id)


def _url(job_id: int, action: str = "publish") -> str:
    return f"/api/jobs/{job_id}/portals/rocketjobs/{action}"


async def test_config_reports_not_connected_until_account_is_linked(api, monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ENABLED", True)
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_ID", "c")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "s")
    monkeypatch.setattr(settings, "JJIT_OAUTH_REDIRECT_URI", "https://x/cb")

    async def not_connected(_db):
        return False

    monkeypatch.setattr(jjit_connection, "is_connected", not_connected)
    headers, job_id = await _ready_job(api)
    body = (await api.get("/api/job-portals/config", headers=headers)).json()
    states = {p["portal"]: p["state"] for p in body["portals"]}
    assert states["rocketjobs"] == "not_connected"
    assert body["any_ready"] is False
    resp = await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "portal_not_connected"


async def test_missing_listing_fields_are_422_with_problems(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    resp = await api.post(_url(job_id), headers=headers)  # domyślne: bez kategorii
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "listing_invalid"
    assert any("kategorię" in p for p in detail["problems"])
    assert await _posting(job_id) is None


async def test_listing_defaults_come_from_the_job(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    resp = await api.get(f"/api/jobs/{job_id}/portal-listing-defaults", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["city"] == "Warszawa"
    assert body["workplace_type"] == "hybrid"
    assert body["office_days"] == 2
    assert body["category"] is None and body["salary"] is None


async def test_publish_update_and_close_cycle(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    resp = await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "publishing"
    assert body["pending_action"] == "publish"
    assert body["options"]["salary"] == {"from": 150.0, "to": 190.0, "unit": "hour"}

    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.published
    assert posting.pending_action is None
    assert posting.external_id == "ad-1"
    assert posting.url and posting.published_at
    assert FakeRocket.calls == [
        ("publish", external_ref_for(job_id, Portal.rocketjobs))
    ]

    changed = dict(OPTIONS, salary=None)
    resp = await api.patch(
        _url(job_id, "options"), json={"options": changed}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending_action"] == "update"
    await _process(job_id)
    assert FakeRocket.calls[-1] == ("update", "ad-1")
    assert (await _posting(job_id)).pending_action is None

    resp = await api.post(_url(job_id, "unpublish"), headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending_action"] == "close"
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.removed
    assert FakeRocket.calls[-1] == ("close", "ad-1")


async def test_new_approved_content_queues_update(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    await _process(job_id)
    resp = await _approve(
        api, headers, job_id, about="Nowy opis projektu.\n\nDrugi akapit."
    )
    assert resp.status_code == 200, resp.text
    assert (await _posting(job_id)).pending_action == "update"
    async with AsyncSessionLocal() as db:
        # Kolejne wywołanie niczego nie dubluje — wiersz już czeka.
        assert await queue_content_update(db, job_id) == 0


async def test_closed_job_closes_live_posting_and_blocks_delete(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    await _process(job_id)
    async with AsyncSessionLocal() as db:
        assert await has_live_postings(db, job_id)
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await close_postings_of_closed_jobs(db)
        await db.commit()
    assert (await _posting(job_id)).pending_action == "close"


def test_delete_job_checks_live_postings_before_deleting():
    source = (BACKEND / "app/api/jobs.py").read_text()
    start = source.index("async def delete_job(")
    body = source[start : source.index("async def close_job(")]
    assert body.index("has_live_postings") < body.index("await db.delete(job)")
    assert "job_has_live_postings" in body


async def test_worker_refuses_to_publish_closed_job(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.closed)
        )
        await db.commit()
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.failed
    assert "nie jest opublikowana" in (posting.last_error or "")
    assert FakeRocket.calls == []


async def test_retryable_error_backs_off_and_reconnect_keeps_attempts(
    api, rocket_ready
):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    FakeRocket.fail_with = [PortalError("chwilowo", retryable=True)]
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.publishing
    assert posting.attempts == 1
    assert posting.next_attempt_at is not None
    async with AsyncSessionLocal() as db:
        claimed = await claim_batch(db, 1000)
        assert posting.id not in {p.id for p in claimed}
        await db.rollback()

    FakeRocket.fail_with = [PortalReconnectRequired("połącz ponownie")]
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.attempts == 1  # konto do połączenia nie zużywa prób
    assert posting.status == PostingStatus.publishing
    assert posting.next_attempt_at > datetime.now(timezone.utc) + timedelta(minutes=50)


async def test_status_sync_marks_expired(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    await _process(job_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(JobPosting)
            .where(JobPosting.job_id == job_id)
            .values(last_synced_at=datetime.now(timezone.utc) - timedelta(days=2))
        )
        await db.commit()
    FakeRocket.remote_state = "expired"
    await sync_remote_states(limit=1000)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.expired
    assert posting.remote_state == "expired"


def test_migration_and_entrypoint_mirror():
    import re

    ns: dict = {}
    source = (
        BACKEND / "alembic/versions/0381_job_boards_jjit_rocketjobs.py"
    ).read_text()
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    entry = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
    for statement in (
        ns["ENUM_STATEMENTS"]
        + ns["COLUMN_STATEMENTS"]
        + ns["CONSTRAINT_STATEMENTS"]
        + ns["TABLE_STATEMENTS"]
    ):
        assert re.sub(r"\s+", " ", statement) in entry, statement.splitlines()[0]
    assert ns["down_revision"] == "0380_job_client_reference_working_title"
    main = (BACKEND / "app/main.py").read_text()
    assert '("job_board_connections", JobBoardConnection)' in main


async def test_unpublish_after_an_attempt_closes_instead_of_dropping(api, rocket_ready):
    """Po próbie POST ogłoszenie mogło powstać — wycofanie musi je zamknąć."""
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    FakeRocket.fail_with = [PortalError("timeout", retryable=True)]
    await _process(job_id)
    resp = await api.post(_url(job_id, "unpublish"), headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["pending_action"] == "close"
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(JobPosting)
            .where(JobPosting.job_id == job_id)
            .values(next_attempt_at=None)
        )
        await db.commit()
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.removed
    # Bez id ogłoszenia adapter dostaje nasz stały externalId do odszukania.
    assert FakeRocket.calls[-1] == (
        "close",
        external_ref_for(job_id, Portal.rocketjobs),
    )


async def test_exhausted_timeouts_fail_and_queue_cleanup(
    api, rocket_ready, monkeypatch
):
    monkeypatch.setattr(settings, "JOB_PORTAL_MAX_ATTEMPTS", 1)
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    FakeRocket.fail_with = [PortalError("timeout", retryable=True)]
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.failed
    assert posting.pending_action == "close"
    async with AsyncSessionLocal() as db:
        assert await has_live_postings(db, job_id)


async def test_certain_refusal_fails_without_cleanup(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    FakeRocket.fail_with = [PortalError("Brak kodów", retryable=False)]
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.failed
    assert posting.pending_action is None
    assert posting.last_error == "Brak kodów"


async def test_unexpected_exception_is_contained_and_retried(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    FakeRocket.fail_with = [ValueError("non-json body")]
    await _process(job_id)
    posting = await _posting(job_id)
    assert posting.status == PostingStatus.publishing
    assert posting.attempts == 1
    assert "Nieoczekiwany" in (posting.last_error or "")


async def test_unpublish_before_first_attempt_drops_row(api, rocket_ready):
    headers, job_id = await _ready_job(api)
    await api.post(_url(job_id), json={"options": OPTIONS}, headers=headers)
    resp = await api.post(_url(job_id, "unpublish"), headers=headers)
    assert resp.json()["status"] == "removed"
    assert FakeRocket.calls == []
