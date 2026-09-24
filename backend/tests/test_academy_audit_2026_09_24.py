"""Akademia — poprawki po audycie 24.09.2026 (na prawdziwej bazie).

- zbiorcze „Zatwierdź — wyklucz” (powód z sortowania) nie odrzuca osoby,
  którą ktoś w międzyczasie przesunął (odrzucenie jest trwałe);
- lista zgłoszeń przy limicie ucina najstarszych zamkniętych, nigdy
  najnowszych ani osób w toku, i mówi, ile pasuje wszystkich.
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
async def test_bulk_approve_skips_people_someone_already_moved(app_client, monkeypatch):
    from app.services import academy as svc

    monkeypatch.setattr(svc, "_call_model", _fake_luna([]))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/sync", headers=rec_h
    )
    await _settle()
    assert resp.status_code == 200, resp.text
    apps = await _apps_by_candidate(app_client, program_id, rec_h)
    senior, junior = apps[ids["senior"]], apps[ids["junior"]]
    assert (senior["status"], senior["screening_verdict"]) == ("new", "skip")

    # Rekruter B: „Dzwonimy mimo to” — osoba przechodzi do telefonów.
    resp = await app_client.post(
        f"/api/academy/applications/{senior['id']}/actions",
        headers=rec_h,
        json={"action": "call"},
    )
    assert resp.status_code == 200, resp.text

    # Rekruter A klika „Zatwierdź” na starej liście (i przy okazji junior,
    # który w ogóle nie był odłożony przez Lunę).
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={"ids": [senior["id"], junior["id"]], "action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == []
    assert sorted(f["id"] for f in body["failed"]) == sorted(
        [senior["id"], junior["id"]]
    )
    assert all("nie czeka już" in f["message"] for f in body["failed"])
    apps = await _apps_by_candidate(app_client, program_id, rec_h)
    assert apps[ids["senior"]]["status"] == "to_call"
    assert apps[ids["junior"]]["status"] == "to_call"

    # Jawny powód (ręczne wykluczenie) dalej działa z każdego etapu aktywnego.
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={
            "ids": [junior["id"]],
            "action": "reject",
            "reason": "Nie pasuje praca w biurze",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == [junior["id"]]


@needs_db
@pytest.mark.asyncio
async def test_list_never_drops_newest_or_active_when_truncated():
    from app.core.database import AsyncSessionLocal
    from app.models.academy import AcademyApplication, AcademyProgram
    from app.services import academy as svc

    async with AsyncSessionLocal() as db:
        program = AcademyProgram(name=f"Limit {uuid.uuid4().hex[:6]}")
        db.add(program)
        await db.flush()
        base = _now() - timedelta(days=100)
        people: dict[str, int] = {}
        for key, status, days in (
            ("old_rejected", "rejected", 0),
            ("old_active", "to_call", 1),
            ("mid_rejected", "rejected", 50),
            ("newest", "new", 99),
        ):
            cand = await _candidate(db)
            row = AcademyApplication(
                program_id=program.id,
                candidate_id=cand.id,
                applied_at=base + timedelta(days=days),
                status=status,
                closed_reason="powód" if status == "rejected" else None,
            )
            db.add(row)
            await db.flush()
            people[key] = row.id
        await db.commit()

        items, total = await svc.list_applications(db, program.id, limit=3)
        shown = [i["id"] for i in items]
        assert total == 4
        # W toku pierwsi, w grupie najnowsi pierwsi; odpada najstarszy zamknięty.
        assert shown == [people["newest"], people["old_active"], people["mid_rejected"]]

        items, total = await svc.list_applications(db, program.id)
        assert total == len(items) == 4
