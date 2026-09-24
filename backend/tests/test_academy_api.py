"""Akademia — przepływ przez API na prawdziwej bazie (0369).

Kontrakty (decyzje Artura 23–24.09.2026):

- ludzie z ogłoszeń-źródeł wpadają sami; Luna sortuje, ale nikogo nie odrzuca;
- „nie” klika człowiek i ta decyzja jest pamiętana NA ZAWSZE: kolejna
  aplikacja tej osoby tylko stempluje ``reapplied_at`` i Luna nie czyta CV;
- osoba, która sama zrezygnowała, przy kolejnym zgłoszeniu wraca na początek;
- termin w biurze ma limit miejsc;
- ustawienia programu zmienia admin albo Head of Recruitment.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własny program,
rekrutację i kandydatów i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

NOW = datetime.now(timezone.utc)


async def _user(db, role: str):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"academy-{marker}@example.com",
        name=f"Akademia {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _job(db):
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    marker = uuid.uuid4().hex[:10]
    client = Client(name=f"academy-client-{marker}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"Akademia Rekrutera {marker}",
        client_id=client.id,
        status=JobStatus("published"),
    )
    db.add(job)
    await db.flush()
    return job


async def _candidate(db, **kw):
    from app.models.candidate import Candidate

    cand = Candidate(name="Ala", lastname=f"Ak{uuid.uuid4().hex[:8]}", **kw)
    db.add(cand)
    await db.flush()
    return cand


async def _apply(db, *, cand, job, at: datetime):
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    db.add(
        CandidateStage(
            candidate_id=cand.id, job_id=job.id, stage=PipelineStage("posting"), moved_at=at
        )
    )
    await db.flush()


def _headers(user_id: int, role: str) -> dict:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(subject=user_id, role=role)}"}


def _row(body: dict, application_id: int) -> dict:
    return next(r for r in body["items"] if r["id"] == application_id)


async def _setup(app_client):
    """Admin zakłada program ze źródłem; dwie osoby już zaaplikowały."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        admin = await _user(db, "admin")
        recruiter = await _user(db, "recruiter")
        job = await _job(db)
        junior = await _candidate(
            db,
            raw_cv_text="Magister psychologii 2024. Polski ojczysty.",
            education=[{"level": "master", "school": "UW", "year": 2024}],
            languages=[{"code": "PL", "lang": "polski", "level": "native"}],
        )
        senior = await _candidate(
            db,
            raw_cv_text="Licencjat 2010. Pracuję od 2010.",
            education=[{"level": "bachelor", "school": "UW", "year": 2010}],
            experience=[{"start": "2010-09", "end": "present", "role": "Manager"}],
            languages=[{"code": "PL", "lang": "polski", "level": "native"}],
        )
        old_applicant = await _candidate(db, raw_cv_text="stare zgłoszenie")
        await _apply(db, cand=junior, job=job, at=NOW - timedelta(days=2))
        await _apply(db, cand=senior, job=job, at=NOW - timedelta(days=1))
        await _apply(db, cand=old_applicant, job=job, at=NOW - timedelta(days=400))
        await db.commit()
        ids = {
            "admin": admin.id,
            "recruiter": recruiter.id,
            "job": job.id,
            "junior": junior.id,
            "senior": senior.id,
            "old": old_applicant.id,
        }

    admin_h = _headers(ids["admin"], "admin")
    resp = await app_client.post(
        "/api/academy/programs",
        headers=admin_h,
        json={
            "name": f"Akademia Rekrutera {uuid.uuid4().hex[:6]}",
            "conditions": ["Umowa zlecenie — pasuje?", "Praca w biurze — pasuje?"],
            "session_capacity": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    program_id = resp.json()["id"]
    since = (NOW - timedelta(days=30)).date().isoformat()
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/sources",
        headers=admin_h,
        json={"job_id": ids["job"], "since": since},
    )
    assert resp.status_code == 201, resp.text
    return program_id, ids


def _fake_luna(calls: list):
    def fake(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"polish": {"level": "unknown", "quote": ""}, "education": [], "work": []})

    return fake


