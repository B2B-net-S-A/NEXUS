"""Cykl życia COMPASS → NEXUS: co odbiera dostęp, a co go NIE odbiera.

Ta pętla jako jedyna w integracji ODBIERA ludziom dostęp, więc testy pilnują
przede wszystkim tego, czego NIE wolno jej zrobić.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.app_setting import AppSetting
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
async def test_deactivation_log_carries_ids_not_emails(monkeypatch, caplog):
    """Logi przebiegu niosą liczby i ID — adres e-mail zostaje w Activity."""
    email = f"lc-log-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    with caplog.at_level(logging.INFO, logger=compass_lifecycle.__name__):
        async with AsyncSessionLocal() as db:
            result = await compass_lifecycle.sync_user_lifecycle(db)

    assert uid in result.deactivated_user_ids
    assert email not in caplog.text
    assert str(uid) in caplog.text


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


# ── Epizod odejścia i jawne włączenie przez admina (09.2026) ────────────────
#
# Reguła: aktywne konto osoby `exited` jest deaktywowane, CHYBA ŻE admin
# jawnie je włączył (`PUT /api/admin/users/{id}` → `active_changed`, `to=True`)
# PO początku bieżącego epizodu odejścia. Flip bez tego śladu (SSO, resync AAD)
# nie liczy się, a włączenie sprzed odejścia nie jest decyzją o tym odejściu.


async def _run_sync():
    async with AsyncSessionLocal() as db:
        return await compass_lifecycle.sync_user_lifecycle(db)


async def _set_active(user_id: int, active: bool) -> None:
    """Flip `is_active` BEZ śladu admina — tak jak robi to callback SSO."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_active = active
        await db.commit()


