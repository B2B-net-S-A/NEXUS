"""„Stawka od” (0414) z bazą: wyzwalacze, przeliczenie, API, filtr listy."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recommendation_card import RecommendationCard
from app.services import candidate_rate_from as rf


async def _seed(profile_rate: str | None = "140.00") -> tuple[int, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Rate client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Rate job {unique}", client_id=client.id, status=JobStatus.published
        )
        candidate = Candidate(
            name="Tomasz",
            lastname=f"Stawkowy{unique}",
            email=f"rate-{unique}@x.com",
            expected_rate_hourly=Decimal(profile_rate) if profile_rate else None,
            expected_rate_currency="PLN" if profile_rate else None,
        )
        db.add_all([job, candidate])
        await db.commit()
        return candidate.id, job.id


async def _card(
    candidate_id: int, job_id: int, value: float, *, days_ago: int = 30
) -> int:
    at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    async with AsyncSessionLocal() as db:
        card = RecommendationCard(
            candidate_id=candidate_id,
            job_id=job_id,
            fields_notes={
                "rate": {
                    "raw": f"{value:g} zł/h",
                    "value": value,
                    "currency": "PLN",
                    "period": "h",
                    "at": at,
                }
            },
        )
        db.add(card)
        await db.commit()
        return card.id


async def _queued(candidate_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            await db.scalar(
                text("SELECT 1 FROM candidate_rate_from_queue WHERE candidate_id = :c"),
                {"c": candidate_id},
            )
        )


async def _drain() -> None:
    for _ in range(100):
        async with AsyncSessionLocal() as db:
            done = await rf.process_queue(db, limit=500)
            await db.commit()
        if not done:
            return
    raise AssertionError("kolejka „Stawki od” nie doszła do końca")


async def _row(candidate_id: int):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(
                    Candidate.rate_from_hourly,
                    Candidate.rate_from_computed_at,
                    Candidate.rate_latest_hourly,
                    Candidate.rate_observation_count,
                    Candidate.updated_at,
                ).where(Candidate.id == candidate_id)
            )
        ).one()


@pytest.mark.asyncio
async def test_card_rate_enqueues_and_lowers_rate_from_without_touching_updated_at(
    app_client: AsyncClient,
):
    candidate_id, job_id = await _seed("140.00")
    await _drain()
    before = await _row(candidate_id)
    assert before.rate_from_hourly == Decimal("140.00")

    await _card(candidate_id, job_id, 80.0)
    assert await _queued(candidate_id)
    await _drain()

    after = await _row(candidate_id)
    assert after.rate_from_hourly == Decimal("80.00")
    assert after.rate_from_computed_at is not None
    assert after.rate_observation_count == 2
    # Surowy UPDATE — alerty zapisanych wyszukiwań nie widzą zmiany kandydata.
    assert after.updated_at == before.updated_at


@pytest.mark.asyncio
async def test_list_filter_finds_candidate_by_rate_from(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, job_id = await _seed("140.00")
    await _card(candidate_id, job_id, 80.0)
    await _drain()
    async with AsyncSessionLocal() as db:
        lastname = await db.scalar(
            select(Candidate.lastname).where(Candidate.id == candidate_id)
        )
    resp = await app_client.get(
        "/api/candidates",
        params={"max_rate": 100, "q": lastname, "semantics_version": 2},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    row = next(i for i in items if i["id"] == candidate_id)
    assert Decimal(str(row["rate_from_hourly"])) == Decimal("80")
    assert Decimal(str(row["expected_rate_hourly"])) == Decimal("140")


@pytest.mark.asyncio
async def test_overview_exclusion_and_explicit_minimum(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, job_id = await _seed("140.00")
    card_id = await _card(candidate_id, job_id, 80.0)
    await _drain()

    resp = await app_client.get(
        f"/api/candidates/{candidate_id}/rate-overview", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(str(body["rate_from"]["amount"])) == Decimal("80")
    reasons = {o["key"]: o["reason"] for o in body["observations"]}
    assert reasons[f"card:{card_id}"] == "minimum"

    resp = await app_client.put(
        f"/api/candidates/{candidate_id}/rate-observations/card:{card_id}",
        json={"decision": "exclude"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("140.00")

    # Przywrócenie, potem jawne minimum 130 — 80 sprzed niego przestaje się liczyć.
    resp = await app_client.put(
        f"/api/candidates/{candidate_id}/rate-observations/card:{card_id}",
        json={"decision": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    rate = await app_client.get(
        f"/api/candidates/{candidate_id}/profile-rate", headers=app_auth_headers
    )
    etag = rate.headers["etag"]
    resp = await app_client.patch(
        f"/api/candidates/{candidate_id}/profile-rate",
        json={"amount": "130", "is_minimum": True},
        headers={**app_auth_headers, "If-Match": etag},
    )
    assert resp.status_code == 200, resp.text
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("130.00")


@pytest.mark.asyncio
async def test_unknown_observation_key_is_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, _ = await _seed("140.00")
    resp = await app_client.put(
        f"/api/candidates/{candidate_id}/rate-observations/card:999999999",
        json={"decision": "exclude"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_minimum_leaving_the_window_is_requeued_and_recomputed(
    app_client: AsyncClient,
):
    candidate_id, job_id = await _seed("150.00")
    await _card(candidate_id, job_id, 100.0, days_ago=500)
    await _drain()
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("100.00")

    # 60 dni później karta sprzed 560 dni jest już poza oknem 18 miesięcy.
    later = (datetime.now(timezone.utc) + timedelta(days=60)).date()
    async with AsyncSessionLocal() as db:
        await rf.requeue_expiring(db, today=later)
        await db.commit()
    assert await _queued(candidate_id)
    async with AsyncSessionLocal() as db:
        await rf.recompute(db, [candidate_id], today=later)
        await db.commit()
    row = await _row(candidate_id)
    assert row.rate_from_hourly == Decimal("150.00")
    assert not await _queued(candidate_id)


# ── Wpis DL-a „X/Y” w notatce (07.10.2026) ────────────────────────────────────


async def _note(candidate_id: int, job_id: int, content: str) -> int:
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        note = Note(candidate_id=candidate_id, job_id=job_id, content=content)
        db.add(note)
        await db.commit()
        return note.id


@pytest.mark.asyncio
async def test_dl_pair_note_is_a_candidate_rate_observation_without_client_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, job_id = await _seed("140.00")
    await _drain()
    note_id = await _note(candidate_id, job_id, "160/115 @Jan Testowy")
    # Wyzwalacz na notatkach kolejkuje kandydata (także przy imporcie Traffita).
    assert await _queued(candidate_id)
    await _drain()
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("115.00")

    resp = await app_client.get(
        f"/api/candidates/{candidate_id}/rate-overview", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    observation = next(o for o in body["observations"] if o["key"] == f"note:{note_id}")
    assert observation["source"] == "note"
    assert observation["raw"] == "115 PLN/h"
    # Stawka do klienta nie wychodzi w historii stawek (widzi ją każda rola).
    assert "160" not in resp.text

    # „Nie licz jako minimum” działa także na wpisie z notatki.
    resp = await app_client.put(
        f"/api/candidates/{candidate_id}/rate-observations/note:{note_id}",
        json={"decision": "exclude"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("140.00")


@pytest.mark.asyncio
async def test_candidate_range_and_long_notes_are_not_observations():
    from app.services.candidate_rate_observations import collect

    candidate_id, job_id = await _seed(None)
    await _note(candidate_id, job_id, "Rate: 100/110 PLN/h")
    await _note(candidate_id, job_id, "score: 67/100")
    await _note(
        candidate_id,
        job_id,
        "Rozmowa o projekcie, zespół rozproszony, Java i Spring, kandydat "
        "pracuje zdalnie, ustalenia z klientem z poprzedniej rekrutacji "
        "obejmowały też widełki 160/115 i termin startu po wypowiedzeniu",
    )
    async with AsyncSessionLocal() as db:
        observations = (await collect(db, [candidate_id]))[candidate_id]
    assert not [o for o in observations if o.key.startswith("note:")]


@pytest.mark.asyncio
async def test_note_api_recomputes_rate_from_right_away(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id, job_id = await _seed("140.00")
    await _drain()
    resp = await app_client.post(
        "/api/notes",
        json={"candidate_id": candidate_id, "job_id": job_id, "content": "170/120"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("120.00")

    resp = await app_client.delete(
        f"/api/notes/{resp.json()['id']}", headers=app_auth_headers
    )
    assert resp.status_code == 204, resp.text
    assert (await _row(candidate_id)).rate_from_hourly == Decimal("140.00")
