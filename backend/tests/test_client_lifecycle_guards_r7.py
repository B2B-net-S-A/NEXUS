"""Runda 7 audytu (R7-X5-2/3/4): klient usunięty albo scalony nie zostawia
żywych danych na niewidocznym wierszu i nie przyjmuje nowych zapisów.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własnych
klientów (z pominięciem ID zaszytych w kodzie) i sprawdza tylko swoje wiersze.
Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import ContractStatus
from app.models.job import Job, JobStatus
from app.services.request_allocation import _pool_clause
from tests.test_client_deletion import _client, _contract, _user

pytestmark = pytest.mark.asyncio


async def _mark_deleted(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Client, client_id)
        row.deleted_at = datetime.now(timezone.utc)
        await db.commit()


async def _mark_merged(client_id: int, target_id: int) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(Client, client_id)
        row.merged_into_client_id = target_id
        row.archived_at = datetime.now(timezone.utc)
        await db.commit()


async def _published_job(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Rekrutacja bez kandydatów {uuid.uuid4().hex[:6]}",
            client_id=client_id,
            status=JobStatus.published,
            work_state="searching",
        )
        db.add(job)
        await db.commit()
        return job.id


# ── R7-X5-2: scalenie z żywymi danymi jest blokowane ─────────────────────────


async def test_merge_of_client_with_live_contractor_is_409_with_blockers(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    source_id = await _client("scalenie-kontrakt")
    target_id = await _client("scalenie-cel")
    await _contract(source_id, status=ContractStatus.active)

    resp = await app_client.post(
        f"/api/clients/{source_id}/merge-into/{target_id}", headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "client_merge_blocked"
    assert "active_contractors" in [b["code"] for b in detail["blockers"]]
    async with AsyncSessionLocal() as db:
        row = await db.get(Client, source_id)
        assert row.merged_into_client_id is None


async def test_merge_of_client_with_open_recruitment_is_409(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    source_id = await _client("scalenie-rekrutacja")
    target_id = await _client("scalenie-cel2")
    await _published_job(source_id)

    resp = await app_client.post(
        f"/api/clients/{source_id}/merge-into/{target_id}", headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    codes = [b["code"] for b in resp.json()["detail"]["blockers"]]
    assert codes == ["open_recruitments"]


async def test_merge_of_client_named_in_configuration_is_409(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    source_id = await _client("scalenie-konfiguracja")
    target_id = await _client("scalenie-cel3")
    monkeypatch.setenv("R7_TEST_CLIENT_IDS", str(source_id))

    resp = await app_client.post(
        f"/api/clients/{source_id}/merge-into/{target_id}", headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    blocker = resp.json()["detail"]["blockers"][0]
    assert blocker["code"] == "configuration"
    assert blocker["items"] == ["R7_TEST_CLIENT_IDS"]


# ── R7-X5-3: usunięcie klienta zamyka rekrutacje bez kandydatów ──────────────


async def test_deleting_client_with_history_closes_its_empty_open_recruitment(
    app_client: AsyncClient,
):
    client_id = await _client("usuwanie-rekrutacja")
    await _contract(client_id, status=ContractStatus.ended)
    job_id = await _published_job(client_id)
    actor_id, headers = await _user(app_client, can_delete_clients=True)

    done = await app_client.delete(
        f"/api/clients/{client_id}", params={"confirmation": "0"}, headers=headers
    )

    assert done.status_code == 200, done.text
    assert done.json()["result"] == "archived"
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.status == JobStatus.closed
        assert job.work_state == "finished"
        assert job.is_open is False
        # Hit ratio Ligi DL liczy zamknięte po ``closed_at`` — nie stemplujemy.
        assert job.closed_at is None
        in_pool = await db.scalar(
            select(Job.id).where(Job.id == job_id, _pool_clause())
        )
        assert in_pool is None
        entry = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "job",
                Activity.entity_id == job_id,
                Activity.action == "archived",
            )
        )
        assert entry is not None
        assert entry.user_id == actor_id
        assert entry.details["reason"] == "client_deleted"


async def test_canonical_client_with_merged_duplicate_cannot_be_deleted(
    app_client: AsyncClient,
):
    canonical_id = await _client("kanoniczny")
    duplicate_id = await _client("duplikat")
    await _mark_merged(duplicate_id, canonical_id)
    _, headers = await _user(app_client, can_delete_clients=True)

    check = await app_client.post(
        f"/api/clients/{canonical_id}/deletion-check", headers=headers
    )

    body = check.json()
    assert body["mode"] == "blocked"
    assert [b["code"] for b in body["blockers"]] == ["merged_duplicates"]


# ── R7-X5-4: zapisy nie przyjmują klienta usuniętego ani scalonego ───────────


async def test_create_job_for_deleted_client_is_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _client("rekrutacja-usuniety")
    await _mark_deleted(client_id)

    resp = await app_client.post(
        "/api/jobs",
        json={"title": "Programista", "work_mode": "fulltime", "client_id": client_id},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"


async def test_create_job_for_merged_client_names_the_canonical_record(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    canonical_id = await _client("rekrutacja-kanoniczny")
    duplicate_id = await _client("rekrutacja-duplikat")
    await _mark_merged(duplicate_id, canonical_id)

    resp = await app_client.post(
        "/api/jobs",
        json={
            "title": "Programista",
            "work_mode": "fulltime",
            "client_id": duplicate_id,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "client_merged"
    assert detail["merged_into_client_id"] == canonical_id


async def test_moving_job_to_deleted_client_is_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    live_id = await _client("rekrutacja-zywy")
    deleted_id = await _client("rekrutacja-cel-usuniety")
    create = await app_client.post(
        "/api/jobs",
        json={"title": "Tester", "work_mode": "fulltime", "client_id": live_id},
        headers=app_auth_headers,
    )
    assert create.status_code == 201, create.text
    await _mark_deleted(deleted_id)

    resp = await app_client.patch(
        f"/api/jobs/{create.json()['id']}",
        json={"client_id": deleted_id},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"


async def test_create_contract_for_deleted_client_is_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _client("kontrakt-usuniety")
    await _mark_deleted(client_id)
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:6]
        candidate = Candidate(
            name="Adam",
            lastname=f"Zmyslony-{suffix}",
            email=f"r7x5-{suffix}@example.com",
        )
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id

    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": client_id,
            "start_date": "2026-09-01",
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"


async def test_create_contact_for_deleted_client_is_422(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _client("kontakt-usuniety")
    await _mark_deleted(client_id)

    resp = await app_client.post(
        "/api/contacts",
        json={"client_id": client_id, "name": "Anna Zmyślona"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "client_deleted"


async def test_required_documents_of_deleted_client_are_not_writable(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _client("dokumenty-usuniety")
    await _mark_deleted(client_id)

    resp = await app_client.post(
        f"/api/clients/{client_id}/required-documents",
        json={"name": "Oświadczenie"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 404, resp.text


async def test_clients_lookup_skips_deleted_client_even_without_archived_at(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _client("lookup-usuniety")
    await _mark_deleted(client_id)

    resp = await app_client.get("/api/clients-lookup", headers=app_auth_headers)

    assert resp.status_code == 200, resp.text
    assert client_id not in {row["id"] for row in resp.json()}
