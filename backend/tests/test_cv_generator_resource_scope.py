"""Generator resource scope is enforced before disclosure and side effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import BackgroundTasks, HTTPException, Request
from app.api import cv_generator_b2b as api, recruitment_access
from app.models.user import User, UserRole


@pytest.fixture(autouse=True)
def fixed_priority_policy(monkeypatch):
    monkeypatch.setattr(
        recruitment_access,
        "effective_priority_mode",
        AsyncMock(return_value=recruitment_access.PriorityMode.off),
    )


def user(role=UserRole.recruiter):
    return User(
        id=71, email="scope@example.test", name="Scope", role=role, roles=[role.value]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "download_generated_cv",
        "download_generated_cv_html",
        "delete_generated_cv",
        "create_generated_cv_share_token",
        "list_generated_cv_share_tokens",
    ],
)
async def test_outsider_rejected_before_render_or_mutation(monkeypatch, endpoint):
    row = SimpleNamespace(
        id=12, job_id=45, status="ready", render_payload={"name": "Private"}
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=row), execute=AsyncMock(), commit=AsyncMock()
    )
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await getattr(api, endpoint)(generated_id=12, current_user=user(), db=db)
    assert exc.value.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_checks_scope_even_when_already_revoked(monkeypatch):
    token = SimpleNamespace(generated_document_id=12, revoked=True)
    doc = SimpleNamespace(id=12, job_id=45)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=token), get=AsyncMock(return_value=doc)
    )
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await api.revoke_generated_cv_share_token("v2$fixture", user(), db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_generation_scope_precedes_rules_sources_and_quota(monkeypatch):
    db = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                SimpleNamespace(id=2),
                SimpleNamespace(candidate_id=2, job_id=45),
                SimpleNamespace(id=45),
            ]
        )
    )
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    quota, rules = AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "_charge_cv_generation_quota", quota)
    monkeypatch.setattr(api, "resolve_client_rule", rules)
    with pytest.raises(HTTPException) as exc:
        await api.generate.__wrapped__(
            Request({"type": "http"}),
            api.GenerateRequest(candidate_id=2, stage_id=3, cv_document_id=9),
            user(),
            BackgroundTasks(),
            db,
        )
    assert exc.value.status_code == 403
    quota.assert_not_awaited()
    rules.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        UserRole.finance,
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    ],
)
async def test_existing_org_read_scope_preserved(monkeypatch, role):
    row = SimpleNamespace(job_id=45)
    db = SimpleNamespace(get=AsyncMock(return_value=row))
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    assert await api._load_generated_document(db, 12, user(role)) is row
    membership.assert_not_awaited()


@pytest.mark.asyncio
async def test_finance_read_bypass_does_not_grant_job_write(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(job_id=45)))
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await api._load_generated_document(db, 12, user(UserRole.finance), write=True)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unassociated_upload_preserves_global_access(monkeypatch):
    row = SimpleNamespace(job_id=None)
    db = SimpleNamespace(get=AsyncMock(return_value=row))
    monkeypatch.setattr(
        recruitment_access,
        "is_member_of_job",
        AsyncMock(side_effect=AssertionError("no job")),
    )
    assert await api._load_generated_document(db, 12, user()) is row


@pytest.mark.asyncio
async def test_pending_document_scoped_before_worker_finishes():
    rows = []
    db = SimpleNamespace(add=rows.append, flush=AsyncMock())
    await api._create_pending_row(
        db,
        mode="new",
        candidate_id=2,
        candidate_name="Fixture",
        position=None,
        language="pl",
        blind_cv=False,
        user_id=71,
        content_mode="faithful",
        job_id=45,
    )
    assert rows[0].job_id == 45
    assert rows[0].status == "processing"


@pytest.mark.asyncio
async def test_consent_binding_checks_scope_before_upload(monkeypatch):
    stage = SimpleNamespace(candidate_id=2, job_id=45)
    db = SimpleNamespace(get=AsyncMock(return_value=stage))
    upload = SimpleNamespace(read=AsyncMock())
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await api.upload_consent_screenshot.__wrapped__(
            Request({"type": "http"}),
            user(),
            upload,
            candidate_id=2,
            stage_id=3,
            client_id=None,
            cv_sha256=None,
            db=db,
        )
    assert exc.value.status_code == 403
    upload.read.assert_not_awaited()
