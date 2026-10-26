"""„Nowa rekrutacja u Twojego klienta” — mail obowiązkowy dla DL-a (26.10.2026).

Dzwonek powstaje z wpisu ``Activity`` ``published`` (założenie i ponowne
otwarcie), do DL-a rekrutacji, a bez niego do Head of Recruitment, bez osoby,
która otworzyła. Kolejka maili zbiera wpisy osoby z 10 minut w jeden mail.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import client_job_opened as opened
from app.services import notification_delivery as delivery
from app.services import notification_email_prefs as prefs
from app.tasks import notification_email_outbox as outbox

# Daleko w przyszłości: okno skanera widzi wyłącznie otwarcia z tego testu,
# nie wpisy, które inne testy zostawiają we wspólnej bazie.
FUTURE = datetime(2035, 3, 6, 10, 0, tzinfo=timezone.utc)


def _plain_user(role: UserRole) -> User:
    return User(
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
        daily_digest_email_enabled=True,
        email_opt_outs={},
        muted_notification_categories={},
    )


# ── Bez bazy ────────────────────────────────────────────────────────────────


def test_kind_is_required_immediate_and_in_the_catalog():
    kind = delivery.CLIENT_JOB_KIND
    assert kind in delivery.REQUIRED_KINDS and kind in delivery.IMMEDIATE_KINDS
    assert delivery.notification_kind(NotificationType.client_job_opened) == kind
    assert (
        delivery.immediate_email_kind(
            NotificationType.client_job_opened,
            title=opened.TITLE,
            related_entity_type="job",
        )
        == kind
    )
    spec = next(item for item in delivery.CATALOG if item["id"] == kind)
    assert spec["label"] == "Nowa rekrutacja u Twojego klienta"
    # Zbiorczy dzwonek rano zostaje bez maila.
    assert delivery.notification_kind(NotificationType.request_review_needed) is None


def test_bell_message_names_job_client_and_opening_day():
    at = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)  # 22.10 w Warszawie
    assert (
        opened.bell_message(
            title="Scrum Master", client="Klient A", opened_at=at, reopened=False
        )
        == "Scrum Master · Klient A · otwarta 22.10.2026"
    )
    assert opened.bell_message(
        title="Scrum Master", client=None, opened_at=at, reopened=True
    ).endswith("Scrum Master · otwarta ponownie 22.10.2026")


def test_mail_applies_to_delivery_leads_and_heads_only():
    assert prefs.APPLIES["client_job_opened"](
        _plain_user(UserRole.delivery_lead), prefs._Context()
    )
    assert prefs.APPLIES["client_job_opened"](
        _plain_user(UserRole.head_of_recruitment), prefs._Context()
    )
    for role in (UserRole.recruiter, UserRole.finance, UserRole.employee):
        assert not prefs.APPLIES["client_job_opened"](
            _plain_user(role), prefs._Context()
        )


@pytest.mark.asyncio
async def test_account_cannot_switch_it_off_and_not_where_it_does_not_apply():
    lead = _plain_user(UserRole.delivery_lead)
    with pytest.raises(prefs.EmailKindRequired):
        await prefs.set_enabled(object(), lead, "client_job_opened", False)
    recruiter = _plain_user(UserRole.recruiter)
    with pytest.raises(prefs.EmailKindNotApplicable):
        await prefs.set_enabled(object(), recruiter, "client_job_opened", False)
    assert lead.email_opt_outs == {} and recruiter.email_opt_outs == {}


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _account(db, role: UserRole, name: str) -> User:
    user = User(
        email=f"client-job-{uuid.uuid4().hex}@example.com",
        password_hash="test-only",
        name=name,
        role=role,
        roles=[role.value],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db, client: Client, title: str, **fields) -> Job:
    job = Job(title=title, status=JobStatus.published, client_id=client.id, **fields)
    db.add(job)
    await db.flush()
    return job


def _published(job: Job, actor: User | None, at: datetime, **details) -> Activity:
    return Activity(
        entity_type="job",
        entity_id=job.id,
        action="published",
        user_id=actor.id if actor else None,
        details=details or None,
        created_at=at,
    )


async def _bells(db, user_ids: list[int]) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification)
                .where(
                    Notification.notification_type
                    == NotificationType.client_job_opened,
                    Notification.user_id.in_(user_ids),
                )
                .order_by(Notification.id)
            )
        ).all()
    )


async def _cleanup(db, objects: list) -> None:
    for obj in reversed(objects):
        await db.delete(obj)
    await db.commit()


@pytest.mark.asyncio
async def test_opening_rings_the_lead_but_not_the_one_who_opened_it():
    async with AsyncSessionLocal() as db:
        lead = await _account(db, UserRole.delivery_lead, "Dorota Przykładowa")
        other_lead = await _account(db, UserRole.delivery_lead, "Daniel Przykładowy")
        head = await _account(db, UserRole.head_of_recruitment, "Hanna Przykładowa")
        tcm = await _account(db, UserRole.recruiter, "Tomasz Przykładowy")
        client = Client(name=f"Klient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        by_other = await _job(db, client, "Analityk A", delivery_lead_id=lead.id)
        by_lead = await _job(db, client, "Analityk B", delivery_lead_id=lead.id)
        no_lead = await _job(db, client, "Analityk C")
        reopened = await _job(db, client, "Analityk D", delivery_lead_id=other_lead.id)
        closed = await _job(db, client, "Analityk E", delivery_lead_id=lead.id)
        closed.status = JobStatus.closed
        events = [
            _published(by_other, tcm, FUTURE - timedelta(hours=2)),
            # 52 z 56 rekrutacji z 14 dni założył sam DL — bez maila o sobie.
            _published(by_lead, lead, FUTURE - timedelta(hours=2)),
            # Konto serwisowe API (wpis bez autora), rekrutacja bez DL-a.
            _published(no_lead, None, FUTURE - timedelta(hours=1)),
            _published(reopened, tcm, FUTURE - timedelta(minutes=30), reopened=True),
            _published(closed, tcm, FUTURE - timedelta(hours=1)),
            # Poza oknem skanera.
            _published(by_other, tcm, FUTURE - opened.LOOKBACK - timedelta(hours=1)),
        ]
        db.add_all(events)
        await db.commit()
        people = [lead.id, other_lead.id, head.id, tcm.id]
        try:
            created = await opened.emit_opened(db, FUTURE)
            await db.commit()
            bells = await _bells(db, people)
            got = {(b.user_id, b.related_entity_id) for b in bells}
            assert got == {
                (lead.id, by_other.id),
                (head.id, no_lead.id),
                (other_lead.id, reopened.id),
            }
            assert created >= 3  # inni Head of Recruitment ze wspólnej bazy też
            by_job = {b.related_entity_id: b for b in bells}
            assert by_job[by_other.id].title == opened.TITLE
            assert by_job[by_other.id].link == f"/jobs/{by_other.id}"
            assert by_job[by_other.id].message.startswith(f"Analityk A · {client.name}")
            assert "otwarta ponownie" in by_job[reopened.id].message
            # Drugi przebieg niczego nie dokłada.
            await opened.emit_opened(db, FUTURE)
            await db.commit()
            assert len(await _bells(db, people)) == 3
        finally:
            leftovers = (
                await db.scalars(
                    select(Notification).where(
                        Notification.notification_type
                        == NotificationType.client_job_opened,
                        Notification.related_entity_id.in_(
                            [
                                by_other.id,
                                by_lead.id,
                                no_lead.id,
                                reopened.id,
                                closed.id,
                            ]
                        ),
                    )
                )
            ).all()
            await _cleanup(
                db,
                [lead, other_lead, head, tcm, client, by_other, by_lead, no_lead]
                + [reopened, closed, *events, *leftovers],
            )


@pytest.mark.asyncio
async def test_openings_before_the_mail_was_switched_on_get_no_bell(monkeypatch):
    cutoff = FUTURE - timedelta(minutes=5)

    async def policy(_db):
        return delivery.DeliveryPolicy.from_value(
            {
                "enabled": True,
                "send_not_before": cutoff.isoformat(),
                "types": {
                    "client_job_opened": {
                        "email_enabled": True,
                        "send_not_before": cutoff.isoformat(),
                    }
                },
            }
        )

    monkeypatch.setattr(opened, "load_policy", policy)
    async with AsyncSessionLocal() as db:
        lead = await _account(db, UserRole.delivery_lead, "Dorota Przykładowa")
        tcm = await _account(db, UserRole.recruiter, "Tomasz Przykładowy")
        client = Client(name=f"Klient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = await _job(db, client, "Analityk F", delivery_lead_id=lead.id)
        event = _published(job, tcm, FUTURE - timedelta(hours=1))
        db.add(event)
        await db.commit()
        try:
            await opened.emit_opened(db, FUTURE)
            await db.commit()
            assert await _bells(db, [lead.id]) == []
        finally:
            await _cleanup(db, [lead, tcm, client, job, event])


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


def _wire(monkeypatch, policy) -> list[tuple[str, str, str, str]]:
    async def load(_db):
        return policy

    monkeypatch.setattr(outbox, "load_policy", load)
    monkeypatch.setattr(delivery, "load_policy_sync", lambda: policy)
    monkeypatch.setattr(outbox, "email_channel_enabled", lambda: True)
    sent: list[tuple[str, str, str, str]] = []

    def fake_send(to, subject, text_body, html_body=None):
        sent.append((to, subject, text_body, html_body or ""))
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)
    return sent


def _bell(user: User, job: Job, minutes_ago: int) -> Notification:
    return Notification(
        user_id=user.id,
        notification_type=NotificationType.client_job_opened,
        title=opened.TITLE,
        message=f"{job.title} · Klient · otwarta 06.03.2035",
        link=f"/jobs/{job.id}",
        related_entity_type="job",
        related_entity_id=job.id,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_queue_sends_one_mail_for_openings_from_ten_minutes(monkeypatch):
    now = datetime.now(timezone.utc)
    sent = _wire(monkeypatch, _policy_on(now - timedelta(hours=1)))
    async with AsyncSessionLocal() as db:
        lead = await _account(db, UserRole.delivery_lead, "Dorota Przykładowa")
        single = await _account(db, UserRole.delivery_lead, "Daniel Przykładowy")
        waiting = await _account(db, UserRole.delivery_lead, "Dagmara Przykładowa")
        owner = await _account(db, UserRole.recruiter, "Roman Przykładowy")
        client = Client(name=f"Klient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        led = await _job(db, client, "Tester G", recruiter_id=owner.id)
        free = await _job(db, client, "Tester H")
        late = await _job(db, client, "Tester I")
        closed = await _job(db, client, "Tester J")
        closed.status = JobStatus.closed
        rows = [
            _bell(lead, led, 12),
            _bell(lead, free, 11),
            # Młodszy niż okno — dołącza do paczki najstarszego.
            _bell(lead, late, 2),
            # Rekrutacja zamknięta przed wysyłką wypada z maila.
            _bell(lead, closed, 11),
            _bell(single, free, 15),
            # Jedyny wpis osoby jest młodszy niż okno — mail jeszcze czeka.
            _bell(waiting, free, 3),
        ]
        db.add_all(rows)
        await db.commit()
        ids = [row.id for row in rows]
        try:
            await outbox.dispatch(db)
            await outbox.dispatch(db)  # drugi przebieg nic nie dokłada
            by_to: dict[str, list] = {}
            for item in sent:
                by_to.setdefault(item[0], []).append(item)
            assert len(by_to[lead.email]) == 1
            _to, subject, text, _html = by_to[lead.email][0]
            assert subject == "[Nexus] Nowe rekrutacje u Twoich klientów: 3"
            assert "Tester G" in text and "Prowadzi: Roman Przykładowy." in text
            assert "Tester H" in text and "Tester I" in text
            assert "Nikt jej jeszcze nie prowadzi." in text
            assert "Tester J" not in text
            assert "/jobs" in text

            assert len(by_to[single.email]) == 1
            _to, subject, text, _html = by_to[single.email][0]
            assert subject == "[Nexus] Nowa rekrutacja u Twojego klienta"
            assert f"/jobs/{free.id}" in text
            assert waiting.email not in by_to

            stamped = dict(
                (
                    await db.execute(
                        select(Notification.id, Notification.email_sent_at).where(
                            Notification.id.in_(ids)
                        )
                    )
                ).all()
            )
            assert all(stamped[i] is not None for i in (ids[0], ids[1], ids[2], ids[4]))
            assert stamped[ids[3]] is None and stamped[ids[5]] is None
        finally:
            await _cleanup(
                db,
                [lead, single, waiting, owner, client, led, free, late, closed, *rows],
            )
