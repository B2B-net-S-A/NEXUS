"""``emit`` na prawdziwej bazie: wiersz trafia do zastępcy i pamięta, za kogo."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.client import Client
from app.models.dl_alert import DlAlert
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.core.config import settings
from app.services import dl_alerts
from app.services import notification_substitution as sub
from app.services import notification_triggers as nt
from app.services.workforce_availability import Delegation, WorkforceContext


@pytest_asyncio.fixture
async def db():
    pytest.importorskip("asyncpg")
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            yield session
            await session.rollback()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable: {exc}")


async def _user(db) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(
        email=f"zast-{tag}@example.test",
        password_hash="x",
        name=f"Zast {tag}",
        role=UserRole.recruiter,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _covering(owner: User, substitute: User):
    context = WorkforceContext(
        delegations={
            owner.id: Delegation(
                owner_id=owner.id,
                performer_id=substitute.id,
                start_date=date(2026, 11, 9),
                end_date=date(2026, 11, 13),
                source_ids=("x",),
            )
        }
    )

    async def fake(_db):
        return context

    return fake


async def _emit(db, user_id: int, *, entity: int | None = 5):
    return await nt.emit(
        db,
        user_id=user_id,
        title="Terminy rozmowy od klienta",
        message="2 terminy",
        ntype=NotificationType.interview_slots_requested,
        related_entity_type="interview_slot_request",
        related_entity_id=entity,
        link="/calendar",
    )


@pytest.mark.asyncio
async def test_row_goes_to_substitute_and_counts_for_addressee(db, monkeypatch):
    owner, substitute = await _user(db), await _user(db)
    monkeypatch.setattr(sub, "workforce_context", _covering(owner, substitute))

    row = await _emit(db, owner.id)

    assert row.user_id == substitute.id
    assert row.on_behalf_of_user_id == owner.id
    # Skaner „już wysłano tej osobie” widzi wiersz u zastępcy.
    found = await db.scalar(
        select(Notification.id).where(
            Notification.addressee_id == owner.id,
            Notification.notification_type
            == NotificationType.interview_slots_requested,
        )
    )
    assert found == row.id


@pytest.mark.asyncio
async def test_quiet_row_when_substitute_acted_himself(db, monkeypatch):
    """Zastępca sam wykonał ruch: bez dzwonka i maila, ale wiersz zostaje.

    Do 16.11.2026 nie powstawał wcale i osoba po powrocie nie wiedziała
    np. o zamknięciu rekrutacji z jej kandydatami („Gdy Cię nie było”).
    """
    owner, substitute = await _user(db), await _user(db)
    monkeypatch.setattr(sub, "workforce_context", _covering(owner, substitute))
    db.info[sub.ACTOR_KEY] = substitute.id

    row = await _emit(db, owner.id)
    assert row is not None
    assert (row.user_id, row.on_behalf_of_user_id) == (substitute.id, owner.id)
    assert row.quiet is True and row.is_read is True


@pytest.mark.asyncio
async def test_owner_and_substitute_in_one_list_get_one_row(db, monkeypatch):
    owner, substitute = await _user(db), await _user(db)
    monkeypatch.setattr(sub, "workforce_context", _covering(owner, substitute))

    assert await _emit(db, owner.id, entity=None) is not None
    assert await _emit(db, substitute.id, entity=None) is None


@pytest.mark.asyncio
async def test_dl_alert_goes_to_substitute_and_stays_live(db, monkeypatch):
    """Skaner liczy klucz sprawy z nominalnym DL-em, więc tak ma być zapisany."""
    owner, substitute = await _user(db), await _user(db)
    client = Client(name=f"Zast klient {uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    monkeypatch.setattr(settings, "DL_ALERTS_ENABLED", True)
    monkeypatch.setattr(dl_alerts, "workforce_context", _covering(owner, substitute))

    created = await dl_alerts.emit(
        db,
        alert_type="order_mail_review",
        user_ids=[owner.id],
        client_id=client.id,
        entity_key="e1",
        title="Alert",
        message="Treść",
    )

    assert len(created) == 1
    assert created[0].user_id == substitute.id
    assert created[0].event_key == dl_alerts.event_key_for(
        "order_mail_review", "e1", owner.id
    )
    assert created[0].message.startswith("W zastępstwie za ")
    assert isinstance(created[0], DlAlert)


@pytest.mark.asyncio
async def test_dl_alert_mail_reaches_substitute_outside_client_scope(
    monkeypatch, routine_notification_email_enabled
):
    """Zastępca DL-a nie jest przypisany do klienta, a mail T-14 i tak ma do
    niego dojść (audyt r4, 24.11.2026): bramka `for_client` odrzucała wiersz
    i mail nie szedł do nikogo."""
    pytest.importorskip("asyncpg")
    import app.services.email as email_mod
    import app.services.m365.system_mail as system_mail
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_PERIODIC_ORDER_ENDING
    from app.models.team_structure import DeliveryLeadClientAssignment

    sent: list[str] = []

    async def _no_connection(_db):
        return None

    monkeypatch.setattr(system_mail, "get_system_sender_connection", _no_connection)
    monkeypatch.setattr(email_mod, "email_channel_enabled", lambda: True)
    monkeypatch.setattr(
        email_mod,
        "send_email",
        lambda to, subject, text, html=None: sent.append(to) or True,
    )
    monkeypatch.setattr(settings, "DL_ALERTS_ENABLED", True)
    monkeypatch.setattr(settings, "DL_ALERT_EMAIL_ENABLED", True)

    try:
        async with AsyncSessionLocal() as session:
            owner, substitute = await _user(session), await _user(session)
            owner.role = substitute.role = UserRole.delivery_lead
            client = Client(name=f"Zast mail {uuid.uuid4().hex[:8]}")
            session.add(client)
            await session.flush()
            session.add(
                DeliveryLeadClientAssignment(
                    client_id=client.id, delivery_lead_user_id=owner.id
                )
            )
            await session.commit()
            owner_id, substitute_id, client_id = owner.id, substitute.id, client.id
            owner_email, substitute_email = owner.email, substitute.email
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable: {exc}")

    monkeypatch.setattr(
        dl_alerts,
        "workforce_context",
        _covering(SimpleNamespace(id=owner_id), SimpleNamespace(id=substitute_id)),
    )
    try:
        async with AsyncSessionLocal() as session:
            created = await dl_alerts.emit(
                session,
                alert_type=ALERT_PERIODIC_ORDER_ENDING,
                user_ids=[owner_id],
                client_id=client_id,
                entity_key=f"order:{uuid.uuid4().int % 10**9}:end:2026-12-10",
                title="Zamówienie kończy się",
                message="m",
                link="/clients/1?tab=zamowienia&order=1",
                stage="t14",
                email=True,
            )
            await session.commit()
            assert [row.user_id for row in created] == [substitute_id]
            await dl_alerts.send_pending_alert_emails(session)

        assert sent.count(substitute_email) == 1
        assert owner_email not in sent
        async with AsyncSessionLocal() as session:
            row = await session.get(DlAlert, created[0].id)
            assert row.email_sent_at is not None
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(DlAlert).where(DlAlert.client_id == client_id))
            await session.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == client_id
                )
            )
            await session.commit()
