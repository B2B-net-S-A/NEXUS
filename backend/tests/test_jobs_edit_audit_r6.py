"""Zakładanie i edycja rekrutacji — pozycje J1, J3, J4, J5 rundy 6 audytu.

* J1: PATCH waliduje DL/TAC/klienta tylko przy REALNEJ zmianie wartości —
  okno edycji odsyła `client_id` i `delivery_lead_id` przy każdym zapisie,
  więc rekrutacja z nieaktywnym DL-em nie dawała się zapisać wcale;
  komunikaty po polsku.
* J3: kopia rekrutacji nie dziedziczy briefingu DL-a, a odpięcie briefingu
  nie kasuje nagrania, które wskazuje inna rekrutacja.
* J4: jawny `null` dla kolumny NOT NULL = 422 po polsku, nie 500.
* J5: ranking i wektor unieważnia realna zmiana wartości, nie klucz w żądaniu.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.schemas.job import JobUpdate
from app.services.champion_intake import copy_profile


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_template_copy_drops_the_source_briefing() -> None:
    stored = {
        "briefing": {
            "status": "attached",
            "note_id": 41,
            "title": "Breakout z DL",
            "audio_storage_key": "briefing/abc.mp3",
        }
    }
    copied = copy_profile(stored, 9)
    briefing = copied.get("briefing") or {}
    assert briefing.get("status") in (None, "pending")
    assert briefing.get("note_id") is None
    assert briefing.get("audio_storage_key") is None


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "status",
        "priority",
        "needs_sourcing",
        "work_mode",
        "headcount",
        "client_id",
    ],
)
def test_job_update_rejects_explicit_null_for_not_null_columns(field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        JobUpdate.model_validate({field: None})
    assert "nie może być puste" in str(exc.value)


def test_job_update_still_allows_omitting_and_clearing_nullable_fields() -> None:
    data = JobUpdate.model_validate({"location": None, "deadline": None})
    assert data.model_dump(exclude_unset=True) == {"location": None, "deadline": None}
    assert JobUpdate.model_validate({}).model_dump(exclude_unset=True) == {}


# ── Z bazą ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _user(role: UserRole, *, active: bool = True) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"r6jobs-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!R6J"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"R6 {role.value} {unique}",
            role=role,
            is_active=active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _job(**fields) -> Job:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"R6JobsClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.flush()
        job = Job(
            title=f"R6 rekrutacja {uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            client_id=c.id,
            **fields,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    _, email, password = await _user(UserRole.admin)
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_edit_with_unchanged_inactive_delivery_lead_saves(
    client: AsyncClient,
) -> None:
    dl_id, _, _ = await _user(UserRole.delivery_lead, active=False)
    tac_id, _, _ = await _user(UserRole.tac)  # bez przypisania do klienta
    job = await _job(delivery_lead_id=dl_id, tac_id=tac_id)
    headers = await _admin_headers(client)

    # Tak wysyła okno edycji: klient i DL zawsze, nawet niezmienione.
    resp = await client.patch(
        f"/api/jobs/{job.id}",
        headers=headers,
        json={
            "title": job.title,
            "client_id": job.client_id,
            "delivery_lead_id": dl_id,
            "description": "Nowy opis",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Nowy opis"


@pytest.mark.asyncio
async def test_changing_to_inactive_delivery_lead_is_refused_in_polish(
    client: AsyncClient,
) -> None:
    inactive_id, _, _ = await _user(UserRole.delivery_lead, active=False)
    job = await _job()
    headers = await _admin_headers(client)

    resp = await client.patch(
        f"/api/jobs/{job.id}",
        headers=headers,
        json={"delivery_lead_id": inactive_id},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "Delivery Lead" in detail and "nieaktywne" in detail


@pytest.mark.asyncio
async def test_patch_explicit_null_title_is_422_not_500(client: AsyncClient) -> None:
    job = await _job()
    headers = await _admin_headers(client)
    resp = await client.patch(
        f"/api/jobs/{job.id}", headers=headers, json={"title": None}
    )
    assert resp.status_code == 422, resp.text
    assert "nie może być puste" in resp.text


@pytest.mark.asyncio
async def test_resending_unchanged_scoring_inputs_keeps_the_ranking(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.jobs as jobs_api
    from app.services import match_score_cache

    stale_calls: list[int] = []
    embed_calls: list[int] = []

    async def _mark_stale(db, job_id):  # noqa: ANN001
        stale_calls.append(job_id)
        return 0

    async def _embed(job_id, db):  # noqa: ANN001
        embed_calls.append(job_id)

    monkeypatch.setattr(match_score_cache, "mark_stale_for_job", _mark_stale)
    monkeypatch.setattr(jobs_api, "_maybe_embed_job", _embed)

    # `train_name` ustawiony, bo inaczej zapis tytułu wyciąga go z tekstu —
    # to już realna zmiana wejścia wektora, nie przedmiot tego testu.
    job = await _job(location="Warszawa", train_name="R6-train")
    headers = await _admin_headers(client)

    same = await client.patch(
        f"/api/jobs/{job.id}",
        headers=headers,
        json={"title": job.title, "location": "Warszawa", "remote_policy": None},
    )
    assert same.status_code == 200, same.text
    assert stale_calls == [] and embed_calls == []

    changed = await client.patch(
        f"/api/jobs/{job.id}",
        headers=headers,
        json={"title": job.title + " (zmiana)"},
    )
    assert changed.status_code == 200, changed.text
    assert stale_calls == [job.id]
    assert embed_calls == [job.id]


@pytest.mark.asyncio
async def test_clearing_briefing_keeps_audio_referenced_by_another_job(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import object_storage

    deleted: list[str] = []
    monkeypatch.setattr(object_storage, "is_available", lambda: True)
    monkeypatch.setattr(object_storage, "delete_cv", deleted.append)

    key = f"briefing/r6-{uuid.uuid4().hex}.mp3"
    briefing = {"status": "attached", "note_id": None, "audio_storage_key": key}
    source = await _job(champion_profile={"briefing": briefing})
    copy = await _job(champion_profile={"briefing": dict(briefing)})
    headers = await _admin_headers(client)

    resp = await client.delete(
        f"/api/jobs/{copy.id}/champion-profile/briefing", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert deleted == []

    # Ostatnia rekrutacja z tym nagraniem — obiekt znika.
    resp = await client.delete(
        f"/api/jobs/{source.id}/champion-profile/briefing", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert deleted == [key]
