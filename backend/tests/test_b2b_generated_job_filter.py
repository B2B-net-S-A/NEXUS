"""Filtr `?job_id=` na liście wygenerowanych umów B2B.

Krok 08 „Umowa" (program „flow w języku C2") pyta o umowy JEDNEJ rekrutacji.
Bez filtra serwerowego karta zamknięcia musiałaby pobrać najnowsze ``limit``
wierszy CAŁEGO rejestru i przesiać je w przeglądarce — a wtedy umowa starsza
niż widoczna strona po prostu by nie istniała dla tego ekranu. To ten sam
argument, dla którego ``?q=`` jest serwerowe.

Test celowo wstawia „umowę tej rekrutacji" jako STARSZĄ (niższy ``created_at``)
i dokłada świeższe wiersze innych rekrutacji: przy filtrowaniu po stronie
klienta z ``limit`` ta pierwsza wypadłaby z okna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

PATH = "/api/b2b-generator/generated"


async def _admin_user_id(app_client) -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None, "app_client nie zaseedował admina"
    return uid


async def _seed_job(title: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"B2BJobFilterClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        job = Job(title=title, status=JobStatus.published, client_id=client.id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_contract(created_by: int, *, job_id: int | None, created_at) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="Grzegorz Żebrowski",
            client_name="PKO BP",
            language="pl",
            created_by=created_by,
            job_id=job_id,
            created_at=created_at,
            render_payload={"language": "pl", "client_name": "PKO BP"},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def test_job_filter_finds_a_contract_older_than_the_visible_page(
    app_client, app_auth_headers
) -> None:
    created_by = await _admin_user_id(app_client)
    job_id = await _seed_job(f"B2BJobFilter-{uuid.uuid4().hex[:6]}")
    other_job_id = await _seed_job(f"B2BJobFilterOther-{uuid.uuid4().hex[:6]}")

    now = datetime.now(timezone.utc)
    wanted = await _seed_contract(
        created_by, job_id=job_id, created_at=now - timedelta(days=400)
    )
    # Świeższe wiersze innej rekrutacji — przy `limit=1` to one wypełniłyby okno.
    for offset in range(3):
        await _seed_contract(
            created_by,
            job_id=other_job_id,
            created_at=now - timedelta(minutes=offset),
        )

    resp = await app_client.get(
        PATH, params={"job_id": job_id, "limit": 1}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["id"] for r in rows] == [wanted]
    assert rows[0]["job_id"] == job_id


async def test_without_the_filter_the_same_call_is_not_scoped_to_the_job(
    app_client, app_auth_headers
) -> None:
    """Kontrola negatywna — filtr naprawdę zawęża, a nie jest ignorowany."""
    created_by = await _admin_user_id(app_client)
    job_id = await _seed_job(f"B2BJobFilterNeg-{uuid.uuid4().hex[:6]}")
    now = datetime.now(timezone.utc)
    await _seed_contract(created_by, job_id=job_id, created_at=now)
    await _seed_contract(created_by, job_id=None, created_at=now)

    scoped = await app_client.get(
        PATH, params={"job_id": job_id, "limit": 50}, headers=app_auth_headers
    )
    assert scoped.status_code == 200, scoped.text
    assert {r["job_id"] for r in scoped.json()} == {job_id}

    unscoped = await app_client.get(
        PATH, params={"limit": 50}, headers=app_auth_headers
    )
    assert unscoped.status_code == 200, unscoped.text
    assert any(r["job_id"] != job_id for r in unscoped.json())


async def test_a_job_without_contracts_returns_an_empty_list(
    app_client, app_auth_headers
) -> None:
    job_id = await _seed_job(f"B2BJobFilterEmpty-{uuid.uuid4().hex[:6]}")
    resp = await app_client.get(
        PATH, params={"job_id": job_id}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
