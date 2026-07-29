"""DELETE /api/jobs/{id} musi zwracać 409 dla wierszy Priority Work.

Migracja 0200 dołożyła do `jobs` trzy klucze obce z ON DELETE RESTRICT
(`recruitment_priority_demands`, `_assignments`, `_exceptions`), a model `Job`
nie ma do nich żadnej relacji ORM — `db.delete(job)` nie emituje więc DELETE na
dzieciach i Postgres podnosił ForeignKeyViolation dopiero na COMMIT. Jedyny
handler wyjątków w `app/main.py` to RateLimitExceeded, więc użytkownik dostawał
nieobsłużone 500 zamiast czytelnego 409 — mimo że strażnik 409 w `delete_job`
istniał, tylko liczył wyłącznie procesy i candidate_stages.

Używa fixture'ów `app_client` / `app_auth_headers` z conftest (realny postgres).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PrioGuardClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"PrioGuard-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_user() -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        user = User(
            email=f"prio-guard-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("T3st_PrioGuard!Pass"),
            name="Prio Guard",
            role=UserRole.user,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def test_job_without_priority_rows_still_deletes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Kontrola negatywna — strażnik nie może blokować czystego requestu."""
    job_id = await _seed_job()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 204, resp.text


async def test_job_with_priority_demand_returns_409_not_500(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_priority import RecruitmentPriorityDemand

    job_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentPriorityDemand(
                job_id=job_id,
                rationale="test: demand blokuje usunięcie requestu",
            )
        )
        await db.commit()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "PRIORITY_CARRY_OVER_EXISTS"
    assert detail["priority_demand_rows"] == 1
    # Bez zapotrzebowania nie ma ani procesu, ani stage'a — 409 musi wynikać
    # wyłącznie z nowo zliczanej tabeli, nie ze starych warunków.
    assert detail["process_rows"] == 0
    assert detail["candidate_stage_rows"] == 0


async def test_job_with_priority_exception_returns_409_not_500(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_priority import RecruitmentPriorityException

    job_id = await _seed_job()
    user_id = await _seed_user()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentPriorityException(
                user_id=user_id,
                job_id=job_id,
                reason="test: odstępstwo blokuje usunięcie requestu",
                valid_from=now,
                expires_at=now + timedelta(days=1),
            )
        )
        await db.commit()

    resp = await app_client.delete(f"/api/jobs/{job_id}", headers=app_auth_headers)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "PRIORITY_CARRY_OVER_EXISTS"
    assert detail["priority_exception_rows"] == 1
