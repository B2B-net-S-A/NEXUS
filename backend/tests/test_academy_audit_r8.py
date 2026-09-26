"""Akademia — poprawki rundy 8 audytu (26.09.2026), na prawdziwej bazie.

- R8-N2-2: werdykt „skip” policzony starym limitem lat, starym wymogiem
  polskiego albo starą wersją reguł nie jest wykluczany przez „Zatwierdź” —
  wraca do sortowania;
- R8-N2-9: wykluczeni i zrezygnowani przed spotkaniem nie liczą się jako
  uczestnicy terminu (przycisk „Odwołaj” nie znika).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from tests.test_academy_api import (
    _apps_by_candidate,
    _candidate,
    _fake_luna,
    _headers,
    _now,
    _settle,
    _setup,
    needs_db,
)


@needs_db
@pytest.mark.asyncio
async def test_raising_the_limit_rescreens_skipped_instead_of_rejecting(
    app_client, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.academy import AcademyApplication
    from app.services import academy as svc

    monkeypatch.setattr(svc, "_call_model", _fake_luna([]))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")
    admin_h = _headers(ids["admin"], "admin")
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/sync", headers=rec_h
    )
    assert resp.status_code == 200, resp.text
    await _settle()
    senior = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["senior"]]
    assert (senior["status"], senior["screening_verdict"]) == ("new", "skip")

    # HoR podnosi limit — 16 lat pracy mieści się w nowym kryterium.
    resp = await app_client.patch(
        f"/api/academy/programs/{program_id}",
        headers=admin_h,
        json={"max_experience_years": 20},
    )
    assert resp.status_code == 200, resp.text
    await _settle()

    # „Zatwierdź” na starej liście nie wyklucza osoby, która spełnia kryterium.
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={"ids": [senior["id"]], "action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == []
    senior = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["senior"]]
    assert senior["status"] == "to_call"
    assert senior["screening_verdict"] == "call"

    # Werdykt ze starej wersji reguł też nie jest wykluczany — Luna sortuje go
    # od nowa, a po ponownym sortowaniu „Zatwierdź” działa.
    resp = await app_client.patch(
        f"/api/academy/programs/{program_id}",
        headers=admin_h,
        json={"max_experience_years": 6},
    )
    assert resp.status_code == 200, resp.text
    await _settle()
    async with AsyncSessionLocal() as db:
        row = await db.get(AcademyApplication, senior["id"])
        row.status = "new"
        row.screening_verdict = "skip"
        row.screening = {
            "version": 2,
            "reasons": [{"code": "experience_over", "text": "stary powód"}],
        }
        await db.commit()
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={"ids": [senior["id"]], "action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == []
    assert "Kryteria sortowania" in body["failed"][0]["message"]
    await _settle()
    senior = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["senior"]]
    assert (senior["status"], senior["screening_verdict"]) == ("new", "skip")
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={"ids": [senior["id"]], "action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == [senior["id"]]


@needs_db
@pytest.mark.asyncio
async def test_people_who_left_before_the_meeting_do_not_block_cancelling():
    from app.core.database import AsyncSessionLocal
    from app.models.academy import (
        AcademyApplication,
        AcademyProgram,
        AcademySession,
    )
    from app.services import academy as svc

    async with AsyncSessionLocal() as db:
        program = AcademyProgram(name=f"Termin {uuid.uuid4().hex[:6]}")
        db.add(program)
        await db.flush()
        session = AcademySession(
            program_id=program.id,
            starts_at=_now() + timedelta(days=3),
            capacity=5,
        )
        db.add(session)
        await db.flush()
        # Wiersze sprzed poprawki: zamknięci bez spotkania, wciąż przy terminie.
        for status, attended in (("withdrew", None), ("rejected", False)):
            cand = await _candidate(db)
            db.add(
                AcademyApplication(
                    program_id=program.id,
                    candidate_id=cand.id,
                    applied_at=_now(),
                    status=status,
                    session_id=session.id,
                    attended=attended,
                    closed_reason="powód",
                )
            )
        await db.commit()

        rows = await svc.sessions_with_counts(db, program.id)
        assert [(r["taken"], r["people"]) for r in rows] == [(0, 0)]
