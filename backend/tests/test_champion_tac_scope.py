"""Opiekun rekrutacji (`jobs.tac_id`) widzi Championa SWOICH ofert — i tylko swoich.

Etap 4.4. Rozszerzenie dostępu, którego nie dało się zrobić samą podmianą
guarda: `delivery_lead_job_pairs` zwraca `None` — czyli „bez ograniczeń" — dla
każdego, kto nie jest Delivery Leadem. Bez własnego zawężenia każda rola spoza
Delivery dostałaby wgląd w Championa KAŻDEJ oferty, czyli odtworzyłaby wyciek
zamknięty w #1069 inną drogą.

Roli TAC nie ma od 0411 (02.10.2026) — jej konta są rekruterami, więc ścieżka
opiekuna wymaga dziś roli rekrutera i przypisania `jobs.tac_id`. Sam wpis
w `tac_id` nie poszerza zakresu Delivery Leada.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.recruitment_access import ensure_champion_job_visible
from app.models.user import UserRole


def _user(user_id: int, *roles: UserRole) -> SimpleNamespace:
    held = {r.value for r in roles}
    return SimpleNamespace(
        id=user_id,
        role=roles[0] if roles else None,
        roles=sorted(held),
        has_role=lambda r, _held=held: (
            (r.value if isinstance(r, UserRole) else str(r)) in _held
        ),
        has_any_role=lambda *rs, _held=held: any(
            (r.value if isinstance(r, UserRole) else str(r)) in _held for r in rs
        ),
    )


def _job(job_id: int = 1, client_id: int = 10, tac_id: int | None = None):
    return SimpleNamespace(id=job_id, client_id=client_id, tac_id=tac_id)


@pytest.mark.asyncio
async def test_assigned_guardian_reaches_their_job():
    await ensure_champion_job_visible(
        _job(tac_id=7), _user(7, UserRole.recruiter), db=None
    )


@pytest.mark.asyncio
async def test_recruiter_is_refused_someone_elses_job():
    """Sedno etapu — bez tego rozszerzenie zakresu byłoby wyciekiem."""

    with pytest.raises(HTTPException) as exc:
        await ensure_champion_job_visible(
            _job(tac_id=999), _user(7, UserRole.recruiter), db=None
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == "Job is outside the caller's Champion scope"


@pytest.mark.asyncio
async def test_unassigned_job_is_outside_every_guardian_scope():
    """`tac_id IS NULL` nie może przechodzić przez porównanie dwóch pustych pól."""

    with pytest.raises(HTTPException) as exc:
        await ensure_champion_job_visible(
            _job(tac_id=None), _user(7, UserRole.recruiter), db=None
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_and_head_of_recruitment_stay_unrestricted():
    """Persony nadzorcze — świadomie bez zakresu, tak jak dotąd."""

    await ensure_champion_job_visible(
        _job(tac_id=999), _user(1, UserRole.admin), db=None
    )
    await ensure_champion_job_visible(
        _job(tac_id=999), _user(2, UserRole.head_of_recruitment), db=None
    )


@pytest.mark.asyncio
async def test_delivery_lead_who_is_also_the_guardian_passes_on_the_second_path():
    """Ścieżki są alternatywą, nie łańcuchem.

    Odmowa po stronie delivery nie kończy sprawy, jeśli ten sam człowiek ma
    też rolę rekrutera (dawny TAC) i jest opiekunem (`tac_id`) tej oferty.
    """

    import app.api.recruitment_access as ra

    async def _deny_everything(_user, _db):
        return frozenset()  # pusty zakres delivery = deny-all

    original = ra.delivery_lead_job_pairs
    ra.delivery_lead_job_pairs = _deny_everything
    try:
        hybrid = _user(7, UserRole.delivery_lead, UserRole.recruiter)
        await ensure_champion_job_visible(_job(tac_id=7), hybrid, db=None)
        with pytest.raises(HTTPException) as exc:
            await ensure_champion_job_visible(_job(tac_id=999), hybrid, db=None)
        assert exc.value.status_code == 403
    finally:
        ra.delivery_lead_job_pairs = original


@pytest.mark.asyncio
async def test_guardian_entry_alone_does_not_widen_a_delivery_leads_scope():
    """Opiekunem bywa dziś Delivery Lead — wpis w `tac_id` to nie zakres."""

    import app.api.recruitment_access as ra

    async def _deny_everything(_user, _db):
        return frozenset()

    original = ra.delivery_lead_job_pairs
    ra.delivery_lead_job_pairs = _deny_everything
    try:
        with pytest.raises(HTTPException) as exc:
            await ensure_champion_job_visible(
                _job(tac_id=7), _user(7, UserRole.delivery_lead), db=None
            )
        assert exc.value.status_code == 403
    finally:
        ra.delivery_lead_job_pairs = original
