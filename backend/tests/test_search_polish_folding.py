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
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobStatus


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


async def _seed_with_phone(phone: str) -> int:
    nonce = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Tel{nonce}",
            lastname=f"Numer{nonce}",
            email=f"phone-{nonce}@example.com",
            phone=phone,
            status=CandidateStatus.active,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


def _random_nine_digits() -> str:
    return f"{uuid.uuid4().int % 10**9:09d}"


@pytest.mark.asyncio
async def test_global_search_finds_candidate_by_phone_digits(
    app_client, app_auth_headers
):
    """Numer w dowolnym zapisie (spacje, +48) trafia w numer zapisany inaczej."""
    d = _random_nine_digits()
    cand_id = await _seed_with_phone(f"+48 {d[:3]} {d[3:6]} {d[6:]}")
    for q in (d, f"{d[:3]} {d[3:6]} {d[6:]}", f"+48{d}", f"0048 {d}"):
        resp = await app_client.get(
            "/api/search/global", params={"q": q}, headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        found = resp.json()["candidates"]
        assert cand_id in {c["id"] for c in found}, q
        # Wyszukiwarka nie oddaje numeru — tylko imię, nazwisko i e-mail.
        assert all(d not in str(c) for c in found), q


@pytest.mark.asyncio
async def test_global_search_phone_hidden_from_role_without_candidates(app_client):
    """Rola bez odczytu kandydatów (klient/QC) nie znajdzie nikogo po numerze."""
    from tests.test_search_full_name import _headers_for

    from app.models.user import UserRole

    d = _random_nine_digits()
    await _seed_with_phone(d)
    headers = await _headers_for(app_client, UserRole.user)
    resp = await app_client.get("/api/search/global", params={"q": d}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == []
    assert "candidates" in {s["category"] for s in body["skipped"]}


async def _seed_folding_records(nonce: str) -> dict[str, int]:
    """Rekrutacja, klient i kontakt zapisane z polskimi literami."""
    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Spółka Żółta{nonce}",
            display_name=f"Łódzka Marka{nonce}",
            industry=f"Księgowość{nonce}",
        )
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Wdrożeniowiec{nonce}",
            status=JobStatus.published,
            client_id=client.id,
        )
        contact = Contact(
            client_id=client.id,
            name=f"Małgorzata Wąska{nonce}",
            email=f"bożena{nonce}@example.com",
        )
        db.add_all([job, contact])
        await db.commit()
        return {"client": client.id, "job": job.id, "contact": contact.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", ["wdrozeniowiec", "WDROŻENIOWIEC"])
@pytest.mark.parametrize("path", ["/api/search/global", "/api/search/"])
async def test_search_folds_polish_letters_in_job_titles(
    app_client, app_auth_headers, typed, path
):
    """Jarvis dostawał pustą listę rekrutacji dla „wdrozeniowiec” (audyt 08.11)."""
    nonce = uuid.uuid4().hex[:8]
    ids = await _seed_folding_records(nonce)
    resp = await app_client.get(
        path, params={"q": f"{typed}{nonce}"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    found = body["jobs"] if path.endswith("global") else body["results"]["jobs"]
    assert ids["job"] in {j["id"] for j in found}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "typed",
    ["lodzka marka", "spolka zolta", "ksiegowosc"],
    ids=["display_name", "name", "industry"],
)
@pytest.mark.parametrize("path", ["/api/search/global", "/api/search/"])
async def test_search_folds_polish_letters_in_clients(
    app_client, app_auth_headers, typed, path
):
    nonce = uuid.uuid4().hex[:8]
    ids = await _seed_folding_records(nonce)
    resp = await app_client.get(
        path, params={"q": f"{typed}{nonce}"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    found = body["clients"] if path.endswith("global") else body["results"]["clients"]
    assert ids["client"] in {c["id"] for c in found}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "typed",
    ["malgorzata waska", "MAŁGORZATA WĄSKA", "bozena"],
    ids=["name", "name-with-letters", "email"],
)
async def test_global_search_folds_polish_letters_in_contacts(
    app_client, app_auth_headers, typed
):
    nonce = uuid.uuid4().hex[:8]
    ids = await _seed_folding_records(nonce)
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"{typed}{nonce}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert ids["contact"] in {c["id"] for c in resp.json()["contacts"]}


@pytest.mark.asyncio
async def test_global_search_fold_keeps_wildcards_literal_outside_candidates(
    app_client, app_auth_headers
):
    """Fold rekrutacji nie zdejmuje escapowania: ``_`` nie zastępuje litery."""
    nonce = uuid.uuid4().hex[:8]
    await _seed_folding_records(nonce)
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"Wdro_eniowiec{nonce}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["jobs"] == []
