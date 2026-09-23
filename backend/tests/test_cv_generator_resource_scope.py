"""Generator access (decyzja Artura z 10.09.2026: „wszyscy mogą”).

* Generować CV może każdy z rolą zapisu kandydata — bez członkostwa w zespole
  rekrutacji (#1448 to wymuszał; cofnięte). Poprawność zostaje: etap musi
  należeć do kandydata (404).
* Autor zawsze ma dostęp do własnego dokumentu.
* Cudzy dokument związany z rekrutacją: odczyt i działania w zakresie odczytu
  tej rekrutacji. Od 23.09.2026 (decyzja Artura: „wszystko w rekrutacji widzi
  każdy”) ten zakres ma każda rola wewnętrzna bez przypisania; poza nim zostaje
  stara rola podglądu ``user`` spoza zespołu — ta dostaje 403 przed renderem
  i przed zapisem.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import BackgroundTasks, HTTPException, Request
from app.api import cv_generator_b2b as api, recruitment_access
from app.models.user import User, UserRole

OTHER_AUTHOR = 99


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
async def test_legacy_viewer_outside_team_rejected_on_someone_elses_document(
    monkeypatch, endpoint
):
    row = SimpleNamespace(
        id=12,
        job_id=45,
        created_by=OTHER_AUTHOR,
        status="ready",
        render_payload={"name": "Private"},
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=row), execute=AsyncMock(), commit=AsyncMock()
    )
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await getattr(api, endpoint)(
            generated_id=12, current_user=user(UserRole.user), db=db
        )
    assert exc.value.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_checks_scope_even_when_already_revoked(monkeypatch):
    token = SimpleNamespace(generated_document_id=12, revoked=True)
    doc = SimpleNamespace(id=12, job_id=45, created_by=OTHER_AUTHOR)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=token), get=AsyncMock(return_value=doc)
    )
    monkeypatch.setattr(
        recruitment_access, "is_member_of_job", AsyncMock(return_value=False)
    )
    with pytest.raises(HTTPException) as exc:
        await api.revoke_generated_cv_share_token(
            "v2$fixture", user(UserRole.user), db=db
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_author_keeps_own_document_outside_the_recruitment_team(monkeypatch):
    """Autor spoza zespołu rekrutacji pobiera, udostępnia i zatwierdza SWOJE CV.

    Bez tego „wszyscy mogą generować” kończyłoby się dokumentem, którego autor
    nie może otworzyć — generacja kosztuje, a wynik byłby niedostępny.
    """
    row = SimpleNamespace(id=12, job_id=45, created_by=71)
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))
    db = SimpleNamespace(
        get=AsyncMock(return_value=row), execute=AsyncMock(return_value=rows)
    )
    assert await api._load_generated_document(db, 12, user()) is row
    # Endpoint path, not only the helper: the author lists the document's links.
    assert (
        await api.list_generated_cv_share_tokens(
            generated_id=12, current_user=user(), db=db
        )
        == []
    )
    membership.assert_not_awaited()


@pytest.mark.asyncio
async def test_recruiter_outside_team_acts_on_colleagues_document(monkeypatch):
    """Od 23.09.2026 rekruter spoza zespołu działa na cudzym CV rekrutacji —
    członkostwo nie jest nawet sprawdzane."""
    row = SimpleNamespace(id=12, job_id=45, created_by=OTHER_AUTHOR)
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    db = SimpleNamespace(get=AsyncMock(return_value=row))
    assert await api._load_generated_document(db, 12, user()) is row
    membership.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_outside_bypass_set_still_consults_membership(monkeypatch):
    """Rola spoza zbioru ról wewnętrznych (stary podgląd ``user``) nie omija
    bramki — o dostępie do cudzego CV rekrutacji rozstrzyga członkostwo."""
    row = SimpleNamespace(id=12, job_id=45, created_by=OTHER_AUTHOR)
    membership = AsyncMock(return_value=True)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    db = SimpleNamespace(get=AsyncMock(return_value=row))
    assert await api._load_generated_document(db, 12, user(UserRole.user)) is row
    membership.assert_awaited_once()


@pytest.mark.asyncio
async def test_generation_does_not_consult_recruitment_membership(monkeypatch):
    """A non-member reaches client rules (the next step) — membership is never
    asked. Before 10.09.2026 this was a 403 before rules, sources and quota."""

    class ReachedClientRules(Exception):
        pass

    stage = SimpleNamespace(id=3, candidate_id=2, job_id=45)
    db = SimpleNamespace(
        get=AsyncMock(side_effect=[SimpleNamespace(id=2), stage]),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: 5)),
    )
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    rules = AsyncMock(side_effect=ReachedClientRules)
    monkeypatch.setattr(api, "resolve_client_rule", rules)
    with pytest.raises(ReachedClientRules):
        await api.generate.__wrapped__(
            Request({"type": "http", "headers": []}),
            api.GenerateRequest(candidate_id=2, stage_id=3, cv_document_id=9),
            user(),
            BackgroundTasks(),
            db,
        )
    membership.assert_not_awaited()
    rules.assert_awaited_once_with(db, 5)


@pytest.mark.asyncio
async def test_generation_rejects_stage_of_another_candidate(monkeypatch):
    """Correctness kept from #1448: the stage must belong to the candidate."""
    db = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                SimpleNamespace(id=2),
                SimpleNamespace(id=3, candidate_id=77, job_id=45),
            ]
        )
    )
    quota, rules = AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "_charge_cv_generation_quota", quota)
    monkeypatch.setattr(api, "resolve_client_rule", rules)
    with pytest.raises(HTTPException) as exc:
        await api.generate.__wrapped__(
            Request({"type": "http", "headers": []}),
            api.GenerateRequest(candidate_id=2, stage_id=3, cv_document_id=9),
            user(),
            BackgroundTasks(),
            db,
        )
    assert exc.value.status_code == 404
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
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
async def test_every_internal_role_reads_without_membership(monkeypatch, role):
    row = SimpleNamespace(job_id=45, created_by=OTHER_AUTHOR)
    db = SimpleNamespace(get=AsyncMock(return_value=row))
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
    assert await api._load_generated_document(db, 12, user(role)) is row
    membership.assert_not_awaited()


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
    assert rows[0].created_by == 71
    assert rows[0].status == "processing"


@pytest.mark.asyncio
async def test_consent_upload_does_not_require_membership(monkeypatch):
    """The consent screenshot is a generation step, so it follows the same rule:
    a non-member gets past the stage checks to the file itself."""
    stage = SimpleNamespace(candidate_id=2, job_id=45)
    job = SimpleNamespace(id=45, client_id=None)
    db = SimpleNamespace(get=AsyncMock(side_effect=[stage, job]))
    upload = SimpleNamespace(read=AsyncMock(return_value=b""))
    membership = AsyncMock(return_value=False)
    monkeypatch.setattr(recruitment_access, "is_member_of_job", membership)
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
    # Empty file = the handler reached the upload; no scope 403 in between.
    assert exc.value.status_code == 422
    upload.read.assert_awaited_once()
    membership.assert_not_awaited()


@pytest.mark.asyncio
async def test_consent_upload_rejects_stage_of_another_candidate():
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(candidate_id=77, job_id=45))
    )
    upload = SimpleNamespace(read=AsyncMock())
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
    assert exc.value.status_code == 404
    upload.read.assert_not_awaited()
