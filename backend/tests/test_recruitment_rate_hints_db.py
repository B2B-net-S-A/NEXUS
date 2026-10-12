"""Podpowiedzi stawek pary bez stawki na etapie — z bazą (12.10.2026).

Para z czasów Traffita: etapy bez kwot, oczekiwanie kandydata w karcie
rekomendacji, cena wysłania w notatce Delivery Leada z dnia wysyłki.
Treści fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

SEND_NOTE = "Wysłany 150/100-110"


async def _user(role: UserRole) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rate-hints-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Hints"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Hints {role.value}",
            role=role,
            roles=[role.value],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id, email, password


async def _headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _pair(
    *,
    sender_id: int,
    card_rate: Optional[float] = 90.0,
    stage_candidate_rate: Optional[str] = None,
    stage_client_rate: Optional[str] = None,
) -> tuple[int, int, datetime]:
    """Para po „CV wysłane”; zwraca (kandydat, rekrutacja, chwila wysyłki)."""
    unique = uuid.uuid4().hex[:8]
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Hints client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Hints job {unique}", client_id=client.id, status=JobStatus.published
        )
        candidate = Candidate(
            name="Tomasz", lastname=f"Podpowiedź{unique}", email=f"hints-{unique}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=sent_at - timedelta(days=1),
                    expected_rate_value=(
                        Decimal(stage_candidate_rate) if stage_candidate_rate else None
                    ),
                    expected_rate_unit="hourly" if stage_candidate_rate else None,
                    expected_rate_currency="PLN" if stage_candidate_rate else None,
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=sent_at,
                    moved_by=sender_id,
                    client_rate_value=(
                        Decimal(stage_client_rate) if stage_client_rate else None
                    ),
                    client_rate_unit="hourly" if stage_client_rate else None,
                    client_rate_currency="PLN" if stage_client_rate else None,
                ),
            ]
        )
        if card_rate is not None:
            db.add(
                RecommendationCard(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    fields_notes={
                        "rate": {
                            "raw": f"{card_rate:g} zł/h",
                            "value": card_rate,
                            "currency": "PLN",
                            "period": "h",
                            "at": (sent_at - timedelta(days=1)).isoformat(),
                        }
                    },
                )
            )
        await db.commit()
        return candidate.id, job.id, sent_at


async def _note(
    candidate_id: int,
    *,
    author_id: int,
    at: datetime,
    job_id: Optional[int] = None,
    content: str = SEND_NOTE,
) -> int:
    async with AsyncSessionLocal() as db:
        note = Note(
            candidate_id=candidate_id,
            job_id=job_id,
            author_id=author_id,
            content=content,
            source_created_at=at,
        )
        db.add(note)
        await db.commit()
        return note.id


async def _history_job(
    client: AsyncClient, headers: dict, candidate_id: int, job_id: int
) -> dict:
    resp = await client.get(f"/api/candidates/{candidate_id}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    return next(job for job in resp.json()["jobs"] if job["job_id"] == job_id)


@pytest.mark.asyncio
async def test_history_shows_card_rate_and_send_note_when_stage_rows_have_no_rates(
    app_client: AsyncClient, app_auth_headers: dict
):
    dl_id, _, _ = await _user(UserRole.delivery_lead)
    candidate_id, job_id, sent_at = await _pair(sender_id=dl_id)
    # Notatka bez rekrutacji, minutę po ruchu — tak pisano w Traffit.
    note_id = await _note(
        candidate_id, author_id=dl_id, at=sent_at + timedelta(minutes=1)
    )

    job = await _history_job(app_client, app_auth_headers, candidate_id, job_id)

    # Pola stawek zostają puste: podpowiedź staje się stawką dopiero po zapisie.
    assert job["expected_rate"] is None and job["client_rate"] is None
    assert job["expected_rate_hint"]["amount_hourly"] == 90.0
    assert job["expected_rate_hint"]["source"] == "card"
    assert job["client_rate_note"]["note_id"] == note_id
    assert job["client_rate_note"]["text"] == SEND_NOTE
    assert job["client_rate_note"]["author_name"] == "Hints delivery_lead"


@pytest.mark.asyncio
async def test_recruiter_gets_candidate_rate_but_never_the_send_note(
    app_client: AsyncClient,
):
    dl_id, _, _ = await _user(UserRole.delivery_lead)
    _, email, password = await _user(UserRole.recruiter)
    recruiter = await _headers(app_client, email, password)
    candidate_id, job_id, sent_at = await _pair(sender_id=dl_id)
    await _note(candidate_id, author_id=dl_id, at=sent_at + timedelta(minutes=1))

    job = await _history_job(app_client, recruiter, candidate_id, job_id)
    assert job["expected_rate_hint"]["amount_hourly"] == 90.0
    assert job["client_rate_note"] is None

    resp = await app_client.get(
        f"/api/candidates/{candidate_id}/recruitment-rate-hints",
        params={"job_id": job_id},
        headers=recruiter,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_rate_note"] is None
    assert Decimal(str(resp.json()["expected_rate_hint"]["amount_hourly"])) == 90


@pytest.mark.asyncio
async def test_rates_saved_on_stage_rows_leave_no_hints(
    app_client: AsyncClient, app_auth_headers: dict
):
    dl_id, _, _ = await _user(UserRole.delivery_lead)
    candidate_id, job_id, sent_at = await _pair(
        sender_id=dl_id, stage_candidate_rate="120", stage_client_rate="180"
    )
    await _note(candidate_id, author_id=dl_id, at=sent_at + timedelta(minutes=1))

    job = await _history_job(app_client, app_auth_headers, candidate_id, job_id)
    assert job["expected_rate"]["value"] == 120.0
    assert job["client_rate"]["value"] == 180.0
    assert job["expected_rate_hint"] is None
    assert job["client_rate_note"] is None


@pytest.mark.asyncio
async def test_send_note_must_come_from_the_sender_inside_the_window_and_carry_an_amount(
    app_client: AsyncClient, app_auth_headers: dict
):
    dl_id, _, _ = await _user(UserRole.delivery_lead)
    other_dl_id, _, _ = await _user(UserRole.delivery_lead)
    candidate_id, job_id, sent_at = await _pair(sender_id=dl_id, card_rate=None)
    near = sent_at + timedelta(minutes=1)
    # Inna osoba, za późno, bez kwoty — żadna nie jest notatką z wysyłki.
    await _note(candidate_id, author_id=other_dl_id, at=near)
    await _note(candidate_id, author_id=dl_id, at=sent_at + timedelta(hours=2))
    await _note(candidate_id, author_id=dl_id, at=near, content="Wysłany, czekamy")

    job = await _history_job(app_client, app_auth_headers, candidate_id, job_id)
    assert job["client_rate_note"] is None
    # Bez karty i bez stawki na etapie nie ma czego podpowiedzieć.
    assert job["expected_rate_hint"] is None


@pytest.mark.asyncio
async def test_recruiters_note_near_their_own_send_is_not_a_client_rate_hint(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Rekruter przesuwa na „CV wysłane” (Nordea) i pisze o stawce kandydata.
    recruiter_id, _, _ = await _user(UserRole.recruiter)
    candidate_id, job_id, sent_at = await _pair(sender_id=recruiter_id)
    await _note(
        candidate_id,
        author_id=recruiter_id,
        at=sent_at + timedelta(minutes=1),
        content="Kandydat chce 95 zł/h",
    )

    job = await _history_job(app_client, app_auth_headers, candidate_id, job_id)
    assert job["client_rate_note"] is None


@pytest.mark.asyncio
async def test_pair_route_returns_both_hints_and_404_for_unknown_ids(
    app_client: AsyncClient, app_auth_headers: dict
):
    dl_id, _, _ = await _user(UserRole.delivery_lead)
    candidate_id, job_id, sent_at = await _pair(sender_id=dl_id)
    note_id = await _note(
        candidate_id, author_id=dl_id, job_id=job_id, at=sent_at - timedelta(minutes=2)
    )

    resp = await app_client.get(
        f"/api/candidates/{candidate_id}/recruitment-rate-hints",
        params={"job_id": job_id},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(str(body["expected_rate_hint"]["amount_hourly"])) == 90
    assert body["client_rate_note"]["note_id"] == note_id

    for path, params in (
        (
            f"/api/candidates/{candidate_id}/recruitment-rate-hints",
            {"job_id": 2**31 - 1},
        ),
        ("/api/candidates/2147483647/recruitment-rate-hints", {"job_id": job_id}),
    ):
        resp = await app_client.get(path, params=params, headers=app_auth_headers)
        assert resp.status_code == 404, resp.text
    resp = await app_client.get(
        f"/api/candidates/{candidate_id}/recruitment-rate-hints",
        params={"job_id": 2**31},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
