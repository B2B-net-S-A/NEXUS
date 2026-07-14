"""Parity and validation tests for POST /api/candidates/export."""

from __future__ import annotations

import csv
import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


async def _seed_candidate(
    cohort: str,
    *,
    suffix: str,
    status: CandidateStatus = CandidateStatus.active,
    open_to_side_projects: bool = False,
    changed_at: datetime | None = None,
    preferences: dict | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=cohort,
            lastname=suffix,
            email=f"{cohort.lower()}-{suffix.lower()}@example.com",
            status=status,
            open_to_side_projects=open_to_side_projects,
            linkedin_employment_changed_at=changed_at,
            preferences=preferences,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


async def _seed_recruitment(candidate_id: int) -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ExportClient-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"ExportJob-{uuid.uuid4().hex[:8]}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job.id,
                stage=PipelineStage.screening,
            )
        )
        await db.commit()
        return job.id, client.id


async def _cleanup(
    candidate_ids: list[int],
    *,
    job_id: int | None = None,
    client_id: int | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(candidate_ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if job_id is not None:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == job_id)
            )
            await db.execute(delete(Job).where(Job.id == job_id))
        if client_id is not None:
            await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _csv_ids(response) -> set[int]:
    return {int(row["id"]) for row in csv.DictReader(io.StringIO(response.text))}


def _csv_ids_in_order(response) -> list[int]:
    return [int(row["id"]) for row in csv.DictReader(io.StringIO(response.text))]


async def _assert_parity(
    app_client: AsyncClient,
    headers: dict,
    *,
    query_params: list[tuple[str, str]],
    filters: dict,
) -> set[int]:
    list_response = await app_client.get(
        "/api/candidates",
        params=[*query_params, ("page_size", "100")],
        headers=headers,
    )
    assert list_response.status_code == 200, list_response.text
    list_ids = {item["id"] for item in list_response.json()["items"]}

    export_response = await app_client.post(
        "/api/candidates/export",
        json={
            "format": "csv",
            "scope": "filtered",
            "filters": filters,
            "candidate_ids": [],
            "limit": 100_000,
        },
        headers=headers,
    )
    assert export_response.status_code == 200, export_response.text
    assert _csv_ids(export_response) == list_ids
    return list_ids


@pytest.mark.asyncio
async def test_filtered_export_status_and_search_match_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportParity{uuid.uuid4().hex[:12]}"
    active = await _seed_candidate(cohort, suffix="Active")
    passive = await _seed_candidate(
        cohort, suffix="Passive", status=CandidateStatus.passive
    )
    try:
        ids = await _assert_parity(
            app_client,
            app_auth_headers,
            query_params=[("q", cohort), ("status", "active")],
            filters={"q": cohort, "status": ["active"]},
        )
        assert ids == {active}
        assert passive not in ids
    finally:
        await _cleanup([active, passive])


@pytest.mark.asyncio
async def test_filtered_export_open_to_matches_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportOpenTo{uuid.uuid4().hex[:12]}"
    open_candidate = await _seed_candidate(
        cohort, suffix="Open", open_to_side_projects=True
    )
    closed_candidate = await _seed_candidate(cohort, suffix="Closed")
    try:
        ids = await _assert_parity(
            app_client,
            app_auth_headers,
            query_params=[("q", cohort), ("open_to", "side_projects")],
            filters={"q": cohort, "open_to": ["side_projects"]},
        )
        assert ids == {open_candidate}
        assert closed_candidate not in ids
    finally:
        await _cleanup([open_candidate, closed_candidate])