async def _admin_reenable(app_client, headers, user_id: int) -> None:
    """Jawne włączenie przez PRAWDZIWY endpoint admina (on zapisuje `Activity`)."""
    resp = await app_client.put(
        f"/api/admin/users/{user_id}", json={"is_active": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def _add_activity(user_id: int, action: str, details: dict, *, at=None) -> None:
    async with AsyncSessionLocal() as db:
        row = Activity(
            entity_type="user", entity_id=user_id, action=action, details=details
        )
        if at is not None:
            row.created_at = at
        db.add(row)
        await db.commit()


async def _deactivation_count(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return len(
            (
                await db.execute(
                    select(Activity.id).where(
                        Activity.entity_type == "user",
                        Activity.entity_id == user_id,
                        Activity.action == compass_lifecycle.DEACTIVATION_ACTION,
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_an_old_admin_reenable_does_not_protect_against_a_new_exit(monkeypatch):
    """(a) Włączenie sprzed ponad roku nie jest decyzją o dzisiejszym odejściu.

    Do 09.2026 pierwszy przebieg szanował OSTATNIE `active_changed → True`
    niezależnie od tego, kiedy padło — więc konto włączone rok wcześniej,
    z zupełnie innego powodu, zachowywało dostęp mimo `exited`.
    """
    email = f"lc-old-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    await _add_activity(
        uid,
        "active_changed",
        {"from": False, "to": True, "target_email": email},
        # Czas względny, nie stały rok — baza testowa jest wspólna dla przebiegu.
        at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    result = await _run_sync()

    assert email in result.deactivated
    assert result.skipped_reenabled == []
    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_a_reactivation_without_an_admin_trace_is_undone_by_the_next_run(
    monkeypatch,
):
    """(b) Flip SSO po deaktywacji nie przywraca dostępu osobie `exited`.

    Callback SSO ustawia `is_active=True` każdemu z grupą AAD, bez `Activity`
    `active_changed`. Do 09.2026 pętla brała KAŻDE aktywne konto przy
    `exited` z poprzedniego przebiegu za świadomą decyzję admina i zostawiała
    je włączone na zawsze.
    """
    email = f"lc-sso-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    first = await _run_sync()
    assert email in first.deactivated

    await _set_active(uid, True)  # logowanie SSO — bez śladu admina

    second = await _run_sync()
    assert email in second.deactivated
    assert email not in second.skipped_reenabled
    assert await _is_active(uid) is False
    assert await _deactivation_count(uid) == 2


@pytest.mark.asyncio
async def test_admin_reenable_survives_every_following_run(
    monkeypatch, caplog, app_client, app_auth_headers
):
    """(c) Włączenie przez admina PO deaktywacji zostaje — w każdym przebiegu.

    Log przebiegu niesie liczbę i identyfikatory, nie adres: to konto wraca
    w każdym przebiegu (co 6 h i przy każdym starcie kontenera).
    """
    email = f"lc-reen-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    first = await _run_sync()
    assert email in first.deactivated
    assert await _is_active(uid) is False

    await _admin_reenable(app_client, app_auth_headers, uid)

    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=compass_lifecycle.__name__):
            again = await _run_sync()
        assert email not in again.deactivated
        assert email in again.skipped_reenabled
        assert uid in again.skipped_reenabled_user_ids
        assert await _is_active(uid) is True
        kept_logs = [
            r.getMessage() for r in caplog.records if "kept_reenabled" in r.getMessage()
        ]
        assert kept_logs, "przebieg ma raportować zachowane konta"
        assert all(email not in line for line in kept_logs), kept_logs
        assert any(str(uid) in line for line in kept_logs), kept_logs


@pytest.mark.asyncio
async def test_a_new_exit_after_a_return_ignores_the_earlier_admin_reenable(
    monkeypatch, app_client, app_auth_headers
):
    """(d) `exited → active → exited` to NOWE odejście — dawne włączenie nie chroni."""
    email = f"lc-cycle-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)

    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])
    await _run_sync()
    await _admin_reenable(app_client, app_auth_headers, uid)
    kept = await _run_sync()
    assert email in kept.skipped_reenabled

    _configure(monkeypatch, [{"email": email, "employment_status": "active"}])
    await _run_sync()
    assert await _is_active(uid) is True

    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])
    result = await _run_sync()
    assert email in result.deactivated
    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_first_run_honours_a_reenable_after_a_recorded_lifecycle_deactivation(
    monkeypatch, app_client, app_auth_headers
):
    """(e) Brak zapisanego stanu + ślad deaktywacji tą pętlą + późniejsze włączenie.

    Stan pętli potrafi zniknąć (pierwsze wdrożenie, wyczyszczony wiersz).
    Wtedy początkiem epizodu jest ostatnia deaktywacja pętli — włączenie przez
    admina PO niej zostaje uszanowane także w kolejnych przebiegach.
    """
    email = f"lc-legacy-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email, active=False)
    await _add_activity(
        uid,
        compass_lifecycle.DEACTIVATION_ACTION,
        {"target_email": email, "compass_status": "exited"},
        at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    await _admin_reenable(app_client, app_auth_headers, uid)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])

    for _ in range(2):
        result = await _run_sync()
        assert result.deactivated == []
        assert email in result.skipped_reenabled
        assert await _is_active(uid) is True


@pytest.mark.asyncio
async def test_a_later_admin_deactivation_revokes_the_reenable(
    monkeypatch, app_client, app_auth_headers
):
    """Włączenie odwołane późniejszą deaktywacją admina nie jest już decyzją.

    Admin włącza, potem wyłącza (`DELETE`), a logowanie SSO włącza konto
    ponownie — bez tego warunku stare `active_changed → True` dalej chroniłoby
    osobę `exited`.
    """
    email = f"lc-revoke-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    uid = await _seed_user(email)
    _configure(monkeypatch, [{"email": email, "employment_status": "exited"}])
    await _run_sync()
    await _admin_reenable(app_client, app_auth_headers, uid)
    assert email in (await _run_sync()).skipped_reenabled

    resp = await app_client.delete(f"/api/admin/users/{uid}", headers=app_auth_headers)
    assert resp.status_code == 204, resp.text
    await _set_active(uid, True)  # logowanie SSO

    result = await _run_sync()
    assert email in result.deactivated
    assert await _is_active(uid) is False


@pytest.mark.asyncio
async def test_deactivation_leaves_an_audit_entry(monkeypatch):
    """Konto wyłączone automatem musi mieć ślad KTO i DLACZEGO."""
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
    assert entries[0].details["exit_episode_started_at"]


@pytest.mark.asyncio
async def test_state_write_is_an_upsert_under_overlapping_runs() -> None:
    """Dwa kontenery w trakcie deployu zapisują stan naraz — bez IntegrityError.

    Obie transakcje startują bez wiersza stanu. Zwykły INSERT drugiej padał
    na kluczu głównym po commicie pierwszej; `ON CONFLICT DO UPDATE` czeka
    na pierwszą i nadpisuje jej zapis.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == compass_lifecycle._STATE_KEY)
        )
        await db.commit()

    async def _second_container() -> None:
        async with AsyncSessionLocal() as other:
            await compass_lifecycle._save_state(other, {"-2": "active"}, {})
            await other.commit()

    async with AsyncSessionLocal() as first:
        await compass_lifecycle._save_state(first, {"-1": "exited"}, {})
        second = asyncio.create_task(_second_container())
        await asyncio.sleep(0.3)  # druga transakcja czeka na unikalnym kluczu
        await first.commit()
    await asyncio.wait_for(second, timeout=10)

    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, compass_lifecycle._STATE_KEY)
        assert row is not None
        assert row.value["last_seen"] == {"-2": "active"}
        assert row.value["version"] == 2
