"""``emit`` na prawdziwej bazie: wiersz trafia do zastępcy i pamięta, za kogo."""

from __future__ import annotations

import uuid
from datetime import date

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
async def test_no_row_when_substitute_acted_himself(db, monkeypatch):
    owner, substitute = await _user(db), await _user(db)
    monkeypatch.setattr(sub, "workforce_context", _covering(owner, substitute))
    db.info[sub.ACTOR_KEY] = substitute.id

    assert await _emit(db, owner.id) is None


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
    assert created[0].event_key == dl_alerts.event_key_for("order_mail_review", "e1", owner.id)
    assert created[0].message.startswith("W zastępstwie za ")
    assert isinstance(created[0], DlAlert)
