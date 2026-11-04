"""Notatka DL-a z wysyłki zakryta w `GET /api/notes` — z bazą (decyzja C, 14.10.2026).

Wymaga Postgresa (CI). Para i notatki z ``test_recruitment_rate_hints_db.py``:
ta sama reguła rozpoznaje notatkę z wysyłki dla podpowiedzi stawki do klienta
i dla zakrycia treści. Treści fikcyjne.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.models.user import UserRole
from app.services import note_kinds
from tests.test_recruitment_rate_hints_db import (
    SEND_NOTE,
    _headers,
    _note,
    _pair,
    _user,
)


@pytest.mark.asyncio
async def test_recruiter_sees_the_send_note_covered_and_the_lead_sees_it(
    app_client: AsyncClient,
):
    dl_id, dl_email, dl_pass = await _user(UserRole.delivery_lead)
    recruiter_id, r_email, r_pass = await _user(UserRole.recruiter)
    candidate_id, job_id, sent_at = await _pair(sender_id=dl_id)
    near = sent_at + timedelta(minutes=1)
    send_id = await _note(candidate_id, author_id=dl_id, at=near)
    send_in_job_id = await _note(
        candidate_id,
        author_id=dl_id,
        at=sent_at - timedelta(minutes=3),
        job_id=job_id,
        content="Pokazujemy 165, kandydat 120",
    )
    later_id = await _note(
        candidate_id,
        author_id=dl_id,
        at=sent_at + timedelta(hours=3),
        content="Klient pyta o rozmowę, termin 160 minut",
    )
    candidate_rate_id = await _note(
        candidate_id,
        author_id=recruiter_id,
        at=near,
        content="Kandydat chce 95 zł/h",
    )

    recruiter = await _headers(app_client, r_email, r_pass)
    listed = await app_client.get(
        "/api/notes", params={"candidate_id": candidate_id}, headers=recruiter
    )
    assert listed.status_code == 200, listed.text
    by_id = {item["id"]: item for item in listed.json()["items"]}
    for hidden_id in (send_id, send_in_job_id):
        assert by_id[hidden_id]["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
        assert (
            by_id[hidden_id]["content_rendered"] == note_kinds.CLIENT_RATE_PLACEHOLDER
        )
        assert by_id[hidden_id]["content_hidden"] is True
    assert "150/100-110" not in listed.text
    assert "Pokazujemy 165" not in listed.text
    # Poza oknem wysyłki i notatka rekrutera o stawce KANDYDATA — jawne.
    assert by_id[later_id]["content_hidden"] is False
    assert by_id[candidate_rate_id]["content"] == "Kandydat chce 95 zł/h"

    by_job = await app_client.get(
        "/api/notes", params={"job_id": job_id}, headers=recruiter
    )
    assert by_job.status_code == 200, by_job.text
    job_items = {item["id"]: item for item in by_job.json()["items"]}
    assert job_items[send_in_job_id]["content_hidden"] is True
    assert "Pokazujemy 165" not in by_job.text

    single = await app_client.get(f"/api/notes/{send_id}", headers=recruiter)
    assert single.status_code == 200, single.text
    assert single.json()["content"] == note_kinds.CLIENT_RATE_PLACEHOLDER
    assert single.json()["content_hidden"] is True

    lead = await _headers(app_client, dl_email, dl_pass)
    for_lead = await app_client.get(
        "/api/notes", params={"candidate_id": candidate_id}, headers=lead
    )
    lead_by_id = {item["id"]: item for item in for_lead.json()["items"]}
    assert lead_by_id[send_id]["content"] == SEND_NOTE
    assert lead_by_id[send_id]["content_hidden"] is False
