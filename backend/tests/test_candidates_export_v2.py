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

    too_many_unique = await app_client.post(
        "/api/candidates/export",
        json={
            "scope": "selected",
            "filters": {},
            "candidate_ids": list(range(1, 10_002)),
        },
        headers=app_auth_headers,
    )
    assert too_many_unique.status_code == 422

    deduplicated_before_limit = await app_client.post(
        "/api/candidates/export",
        json={
            "format": "csv",
            "scope": "selected",
            "filters": {},
            "candidate_ids": [9_999_999] * 10_001,
        },
        headers=app_auth_headers,
    )
    assert deduplicated_before_limit.status_code == 422
    assert "do not exist" in deduplicated_before_limit.json()["detail"]

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


def _xlsx_ids(response) -> set[int]:
    """Read the first sheet without depending on openpyxl's read-side API."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(response.content), read_only=True)
    sheet = workbook.worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == tuple(_expected_export_header())
    return {int(row[0]) for row in rows[1:]}


def _expected_export_header() -> list[str]:
    from app.api.candidates import _EXPORT_COLUMNS

    return list(_EXPORT_COLUMNS)


@pytest.mark.asyncio
async def test_xlsx_export_is_built_off_the_event_loop_on_both_routes(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """GET i POST budują arkusz przez `asyncio.to_thread`, ten sam pomocnik.

    Do 09.2026 `GET /api/candidates/export` ładował do 50k pełnych wierszy ORM
    i wołał `Workbook().save()` na pętli zdarzeń; POST miał `write_only`, ale
    `save()` też blokował pętlę. Test zlicza wywołania `to_thread` z naszym
    builderem i sprawdza, że obie trasy oddają identyczny zbiór wierszy.
    """
    import asyncio as _asyncio

    from app.api import candidates as candidates_api

    threaded: list[str] = []
    original_to_thread = _asyncio.to_thread

    async def _spy(func, /, *args, **kwargs):
        if func is candidates_api._build_xlsx_bytes:
            threaded.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(candidates_api.asyncio, "to_thread", _spy)

    cohort = f"ExportXlsx{uuid.uuid4().hex[:12]}"
    first = await _seed_candidate(cohort, suffix="One")
    second = await _seed_candidate(cohort, suffix="Two")
    try:
        posted = await app_client.post(
            "/api/candidates/export",
            json={
                "format": "xlsx",
                "scope": "filtered",
                "filters": {"q": cohort},
                "candidate_ids": [],
                "limit": 100_000,
            },
            headers=app_auth_headers,
        )
        assert posted.status_code == 200, posted.text
        assert posted.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert _xlsx_ids(posted) == {first, second}

        legacy = await app_client.get(
            "/api/candidates/export",
            params={"format": "xlsx", "q": cohort},
            headers=app_auth_headers,
        )
        assert legacy.status_code == 200, legacy.text
        assert _xlsx_ids(legacy) == {first, second}
        assert 'filename="candidates_' in legacy.headers["content-disposition"]

        assert threaded == ["_build_xlsx_bytes", "_build_xlsx_bytes"]
    finally:
        await _cleanup([first, second])


@pytest.mark.asyncio
async def test_legacy_get_csv_export_streams_the_same_rows_as_post(
    app_client: AsyncClient, app_auth_headers: dict
):
    cohort = f"ExportGetCsv{uuid.uuid4().hex[:12]}"
    first = await _seed_candidate(cohort, suffix="One")
    second = await _seed_candidate(cohort, suffix="Two")
    try:
        legacy = await app_client.get(
            "/api/candidates/export",
            params={"format": "csv", "q": cohort, "limit": 100},
            headers=app_auth_headers,
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.headers["content-type"].startswith("text/csv")
        assert _csv_ids(legacy) == {first, second}
    finally:
        await _cleanup([first, second])


@pytest.mark.asyncio
async def test_filtered_export_follows_match_order_like_the_list(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
):
    """Runda 6 audytu (M4): eksport „z filtra” przy ``sort=match`` ma tę samą
    kolejność co lista (``candidate_match_order``), a nie „najnowsi”."""
    from app.core.config import settings
    from app.services import candidate_match_order

    cohort = f"ExportMatch{uuid.uuid4().hex[:12]}"
    first = await _seed_candidate(cohort, suffix="A")
    second = await _seed_candidate(cohort, suffix="B")
    third = await _seed_candidate(cohort, suffix="C")
    # Kolejność „dopasowania” celowo inna niż created_at (najnowsi = C, B, A).
    match_order = (second, first, third)

    async def fake_ordered_ids(db, user, filters, ids_query, q_any_groups, prefix):
        return match_order

    monkeypatch.setattr(settings, "CANDIDATE_MATCH_SORT", True)
    monkeypatch.setattr(candidate_match_order, "ordered_ids", fake_ordered_ids)
    try:
        response = await app_client.post(
            "/api/candidates/export",
            json={
                "format": "csv",
                "scope": "filtered",
                "filters": {"q": cohort, "sort": "match"},
                "candidate_ids": [],
                "limit": 100_000,
            },
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        assert _csv_ids_in_order(response) == list(match_order)
    finally:
        await _cleanup([first, second, third])
