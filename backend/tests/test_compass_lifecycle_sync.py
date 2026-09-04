"""Cykl życia COMPASS → NEXUS: co odbiera dostęp, a co go NIE odbiera.

Ta pętla jako jedyna w integracji ODBIERA ludziom dostęp, więc testy pilnują
przede wszystkim tego, czego NIE wolno jej zrobić.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import compass_lifecycle


async def _seed_user(email: str, *, active: bool = True) -> int:
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"LC {uuid.uuid4().hex[:6]}",
            password_hash=hash_password("T3st_lifecycle!x0"),
            role=UserRole.recruiter,
            is_active=active,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _is_active(user_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(await db.scalar(select(User.is_active).where(User.id == user_id)))


def _configure(monkeypatch, people):
    async def fake_fetch():
        return {"people": people}

    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_URL", "http://x")
    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_SECRET", "s")
    monkeypatch.setattr(compass_lifecycle, "fetch_roster", fake_fetch)


@pytest.mark.asyncio
async def test_exited_deactivates_the_account(monkeypatch):
    email = f"lc-exit-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)

    assert email in result.deactivated
    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_offboarding_does_not_deactivate(monkeypatch):
    """COMPASS sam przepuszcza `offboarding` wszędzie.

    Offboarding trwa PO ostatnim dniu pracy i człowiek musi się jeszcze
    logować, żeby przekazać obowiązki. Traktowanie go jak odejścia odcięłoby
    ludzi w środku tego procesu.
    """
    email = f"lc-off-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "offboarding"}])

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)

    assert result.deactivated == []
    assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_never_reactivates_an_account(monkeypatch):
    """Deaktywacja jest JEDNOKIERUNKOWA.

    Odebranie dostępu na podstawie cudzego feedu jest odwracalne kliknięciem
    admina. NADANIE dostępu automatem — na podstawie feedu, który może być
    nieaktualny albo niepełny — jest zupełnie inną klasą zdarzenia.
    """
    email = f"lc-re-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email, active=False)
    _configure(monkeypatch, [{"email": email, "employment_status": "active"}])

    async with AsyncSessionLocal() as db:
        await compass_lifecycle.sync_user_lifecycle(db)

    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_absence_from_the_feed_never_deactivates(monkeypatch):
    """Cisza to nie dowód odejścia.

    Brak w feedzie może znaczyć „inna domena", „konto techniczne" albo
    „COMPASS przysłał niepełną listę". Deaktywacja wymaga JAWNEGO `exited`.
    """
    email = f"lc-abs-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    other = f"lc-other-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    _configure(monkeypatch, [{"email": other, "employment_status": "exited"}])

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)

    assert await _is_active(uid) is True
    assert email in result.nexus_users_without_compass


@pytest.mark.asyncio
async def test_empty_roster_is_treated_as_a_failure_not_as_mass_departure(monkeypatch):
    """Pusta lista = awaria po drugiej stronie, nie „wszyscy odeszli".

    Bez tego bezpiecznika awaria eksportu w COMPASSIE wpisywałaby KAŻDE żywe
    konto na listę „bez odpowiednika" — czyli zamieniała sygnał w szum
    dokładnie wtedy, gdy jest najbardziej potrzebny.
    """
    email = f"lc-empty-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [])

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)

    assert result.error == "empty_roster"
    assert result.nexus_users_without_compass == []
    assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_compass_outage_changes_nothing(monkeypatch):
    email = f"lc-boom-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)

    async def boom():
        raise RuntimeError("compass down")

    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_ENABLED", True)
    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_URL", "http://x")
    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_SECRET", "s")
    monkeypatch.setattr(compass_lifecycle, "fetch_roster", boom)

    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)

    assert result.error and result.error.startswith("fetch_failed:")
    assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_disabled_is_a_no_op(monkeypatch):
    monkeypatch.setattr(compass_lifecycle.settings, "COMPASS_LIFECYCLE_ENABLED", False)
    async with AsyncSessionLocal() as db:
        result = await compass_lifecycle.sync_user_lifecycle(db)
    assert result.error == "disabled"
    assert result.deactivated == []