async def _apps_by_candidate(app_client, program_id, headers) -> dict[int, dict]:
    resp = await app_client.get(
        f"/api/academy/programs/{program_id}/applications", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return {r["candidate_id"]: r for r in resp.json()["items"]}


@needs_db
@pytest.mark.asyncio
async def test_full_flow_luna_sorts_human_decides_and_rejection_is_forever(
    app_client, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.services import academy as svc

    calls: list[str] = []
    monkeypatch.setattr(svc, "_call_model", _fake_luna(calls))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")

    resp = await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["new"] == 2  # zgłoszenie sprzed `since` nie wpada

    apps = await _apps_by_candidate(app_client, program_id, rec_h)
    assert ids["old"] not in apps
    junior, senior = apps[ids["junior"]], apps[ids["senior"]]
    assert junior["status"] == "to_call"
    assert junior["screening_verdict"] == "call"
    # Luna odkłada, ale NIE odrzuca — osoba czeka na decyzję człowieka.
    assert senior["status"] == "new"
    assert senior["screening_verdict"] == "skip"
    assert len(calls) == 2

    # Termin z limitem 1 miejsca: druga osoba dostaje 409.
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/sessions",
        headers=rec_h,
        json={"starts_at": (NOW + timedelta(days=3)).isoformat()},
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    resp = await app_client.post(
        f"/api/academy/applications/{junior['id']}/actions",
        headers=rec_h,
        json={"action": "schedule", "session_id": session_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scheduled"

    # Człowiek zatwierdza odłożonych przez Lunę — powód z sortowania.
    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/applications/bulk",
        headers=rec_h,
        json={"ids": [senior["id"]], "action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == [senior["id"]]
    apps = await _apps_by_candidate(app_client, program_id, rec_h)
    assert apps[ids["senior"]]["status"] == "rejected"
    assert "limit 6 lat" in apps[ids["senior"]]["closed_reason"]

    # Ta sama osoba aplikuje ponownie za miesiąc: zostaje wykluczona,
    # Luna nie czyta jej CV drugi raz.
    async with AsyncSessionLocal() as db:
        from app.models.candidate import Candidate
        from app.models.job import Job

        await _apply(
            db,
            cand=await db.get(Candidate, ids["senior"]),
            job=await db.get(Job, ids["job"]),
            at=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        await db.commit()
    calls_before = len(calls)
    resp = await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["reapplied"] == 1
    apps = await _apps_by_candidate(app_client, program_id, rec_h)
    assert apps[ids["senior"]]["status"] == "rejected"
    assert apps[ids["senior"]]["reapplied_at"] is not None
    assert len(calls) == calls_before

    # Dokumentów nie ma przed zaliczonym zadaniem.
    early = await app_client.post(
        f"/api/academy/applications/{junior['id']}/documents", headers=rec_h, json={}
    )
    assert early.status_code == 409

    # Dalej: zadanie → zaliczone → dokumenty → podpis = edycja od 1. dnia miesiąca.
    for action in ("give_task", "task_passed"):
        resp = await app_client.post(
            f"/api/academy/applications/{junior['id']}/actions",
            headers=rec_h,
            json={"action": action},
        )
        assert resp.status_code == 200, (action, resp.text)
    bad = await app_client.post(
        f"/api/academy/applications/{junior['id']}/documents",
        headers=rec_h,
        json={"pesel": "12345678901"},
    )
    assert bad.status_code == 422
    package = await app_client.post(
        f"/api/academy/applications/{junior['id']}/documents",
        headers=rec_h,
        json={"signing_date": "2026-10-20", "handover_name": "Jan Rekruter"},
    )
    assert package.status_code == 200, package.text
    assert package.headers["content-type"] == "application/zip"
    import io
    import zipfile

    assert len(zipfile.ZipFile(io.BytesIO(package.content)).namelist()) == 5

    for action in ("signed",):
        resp = await app_client.post(
            f"/api/academy/applications/{junior['id']}/actions",
            headers=rec_h,
            json={"action": action},
        )
        assert resp.status_code == 200, (action, resp.text)
    body = resp.json()
    assert body["status"] == "signed"
    assert body["cohort_month"].endswith("-01")


@needs_db
@pytest.mark.asyncio
async def test_session_capacity_and_wrong_stage(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.services import academy as svc

    monkeypatch.setattr(svc, "_call_model", _fake_luna([]))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")

    # Druga osoba do telefonu, bez Luny: bezpośrednio „Dzwonimy”.
    async with AsyncSessionLocal() as db:
        extra = await _candidate(db, raw_cv_text="x")
        from app.models.job import Job

        await _apply(db, cand=extra, job=await db.get(Job, ids["job"]), at=NOW)
        await db.commit()
        extra_id = extra.id
    await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    apps = await _apps_by_candidate(app_client, program_id, rec_h)

    resp = await app_client.post(
        f"/api/academy/programs/{program_id}/sessions",
        headers=rec_h,
        json={"starts_at": (NOW + timedelta(days=5)).isoformat()},
    )
    session_id = resp.json()["id"]
    first = apps[ids["junior"]]
    second = apps[extra_id]
    if second["status"] == "new":
        resp = await app_client.post(
            f"/api/academy/applications/{second['id']}/actions",
            headers=rec_h,
            json={"action": "call"},
        )
        assert resp.status_code == 200, resp.text
    ok = await app_client.post(
        f"/api/academy/applications/{first['id']}/actions",
        headers=rec_h,
        json={"action": "schedule", "session_id": session_id},
    )
    assert ok.status_code == 200, ok.text
    full = await app_client.post(
        f"/api/academy/applications/{second['id']}/actions",
        headers=rec_h,
        json={"action": "schedule", "session_id": session_id},
    )
    assert full.status_code == 409, full.text
    assert full.json()["detail"]["code"] == "session_full"

    wrong = await app_client.post(
        f"/api/academy/applications/{first['id']}/actions",
        headers=rec_h,
        json={"action": "signed"},
    )
    assert wrong.status_code == 409
    assert wrong.json()["detail"]["code"] == "wrong_stage"


@needs_db
@pytest.mark.asyncio
async def test_person_who_withdrew_returns_on_next_application(app_client, monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.services import academy as svc

    monkeypatch.setattr(svc, "_call_model", _fake_luna([]))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")
    await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    junior = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["junior"]]

    resp = await app_client.post(
        f"/api/academy/applications/{junior['id']}/actions",
        headers=rec_h,
        json={"action": "withdraw", "reason": "Znalazł pracę"},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        from app.models.candidate import Candidate
        from app.models.job import Job

        await _apply(
            db,
            cand=await db.get(Candidate, ids["junior"]),
            job=await db.get(Job, ids["job"]),
            at=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        await db.commit()
    resp = await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    assert resp.json()["returned"] == 1
    again = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["junior"]]
    assert again["status"] in ("new", "to_call")
    assert again["closed_reason"] is None


@needs_db
@pytest.mark.asyncio
async def test_only_admin_or_head_of_recruitment_manage_programs(app_client):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        await db.commit()
        rid = recruiter.id
    resp = await app_client.post(
        "/api/academy/programs",
        headers=_headers(rid, "recruiter"),
        json={"name": "Akademia bez uprawnień"},
    )
    assert resp.status_code == 403
    listing = await app_client.get("/api/academy/programs", headers=_headers(rid, "recruiter"))
    assert listing.status_code == 200
    assert listing.json()["can_manage"] is False


@needs_db
@pytest.mark.asyncio
async def test_reject_without_reason_is_refused(app_client, monkeypatch):
    from app.services import academy as svc

    monkeypatch.setattr(svc, "_call_model", _fake_luna([]))
    program_id, ids = await _setup(app_client)
    rec_h = _headers(ids["recruiter"], "recruiter")
    await app_client.post(f"/api/academy/programs/{program_id}/sync", headers=rec_h)
    junior = (await _apps_by_candidate(app_client, program_id, rec_h))[ids["junior"]]
    resp = await app_client.post(
        f"/api/academy/applications/{junior['id']}/actions",
        headers=rec_h,
        json={"action": "reject", "reason": "  "},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "reason_required"
