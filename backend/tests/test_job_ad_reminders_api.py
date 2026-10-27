"""Przypomnienia o brakujących ogłoszeniach (0526) — trasy i przebieg z bazą.

- poranny przebieg zakłada wpis o nowej rekrutacji dla DL-a i rekrutera,
  a o starej — jeden zbiorczy; drugi przebieg tego dnia nic nie dokłada;
- kolejka maili składa kartę ze świeżego stanu: kanał zrobiony od rana
  wypada, a gdy nic nie brakuje, mail nie wychodzi;
- „nie publikujemy” i „Przypomnij”: DL rekrutacji tak, rekruter nie (403);
- lista „do nadrobienia” niesie rekrutacje, w których osoba ma brak.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_ad_channel_skip import JobAdChannelSkip
from app.models.job_ad_publication import JobAdPublication
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import notification_delivery as delivery
from app.services.job_ad import reminders
from app.tasks import notification_email_outbox as outbox

pytestmark = pytest.mark.asyncio

WARSAW = ZoneInfo("Europe/Warsaw")
# Wtorek, dzień roboczy, 9:00 w Warszawie.
MORNING = datetime(2035, 3, 6, 9, 0, tzinfo=WARSAW)


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


def _policy_on(cutoff: datetime) -> delivery.DeliveryPolicy:
    return delivery.DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": cutoff.isoformat(),
            "types": {
                kind: {"email_enabled": True, "send_not_before": cutoff.isoformat()}
                for kind in delivery.ROUTINE_KINDS
            },
        }
    )


def _wire_policy(monkeypatch, policy: delivery.DeliveryPolicy) -> None:
    async def load(_db):
        return policy

    monkeypatch.setattr(delivery, "load_policy", load)
    monkeypatch.setattr(outbox, "load_policy", load)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: policy)


async def _account(role: UserRole, name: str) -> tuple[User, str]:
    unique = uuid.uuid4().hex[:8]
    password = f"T3st_{unique}!Rem"
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"reminders-{role.value}-{unique}@example.com",
            password_hash=hash_password(password),
            name=f"{name} {unique}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, password


async def _job(lead: User, recruiter: User, opened_at: datetime) -> Job:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient przypomnień {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Analityk przypomnień {uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter.id,
            delivery_lead_id=lead.id,
            opened_at=opened_at,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _login(api: AsyncClient, user: User, password: str) -> dict[str, str]:
    resp = await api.post(
        "/api/auth/login", json={"email": user.email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(job_ids: list[int], user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await db.execute(
            delete(JobAdChannelSkip).where(JobAdChannelSkip.job_id.in_(job_ids))
        )
        await db.execute(
            delete(JobAdPublication).where(JobAdPublication.job_id.in_(job_ids))
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "job", Activity.entity_id.in_(job_ids)
            )
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.execute(
            delete(AppSetting).where(AppSetting.key == reminders.STATE_KEY)
        )
        await db.commit()


async def _rows(user_ids: list[int]) -> list[tuple[int, str, int | None]]:
    async with AsyncSessionLocal() as db:
        return [
            (uid, ntype.value, entity)
            for uid, ntype, entity in (
                await db.execute(
                    select(
                        Notification.user_id,
                        Notification.notification_type,
                        Notification.related_entity_id,
                    ).where(
                        Notification.user_id.in_(user_ids),
                        Notification.notification_type.in_(
                            [
                                NotificationType.job_ad_missing,
                                NotificationType.job_ad_backlog,
                                NotificationType.job_ad_nudge,
                            ]
                        ),
                    )
                )
            ).all()
        ]


async def test_morning_run_writes_per_job_and_backlog_entries(monkeypatch) -> None:
    cutoff = MORNING - timedelta(days=3)
    _wire_policy(monkeypatch, _policy_on(cutoff))
    lead, _ = await _account(UserRole.delivery_lead, "Dorota Prowadząca")
    rec, _ = await _account(UserRole.recruiter, "Roman Rekrutujący")
    new = await _job(lead, rec, MORNING - timedelta(days=1))
    old = await _job(lead, rec, cutoff - timedelta(days=10))
    today = await _job(lead, rec, MORNING - timedelta(hours=1))
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(AppSetting).where(AppSetting.key == reminders.STATE_KEY)
            )
            await db.commit()
            assert await reminders.send_daily(db, MORNING) > 0
            await db.commit()
            # Drugi przebieg tego dnia nic nie dokłada.
            assert await reminders.send_daily(db, MORNING + timedelta(minutes=5)) == 0
        rows = await _rows([lead.id, rec.id])
        per_job = sorted((u, e) for u, t, e in rows if t == "job_ad_missing")
        assert per_job == sorted([(lead.id, new.id), (rec.id, new.id)])
        backlog = sorted(u for u, t, _ in rows if t == "job_ad_backlog")
        assert backlog == sorted([lead.id, rec.id])
        # Rekrutacja otwarta dziś — pierwsze przypomnienie jutro.
        assert all(e != today.id for _, _, e in rows)
        assert all(e != old.id for _, t, e in rows if t == "job_ad_missing")
    finally:
        await _cleanup([new.id, old.id, today.id], [lead.id, rec.id])


async def test_mail_is_built_from_fresh_state_and_skipped_when_done(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    _wire_policy(monkeypatch, _policy_on(now - timedelta(days=3)))
    monkeypatch.setattr(outbox, "email_channel_enabled", lambda: True)
    sent: list[tuple[str, str, str]] = []

    def fake_send(to, subject, text_body, html_body=None, **_kw):
        sent.append((to, subject, text_body))
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)
    lead, _ = await _account(UserRole.delivery_lead, "Dorota Prowadząca")
    rec, _ = await _account(UserRole.recruiter, "Roman Rekrutujący")
    job = await _job(lead, rec, now - timedelta(days=1))
    try:
        async with AsyncSessionLocal() as db:
            # Pracuj.pl wisi od rana — wypada z maila DL-a.
            db.add(
                JobAdPublication(
                    job_id=job.id,
                    portal="pracuj",
                    content_hash="x",
                    published_at=now,
                    published_by=lead.id,
                )
            )
            for user in (lead, rec):
                title, message, link = (
                    f"{reminders.TITLE_MISSING}: {job.title}",
                    "Brakuje: Strona kariery.",
                    f"/jobs/{job.id}?ogloszenie=kariera",
                )
                db.add(
                    Notification(
                        user_id=user.id,
                        notification_type=NotificationType.job_ad_missing,
                        title=title,
                        message=message,
                        link=link,
                        related_entity_type="job",
                        related_entity_id=job.id,
                    )
                )
            await db.commit()
            # Przebieg ma limit prób, a baza testów niesie wpisy innych testów —
            # wołamy kolejkę, aż oba maile wyjdą (jak kolejne minuty pętli).
            for _ in range(20):
                await outbox.dispatch(db)
                if {lead.email, rec.email} <= {to for to, _s, _t in sent}:
                    break
        by_to = {to: (subject, text) for to, subject, text in sent}
        subject, text = by_to[lead.email]
        assert subject == f"[NEXUS] Wstaw ogłoszenia · {job.title}"
        assert "Pracuj.pl: ✓ wisi od" in text
        assert f"/jobs/{job.id}?ogloszenie=jjit" in text
        assert "ogloszenie=pracuj" not in text
        subject, text = by_to[rec.email]
        assert subject == f"[NEXUS] Opublikuj na stronie kariery · {job.title}"
        assert f"/jobs/{job.id}?ogloszenie=kariera" in text
    finally:
        await _cleanup([job.id], [lead.id, rec.id])


async def test_skip_and_nudge_belong_to_the_lead(api: AsyncClient, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _wire_policy(monkeypatch, _policy_on(now - timedelta(days=3)))
    lead, lead_pw = await _account(UserRole.delivery_lead, "Dorota Prowadząca")
    rec, rec_pw = await _account(UserRole.recruiter, "Roman Rekrutujący")
    job = await _job(lead, rec, now - timedelta(days=1))
    try:
        lead_h = await _login(api, lead, lead_pw)
        rec_h = await _login(api, rec, rec_pw)

        state = (await api.get(f"/api/jobs/{job.id}/portal-ad", headers=rec_h)).json()
        channels = {c["channel"]: c for c in state["reminders"]["channels"]}
        assert channels["kariera"]["mine"] is True
        assert channels["pracuj"]["mine"] is False
        assert state["reminders"]["can_manage"] is False

        # Rekruter nie decyduje o kanałach ani nie przypomina.
        denied = await api.put(
            f"/api/jobs/{job.id}/portal-ad/skips/pracuj",
            json={"reason": "Klient nie chce"},
            headers=rec_h,
        )
        assert denied.status_code == 403
        assert (
            await api.post(f"/api/jobs/{job.id}/portal-ad/remind", headers=rec_h)
        ).status_code == 403

        short = await api.put(
            f"/api/jobs/{job.id}/portal-ad/skips/pracuj",
            json={"reason": "x"},
            headers=lead_h,
        )
        assert short.status_code == 422
        skipped = await api.put(
            f"/api/jobs/{job.id}/portal-ad/skips/pracuj",
            json={"reason": "Klient nie chce ogłoszeń na Pracuj.pl"},
            headers=lead_h,
        )
        assert skipped.status_code == 200, skipped.text
        channels = {c["channel"]: c for c in skipped.json()["reminders"]["channels"]}
        assert channels["pracuj"]["state"] == "skipped"
        assert (
            channels["pracuj"]["skip_reason"] == "Klient nie chce ogłoszeń na Pracuj.pl"
        )
        assert channels["pracuj"]["skipped_by_name"] == lead.name

        missing = (await api.get("/api/job-ads/missing", headers=lead_h)).json()
        item = next(i for i in missing["items"] if i["job_id"] == job.id)
        assert [c["state"] for c in item["channels"]] == [
            "missing",
            "skipped",
            "missing",
        ]
        assert item["backlog"] is False

        undone = await api.delete(
            f"/api/jobs/{job.id}/portal-ad/skips/pracuj", headers=lead_h
        )
        assert undone.status_code == 200
        assert (
            await api.delete(
                f"/api/jobs/{job.id}/portal-ad/skips/pracuj", headers=lead_h
            )
        ).status_code == 404

        first = await api.post(f"/api/jobs/{job.id}/portal-ad/remind", headers=lead_h)
        assert first.status_code == 200, first.text
        assert first.json() == {"sent_to": [rec.name], "already": []}
        again = await api.post(f"/api/jobs/{job.id}/portal-ad/remind", headers=lead_h)
        assert again.json() == {"sent_to": [], "already": [rec.name]}
        assert (rec.id, "job_ad_nudge", job.id) in await _rows([rec.id])

        rec_missing = (await api.get("/api/job-ads/missing", headers=rec_h)).json()
        assert any(i["job_id"] == job.id for i in rec_missing["items"])
        async with AsyncSessionLocal() as db:
            actions = (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "job", Activity.entity_id == job.id
                    )
                )
            ).all()
        assert "job_ad_channel_skipped" in actions
        assert "job_ad_channel_unskipped" in actions
    finally:
        await _cleanup([job.id], [lead.id, rec.id])
