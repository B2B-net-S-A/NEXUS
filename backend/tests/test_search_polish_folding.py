"""Wyszukiwarka globalna bez wrażliwości na polskie znaki (Jarvis, 07.11.2026).

`GET /api/search/global` (narzędzie Jarvisa `global_search`) porównywał frazę
z ``name``/``lastname`` zwykłym ``ILIKE``: „Jerzy Leśniawski” nie znajdował
osoby zapisanej jako „Lesniawski”, a Jarvis odpowiadał rekruterce „nie ma
takiej osoby” (produkcja, 04.11.2026). Lista rekrutacji i paleta ⌘K składały
polskie znaki od dawna. Osoby są zmyślone; baza testowa nie jest czyszczona,
więc nazwiska niosą losowy przyrostek.
"""

from __future__ import annotations

import uuid

import pytest

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus


async def _seed(first: str, last: str) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first,
            lastname=last,
            email=f"fold-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_last", "typed_last"),
    [
        ("Lesniawski", "Leśniawski"),  # baza bez znaków, pytanie ze znakami
        ("Leśniawski", "Lesniawski"),  # odwrotnie
        ("ŻÓŁĆ", "zolc"),  # wielkie litery po obu stronach
    ],
)
@pytest.mark.parametrize("path", ["/api/search/global", "/api/search/"])
async def test_search_folds_polish_letters_in_candidate_names(
    app_client, app_auth_headers, stored_last, typed_last, path
):
    nonce = uuid.uuid4().hex[:8]
    cand_id = await _seed(f"Jerzy{nonce}", f"{stored_last}{nonce}")

    for q in (
        f"{typed_last}{nonce}",
        f"Jerzy{nonce} {typed_last}{nonce}",
        f"{typed_last}{nonce} Jerzy{nonce}",
    ):
        resp = await app_client.get(path, params={"q": q}, headers=app_auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        found = (
            body["candidates"]
            if path.endswith("global")
            else body["results"]["candidates"]
        )
        assert cand_id in {c["id"] for c in found}, q


@pytest.mark.asyncio
async def test_search_fold_keeps_like_wildcards_literal(app_client, app_auth_headers):
    """Fold nie może zdjąć escapowania: ``%`` i ``_`` dalej są dosłowne."""
    nonce = uuid.uuid4().hex[:8]
    await _seed(f"Jerzy{nonce}", f"Leśniawski{nonce}")
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"L_sniawski{nonce}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == []
