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


# ── Tylko przy ZMIANIE statusu (09.2026) ─────────────────────────────────────


async def _run_sync():
    async with AsyncSessionLocal() as db:
        return await compass_lifecycle.sync_user_lifecycle(db)


async def _set_active(user_id: int, active: bool) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_active = active
        await db.commit()


@pytest.mark.asyncio
async def test_admin_reenable_survives_every_following_run(monkeypatch):
    """Konto włączone przez admina mimo `exited` zostaje włączone.

    Do 09.2026 pętla wyłączała je z powrotem przy każdym starcie kontenera
    i co 6 h, dopóki COMPASS pokazywał `exited` — decyzja admina żyła do
    najbliższego deployu.
    """
    email = f"lc-reen-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    first = await _run_sync()
    assert email in first.deactivated
    assert await _is_active(uid) is False

    await _set_active(uid, True)  # świadoma decyzja admina

    for _ in range(2):
        again = await _run_sync()
        assert email not in again.deactivated
        assert email in again.skipped_reenabled
        assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_first_run_after_deploy_respects_an_earlier_admin_reenable(monkeypatch):
    """Brak zapisanej obserwacji ≠ nowe odejście, gdy admin już zdecydował.

    Stara pętla nie zapisywała stanu, więc konto włączone ręcznie po jej
    deaktywacji wyglądałoby przy pierwszym przebiegu nowego kodu jak świeże
    `exited`. Ślad `active_changed → True` z panelu admina rozstrzyga.
    """
    from app.models.activity import Activity

    email = f"lc-boot-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    async with AsyncSessionLocal() as db:
        db.add(
            Activity(
                entity_type="user",
                entity_id=uid,
                action="active_changed",
                details={"from": False, "to": True, "target_email": email},
            )
        )
        await db.commit()
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    result = await _run_sync()

    assert result.deactivated == []
    assert email in result.skipped_reenabled
    assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_a_new_exit_after_a_return_deactivates_again(monkeypatch):
    """Zmiana `active → exited` to NOWE odejście — i ono nadal odbiera dostęp."""
    email = f"lc-cycle-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)

    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])
    await _run_sync()
    await _set_active(uid, True)

    _configure(monkeypatch, [{"email": email, "employment_status": "active"}])
    await _run_sync()
    assert await _is_active(uid) is True

    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])
    result = await _run_sync()
    assert email in result.deactivated
    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_deactivation_leaves_an_audit_entry(monkeypatch):
    """Konto wyłączone automatem musi mieć ślad KTO i DLACZEGO."""
    from app.models.activity import Activity

    email = f"lc-audit-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    await _run_sync()

    async with AsyncSessionLocal() as db:
        entries = (
            (
                await db.execute(
                    select(Activity).where(
                        Activity.entity_type == "user",
                        Activity.entity_id == uid,
                        Activity.action == compass_lifecycle.DEACTIVATION_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(entries) == 1
    assert entries[0].user_id is None
    assert entries[0].details["compass_status"] == "exited"
    assert entries[0].details["target_email"] == email
