"""Decyzja C na pozostałych powierzchniach — z bazą (14.10.2026).

Wymaga Postgresa (CI). Notatka Delivery Leada z wysyłki („Wysłany
150/100-110”) jest zakryta dla rekrutera nie tylko w ``GET /api/notes``
(WS10), ale też w „Ostatniej rozmowie”, „ostatniej notatce” i wycinkach
listy kandydatów, w podglądzie kandydata, na osi ``/timeline`` i na osi
kontraktu. Delivery Lead widzi cenę. Wariant bez bazy:
``test_fix48_ws14_send_note_surfaces.py``. Treści fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import note_kinds
from tests._permission_grants import grant_permissions
from tests.test_recruitment_rate_hints_db import SEND_NOTE, _headers, _user

PRICE = "150/100-110"


async def _seed(*, dl_id: int, recruiter_id: int) -> dict:
    """Para po „CV wysłane” przez DL-a, rozmowa rekrutera i notatka z wysyłki.

    Fraza ``marker`` (same litery — całe słowo dla słów kluczowych) siedzi
    w firmie z LinkedIna (zawężenie listy) i w obu notatkach (wycinki).
    Notatka z wysyłki jest najnowsza i przypięta do umowy osoby.
    """
    marker = "zq" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:10])
    sent_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Ws14 klient {marker}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Ws14 {marker}", client_id=client.id, status=JobStatus.published
        )
        candidate = Candidate(
            name="Tomasz",
            lastname=f"Ws14{marker}",
            email=f"ws14-{marker}@example.com",
            linkedin_current_company=marker,
        )
        db.add_all([job, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            start_date=business_today(),
            status=ContractStatus.active,
        )
        db.add_all(
            [
                contract,
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=sent_at - timedelta(days=1),
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=sent_at,
                    moved_by=dl_id,
                ),
                Note(
                    candidate_id=candidate.id,
                    author_id=recruiter_id,
                    content=f"Rozmowa: {marker}, Java od 5 lat",
                    source_created_at=sent_at - timedelta(hours=2),
                ),
            ]
        )
        await db.commit()
        ids = {
            "candidate": candidate.id,
            "contract": contract.id,
            "marker": marker,
        }
    async with AsyncSessionLocal() as db:
        send = Note(
            candidate_id=ids["candidate"],
            contract_id=ids["contract"],
            author_id=dl_id,
            content=f"{SEND_NOTE} {marker}",
            source_created_at=sent_at + timedelta(minutes=1),
        )
        db.add(send)
        await db.commit()
        ids["send"] = send.id
    return ids


async def _list_row(client: AsyncClient, headers: dict, world: dict) -> tuple:
    resp = await client.get(
        "/api/candidates",
        params={
            "q": world["marker"],
            "text_mode": "literal",
            "page_size": 100,
            "include_last_talk": "true",
            "include_last_activity": "true",
            "q_all": world["marker"],
            "q_scope": "notes",
            "semantics_version": 2,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    row = next(i for i in resp.json()["items"] if i["id"] == world["candidate"])
    return row, resp.text


@pytest.mark.asyncio
async def test_candidate_list_covers_the_send_note_for_the_recruiter(
    app_client: AsyncClient,
):
    dl_id, dl_email, dl_pass = await _user(UserRole.delivery_lead)
    recruiter_id, r_email, r_pass = await _user(UserRole.recruiter)
    world = await _seed(dl_id=dl_id, recruiter_id=recruiter_id)

    recruiter = await _headers(app_client, r_email, r_pass)
    row, text = await _list_row(app_client, recruiter, world)
    # „Ostatnia rozmowa” i „ostatnia notatka” — data i autor zostają, cena nie.
    assert row["last_talk_preview"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert row["last_talk_at"] is not None
    assert row["last_note_preview"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    # Wycinek bierze rozmowę rekrutera, nie notatkę z wysyłki.
    assert row["match_snippets"], row
    assert PRICE not in text

    lead = await _headers(app_client, dl_email, dl_pass)
    lead_row, _ = await _list_row(app_client, lead, world)
    assert lead_row["last_talk_preview"].startswith(SEND_NOTE)
    assert lead_row["last_note_preview"].startswith(SEND_NOTE)


@pytest.mark.asyncio
async def test_quick_view_and_timeline_cover_the_send_note_for_the_recruiter(
    app_client: AsyncClient,
):
    dl_id, dl_email, dl_pass = await _user(UserRole.delivery_lead)
    recruiter_id, r_email, r_pass = await _user(UserRole.recruiter)
    world = await _seed(dl_id=dl_id, recruiter_id=recruiter_id)
    base = f"/api/candidates/{world['candidate']}"

    recruiter = await _headers(app_client, r_email, r_pass)
    quick = await app_client.get(f"{base}/quick-view", headers=recruiter)
    assert quick.status_code == 200, quick.text
    contents = [note["content"] for note in quick.json()["recent_notes"]]
    assert note_kinds.CLIENT_RATE_PLACEHOLDER in contents
    assert PRICE not in quick.text

    timeline = await app_client.get(f"{base}/timeline", headers=recruiter)
    assert timeline.status_code == 200, timeline.text
    notes = {
        item["id"]: item
        for item in timeline.json()["timeline"]
        if item["type"] == "note"
    }
    assert notes[world["send"]]["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert notes[world["send"]]["content_hidden"] is True
    assert PRICE not in timeline.text

    lead = await _headers(app_client, dl_email, dl_pass)
    lead_timeline = await app_client.get(f"{base}/timeline", headers=lead)
    lead_notes = {
        item["id"]: item
        for item in lead_timeline.json()["timeline"]
        if item["type"] == "note"
    }
    assert lead_notes[world["send"]]["content"].startswith(SEND_NOTE)
    assert lead_notes[world["send"]]["content_hidden"] is False


@pytest.mark.asyncio
async def test_contract_timeline_covers_the_send_note_for_a_recruiter_with_delivery_view(
    app_client: AsyncClient,
):
    dl_id, dl_email, dl_pass = await _user(UserRole.delivery_lead)
    recruiter_id, r_email, r_pass = await _user(UserRole.recruiter)
    world = await _seed(dl_id=dl_id, recruiter_id=recruiter_id)
    # Podgląd Delivery nadany rekruterowi — oś kontraktu jest dla niego otwarta.
    await grant_permissions(recruiter_id, "delivery_view")
    url = f"/api/contracts/{world['contract']}/notes"

    recruiter = await _headers(app_client, r_email, r_pass)
    resp = await app_client.get(url, headers=recruiter)
    assert resp.status_code == 200, resp.text
    by_id = {item["id"]: item for item in resp.json() if item["kind"] == "note"}
    assert by_id[world["send"]]["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert PRICE not in resp.text

    async with AsyncSessionLocal() as db:
        from app.models.team_structure import DeliveryLeadClientAssignment

        contract = await db.get(Contract, world["contract"])
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=contract.client_id
            )
        )
        await db.commit()
    lead = await _headers(app_client, dl_email, dl_pass)
    lead_resp = await app_client.get(url, headers=lead)
    assert lead_resp.status_code == 200, lead_resp.text
    lead_by_id = {
        item["id"]: item for item in lead_resp.json() if item["kind"] == "note"
    }
    assert lead_by_id[world["send"]]["content"].startswith(SEND_NOTE)
