"""Rejestr konfliktów kandydat↔klient — API na żywej bazie (17.09.2026).

Baza testowa jest WSPÓLNA dla przebiegu i nie jest czyszczona, więc każdy test
zakłada własnych kandydatów, klientów i użytkowników, a asercje rejestru
zawęża do własnych identyfikatorów. Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole

# ── Seedy ───────────────────────────────────────────────────────────────────


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_candidate(lastname: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Anna",
            lastname=lastname or f"Konfliktowa-{_hex()}",
            email=f"conflict-{_hex()}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_client(name: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=name or f"Konflikt-Klient-{_hex()}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _seed_conflict(
    candidate_id: int,
    client_id: int,
    *,
    type: ConflictType = ConflictType.blacklist,
    expires_at: datetime | None = None,
    active: bool = True,
) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateConflict(
            candidate_id=candidate_id,
            client_id=client_id,
            type=type,
            expires_at=expires_at,
            active=active,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _headers_for(
    app_client: AsyncClient,
    role: UserRole,
    *,
    assigned_client_id: int | None = None,
) -> dict[str, str]:
    suffix = _hex()
    email = f"conflicts-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Konflikty {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id,
                    client_id=assigned_client_id,
                )
            )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _future(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def _registry_ids(app_client, headers, **params) -> tuple[set[int], dict]:
    resp = await app_client.get("/api/conflicts", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {row["id"] for row in body["items"]}, body


# ── Tworzenie ───────────────────────────────────────────────────────────────


async def test_create_nda_with_expiry_returns_enriched_row_and_audits(
    app_client: AsyncClient, app_auth_headers: dict
):
    lastname = f"Poufna-{_hex()}"
    candidate_id = await _seed_candidate(lastname)
    client_id = await _seed_client()

    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={
            "client_id": client_id,
            "type": "nda",
            "reason": "  Cooling-off po projekcie  ",
            "expires_at": _future(40),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["type"] == "nda"
    assert row["type_label"] == "NDA / cooling-off"
    assert row["state"] == "active"
    assert row["active"] is True
    assert row["reason"] == "Cooling-off po projekcie"
    assert row["client_name"].startswith("Konflikt-Klient-")
    assert row["created_by_name"] == "Pytest Admin"
    assert row["deactivated_at"] is None and row["deactivation_reason"] is None
    assert row["expires_at"].endswith("+00:00")

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == "conflict_added",
            )
        )
    assert activity is not None
    # Tylko identyfikatory — wolny tekst powodu zostaje na wierszu konfliktu.
    assert set(activity.details) == {
        "conflict_id",
        "client_id",
        "type",
        "expires_at",
    }
    assert activity.details["conflict_id"] == row["id"]
    assert lastname not in str(activity.details)


async def test_naive_expiry_is_stored_as_utc(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    naive = (datetime.now(timezone.utc) + timedelta(days=5)).replace(
        tzinfo=None, microsecond=0
    )
    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={
            "client_id": client_id,
            "type": "competitor",
            "expires_at": naive.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    stored = datetime.fromisoformat(resp.json()["expires_at"])
    assert stored == naive.replace(tzinfo=timezone.utc)


async def test_nda_without_expiry_is_rejected_in_polish(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={"client_id": client_id, "type": "nda"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "NDA wymaga daty wygaśnięcia."


async def test_expiry_in_the_past_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={
            "client_id": client_id,
            "type": "blacklist",
            "expires_at": _future(-1),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Data wygaśnięcia musi być w przyszłości."


async def test_missing_client_is_404_not_a_raw_integrity_error(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    resp = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={"client_id": 2_000_000_000, "type": "blacklist"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_two_types_coexist_but_the_same_type_is_409_without_sql(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    url = f"/api/candidates/{candidate_id}/conflicts"

    first = await app_client.post(
        url,
        json={"client_id": client_id, "type": "nda", "expires_at": _future()},
        headers=app_auth_headers,
    )
    second = await app_client.post(
        url,
        json={"client_id": client_id, "type": "blacklist"},
        headers=app_auth_headers,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    duplicate = await app_client.post(
        url,
        json={"client_id": client_id, "type": "blacklist"},
        headers=app_auth_headers,
    )
    assert duplicate.status_code == 409
    detail = duplicate.json()["detail"]
    assert detail == "Ten kandydat ma już aktywny konflikt tego typu u tego klienta"
    for leak in ("INSERT", "uq_", "candidate_conflicts", "IntegrityError"):
        assert leak not in duplicate.text

    listed = await app_client.get(url, headers=app_auth_headers)
    assert listed.status_code == 200
    assert {row["type"] for row in listed.json()} == {"nda", "blacklist"}


# ── Dezaktywacja ────────────────────────────────────────────────────────────


async def test_deactivate_requires_reason_records_audit_and_is_one_shot(
    app_client: AsyncClient, app_auth_headers: dict
):
    lastname = f"Zdjeta-{_hex()}"
    candidate_id = await _seed_candidate(lastname)
    client_id = await _seed_client()
    url = f"/api/candidates/{candidate_id}/conflicts"
    created = await app_client.post(
        url,
        json={"client_id": client_id, "type": "blacklist"},
        headers=app_auth_headers,
    )
    conflict_id = created.json()["id"]
    deactivate = f"/api/conflicts/{conflict_id}/deactivate"

    no_body = await app_client.patch(deactivate, headers=app_auth_headers)
    assert no_body.status_code == 422
    too_short = await app_client.patch(
        deactivate, json={"reason": "  ok  "}, headers=app_auth_headers
    )
    assert too_short.status_code == 422

    ok = await app_client.patch(
        deactivate,
        json={"reason": "Klient zdjął zastrzeżenie"},
        headers=app_auth_headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["active"] is False
    assert body["state"] == "inactive"
    assert body["deactivation_reason"] == "Klient zdjął zastrzeżenie"
    assert body["deactivated_at"] is not None
    assert body["deactivated_by_name"] == "Pytest Admin"

    again = await app_client.patch(
        deactivate, json={"reason": "Drugi raz"}, headers=app_auth_headers
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "Ten konflikt jest już nieaktywny."

    missing = await app_client.patch(
        "/api/conflicts/2000000000/deactivate",
        json={"reason": "Nie istnieje"},
        headers=app_auth_headers,
    )
    assert missing.status_code == 404

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == "conflict_deactivated",
            )
        )
    assert activity is not None
    assert activity.details == {
        "conflict_id": conflict_id,
        "client_id": client_id,
        "type": "blacklist",
    }
    assert lastname not in str(activity.details)

    # Nieaktywny wiersz nie zajmuje już klucza unikalności.
    recreated = await app_client.post(
        url,
        json={"client_id": client_id, "type": "blacklist"},
        headers=app_auth_headers,
    )
    assert recreated.status_code == 201, recreated.text

    history = await app_client.get(
        url, params={"active_only": "false"}, headers=app_auth_headers
    )
    assert sorted(row["state"] for row in history.json()) == ["active", "inactive"]


async def test_expired_conflict_is_history_not_active(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    expired_id = await _seed_conflict(
        candidate_id,
        client_id,
        type=ConflictType.nda,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    url = f"/api/candidates/{candidate_id}/conflicts"

    active = await app_client.get(url, headers=app_auth_headers)
    assert active.json() == []

    history = await app_client.get(
        url, params={"active_only": "false"}, headers=app_auth_headers
    )
    rows = history.json()
    assert [(row["id"], row["state"], row["active"]) for row in rows] == [
        (expired_id, "expired", True)
    ]


async def test_new_conflict_after_expiry_supersedes_the_expired_row(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Wygasły wpis nadal zajmuje indeks unikalności, a widżet go nie pokazuje —
    # odnowienie NDA nie może kończyć się 409.
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    expired_id = await _seed_conflict(
        candidate_id,
        client_id,
        type=ConflictType.nda,
        expires_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    created = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={"client_id": client_id, "type": "nda", "expires_at": _future(60)},
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["state"] == "active"

    history = await app_client.get(
        f"/api/candidates/{candidate_id}/conflicts",
        params={"active_only": "false"},
        headers=app_auth_headers,
    )
    old = next(row for row in history.json() if row["id"] == expired_id)
    assert old["state"] == "inactive"
    assert old["deactivation_reason"] == "Zastąpiony nowym wpisem po wygaśnięciu"

    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
                Activity.action == "conflict_deactivated",
            )
        )
    assert activity is not None
    assert activity.details == {
        "conflict_id": expired_id,
        "client_id": client_id,
        "type": "nda",
        "superseded": True,
    }


async def test_expiring_filter_rejects_a_non_active_state(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/conflicts",
        params={"state": "inactive", "expiring_within_days": 30},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


# ── Rejestr ─────────────────────────────────────────────────────────────────


async def test_registry_filters_by_client_type_state_and_expiry(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _seed_client()
    other_client = await _seed_client()
    c1, c2, c3, c4 = [await _seed_candidate() for _ in range(4)]
    now = datetime.now(timezone.utc)

    soon = await _seed_conflict(
        c1, client_id, type=ConflictType.nda, expires_at=now + timedelta(days=10)
    )
    later = await _seed_conflict(
        c2, client_id, type=ConflictType.competitor, expires_at=now + timedelta(days=60)
    )
    forever = await _seed_conflict(c3, client_id, type=ConflictType.blacklist)
    expired = await _seed_conflict(
        c4, client_id, type=ConflictType.nda, expires_at=now - timedelta(days=2)
    )
    inactive = await _seed_conflict(
        c1, client_id, type=ConflictType.blacklist, active=False
    )
    elsewhere = await _seed_conflict(c1, other_client, type=ConflictType.blacklist)

    ids, body = await _registry_ids(app_client, app_auth_headers, client_id=client_id)
    assert ids == {soon, later, forever}
    assert body["total"] == 3
    assert body["limit"] == 50 and body["offset"] == 0
    assert body["type_labels"]["nda"] == "NDA / cooling-off"
    row = next(item for item in body["items"] if item["id"] == soon)
    assert row["candidate_name"].startswith("Anna Konfliktowa-")
    assert row["client_name"].startswith("Konflikt-Klient-")
    assert elsewhere not in ids

    ids, _ = await _registry_ids(
        app_client, app_auth_headers, client_id=client_id, type="nda"
    )
    assert ids == {soon}

    ids, _ = await _registry_ids(
        app_client, app_auth_headers, client_id=client_id, active="false"
    )
    assert ids == {expired, inactive}

    ids, _ = await _registry_ids(
        app_client, app_auth_headers, client_id=client_id, state="expired"
    )
    assert ids == {expired}
    ids, _ = await _registry_ids(
        app_client, app_auth_headers, client_id=client_id, state="all"
    )
    assert ids == {soon, later, forever, expired, inactive}
    bad = await app_client.get(
        "/api/conflicts", params={"state": "zombie"}, headers=app_auth_headers
    )
    assert bad.status_code == 422

    ids, body = await _registry_ids(
        app_client, app_auth_headers, client_id=client_id, expiring_within_days=30
    )
    assert ids == {soon}
    assert body["items"][0]["state"] == "active"

    ids, _ = await _registry_ids(
        app_client, app_auth_headers, candidate_id=c1, state="all"
    )
    assert ids == {soon, inactive, elsewhere}


async def test_registry_pagination_is_stable(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _seed_client()
    created = [
        await _seed_conflict(await _seed_candidate(), client_id) for _ in range(3)
    ]
    pages = []
    for offset in range(3):
        ids, body = await _registry_ids(
            app_client,
            app_auth_headers,
            client_id=client_id,
            limit=1,
            offset=offset,
        )
        assert body["total"] == 3
        assert len(ids) == 1
        pages.extend(ids)
    assert sorted(pages) == sorted(created)
    # Najnowsze pierwsze.
    assert pages[0] == max(created)


async def test_registry_search_folds_polish_characters(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _hex()
    candidate_id = await _seed_candidate(f"Żółkiewska{token}")
    client_id = await _seed_client(f"Łódzka Spółka {token}")
    conflict_id = await _seed_conflict(candidate_id, client_id)

    for query in (
        f"zolkiewska{token}",
        f"anna żółkiewska{token}",
        f"lodzka spolka {token}",
    ):
        ids, _ = await _registry_ids(app_client, app_auth_headers, q=query)
        assert ids == {conflict_id}, query

    ids, _ = await _registry_ids(app_client, app_auth_headers, q=f"nikt-{token}")
    assert ids == set()


# ── Uprawnienia ─────────────────────────────────────────────────────────────


async def test_delivery_lead_reads_conflicts_within_scope(app_client: AsyncClient):
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    conflict_id = await _seed_conflict(candidate_id, client_id)
    headers = await _headers_for(
        app_client, UserRole.delivery_lead, assigned_client_id=client_id
    )

    # Do 17.09.2026 za bramką Finance: DL (finance=none) dostawał 403.
    listed = await app_client.get(
        f"/api/candidates/{candidate_id}/conflicts", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [conflict_id]

    ids, _ = await _registry_ids(app_client, headers, client_id=client_id)
    assert ids == {conflict_id}

    outside = await app_client.get(
        "/api/conflicts", params={"client_id": 2_000_000_000}, headers=headers
    )
    assert outside.status_code == 403

    # Od 25.09.2026 rejestr klienta bez przypisania DL = 403 (zakres Delivery).
    stranger = await _headers_for(app_client, UserRole.delivery_lead)
    denied = await app_client.get(
        "/api/conflicts", params={"client_id": client_id}, headers=stranger
    )
    assert denied.status_code == 403, denied.text


async def test_viewer_role_is_forbidden(app_client: AsyncClient):
    headers = await _headers_for(app_client, UserRole.user)
    candidate_id = await _seed_candidate()
    for path in (f"/api/candidates/{candidate_id}/conflicts", "/api/conflicts"):
        resp = await app_client.get(path, headers=headers)
        assert resp.status_code == 403, (path, resp.text)


async def test_recruiter_reads_but_cannot_write(app_client: AsyncClient):
    headers = await _headers_for(app_client, UserRole.recruiter)
    candidate_id = await _seed_candidate()
    client_id = await _seed_client()
    conflict_id = await _seed_conflict(candidate_id, client_id)

    ids, _ = await _registry_ids(app_client, headers, client_id=client_id)
    assert ids == {conflict_id}
    created = await app_client.post(
        f"/api/candidates/{candidate_id}/conflicts",
        json={"client_id": client_id, "type": "competitor"},
        headers=headers,
    )
    assert created.status_code == 403
    deactivated = await app_client.patch(
        f"/api/conflicts/{conflict_id}/deactivate",
        json={"reason": "Nie moja decyzja"},
        headers=headers,
    )
    assert deactivated.status_code == 403
