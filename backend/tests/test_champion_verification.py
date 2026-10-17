"""Tests for the Champion Profile two-sided verification.

Covers:
  - validation rules (delta-or-confirm for the client side, reason for skip,
    insights required for the consultant side),
  - server-side stamping of who/when,
  - the PUT champion-profile endpoint preserving stored verification,
  - the consultant-suggestions endpoint (the „Pracuje u nas” rule at this
    client, scalone rekordy klienta, no per-source cap).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def _seed_client_and_job():
    """Seed a minimal client + job directly through the DB."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="VerifClient Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(
            title="Senior Java Developer",
            client_id=client.id,
            description="",
            requirements="",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return client.id, job.id


async def _seed_hired_candidate(client_id: int, *, lastname: str = "Konsultant"):
    """Seed a candidate whose LATEST stage is `hired` on a job of `client_id`."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        job = Job(
            title="Java Developer (placed)",
            client_id=client_id,
            description="",
            requirements="",
        )
        candidate = Candidate(name="Janina", lastname=lastname)
        db.add_all([job, candidate])
        await db.flush()
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.hired,
            moved_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(stage)
        await db.commit()
        return candidate.id


@pytest.mark.asyncio
async def test_client_verification_requires_delta_or_confirmation(
    app_client, app_auth_headers
):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {
                "method": "call",
                "key_corrections": "  ",
                "confirmed_as_is": False,
            },
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "request" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_client_verification_happy_path_stamps_actor(
    app_client, app_auth_headers
):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {
                "method": "meeting",
                "key_corrections": "Klient pisał Java 8, realnie migrują na 17.",
                "confirmed_as_is": False,
            },
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    verification = resp.json()["champion_profile"]["verification"]
    assert verification["client"]["status"] == "verified"
    assert verification["client"]["verified_by_id"] is not None
    assert verification["client"]["verified_by_name"]
    assert verification["client"]["verified_at"]
    assert verification["client"]["method"] == "meeting"
    assert verification["consultant"]["status"] == "pending"


@pytest.mark.asyncio
async def test_consultant_skip_requires_reason(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={"side": "consultant", "consultant": {"skipped": True, "skip_reason": ""}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_consultant_verification_requires_insights(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "consultant",
            "consultant": {"consultant_name": "Jan Kowalski", "insights": "   "},
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_consultant_verification_resolves_candidate_name(
    app_client, app_auth_headers
):
    client_id, job_id = await _seed_client_and_job()
    consultant_id = await _seed_hired_candidate(client_id, lastname="Nowakowska")
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "consultant",
            "consultant": {
                "consultant_candidate_id": consultant_id,
                "insights": "Dużo legacy, standupy po angielsku, realnie 3 dni z biura.",
            },
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    consultant = resp.json()["champion_profile"]["verification"]["consultant"]
    assert consultant["status"] == "verified"
    assert consultant["consultant_candidate_id"] == consultant_id
    assert consultant["consultant_name"] == "Janina Nowakowska"


@pytest.mark.asyncio
async def test_put_profile_preserves_verification(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    verify = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {
                "method": "call",
                "key_corrections": "x",
                "confirmed_as_is": True,
            },
        },
        headers=app_auth_headers,
    )
    assert verify.status_code == 200

    # A regular profile save (even one trying to forge/clear verification)
    # must not touch the stored block.
    put = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "sourcing": {
                "sources": ["linkedin"],
                "keywords": "kafka",
                "target_companies": "",
                "notes": "",
            },
            "verification": {
                "client": {
                    "status": "pending",
                    "key_corrections": "",
                    "confirmed_as_is": False,
                },
                "consultant": {
                    "status": "verified",
                    "insights": "forged",
                    "skip_reason": "",
                },
            },
        },
        headers=app_auth_headers,
    )
    assert put.status_code == 200
    verification = put.json()["champion_profile"]["verification"]
    assert verification["client"]["status"] == "verified"
    assert verification["consultant"]["status"] == "pending"

    got = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile", headers=app_auth_headers
    )
    assert (
        got.json()["champion_profile"]["verification"]["client"]["status"] == "verified"
    )


@pytest.mark.asyncio
async def test_verification_reset(app_client, app_auth_headers):
    _, job_id = await _seed_client_and_job()
    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={
            "side": "client",
            "client": {
                "method": "call",
                "key_corrections": "y",
                "confirmed_as_is": False,
            },
        },
        headers=app_auth_headers,
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/verification",
        json={"side": "client", "reset": True},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    client_v = resp.json()["champion_profile"]["verification"]["client"]
    assert client_v["status"] == "pending"
    assert client_v["verified_by_id"] is None


@pytest.mark.asyncio
async def test_consultant_suggestions_skip_a_hire_without_a_contract(
    app_client, app_auth_headers
):
    """17.10.2026: „Pracuje u nas” wyłącznie z umowy — karta „Zatrudniony”
    bez umowy nie trafia na listę (okno i tak szuka w całej bazie)."""
    client_id, job_id = await _seed_client_and_job()
    consultant_id = await _seed_hired_candidate(client_id, lastname="Hirowana")

    resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/consultant-suggestions",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert consultant_id not in {r["candidate_id"] for r in resp.json()}


async def _seed_consultants_at_client(client_id: int, job_id: int) -> dict:
    """Konsultanci u klienta rekrutacji — każdy przypadek, który 14.10.2026
    gubił albo dokładał listę „Nasi konsultanci u tego klienta”."""
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    today = business_today()
    async with AsyncSessionLocal() as db:
        duplicate = Client(
            name=f"VerifClient duplikat {tag}", merged_into_client_id=client_id
        )
        db.add(duplicate)
        await db.flush()

        def person(name: str) -> Candidate:
            candidate = Candidate(
                name=name,
                lastname=f"Kons-{tag}",
                email=f"kons-{uuid.uuid4().hex[:10]}@example.com",
            )
            db.add(candidate)
            return candidate

        def contract(candidate: Candidate, status: ContractStatus, **kw) -> None:
            db.add(
                Contract(
                    candidate_id=candidate.id,
                    client_id=kw.pop("client_id", client_id),
                    start_date=today - timedelta(days=400),
                    status=status,
                    **kw,
                )
            )

        # Ponad 30 osób z umową: dawniej lista ucinała umowy na 30
        # w przypadkowej kolejności.
        many = [person(f"Osoba{i:02d}") for i in range(32)]
        polish = person("Łucja")
        ending = person("Wypowiedziany")
        on_duplicate = person("Duplikat")
        former = person("Byly")
        ended = person("Zakonczony")
        await db.flush()
        for candidate in [*many, polish]:
            contract(candidate, ContractStatus.active)
        contract(ending, ContractStatus.ending)
        contract(on_duplicate, ContractStatus.active, client_id=duplicate.id)
        contract(
            former,
            ContractStatus.ended,
            end_date=today - timedelta(days=200),
            terminated_at=today - timedelta(days=200),
        )
        db.add(
            CandidateStage(
                candidate_id=former.id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=datetime.now(timezone.utc) - timedelta(days=380),
            )
        )
        contract(ended, ContractStatus.ended, end_date=today - timedelta(days=10))
        await db.commit()
        return {
            "many": [c.id for c in many],
            "ending": ending.id,
            "on_duplicate": on_duplicate.id,
            "former": former.id,
            "ended": ended.id,
        }


@pytest.mark.asyncio
async def test_consultant_suggestions_follow_the_working_with_us_rule(
    app_client, app_auth_headers
):
    """Zgłoszenie Marcina 14.10.2026: „miałem do wyboru z 20, a nie ma tego,
    z którym rozmawiałem”. Lista ma liczyć to samo co znacznik „Pracuje
    u nas”: wszystkie żywe umowy (także wypowiedziane), scalone rekordy
    klienta, bez byłych konsultantów i bez limitu 30 na źródło."""
    client_id, job_id = await _seed_client_and_job()
    world = await _seed_consultants_at_client(client_id, job_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile/consultant-suggestions",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    ids = [r["candidate_id"] for r in rows]

    assert set(world["many"]) <= set(ids)
    assert world["ending"] in ids
    assert world["on_duplicate"] in ids
    assert world["former"] not in ids
    assert world["ended"] not in ids
    assert len(ids) == len(set(ids))
    # Alfabetycznie — okno szuka po nazwisku, kolejność ma być przewidywalna;
    # „Łucja” stoi między „L” a „M”, nie za „Z”.
    names = [r["name"] for r in rows]
    assert names[0].startswith("Duplikat")
    assert names[1].startswith("Łucja")
    assert names[2].startswith("Osoba00")
    assert names[-1].startswith("Wypowiedziany")
