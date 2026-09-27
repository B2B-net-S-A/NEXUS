"""`POST /api/candidates` z zajętym adresem e-mail zwraca 409, nie 500.

Unikalny indeks `candidates.email` wywracał flush w IntegrityError, a
`UnhandledErrorMiddleware` zamieniał to w 500 „nieoczekiwany błąd serwera".
Scenariusz E2E „duplikat e-maila" przechodził wyłącznie dlatego, że przyjmował
każdy status poniżej 500 (audyt QA 14.09.2026, B4 planu poprawy).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


def _payload(email: str) -> dict[str, str]:
    return {"name": "Duplikat", "lastname": "Testowy", "email": email}


async def test_duplicate_email_returns_409_and_keeps_single_candidate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    email = f"dup-{uuid.uuid4().hex[:10]}@example.com"

    first = await app_client.post(
        "/api/candidates", json=_payload(email), headers=app_auth_headers
    )
    assert first.status_code == 201, first.text

    second = await app_client.post(
        "/api/candidates", json=_payload(email), headers=app_auth_headers
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "Kandydat z tym adresem e-mail już istnieje."

    # Odmowa nie może zostawić sesji w zepsutej transakcji — kolejny zapis
    # z innym adresem w tym samym kliencie przechodzi.
    third = await app_client.post(
        "/api/candidates",
        json=_payload(f"dup-{uuid.uuid4().hex[:10]}@example.com"),
        headers=app_auth_headers,
    )
    assert third.status_code == 201, third.text


async def test_candidates_without_email_are_not_duplicates(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    body = {"name": "BezMaila", "lastname": uuid.uuid4().hex[:8]}
    for _ in range(2):
        response = await app_client.post(
            "/api/candidates", json=body, headers=app_auth_headers
        )
        assert response.status_code == 201, response.text


async def test_patch_to_taken_email_returns_409_not_500(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Runda 9 (R9-N8-8): PATCH na cudzy adres dawał IntegrityError → 500."""
    taken = f"dup-{uuid.uuid4().hex[:10]}@example.com"
    first = await app_client.post(
        "/api/candidates", json=_payload(taken), headers=app_auth_headers
    )
    assert first.status_code == 201, first.text
    other = await app_client.post(
        "/api/candidates",
        json=_payload(f"dup-{uuid.uuid4().hex[:10]}@example.com"),
        headers=app_auth_headers,
    )
    assert other.status_code == 201, other.text

    resp = await app_client.patch(
        f"/api/candidates/{other.json()['id']}",
        json={"email": taken},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Kandydat z tym adresem e-mail już istnieje."

    # Własny, niezmieniony adres przechodzi.
    same = await app_client.patch(
        f"/api/candidates/{first.json()['id']}",
        json={"email": taken, "city": "Gdańsk"},
        headers=app_auth_headers,
    )
    assert same.status_code == 200, same.text


async def test_too_long_fields_are_422_not_500(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Runda 9 (R9-N8-8): wartość dłuższa niż kolumna = 422, nie błąd bazy."""
    body = {"name": "Dlugi", "lastname": "Test", "phone": "1" * 31}
    created = await app_client.post(
        "/api/candidates", json=body, headers=app_auth_headers
    )
    assert created.status_code == 422, created.text

    ok = await app_client.post(
        "/api/candidates",
        json={"name": "Dlugi", "lastname": uuid.uuid4().hex[:8]},
        headers=app_auth_headers,
    )
    assert ok.status_code == 201, ok.text
    for field, size in (("nip", 33), ("business_form", 65), ("source", 101)):
        resp = await app_client.patch(
            f"/api/candidates/{ok.json()['id']}",
            json={field: "x" * size},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, (field, resp.text)


async def test_patch_office_days_change_clears_consent_for_more_days(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Runda 9 (R9-N8-5): zgoda na więcej dni dotyczyła poprzedniego limitu."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    created = await app_client.post(
        "/api/candidates",
        json={
            "name": "Biuro",
            "lastname": uuid.uuid4().hex[:8],
            "max_onsite_days_per_week": 2,
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    cand_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        row = await db.get(Candidate, cand_id)
        row.accepts_more_office_days = True
        await db.commit()

    same = await app_client.patch(
        f"/api/candidates/{cand_id}",
        json={"max_onsite_days_per_week": 2},
        headers=app_auth_headers,
    )
    assert same.status_code == 200, same.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Candidate, cand_id)).accepts_more_office_days is True

    changed = await app_client.patch(
        f"/api/candidates/{cand_id}",
        json={"max_onsite_days_per_week": 4},
        headers=app_auth_headers,
    )
    assert changed.status_code == 200, changed.text
    async with AsyncSessionLocal() as db:
        row = await db.get(Candidate, cand_id)
        assert row.max_onsite_days_per_week == 4
        assert row.accepts_more_office_days is None
