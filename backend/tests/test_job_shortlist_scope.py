"""Zakres oferty na shortliście — pięć tras, obie strony bramki (P2-13).

#984 dołożył ``ensure_job_membership`` do pięciu istniejących wcześniej tras
shortlisty. Bramka nie miała ŻADNEGO testu: ``test_job_shortlist.py`` jest
czysto pydanticowy, a kontrakt ``test_job_scope_contract.py`` obejmuje tylko
``_SCOPED_MODULES`` (candidate_stage_cv / interview_feedback /
application_submissions), więc ``app.api.job_shortlist`` nie był w nim
sprawdzany. Nic nie asertowało zachowania bramki w żadną stronę — ani że obcy
dostaje 403, ani że członek zespołu dalej przechodzi. Fail-closed bez testu na
stronę „wolno" to gotowy sposób na ciche zaoranie roboczego przepływu.

Ten plik zamyka obie strony. Od 23.09.2026 (decyzja Artura: „wszystko
w rekrutacji widzi i robi każdy, nie musisz być przypisany") bramka zespołu
przepuszcza każdą rolę wewnętrzną:
- rekruter spoza zespołu przechodzi przez wszystkie pięć tras i jego zapis
  zostaje w bazie,
- członek zespołu, aktywny współpracownik i admin → przechodzą,
- stara rola podglądu ``user`` → 403 bez śladu zapisu.
Test „odznaczony współpracownik → 403" usunięty 23.09.2026: dla ról
wewnętrznych przypisanie przestało decydować o dostępie.

Cięższy bliźniak z tego samego ekranu, ``POST /api/jobs/{job_id}/proposals/bulk``,
ma tę samą bramkę (``app/api/proposals_bulk.py``, ``bulk_add_proposals``) —
test niżej pilnuje, że obie trasy odpowiadają rekruterowi spoza zespołu tak samo.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_shortlist import JobShortlistEntry
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _new_user(db, role: UserRole = UserRole.recruiter) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"slscope-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"SL Scope {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, pwd


async def _new_job(db, *, recruiter_id: int) -> Job:
    suffix = uuid.uuid4().hex[:6]
    client = Client(name=f"SLScope Client {suffix}")
    db.add(client)
    await db.flush()
    job = Job(
        title=f"SLScope Job {suffix}",
        client_id=client.id,
        recruiter_id=recruiter_id,
        status=JobStatus.published,
    )
    db.add(job)
    await db.flush()
    return job


async def _new_candidate(db) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    candidate = Candidate(
        name="SL",
        lastname=f"Scope-{suffix}",
        email=f"slscope-cand-{suffix}@example.com",
        status=CandidateStatus.active,
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def _new_entry(db, *, job_id: int, candidate_id: int, created_by: int) -> int:
    entry = JobShortlistEntry(
        job_id=job_id,
        candidate_id=candidate_id,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(entry)
    await db.flush()
    return entry.id


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def shortlist_setup(app_client: AsyncClient) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        member, member_pwd = await _new_user(db)
        outsider, outsider_pwd = await _new_user(db)
        collaborator, collaborator_pwd = await _new_user(db)
        viewer, viewer_pwd = await _new_user(db, UserRole.user)
        job = await _new_job(db, recruiter_id=member.id)
        db.add(
            JobCollaborator(
                job_id=job.id,
                user_id=collaborator.id,
                source=JobCollaboratorSource.manual,
            )
        )
        candidate = await _new_candidate(db)
        entry_id = await _new_entry(
            db, job_id=job.id, candidate_id=candidate.id, created_by=member.id
        )
        second_candidate = await _new_candidate(db)
        await db.commit()
        data = {
            "member_email": member.email,
            "member_password": member_pwd,
            "outsider_email": outsider.email,
            "outsider_password": outsider_pwd,
            "collaborator_email": collaborator.email,
            "collaborator_password": collaborator_pwd,
            "viewer_email": viewer.email,
            "viewer_password": viewer_pwd,
            "outsider_id": outsider.id,
            "job_id": job.id,
            "candidate_id": candidate.id,
            "second_candidate_id": second_candidate.id,
            "entry_id": entry_id,
        }
    for actor in ("member", "outsider", "collaborator", "viewer"):
        data[f"{actor}_headers"] = await _login(
            app_client, data[f"{actor}_email"], data[f"{actor}_password"]
        )
    return data


async def _call_every_shortlist_route(
    app_client: AsyncClient,
    setup: dict[str, Any],
    headers: dict[str, str],
    *,
    candidate_id: Optional[int] = None,
) -> dict[str, int]:
    """Wszystkie pięć tras jednym przebiegiem — zwraca mapę nazwa → status."""
    job_id = setup["job_id"]
    entry_id = setup["entry_id"]
    add = await app_client.post(
        f"/api/jobs/{job_id}/shortlist",
        headers=headers,
        json={"candidate_ids": [candidate_id or setup["second_candidate_id"]]},
    )
    listing = await app_client.get(f"/api/jobs/{job_id}/shortlist", headers=headers)
    patch = await app_client.patch(
        f"/api/shortlist/{entry_id}",
        headers=headers,
        json={"version": 1, "evaluation_status": "potencjalny"},
    )
    promote = await app_client.post(
        f"/api/shortlist/{entry_id}/promote", headers=headers
    )
    delete = await app_client.delete(f"/api/shortlist/{entry_id}", headers=headers)
    return {
        "add": add.status_code,
        "list": listing.status_code,
        "patch": patch.status_code,
        "promote": promote.status_code,
        "delete": delete.status_code,
    }


async def _shortlisted(job_id: int) -> list[tuple[int, int | None]]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(JobShortlistEntry.candidate_id, JobShortlistEntry.created_by)
            .where(JobShortlistEntry.job_id == job_id)
            .order_by(JobShortlistEntry.id)
        )
        return [tuple(r) for r in rows.all()]


# ── Rekruter spoza zespołu (23.09.2026) ──────────────────────────────────────


async def test_outsider_passes_every_shortlist_route(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    statuses = await _call_every_shortlist_route(
        app_client, shortlist_setup, shortlist_setup["outsider_headers"]
    )
    assert all(code < 400 for code in statuses.values()), statuses


async def test_outsider_write_is_saved(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    """Zapis rekrutera spoza zespołu ląduje na shortliście z jego podpisem."""
    resp = await app_client.post(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist",
        headers=shortlist_setup["outsider_headers"],
        json={"candidate_ids": [shortlist_setup["second_candidate_id"]]},
    )
    assert resp.status_code == 200, resp.text
    rows = await _shortlisted(shortlist_setup["job_id"])
    assert [cid for cid, _ in rows] == [
        shortlist_setup["candidate_id"],
        shortlist_setup["second_candidate_id"],
    ]
    assert rows[-1][1] == shortlist_setup["outsider_id"]


async def test_legacy_viewer_is_denied_without_a_trace(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    """Stara rola podglądu ``user`` nadal nie dotyka shortlisty — 403 przed zapisem."""
    listing = await app_client.get(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist",
        headers=shortlist_setup["viewer_headers"],
    )
    assert listing.status_code == 403, listing.text
    add = await app_client.post(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist",
        headers=shortlist_setup["viewer_headers"],
        json={"candidate_ids": [shortlist_setup["second_candidate_id"]]},
    )
    assert add.status_code == 403, add.text
    assert [cid for cid, _ in await _shortlisted(shortlist_setup["job_id"])] == [
        shortlist_setup["candidate_id"]
    ]


# ── Strona „wolno" ───────────────────────────────────────────────────────────


async def test_job_owner_passes_every_shortlist_route(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    statuses = await _call_every_shortlist_route(
        app_client, shortlist_setup, shortlist_setup["member_headers"]
    )
    assert all(code < 400 for code in statuses.values()), statuses


async def test_active_collaborator_passes_the_gate(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    listing = await app_client.get(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist",
        headers=shortlist_setup["collaborator_headers"],
    )
    assert listing.status_code == 200, listing.text
    add = await app_client.post(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist",
        headers=shortlist_setup["collaborator_headers"],
        json={"candidate_ids": [shortlist_setup["second_candidate_id"]]},
    )
    assert add.status_code == 200, add.text


async def test_admin_oversight_passes_the_gate(
    app_client: AsyncClient, shortlist_setup: dict[str, Any], app_auth_headers
) -> None:
    listing = await app_client.get(
        f"/api/jobs/{shortlist_setup['job_id']}/shortlist", headers=app_auth_headers
    )
    assert listing.status_code == 200, listing.text


async def test_missing_job_is_404_not_403(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    """Nieistniejąca oferta nie może udawać „nie należysz do zespołu"."""
    resp = await app_client.get(
        "/api/jobs/999999999/shortlist", headers=shortlist_setup["member_headers"]
    )
    assert resp.status_code == 404, resp.text


# ── Cięższy bliźniak na tym samym ekranie ────────────────────────────────────
# Parkowanie na shortliście i wpisanie wprost do pipeline'u tej samej oferty
# odpowiadają rekruterowi spoza zespołu tak samo (od 23.09.2026: przepuszczają).


async def test_outsider_bulk_adds_to_the_pipeline_like_a_member(
    app_client: AsyncClient, shortlist_setup: dict[str, Any]
) -> None:
    from app.models.recruitment_pipeline import CandidateStage

    resp = await app_client.post(
        f"/api/jobs/{shortlist_setup['job_id']}/proposals/bulk",
        headers=shortlist_setup["outsider_headers"],
        json={"candidate_ids": [shortlist_setup["second_candidate_id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == [shortlist_setup["second_candidate_id"]]
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.job_id == shortlist_setup["job_id"],
                CandidateStage.candidate_id == shortlist_setup["second_candidate_id"],
            )
        )
    assert stage is not None
