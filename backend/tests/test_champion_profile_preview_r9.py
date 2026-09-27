"""Runda 9 — odczyt profilu Championa bez efektów ubocznych i adresaci zmian.

- R9-N1-2: admin w „podglądzie jako” nie gasi powiadomień podglądanej osoby;
- R9-V2-4: ``?mark_read=false`` (kopiowanie szablonu na ``/jobs/new``) też nie;
- R9-N2-7: „Profil Championa zaktualizowany” nie idzie do współpracownika
  zdjętego z auto-CC ani do konta nieaktywnego.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własne dane
i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole


def _headers(user_id: int, role: str) -> dict:
    from app.core.security import create_access_token

    return {
        "Authorization": f"Bearer {create_access_token(subject=user_id, role=role)}"
    }


async def _user(db, role: str, *, active: bool = True) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"r9-preview-{marker}@example.com",
        name=f"R9 {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=active,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, *, recruiter_id: int | None) -> Job:
    client = Client(name=f"Synthetic R9 Preview {uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    job = Job(
        title="Synthetic R9 role",
        status=JobStatus.published,
        client_id=client.id,
        recruiter_id=recruiter_id,
        champion_profile={"project": {"about": "Migracja systemu płatności."}},
    )
    db.add(job)
    await db.flush()
    return job


async def _unread(db, user_id: int, job_id: int) -> int:
    notif = Notification(
        user_id=user_id,
        title="Profil Championa zaktualizowany",
        message="R9",
        notification_type=NotificationType.champion_profile_updated,
        link=f"/jobs/{job_id}?tab=champion",
        related_entity_type="job",
        related_entity_id=job_id,
        is_read=False,
    )
    db.add(notif)
    await db.flush()
    return notif.id


async def _is_read(notif_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            await db.scalar(
                select(Notification.is_read).where(Notification.id == notif_id)
            )
        )


@pytest.mark.asyncio
async def test_preview_and_template_copy_do_not_mark_notifications_read(
    app_client,
) -> None:
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        admin = await _user(db, "admin")
        job = await _job(db, recruiter_id=recruiter.id)
        notif_id = await _unread(db, recruiter.id, job.id)
        await db.commit()
        recruiter_id, admin_id, job_id = recruiter.id, admin.id, job.id

    route = f"/api/jobs/{job_id}/champion-profile"

    preview = await app_client.get(
        route,
        headers={
            **_headers(admin_id, "admin"),
            "X-Impersonate-User-Id": str(recruiter_id),
        },
    )
    assert preview.status_code == 200, preview.text
    assert await _is_read(notif_id) is False

    template = await app_client.get(
        f"{route}?mark_read=false", headers=_headers(recruiter_id, "recruiter")
    )
    assert template.status_code == 200, template.text
    assert await _is_read(notif_id) is False

    # Kontrola: zwykłe otwarcie profilu nadal gasi powiadomienie.
    opened = await app_client.get(route, headers=_headers(recruiter_id, "recruiter"))
    assert opened.status_code == 200, opened.text
    assert await _is_read(notif_id) is True


@pytest.mark.asyncio
async def test_champion_update_skips_removed_and_inactive_collaborators(
    app_client, app_auth_headers
) -> None:
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        kept = await _user(db, "recruiter")
        removed = await _user(db, "recruiter")
        inactive = await _user(db, "recruiter", active=False)
        job = await _job(db, recruiter_id=recruiter.id)
        db.add_all(
            [
                JobCollaborator(job_id=job.id, user_id=kept.id),
                JobCollaborator(
                    job_id=job.id, user_id=removed.id, removed_from_auto_cc=True
                ),
                JobCollaborator(job_id=job.id, user_id=inactive.id),
            ]
        )
        await db.commit()
        job_id = job.id
        expected = {recruiter.id, kept.id}
        excluded = {removed.id, inactive.id}

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={"project": {"about": "Migracja płatności kartowych R9."}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        notified = set(
            (
                await db.scalars(
                    select(Notification.user_id).where(
                        Notification.notification_type
                        == NotificationType.champion_profile_updated,
                        Notification.related_entity_type == "job",
                        Notification.related_entity_id == job_id,
                    )
                )
            ).all()
        )
    assert expected <= notified
    assert not (excluded & notified)
