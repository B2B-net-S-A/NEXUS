"""Okno „Czarna lista…” — trasy na żywej bazie (17.10.2026).

Baza testowa jest wspólna dla przebiegu i nie jest czyszczona, więc każdy test
zakłada własnych kandydatów, klientów i użytkowników. Osoby i firmy są zmyślone.
Część czysta: ``test_candidate_blacklist_rule.py``.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.user import User, UserRole


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Anna",
            lastname=f"Czarnolistna-{_hex()}",
            email=f"blacklist-{_hex()}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Czarna-Lista-Klient-{_hex()}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _headers_for(app_client: AsyncClient, role: UserRole) -> dict[str, str]:
    suffix = _hex()
    email = f"blacklist-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Czarna lista {role.value}",
                role=role,
                roles=[role.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def _actions(candidate_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Activity.action)
            .where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action.in_(
                    ("candidate_blacklisted", "candidate_blacklist_removed")
                ),
            )
            .order_by(Activity.id)
        )
        return list(rows.scalars().all())


async def test_recruiter_blacklists_with_a_reason_and_only_a_lead_removes(
    app_client: AsyncClient,
):
    candidate_id = await _seed_candidate()
    recruiter = await _headers_for(app_client, UserRole.recruiter)
    lead = await _headers_for(app_client, UserRole.delivery_lead)
    url = f"/api/candidates/{candidate_id}/blacklist"

    added = await app_client.post(
        url,
        json={"scope": "global", "reason": "  Zrezygnował dzień przed startem  "},
        headers=recruiter,
    )

    assert added.status_code == 200, added.text
    body = added.json()
    assert body["status"] == "blacklisted"
    assert body["blacklist"]["reason"] == "Zrezygnował dzień przed startem"
    assert body["blacklist"]["by_name"] == "Czarna lista recruiter"
    row = await _candidate(candidate_id)
    assert row.status == CandidateStatus.blacklisted
    assert row.blacklisted_at is not None and row.blacklisted_by_user_id is not None

    detail = await app_client.get(f"/api/candidates/{candidate_id}", headers=recruiter)
    assert detail.status_code == 200, detail.text
    assert detail.json()["blacklist"]["reason"] == "Zrezygnował dzień przed startem"

    again = await app_client.post(
        url, json={"scope": "global", "reason": "Drugi raz"}, headers=recruiter
    )
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "already_blacklisted"

    denied = await app_client.post(
        f"{url}/remove", json={"reason": "Pomyłka rekrutera"}, headers=recruiter
    )
    assert denied.status_code == 403, denied.text

    removed = await app_client.post(
        f"{url}/remove", json={"reason": "Wyjaśnione z klientem"}, headers=lead
    )
    assert removed.status_code == 200, removed.text
    row = await _candidate(candidate_id)
    assert row.status == CandidateStatus.active
    assert (row.blacklisted_at, row.blacklist_reason) == (None, None)
    assert await _actions(candidate_id) == [
        "candidate_blacklisted",
        "candidate_blacklist_removed",
    ]
    detail = await app_client.get(f"/api/candidates/{candidate_id}", headers=lead)
    assert detail.json()["blacklist"] is None

    not_listed = await app_client.post(
        f"{url}/remove", json={"reason": "Jeszcze raz"}, headers=lead
    )
    assert not_listed.status_code == 409, not_listed.text


async def test_reason_is_required(app_client: AsyncClient):
    candidate_id = await _seed_candidate()
    recruiter = await _headers_for(app_client, UserRole.recruiter)

    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/blacklist",
        json={"scope": "global", "reason": "  ab "},
        headers=recruiter,
    )

    assert resp.status_code == 422, resp.text
    assert (await _candidate(candidate_id)).status == CandidateStatus.active


async def test_recruiter_adds_a_client_blacklist_as_a_conflict(app_client: AsyncClient):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    recruiter = await _headers_for(app_client, UserRole.recruiter)

    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/blacklist",
        json={
            "scope": "client",
            "client_id": client_id,
            "reason": "Klient prosił po rozmowie z HM",
        },
        headers=recruiter,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["conflict"]["type"] == "blacklist"
    async with AsyncSessionLocal() as db:
        conflict = await db.scalar(
            select(CandidateConflict).where(
                CandidateConflict.candidate_id == candidate_id
            )
        )
    assert conflict.type == ConflictType.blacklist
    assert conflict.reason == "Klient prosił po rozmowie z HM"
    # Czarna lista u klienta to ostrzeżenie — status osoby się nie zmienia.
    assert (await _candidate(candidate_id)).status == CandidateStatus.active

    missing_client = await app_client.post(
        f"/api/candidates/{candidate_id}/blacklist",
        json={"scope": "client", "reason": "Bez klienta"},
        headers=recruiter,
    )
    assert missing_client.status_code == 422, missing_client.text


async def test_edit_form_cannot_change_the_blacklist_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()

    resp = await app_client.patch(
        f"/api/candidates/{candidate_id}",
        json={"status": "blacklisted"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "candidate_blacklist_dedicated_endpoint"
    # Status bez czarnej listy nadal da się zmienić polem.
    passive = await app_client.patch(
        f"/api/candidates/{candidate_id}",
        json={"status": "passive"},
        headers=app_auth_headers,
    )
    assert passive.status_code == 200, passive.text


async def test_manual_employment_conflict_is_retired(
    app_client: AsyncClient, app_auth_headers: dict
):
    """17.10.2026: „Pracuje u nas” tylko z umowy — ręcznego wpisu nie ma."""
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()

    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={"client_id": client_id, "type": "current_employment"},
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "conflict_type_retired"
