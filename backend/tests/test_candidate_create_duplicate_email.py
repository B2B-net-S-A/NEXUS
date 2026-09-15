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
        response = await app_client.post("/api/candidates", json=body, headers=app_auth_headers)
        assert response.status_code == 201, response.text
