"""Tests for GET /api/admin/process-adoption.

Kontrakt raportu adopcji/widoczności:
- auth: X-Snapshot-Token albo JWT admina; zwykły user → 403, brak auth → 401;
- shape: adoption/visibility/supporting/diagnostics + query_version;
- dyskryminator pochodzenia to `external_source = 'manual'` vs `'traffit'`
  (najważniejszy test w tym pliku — predykat `IS NULL` dałby zero wszędzie,
  bo kolumna ma ORM-owy default "manual");
- wodospad jest monotoniczny: credited ≥ credited_with_user ≥ credited_active_user;
- endpoint NICZEGO nie mutuje (row count przed == po);
- zero PII w odpowiedzi (żadnych e-maili ani nazwisk).

Uses in-process `app_client` / `app_auth_headers` fixtures (real postgres in CI).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app

URL = "/api/admin/process-adoption"


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Adopt",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"adopt-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"AdoptClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Adopt-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    external_source: str | None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=datetime.now(timezone.utc) - timedelta(days=1),
            external_source=external_source,
            # `external_id` niosą tylko wiersze z importu — dla 'manual' zostaje
            # pusty, tak jak na produkcji.
            external_id=(
                uuid.uuid4().hex[:10] if external_source == "traffit" else None
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _count_stage_rows() -> int:
    from sqlalchemy import text as sa_text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return int(
            (
                await db.execute(sa_text("SELECT count(*) FROM candidate_stages"))
            ).scalar_one()
        )


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_adoption_requires_auth(app_client: AsyncClient):
    r = await app_client.get(URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_adoption_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "adoption-good-token")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get(URL, headers={"X-Snapshot-Token": "wrong"})
    assert r.status_code == 401


async def test_adoption_rejects_non_admin(app_client: AsyncClient):
    """Zwykły user z ważnym JWT dostaje 403 — raport jest admin-only."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    email = f"adopt-viewer-{uuid.uuid4().hex[:8]}@example.com"
    password = f"V13wer_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Adopt Viewer",
                role=UserRole.user,
                is_active=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    r = await app_client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ── Shape + kontrakt pomiarowy ───────────────────────────────────────────────


async def test_adoption_shape_and_no_mutation(
    app_client: AsyncClient, app_auth_headers: dict
):
    before = await _count_stage_rows()

    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["query_version"]
    assert body["window"]["months"] == 14
    assert body["window"]["adoption_days"] == 90
    assert set(body["adoption"]) == {"by_stage_and_origin", "by_month_and_origin"}
    assert set(body["visibility"]) == {"processes_by_month", "milestone_waterfall"}
    assert "counts" in body["supporting"]

    # Żadne zapytanie nie może paść po cichu — raport ma to wołać wprost.
    assert body["summary"]["queries_failed"] == 0, body["diagnostics"]

    assert await _count_stage_rows() == before


async def test_manual_and_traffit_moves_are_distinguished(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Sedno metody: 'manual' i 'traffit' muszą trafić do OSOBNYCH kubełków.

    Gdyby ktoś przepisał zapytanie na `external_source IS NULL`, ten test padnie
    — kolumna ma ORM-owy default "manual", więc `IS NULL` nie znajduje nic.
    """
    cand = await _seed_candidate()
    job = await _seed_job()
    await _seed_stage(cand, job, "screening", external_source="manual")
    await _seed_stage(cand, job, "screening", external_source="traffit")

    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()["adoption"]["by_stage_and_origin"]

    screening = {row["origin"]: row for row in rows if row["stage"] == "screening"}
    assert "manual" in screening, rows
    assert "traffit" in screening, rows
    assert screening["manual"]["moves"] >= 1
    assert screening["traffit"]["moves"] >= 1

    summary = r.json()["summary"]
    assert summary["moves_manual"] >= 1
    assert summary["moves_in_window"] >= summary["moves_manual"]


async def test_waterfall_is_monotonic(app_client: AsyncClient, app_auth_headers: dict):
    """credited ≥ credited_with_user ≥ credited_active_user — kolejność odpadania.

    Odwrotna nierówność znaczyłaby, że filtr atrybucji DODAJE kamienie milowe,
    czyli że mierzymy co innego niż kafle.
    """
    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text

    for row in r.json()["visibility"]["milestone_waterfall"]:
        assert row["credited"] >= row["credited_with_user"], row
        assert row["credited_with_user"] >= row["credited_active_user"], row
        assert row["raw"] >= 0


async def test_response_carries_no_pii(app_client: AsyncClient, app_auth_headers: dict):
    """Raport ma same liczby i etykiety — żadnych e-maili ani nazwisk."""
    cand = await _seed_candidate()
    job = await _seed_job()
    await _seed_stage(cand, job, "screening", external_source="manual")

    r = await app_client.get(URL, headers=app_auth_headers)
    assert r.status_code == 200, r.text
    raw = json.dumps(r.json())

    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw), "adres e-mail w odpowiedzi"
    assert "Adopt" not in raw, "nazwa kandydata/klienta w odpowiedzi"


async def test_window_params_are_honoured(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        URL, headers=app_auth_headers, params={"months": 2, "adoption_days": 7}
    )
    assert r.status_code == 200, r.text
    window = r.json()["window"]
    assert window["months"] == 2
    assert window["adoption_days"] == 7
    # Krótsze okno adopcji musi zaczynać się PÓŹNIEJ niż okno miesięczne.
    assert window["adoption_since"] > window["monthly_since"]

    too_big = await app_client.get(
        URL, headers=app_auth_headers, params={"months": 999}
    )
    assert too_big.status_code == 422
