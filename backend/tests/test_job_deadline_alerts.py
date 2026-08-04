"""Testy skanera `job_deadline_alerts` — progi, dobór odbiorców, dedup, status."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.tasks.job_deadline_alerts import run_once

pytestmark = pytest.mark.asyncio


async def _mk_user(db, role: UserRole, tag: str) -> User:
    suffix = uuid.uuid4().hex[:6]
    u = User(
        email=f"jda-{tag}-{suffix}@example.com",
        password_hash=hash_password("x"),
        name=f"{tag} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(u)
    return u


async def _setup(deadline: date, status: JobStatus = JobStatus.published):
    """Zwraca (job_id, recruiter_id, collaborator_id, outsider_admin_id, client_id)."""
    async with AsyncSessionLocal() as db:
        recruiter = await _mk_user(db, UserRole.recruiter, "rec")
        collaborator = await _mk_user(db, UserRole.recruiter, "col")
        outsider_admin = await _mk_user(db, UserRole.admin, "adm")
        client = Client(name=f"JDA Client {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()

        job = Job(
            title="Senior Backend Engineer",
            client_id=client.id,
            status=status,
            deadline=deadline,
            recruiter_id=recruiter.id,
        )
        db.add(job)
        await db.flush()

        db.add(
            JobCollaborator(
                job_id=job.id,
                user_id=collaborator.id,
                added_by=recruiter.id,
            )
        )
        await db.commit()
        return (
            job.id,
            recruiter.id,
            collaborator.id,
            outsider_admin.id,
            client.id,
        )


async def _cleanup(job_id: int, client_id: int, user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        for uid in user_ids:
            await db.execute(
                Notification.__table__.delete().where(Notification.user_id == uid)
            )
        await db.execute(
            JobCollaborator.__table__.delete().where(JobCollaborator.job_id == job_id)
        )
        await db.execute(Job.__table__.delete().where(Job.id == job_id))
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        if user_ids:
            await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        await db.commit()


async def _recipients_for(job_id: int, ntype: NotificationType) -> set[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification.user_id).where(
                Notification.related_entity_type == "job",
                Notification.related_entity_id == job_id,
                Notification.notification_type == ntype,
            )
        )
        return {r[0] for r in rows.all()}


async def test_alert_to_assigned_not_to_outsider_admin():
    """7 dni przed deadline → owner + collaborator; NIE globalny admin spoza joba."""
    deadline = date.today() + timedelta(days=7)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(deadline)
    try:
        summary = await run_once()
        assert summary["enabled"] is True
        recipients = await _recipients_for(job_id, NotificationType.job_deadline_7d)
        assert rec_id in recipients
        assert col_id in recipients
        # Globalny admin nieprzypisany do joba NIE dostaje deadline-alertu.
        assert adm_id not in recipients
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])


async def test_no_alert_for_draft_job():
    """Draft (status != published) z deadline w progu → brak notyfikacji."""
    deadline = date.today() + timedelta(days=7)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(
        deadline, status=JobStatus.draft
    )
    try:
        await run_once()
        recipients = await _recipients_for(job_id, NotificationType.job_deadline_7d)
        assert recipients == set()
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])


async def test_no_alert_outside_thresholds():
    """Deadline za 5 dni (poza {7,3,1}) → brak notyfikacji."""
    deadline = date.today() + timedelta(days=5)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(deadline)
    try:
        await run_once()
        async with AsyncSessionLocal() as db:
            cnt = await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                )
            )
        assert cnt == 0
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])


async def test_dedup_no_duplicate_on_second_run():
    """Druga iteracja nie tworzy duplikatów dla (job, user, próg)."""
    deadline = date.today() + timedelta(days=3)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(deadline)
    try:
        await run_once()
        first = await _recipients_for(job_id, NotificationType.job_deadline_3d)
        await run_once()
        async with AsyncSessionLocal() as db:
            cnt = await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                    Notification.notification_type == NotificationType.job_deadline_3d,
                )
            )
        assert first == {rec_id, col_id}
        assert cnt == len(first)  # bez duplikatów po drugim przebiegu
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])


async def test_email_dispatch_marks_sent_on_success(monkeypatch):
    """SMTP on + send_email→True → email_sent_at stemplowany na deadline-notyfikacjach."""
    import app.tasks.job_deadline_alerts as jda
    from app.core.config import settings

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)
    sent_to: list[str] = []

    def _fake_send(to, subject, text_body, html_body=None):
        sent_to.append(to)
        return True

    monkeypatch.setattr(jda, "send_email", _fake_send)

    deadline = date.today() + timedelta(days=7)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(deadline)
    try:
        summary = await run_once()
        assert summary["emails_sent"] >= 2  # recruiter + collaborator
        assert set(sent_to)  # email realnie próbowany

        async with AsyncSessionLocal() as db:
            rows = list(
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.related_entity_type == "job",
                            Notification.related_entity_id == job_id,
                            Notification.notification_type
                            == NotificationType.job_deadline_7d,
                        )
                    )
                ).scalars()
            )
        assert rows
        assert all(n.email_sent_at is not None for n in rows)
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])


async def test_email_dispatch_releases_claim_on_failure(monkeypatch):
    """SMTP on + send_email→False → email_sent_at NULL i rezerwacja zwolniona (retryable)."""
    import app.tasks.job_deadline_alerts as jda
    from app.core.config import settings

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)
    monkeypatch.setattr(jda, "send_email", lambda *a, **k: False)

    deadline = date.today() + timedelta(days=1)
    job_id, rec_id, col_id, adm_id, client_id = await _setup(deadline)
    try:
        summary = await run_once()
        assert summary["emails_sent"] == 0

        async with AsyncSessionLocal() as db:
            rows = list(
                (
                    await db.execute(
                        select(Notification).where(
                            Notification.related_entity_type == "job",
                            Notification.related_entity_id == job_id,
                            Notification.notification_type
                            == NotificationType.job_deadline_1d,
                        )
                    )
                ).scalars()
            )
        assert rows
        # Nie wysłane + claim zwolniony → kolejny przebieg spróbuje ponownie.
        assert all(n.email_sent_at is None for n in rows)
        assert all(n.email_send_started_at is None for n in rows)
    finally:
        await _cleanup(job_id, client_id, [rec_id, col_id, adm_id])
