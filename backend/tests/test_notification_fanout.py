"""Powiadomienie bez adresata to śmieć w tabeli, nie „wysłany alert”.

Audyt 18.09.2026 zmierzył na produkcji dwa niezależne wycieki:

* ``dl_stage_stale_6h`` — 52 263 powiadomienia, z tego 30 993 (59,3%)
  o rekrutacjach ZAMKNIĘTYCH, przeczytane: 1;
* 6 647 z 63 336 powiadomień (10,5%) z 90 dni trafiło na konta NIEAKTYWNE
  (``stage_stuck_7d`` w 30 dni: 1 701 do 4 kont nieaktywnych vs 903 do 3
  aktywnych — 65% donikąd).

Testy DB-owe chodzą po zaseedowanych własnych wierszach i asertują po nich,
nigdy po globalnych licznikach: baza testowa jest współdzielona w przebiegu
i nie jest czyszczona.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import notification_access as na
from app.services import notification_triggers as nt


# --- kontrakt: nowy typ powiadomienia nie może zniknąć po cichu -------------


def test_every_trigger_notification_type_is_known_to_the_policy():
    """`emit` odsiewa odbiorców przez politykę powiadomień, a ta odmawia
    typowi, którego nie zna. Typ spoza mapy byłby więc od teraz kasowany przy
    ZAPISIE — dotąd zapisywał się i był niewidoczny dopiero przy ODCZYCIE
    (`notification_visibility_predicate` filtruje tak samo). Ten test pilnuje,
    żeby dokładając trigger nie zgubić typu w mapie sekcji.
    """
    src = open(nt.__file__, encoding="utf-8").read()
    used = {
        NotificationType[name]
        for name in set(re.findall(r"NotificationType\.(\w+)", src))
        if name in NotificationType.__members__
    }
    assert used, "parser typów przestał cokolwiek znajdować — popraw test"
    known = (
        set(na.NOTIFICATION_SECTION_BY_TYPE)
        | set(na.ALWAYS_VISIBLE_NOTIFICATION_TYPES)
        | set(na.ADMIN_ONLY_NOTIFICATION_TYPES)
    )
    missing = sorted(t.value for t in used - known)
    assert missing == [], (
        "typy używane przez triggery, których polityka powiadomień nie zna "
        f"(emit je odrzuci, a odczyt i tak by ich nie pokazał): {missing}"
    )


# --- DB ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    pytest.importorskip("asyncpg")
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            yield session
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable: {exc}")


async def _mk_user(db, *, is_active: bool) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(
        email=f"fanout-{tag}@example.test",
        password_hash="x",
        name=f"Fanout {tag}",
        role=UserRole.recruiter,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def _mk_job(db, *, status: JobStatus) -> Job:
    tag = uuid.uuid4().hex[:10]
    client = Client(name=f"Fanout klient {tag}")
    db.add(client)
    await db.flush()
    job = Job(title=f"Fanout rekrutacja {tag}", client_id=client.id, status=status)
    db.add(job)
    await db.flush()
    return job


async def _emit(db, user: User, *, entity_id: int) -> Notification | None:
    return await nt.emit(
        db,
        user_id=user.id,
        title="Zaległy kandydat",
        message="Sprawdź etap",
        ntype=NotificationType.dl_stage_stale_6h,
        link=f"/jobs/{entity_id}",
        related_entity_type="job",
        related_entity_id=entity_id,
    )


async def test_emit_skips_an_inactive_recipient(db):
    active = await _mk_user(db, is_active=True)
    inactive = await _mk_user(db, is_active=False)

    assert await _emit(db, active, entity_id=901) is not None
    assert await _emit(db, inactive, entity_id=902) is None

    rows = (
        (
            await db.execute(
                select(Notification.user_id).where(
                    Notification.user_id.in_([active.id, inactive.id])
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [active.id]

    await db.execute(
        delete(Notification).where(Notification.user_id.in_([active.id, inactive.id]))
    )
    await db.rollback()


async def test_emit_returns_none_for_a_recipient_that_no_longer_exists(db):
    # Konto usunięte między zebraniem adresatów a zapisem: dotąd leciał
    # IntegrityError na FK, łapany savepointem i raportowany jako duplikat.
    ghost = await _mk_user(db, is_active=True)
    ghost_id = ghost.id
    await db.delete(ghost)
    await db.flush()

    assert (
        await nt.emit(
            db,
            user_id=ghost_id,
            title="t",
            message="m",
            ntype=NotificationType.dl_stage_stale_6h,
            link="/jobs/903",
            related_entity_type="job",
            related_entity_id=903,
        )
        is None
    )
    await db.rollback()


async def test_open_jobs_lookup_sees_only_published_recruitments(db):
    published = await _mk_job(db, status=JobStatus.published)
    draft = await _mk_job(db, status=JobStatus.draft)
    closed = await _mk_job(db, status=JobStatus.closed)

    found = await nt._open_jobs_by_id(db, [published.id, draft.id, closed.id])

    assert set(found) == {published.id}
    await db.rollback()


def test_there_is_exactly_one_job_lookup_helper():
    """Rozwidlenie było przyczyną, nie jego jedna gałąź: poprawka z 17.09
    (#1593) objęła tylko `check_stage_stuck_7d`, bo obok stał drugi,
    nieprzefiltrowany helper. Dwa helpery = następna poprawka znów obejmie
    jeden z nich."""
    src = open(nt.__file__, encoding="utf-8").read()
    assert "async def _jobs_by_id(" not in src
    assert src.count("async def _open_jobs_by_id(") == 1


def _now() -> datetime:
    return datetime.now(timezone.utc)