@pytest.mark.asyncio
async def test_filtered_export_recent_job_change_matches_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportRecent{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    recent = await _seed_candidate(
        cohort, suffix="Recent", changed_at=now - timedelta(days=5)
    )
    old = await _seed_candidate(
        cohort, suffix="Old", changed_at=now - timedelta(days=100)
    )
    try:
        ids = await _assert_parity(
            app_client,
            app_auth_headers,
            query_params=[("q", cohort), ("recently_changed_jobs", "1")],
            filters={"q": cohort, "recently_changed_jobs": 1},
        )
        assert ids == {recent}
        assert old not in ids
    finally:
        await _cleanup([recent, old])


@pytest.mark.asyncio
async def test_filtered_export_recruitment_matches_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportRecruitment{uuid.uuid4().hex[:12]}"
    member = await _seed_candidate(cohort, suffix="Member")
    outsider = await _seed_candidate(cohort, suffix="Outsider")
    job_id, client_id = await _seed_recruitment(member)
    try:
        ids = await _assert_parity(
            app_client,
            app_auth_headers,
            query_params=[("q", cohort), ("recruitment_id", str(job_id))],
            filters={"q": cohort, "recruitment_id": [job_id]},
        )
        assert ids == {member}
        assert outsider not in ids
    finally:
        await _cleanup([member, outsider], job_id=job_id, client_id=client_id)


@pytest.mark.asyncio
async def test_filtered_export_boolean_search_matches_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportBoolean{uuid.uuid4().hex[:12]}"
    python = await _seed_candidate(cohort, suffix="Python")
    java = await _seed_candidate(cohort, suffix="Java")
    blocked = await _seed_candidate(cohort, suffix="PythonBlocked")
    try:
        ids = await _assert_parity(
            app_client,
            app_auth_headers,
            query_params=[
                ("q_all", cohort),
                ("q_any_group", "Python|Java"),
                ("q_none", "Blocked"),
            ],
            filters={
                "q_all": [cohort],
                "q_any_group": ["Python|Java"],
                "q_none": ["Blocked"],
            },
        )
        assert ids == {python, java}
        assert blocked not in ids
    finally:
        await _cleanup([python, java, blocked])


@pytest.mark.asyncio
async def test_filtered_export_remote_and_sort_order_match_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportSort{uuid.uuid4().hex[:12]}"
    second = await _seed_candidate(
        cohort, suffix="Zulu", preferences={"remote_modes": ["remote"]}
    )
    first = await _seed_candidate(
        cohort, suffix="Alpha", preferences={"remote_modes": ["remote"]}
    )
    onsite = await _seed_candidate(
        cohort, suffix="Onsite", preferences={"remote_modes": ["onsite"]}
    )
    try:
        list_response = await app_client.get(
            "/api/candidates",
            params=[
                ("q", cohort),
                ("remote_policy", "remote"),
                ("sort", "name"),
                ("page_size", "100"),
            ],
            headers=app_auth_headers,
        )
        assert list_response.status_code == 200, list_response.text
        list_ids = [item["id"] for item in list_response.json()["items"]]

        export_response = await app_client.post(
            "/api/candidates/export",
            json={
                "format": "csv",
                "scope": "filtered",
                "filters": {
                    "q": cohort,
                    "remote_policy": ["remote"],
                    "sort": "name",
                },
                "candidate_ids": [],
                "limit": 100_000,
            },
            headers=app_auth_headers,
        )
        assert export_response.status_code == 200, export_response.text
        assert list_ids == [first, second]
        assert _csv_ids_in_order(export_response) == list_ids
        assert onsite not in list_ids
    finally:
        await _cleanup([first, second, onsite])


@pytest.mark.asyncio
async def test_selected_export_deduplicates_ids_and_supports_xlsx(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportSelected{uuid.uuid4().hex[:12]}"
    first = await _seed_candidate(cohort, suffix="First")
    second = await _seed_candidate(cohort, suffix="Second")
    try:
        payload = {
            "scope": "selected",
            "filters": {},
            "candidate_ids": [first, first, second],
            "limit": 1,
        }
        csv_response = await app_client.post(
            "/api/candidates/export",
            json={**payload, "format": "csv"},
            headers=app_auth_headers,
        )
        assert csv_response.status_code == 200, csv_response.text
        assert _csv_ids(csv_response) == {first, second}

        xlsx_response = await app_client.post(
            "/api/candidates/export",
            json={**payload, "format": "xlsx"},
            headers=app_auth_headers,
        )
        assert xlsx_response.status_code == 200, xlsx_response.text
        assert xlsx_response.content[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(xlsx_response.content)) as archive:
            assert archive.testzip() is None
            assert "xl/worksheets/sheet1.xml" in archive.namelist()
    finally:
        await _cleanup([first, second])


@pytest.mark.asyncio
async def test_export_validation_and_filtered_limit(
    app_client: AsyncClient, app_auth_headers: dict
):
    empty_selected = await app_client.post(
        "/api/candidates/export",
        json={"scope": "selected", "filters": {}, "candidate_ids": []},
        headers=app_auth_headers,
    )
    assert empty_selected.status_code == 422

    filtered_with_ids = await app_client.post(
        "/api/candidates/export",
        json={"scope": "filtered", "filters": {}, "candidate_ids": [1]},
        headers=app_auth_headers,
    )
    assert filtered_with_ids.status_code == 422

    cohort = f"ExportLimit{uuid.uuid4().hex[:12]}"
    first = await _seed_candidate(cohort, suffix="First")
    second = await _seed_candidate(cohort, suffix="Second")
    try:
        limited = await app_client.post(
            "/api/candidates/export",
            json={
                "scope": "filtered",
                "filters": {"q": cohort},
                "candidate_ids": [],
                "limit": 1,
            },
            headers=app_auth_headers,
        )
        assert limited.status_code == 422
        assert "exceeding limit 1" in limited.json()["detail"]
    finally:
        await _cleanup([first, second])


@pytest.mark.asyncio
async def test_legacy_get_export_remains_available(
    app_client: AsyncClient, app_auth_headers: dict
):
    response = await app_client.get(
        "/api/candidates/export?format=csv&limit=1",
        headers=app_auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0].startswith("id,name,lastname,email")
