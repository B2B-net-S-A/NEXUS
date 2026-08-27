"""Focused contracts for the process-focused recruitment operations API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.api import dashboard_v2 as dashboard_api
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import PipelineStage
from app.models.user import User, UserRole
from app.services import recruitment_operations as service


def _user(
    role: UserRole,
    *,
    user_id: int = 11,
    roles: list[UserRole] | None = None,
) -> User:
    all_roles = roles or [role]
    return User(
        id=user_id,
        email=f"operations-{role.value}-{user_id}@example.com",
        name=f"Operations {role.value}",
        role=role,
        roles=[item.value for item in all_roles],
        is_active=True,
        profile_completed=True,
    )


@pytest_asyncio.fixture
async def operations_client() -> AsyncIterator[tuple[AsyncClient, dict[str, User]]]:
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/dashboard/v2")
    context = {"user": _user(UserRole.user)}

    async def _current_user() -> User:
        return context["user"]

    async def _db() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client, context


async def _authorized(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=418, detail="authorized")


@pytest.mark.parametrize(
    ("role", "preset"),
    [
        (UserRole.admin, "admin-ops"),
        (UserRole.head_of_recruitment, "head-of-recruitment"),
        (UserRole.delivery_lead, "delivery-lead"),
        (UserRole.tac, "my-work"),
        (UserRole.recruiter, "my-work"),
        (UserRole.sourcer, "my-work"),
    ],
)
@pytest.mark.asyncio
async def test_operations_guard_allows_operational_roles(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
    preset: str,
) -> None:
    client, context = operations_client
    context["user"] = _user(role)
    monkeypatch.setattr(dashboard_api, "list_recruitment_operations", _authorized)

    response = await client.get(
        f"/api/dashboard/v2/recruitment-operations?preset={preset}"
    )

    assert response.status_code == 418
    assert response.json()["detail"] == "authorized"


@pytest.mark.parametrize("role", [UserRole.finance, UserRole.user])
@pytest.mark.asyncio
async def test_operations_guard_excludes_finance_and_viewer(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
) -> None:
    client, context = operations_client
    context["user"] = _user(role)
    monkeypatch.setattr(dashboard_api, "list_recruitment_operations", _authorized)

    response = await client.get(
        "/api/dashboard/v2/recruitment-operations?preset=admin-ops"
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_page_size_is_capped_at_one_hundred(
    operations_client: tuple[AsyncClient, dict[str, User]],
) -> None:
    client, context = operations_client
    context["user"] = _user(UserRole.admin)

    response = await client.get(
        "/api/dashboard/v2/recruitment-operations?preset=admin-ops&page_size=101"
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_detail_runs_membership_guard_before_service(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = operations_client
    context["user"] = _user(UserRole.recruiter)
    membership = AsyncMock()
    monkeypatch.setattr(dashboard_api, "ensure_job_membership", membership)
    monkeypatch.setattr(dashboard_api, "get_recruitment_operation_detail", _authorized)

    response = await client.get(
        "/api/dashboard/v2/recruitment-operations/91?preset=my-work"
    )

    assert response.status_code == 418
    membership.assert_awaited_once()
    assert membership.await_args.args[2] == 91
    assert membership.await_args.kwargs["oversight_bypass"] is False


@pytest.mark.asyncio
async def test_favorite_route_runs_membership_guard_before_service(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = operations_client
    context["user"] = _user(UserRole.recruiter)
    membership = AsyncMock()
    monkeypatch.setattr(dashboard_api, "ensure_job_membership", membership)
    monkeypatch.setattr(
        dashboard_api, "set_recruitment_operation_favorite", _authorized
    )

    response = await client.put(
        "/api/dashboard/v2/recruitment-operations/91/favorite?preset=my-work",
        json={"candidate_id": None},
    )

    assert response.status_code == 418
    membership.assert_awaited_once()
    assert membership.await_args.args[2] == 91
    assert membership.await_args.kwargs["oversight_bypass"] is False


@pytest.mark.asyncio
async def test_preset_is_required(
    operations_client: tuple[AsyncClient, dict[str, User]],
) -> None:
    client, context = operations_client
    context["user"] = _user(UserRole.admin)

    response = await client.get("/api/dashboard/v2/recruitment-operations")

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("role", "preset", "expected"),
    [
        (UserRole.admin, "admin-ops", 418),
        (UserRole.admin, "delivery-lead", 418),
        (UserRole.admin, "head-of-recruitment", 418),
        (UserRole.admin, "my-work", 418),
        (UserRole.head_of_recruitment, "admin-ops", 403),
        (UserRole.head_of_recruitment, "delivery-lead", 403),
        (UserRole.head_of_recruitment, "head-of-recruitment", 418),
        (UserRole.head_of_recruitment, "my-work", 403),
        (UserRole.delivery_lead, "delivery-lead", 418),
        (UserRole.delivery_lead, "my-work", 403),
        (UserRole.recruiter, "my-work", 418),
        (UserRole.recruiter, "head-of-recruitment", 403),
    ],
)
@pytest.mark.asyncio
async def test_preset_role_matrix(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
    preset: str,
    expected: int,
) -> None:
    client, context = operations_client
    context["user"] = _user(role)
    monkeypatch.setattr(dashboard_api, "list_recruitment_operations", _authorized)

    response = await client.get(
        f"/api/dashboard/v2/recruitment-operations?preset={preset}"
    )

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("roles", "preset"),
    [
        ([UserRole.head_of_recruitment, UserRole.recruiter], "my-work"),
        ([UserRole.head_of_recruitment, UserRole.delivery_lead], "delivery-lead"),
    ],
)
@pytest.mark.asyncio
async def test_hybrid_user_can_select_each_held_preset(
    operations_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    roles: list[UserRole],
    preset: str,
) -> None:
    client, context = operations_client
    context["user"] = _user(roles[0], roles=roles)
    monkeypatch.setattr(dashboard_api, "list_recruitment_operations", _authorized)

    response = await client.get(
        f"/api/dashboard/v2/recruitment-operations?preset={preset}"
    )

    assert response.status_code == 418


def test_stage_grouping_uses_canonical_operational_buckets() -> None:
    rows = [
        service._LatestStage(index, 1, stage)
        for index, stage in enumerate(
            [
                PipelineStage.new,
                PipelineStage.prep_call,
                PipelineStage.screening,
                PipelineStage.verified,
                PipelineStage.cv_sent,
                PipelineStage.interview,
                PipelineStage.client_interview,
                PipelineStage.acceptance,
                PipelineStage.negotiation,
                PipelineStage.onboarding,
                PipelineStage.hired,
            ],
            start=1,
        )
    ]

    assert service._stage_counts(rows).model_dump() == {
        "sourcing": 3,
        "verified": 1,
        "recommended": 1,
        "interview": 2,
        "accepted": 4,
    }


def test_current_stage_queries_use_the_canonical_analytics_view() -> None:
    sql = str(
        service._current_pipeline_subquery()
        .select()
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "analytics_current_pipeline" in sql
    assert "candidate_stages" not in sql


def test_hybrid_hor_my_work_scope_does_not_compile_to_global() -> None:
    user = _user(
        UserRole.head_of_recruitment,
        roles=[UserRole.head_of_recruitment, UserRole.recruiter],
    )
    my_work_sql = str(
        service.select(Job.id).where(
            *service._job_filters(
                user,
                scope=service._RecruitmentOperationsScope(preset="my-work"),
            )
        )
    )
    oversight_sql = str(
        service.select(Job.id).where(
            *service._job_filters(
                user,
                scope=service._RecruitmentOperationsScope(preset="head-of-recruitment"),
            )
        )
    )

    assert "jobs.recruiter_id =" in my_work_sql
    assert "job_collaborators" in my_work_sql
    assert "jobs.recruiter_id =" not in oversight_sql
    assert "job_collaborators" not in oversight_sql


def test_delivery_lead_scope_uses_exact_client_tac_pairs_only() -> None:
    user = _user(UserRole.delivery_lead)
    allowed_scope = service._RecruitmentOperationsScope(
        preset="delivery-lead",
        delivery_pairs=frozenset({(12, 34)}),
    )
    allowed_sql = str(
        service.select(Job.id)
        .where(*service._job_filters(user, scope=allowed_scope))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    denied_sql = str(
        service.select(Job.id)
        .where(
            *service._job_filters(
                user,
                scope=service._RecruitmentOperationsScope(
                    preset="delivery-lead",
                    delivery_pairs=frozenset(),
                ),
            )
        )
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "(jobs.client_id, jobs.tac_id) IN ((12, 34))" in allowed_sql
    assert "jobs.recruiter_id =" not in allowed_sql
    assert "job_collaborators" not in allowed_sql
    assert "false" in denied_sql


@pytest.mark.asyncio
async def test_hybrid_hor_delivery_lead_preset_resolves_exact_pairs() -> None:
    class _Values:
        def __init__(self, values: list[object]) -> None:
            self._values = values

        def all(self) -> list[object]:
            return self._values

    class _Database:
        async def scalars(self, _statement: object) -> _Values:
            return _Values([12])

        async def execute(self, _statement: object) -> _Values:
            return _Values([SimpleNamespace(client_id=12, tac_user_id=34)])

    hybrid = _user(
        UserRole.head_of_recruitment,
        roles=[UserRole.head_of_recruitment, UserRole.delivery_lead],
    )

    scope = await service._resolve_operations_scope(
        _Database(),  # type: ignore[arg-type]
        hybrid,
        "delivery-lead",
    )

    assert scope.delivery_pairs == frozenset({(12, 34)})
    assert scope.preset == "delivery-lead"


def test_candidate_overlap_excludes_hired_and_negative_latest_stages() -> None:
    rows = [
        service._LatestStage(1, 7, PipelineStage.client_interview),
        service._LatestStage(2, 7, PipelineStage.hired),
        service._LatestStage(3, 7, PipelineStage.rejected),
        service._LatestStage(4, 7, PipelineStage.withdrawn),
    ]

    assert service._overlap_candidate_ids(rows) == {1}


class _ListResult:
    def __init__(self, *, one: object | None = None, rows: list[object] | None = None):
        self._one = one
        self._rows = rows or []

    def one(self) -> object:
        assert self._one is not None
        return self._one

    def all(self) -> list[object]:
        return self._rows


class _ListDb:
    def __init__(self) -> None:
        self.execute_statements: list[object] = []
        self.scalar_statements: list[object] = []
        self._execute_results = [
            _ListResult(one=SimpleNamespace(total=4, category_total=2)),
            _ListResult(one=SimpleNamespace(active_candidates=9, active_favorites=2)),
            _ListResult(rows=[]),
            _ListResult(rows=[]),
        ]
        self._scalar_results = [1]

    async def execute(self, statement: object) -> _ListResult:
        self.execute_statements.append(statement)
        return self._execute_results.pop(0)

    async def scalar(self, statement: object) -> int:
        self.scalar_statements.append(statement)
        return self._scalar_results.pop(0)


@pytest.mark.asyncio
async def test_summary_and_categories_ignore_item_filters() -> None:
    db = _ListDb()

    response = await service.list_recruitment_operations(
        db,  # type: ignore[arg-type]
        _user(UserRole.recruiter),
        preset="my-work",
        page=1,
        page_size=50,
        q="python",
        category_id=7,
    )

    assert response.total == 1
    assert response.summary.model_dump() == {
        "open_processes": 4,
        "competence_categories": 2,
        "active_candidates": 9,
        "processes_without_favorite": 2,
    }
    summary_sql = str(db.execute_statements[0])
    category_sql = str(db.execute_statements[2])
    page_sql = str(db.execute_statements[3])
    filtered_total_sql = str(db.scalar_statements[0])
    assert "lower(jobs.title) LIKE lower" not in summary_sql
    assert "lower(jobs.title) LIKE lower" not in category_sql
    assert "jobs.competence_category_id =" not in summary_sql
    assert "jobs.competence_category_id =" not in category_sql
    assert "lower(jobs.title) LIKE lower" in filtered_total_sql
    assert "lower(jobs.title) LIKE lower" in page_sql
    assert "jobs.competence_category_id =" in filtered_total_sql
    assert "jobs.competence_category_id =" in page_sql


class _FavoriteDb:
    def __init__(
        self,
        *,
        job: Job,
        stage: PipelineStage | None = None,
        candidate: Candidate | None = None,
    ) -> None:
        self._scalars = [job] + ([stage] if stage is not None else [])
        self.candidate = candidate
        self.scalar_statements: list[object] = []
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, statement: object) -> object | None:
        self.scalar_statements.append(statement)
        return self._scalars.pop(0)

    async def get(self, model: type, object_id: int) -> object | None:
        assert model is Candidate
        assert self.candidate is None or self.candidate.id == object_id
        return self.candidate

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_favorite_requires_an_active_latest_stage() -> None:
    job = Job(
        id=7,
        title="Backend",
        client_id=4,
        recruiter_id=11,
        status=JobStatus.published,
    )
    db = _FavoriteDb(job=job, stage=PipelineStage.rejected)

    with pytest.raises(HTTPException) as exc:
        await service.set_recruitment_operation_favorite(
            db,  # type: ignore[arg-type]
            _user(UserRole.recruiter),
            job.id,
            33,
            preset="my-work",
        )

    assert exc.value.status_code == 422
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_favorite_write_is_audited() -> None:
    job = Job(
        id=7,
        title="Backend",
        client_id=4,
        recruiter_id=11,
        status=JobStatus.published,
    )
    candidate = Candidate(id=33, name="Ada", lastname="Nowak")
    db = _FavoriteDb(
        job=job,
        stage=PipelineStage.client_interview,
        candidate=candidate,
    )

    result = await service.set_recruitment_operation_favorite(
        db,  # type: ignore[arg-type]
        _user(UserRole.recruiter),
        job.id,
        candidate.id,
        preset="my-work",
    )

    assert result is not None
    assert result.model_dump() == {
        "id": 33,
        "name": "Ada Nowak",
        "stage": "client_interview",
    }
    assert job.favorite_candidate_id == 33
    audit = next(item for item in db.added if isinstance(item, Activity))
    assert audit.action == "favorite_candidate_changed"
    assert audit.details == {"previous_candidate_id": None, "candidate_id": 33}
    assert db.commits == 1
    assert "jobs.recruiter_id =" in str(db.scalar_statements[0])


def test_collaborator_read_scope_does_not_grant_favorite_write() -> None:
    collaborator = _user(UserRole.recruiter, user_id=55)
    job = Job(
        id=7,
        title="Backend",
        client_id=4,
        recruiter_id=11,
        status=JobStatus.published,
    )
    read_scope_sql = str(
        service.select(Job.id).where(
            *service._job_filters(
                collaborator,
                scope=service._RecruitmentOperationsScope(preset="my-work"),
            )
        )
    )

    assert "job_collaborators" in read_scope_sql
    assert service._can_edit_favorite(collaborator, job) is False
    with pytest.raises(HTTPException) as exc:
        service._ensure_favorite_write_access(collaborator, job)
    assert exc.value.status_code == 403


def test_explicit_process_owner_can_write_favorite() -> None:
    owner = _user(UserRole.recruiter, user_id=55)
    job = Job(
        id=7,
        title="Backend",
        client_id=4,
        recruiter_id=owner.id,
        status=JobStatus.published,
    )

    assert service._can_edit_favorite(owner, job) is True
    service._ensure_favorite_write_access(owner, job)


def test_plain_sourcer_cannot_write_favorite_even_when_stored_as_owner() -> None:
    sourcer = _user(UserRole.sourcer, user_id=55)
    job = Job(
        id=7,
        title="Backend",
        client_id=4,
        recruiter_id=sourcer.id,
        status=JobStatus.published,
    )

    assert service._can_edit_favorite(sourcer, job) is False
    with pytest.raises(HTTPException) as exc:
        service._ensure_favorite_write_access(sourcer, job)
    assert exc.value.status_code == 403


def test_degraded_similarity_is_not_flattened_to_empty() -> None:
    assert service._visible_similarity_status("degraded", []) == "degraded"


class _SimilarityDb:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _ListResult:
        self.statements.append(statement)
        return _ListResult(rows=self.rows)


@pytest.mark.asyncio
async def test_similar_processes_use_live_scoped_jobs_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = service._JobRecord(
        id=1,
        title="Source",
        client_id=10,
        client_name="Client A",
        competence_category_id=None,
        competence_category_name=None,
        recruiter_id=11,
        tac_id=None,
        delivery_lead_id=None,
        favorite_candidate_id=None,
    )
    visible = SimpleNamespace(
        id=2,
        title="Live visible title",
        client_id=20,
        client_name="Client B",
        competence_category_id=4,
        competence_category_name="Backend",
        recruiter_id=11,
        tac_id=None,
        delivery_lead_id=None,
        favorite_candidate_id=None,
    )
    process = service.RecruitmentOperationsProcess(
        job_id=1,
        title="Source",
        client=service.RecruitmentOperationsLookup(id=10, name="Client A"),
        candidate_count=2,
        stage_counts=service.RecruitmentOperationsStageCounts(),
        owners=service.RecruitmentOperationsOwners(),
        href="/jobs/1",
    )
    source_stages = [
        service._LatestStage(101, 1, PipelineStage.client_interview),
        service._LatestStage(102, 1, PipelineStage.hired),
    ]
    visible_stages = [
        service._LatestStage(101, 2, PipelineStage.verified),
        service._LatestStage(102, 2, PipelineStage.verified),
    ]
    refs = [
        service.SimilarJobRef(3, "Hidden Qdrant title", 0.65, "B"),
        service.SimilarJobRef(2, "Stale Qdrant title", 0.81, "A"),
    ]
    db = _SimilarityDb([visible])
    load_stages = AsyncMock(side_effect=[source_stages, visible_stages])
    fetch_similar = AsyncMock(return_value=(refs, "extended"))
    monkeypatch.setattr(
        service, "_load_scoped_job_record", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(service, "_load_latest_stages", load_stages)
    monkeypatch.setattr(service, "_build_processes", AsyncMock(return_value=[process]))
    monkeypatch.setattr(
        service,
        "_load_candidates",
        AsyncMock(
            return_value={
                101: Candidate(id=101, name="Ada", lastname="Nowak"),
                102: Candidate(id=102, name="Jan", lastname="Kowalski"),
            }
        ),
    )
    monkeypatch.setattr(service, "fetch_similar_jobs", fetch_similar)

    result = await service.get_recruitment_operation_detail(
        db,  # type: ignore[arg-type]
        _user(
            UserRole.head_of_recruitment,
            roles=[UserRole.head_of_recruitment, UserRole.recruiter],
        ),
        1,
        preset="my-work",
    )

    fetch_similar.assert_awaited_once_with(1, tier="all")
    assert result.can_edit_favorite is True
    assert result.similarity_status == "primary"
    assert [item.job_id for item in result.similar_processes] == [2]
    assert result.similar_processes[0].title == "Live visible title"
    assert result.similar_processes[0].candidate_overlap == 1
    scope_sql = str(db.statements[0])
    assert "jobs.status =" in scope_sql
    assert "jobs.recruiter_id =" in scope_sql
    assert "job_collaborators" in scope_sql
