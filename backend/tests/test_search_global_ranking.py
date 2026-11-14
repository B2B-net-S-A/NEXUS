"""Kolejność trafień w `GET /api/search/global` (staging, 14.11.2026).

Paleta ⌘K, zakładka „Szukaj” na telefonie i Jarvis biorą po 5 trafień na
kategorię. Zapytanie nie miało ``ORDER BY``, więc przy częstym prefiksie
wracało 5 dowolnych osób: „Kotow” dawało Kotowskich i Kotowiczów, a osoby
o nazwisku dokładnie „Kotow” nie było, choć lista kandydatów znajdowała ją
jako jedyny wynik. Teraz: dokładne nazwisko (albo imię z nazwiskiem) po
zwinięciu polskich znaków, potem prefiks, potem „zawiera”.

Osoby są zmyślone; baza testowa nie jest czyszczona, więc nazwy niosą losowy
przyrostek. Dokładne trafienie jest wstawiane OSTATNIE — w kolejności
wstawiania byłoby poza pierwszą piątką.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobStatus


def _base() -> str:
    # Same litery: cyfry z uuid w środku nazwiska nie przeszkadzają, ale
    # przyrostek ma być nie do pomylenia z innymi testami.
    return "Kotow" + "".join(
        chr(ord("a") + int(c, 16) % 26) for c in uuid.uuid4().hex[:8]
    )


async def _seed_candidates(lastnames: list[str]) -> list[int]:
    async with AsyncSessionLocal() as db:
        rows = []
        for i, lastname in enumerate(lastnames):
            cand = Candidate(
                name="Jan",
                lastname=lastname,
                email=f"ranking-{uuid.uuid4().hex[:8]}-{i}@example.com",
                status=CandidateStatus.active,
            )
            db.add(cand)
            # Osobne flushe: kolejność wstawiania = kolejność id.
            await db.flush()
            rows.append(cand)
        await db.commit()
        return [c.id for c in rows]


async def _global(app_client: AsyncClient, headers: dict[str, str], q: str) -> dict:
    resp = await app_client.get("/api/search/global", params={"q": q}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_exact_lastname_first_even_when_inserted_last(
    app_client, app_auth_headers
):
    base = _base()
    *others, exact = await _seed_candidates(
        [
            f"{base}ski",
            f"Skrze{base.lower()}ski",
            f"{base}icz",
            f"{base}ski",
            f"{base}icz",
            base,
        ]
    )
    body = await _global(app_client, app_auth_headers, base)
    ids = [c["id"] for c in body["candidates"]]
    assert ids[0] == exact, ids
    assert len(ids) == 5


@pytest.mark.asyncio
async def test_exact_match_ignores_polish_letters_and_case(
    app_client, app_auth_headers
):
    base = _base()
    folded_lastname = base.replace("Kotow", "Kotów")
    *_, exact = await _seed_candidates([f"{base}ski"] * 6 + [folded_lastname])
    body = await _global(app_client, app_auth_headers, base.lower())
    assert body["candidates"][0]["id"] == exact


@pytest.mark.asyncio
async def test_exact_full_name_first(app_client, app_auth_headers):
    base = _base()
    *_, exact = await _seed_candidates([f"{base}ski"] * 6 + [base])
    for q in (f"Jan {base}", f"{base} Jan"):
        body = await _global(app_client, app_auth_headers, q)
        assert body["candidates"][0]["id"] == exact, q


@pytest.mark.asyncio
async def test_prefix_before_contains(app_client, app_auth_headers):
    base = _base()
    ids = await _seed_candidates(
        [f"Skrze{base.lower()}"] * 3 + [f"{base}ski"] * 3 + [base]
    )
    contains, prefix, exact = ids[:3], ids[3:6], ids[6]
    body = await _global(app_client, app_auth_headers, base)
    got = [c["id"] for c in body["candidates"]]
    assert got[0] == exact
    assert set(got[1:4]) == set(prefix)
    assert got[4] in contains


@pytest.mark.asyncio
async def test_jobs_and_contacts_exact_first(app_client, app_auth_headers):
    base = _base()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Firma {base}")
        db.add(client)
        await db.flush()
        for title in [f"{base} Developer"] * 6:
            db.add(Job(title=title, status=JobStatus.published, client_id=client.id))
            await db.flush()
        exact_job = Job(title=base, status=JobStatus.published, client_id=client.id)
        db.add(exact_job)
        await db.flush()
        for i in range(6):
            db.add(
                Contact(
                    client_id=client.id,
                    name=f"Anna {base}ska",
                    email=f"c{i}-{base.lower()}@example.com",
                )
            )
            await db.flush()
        exact_contact = Contact(client_id=client.id, name=f"Anna {base}")
        db.add(exact_contact)
        await db.commit()
        job_id, contact_id = exact_job.id, exact_contact.id

    body = await _global(app_client, app_auth_headers, base)
    assert body["jobs"][0]["id"] == job_id
    body = await _global(app_client, app_auth_headers, f"Anna {base}")
    assert body["contacts"][0]["id"] == contact_id
