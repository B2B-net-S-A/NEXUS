from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from time import perf_counter

import pytest
from sqlalchemy import select
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.candidate_profile_facts import (
    make_profile_fact_etag,
    parse_if_match_version,
)
from app.api.candidate_access import CANDIDATE_PROFILE_FACT_WRITE_ROLES
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_share_token import CVShareToken
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.schemas.candidate_profile_facts import CandidateProfileRateResponse
from app.services.candidate_profile_facts import (
    build_recent_recruitments_stmt,
    get_candidate_with_languages,
    get_recent_recruitments,
)


def _user(*, user_id: int, role: UserRole) -> User:
    return User(
        id=user_id,
        email=f"profile-facts-{user_id}@example.com",
        name="Profile Facts",
        role=role,
        roles=[role.value],
        is_active=True,
    )


def test_global_profile_fact_writer_role_set_is_explicit_and_complete():
    assert set(CANDIDATE_PROFILE_FACT_WRITE_ROLES) == {
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    }
    assert UserRole.user not in CANDIDATE_PROFILE_FACT_WRITE_ROLES


def test_profile_fact_etag_round_trip_and_resource_binding():
    etag = make_profile_fact_etag("languages", candidate_id=7, version=3)

    assert etag == '"candidate-languages-7-v3"'
    assert (
        parse_if_match_version(
            etag,
            kind="languages",
            candidate_id=7,
        )
        == 3
    )

    with pytest.raises(HTTPException) as missing:
        parse_if_match_version(None, kind="languages", candidate_id=7)
    assert missing.value.status_code == 428
    assert missing.value.detail["code"] == "if_match_required"

    for invalid in (
        '"candidate-languages-8-v3"',
        '"candidate-profile-rate-7-v3"',
        'W/"candidate-languages-7-v3"',
        '"candidate-languages-7-v0"',
        "*",
    ):
        with pytest.raises(HTTPException) as stale:
            parse_if_match_version(invalid, kind="languages", candidate_id=7)
        assert stale.value.status_code == 412
        assert stale.value.detail["code"] == "invalid_if_match"


def test_profile_rate_contract_keeps_literals_even_when_amount_is_empty():
    response = CandidateProfileRateResponse(
        candidate_id=7,
        amount=None,
        version=2,
    )

    assert response.model_dump(mode="json") == {
        "candidate_id": 7,
        "amount": None,
        "currency": "PLN",
        "unit": "hour",
        "tax_basis": "net",
        "contract_type": "b2b",
        "version": 2,
        "updated_at": None,
    }

    populated = response.model_copy(update={"amount": Decimal("123.40")})
    assert populated.model_dump(mode="json")["amount"] == "123.40"


def test_recent_recruitments_sql_is_scoped_redacted_deterministic_and_capped():
    recruiter = _user(user_id=17, role=UserRole.recruiter)
    statement = build_recent_recruitments_stmt(
        candidate_id=23,
        current_user=recruiter,
        limit=999,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert "limit 5" in sql
    assert "job_collaborators" in sql
    assert "candidate_source_identity_reviews" in sql
    assert "cv_share_tokens" in sql
    assert "notes.content" not in sql
    assert "salary_min" not in sql
    assert "salary_max" not in sql
    assert "client_rate" not in sql
    assert "expected_rate" not in sql
    assert "greatest(" in sql
    assert "order by last_activity_at desc" in sql
    assert "latest_candidate_stages.latest_stage_id desc" in sql


async def test_language_read_holds_key_share_lock_across_version_and_rows():
    class _Rows:
        def all(self):
            return []

    class _CaptureSession:
        def __init__(self):
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return Candidate(id=23, name="Jan", lastname="Nowak")

        async def scalars(self, statement):
            self.statements.append(statement)
            return _Rows()

    session = _CaptureSession()
    await get_candidate_with_languages(session, 23)  # type: ignore[arg-type]
    candidate_sql = str(
        session.statements[0].compile(dialect=postgresql.dialect())
    ).upper()

    assert "FOR KEY SHARE" in candidate_sql


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="PostgreSQL integration test; hosted CI provides DATABASE_URL",
)
async def test_recent_recruitments_limit_order_reopen_ties_and_membership():
    """Exercise the production PostgreSQL query, including scope changes."""

    from app.core.database import AsyncSessionLocal

    marker = uuid.uuid4().hex[:10]
    base = datetime(2026, 7, 30, 8, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"profile-facts-rec-{marker}@example.com",
            name="Recent Recruiter",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
        )
        admin = User(
            email=f"profile-facts-admin-{marker}@example.com",
            name="Recent Admin",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
        )
        candidate = Candidate(name="Recent", lastname=f"Candidate-{marker}")
        empty_candidate = Candidate(name="Empty", lastname=f"Candidate-{marker}")
        client = Client(name=f"Recent Client {marker}")
        db.add_all([recruiter, admin, candidate, empty_candidate, client])
        await db.flush()

        jobs = [
            Job(
                title=f"Recent {marker} {index}",
                client_id=client.id,
                recruiter_id=recruiter.id,
            )
            for index in range(6)
        ]
        hidden_job = Job(
            title=f"Hidden {marker}",
            client_id=client.id,
            recruiter_id=admin.id,
        )
        db.add_all([*jobs, hidden_job])
        await db.flush()

        first_stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=jobs[0].id,
            stage=PipelineStage.new,
            moved_at=base + timedelta(hours=1),
        )
        reopened_stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=jobs[0].id,
            stage=PipelineStage.screening,
            moved_at=base + timedelta(hours=10),
        )
        stages = [
            first_stage,
            reopened_stage,
            CandidateStage(
                candidate_id=candidate.id,
                job_id=jobs[1].id,
                stage=PipelineStage.cv_sent,
                moved_at=base + timedelta(hours=9),
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=jobs[2].id,
                stage=PipelineStage.interview,
                moved_at=base + timedelta(hours=8),
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=jobs[3].id,
                stage=PipelineStage.verified,
                moved_at=base + timedelta(hours=7),
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=jobs[4].id,
                stage=PipelineStage.new,
                moved_at=base + timedelta(hours=6),
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=jobs[5].id,
                stage=PipelineStage.new,
                moved_at=base + timedelta(hours=5),
            ),
            CandidateStage(
                candidate_id=candidate.id,
                job_id=hidden_job.id,
                stage=PipelineStage.new,
                moved_at=base + timedelta(hours=20),
            ),
        ]
        db.add_all(stages)
        await db.flush()
        db.add(
            Note(
                content="Treść nie może trafić do odpowiedzi.",
                note_type=NoteType.general,
                candidate_id=candidate.id,
                job_id=jobs[5].id,
                author_id=recruiter.id,
                source_created_at=base + timedelta(hours=11),
            )
        )
        await db.flush()

        result = await get_recent_recruitments(
            db,
            candidate_id=candidate.id,
            current_user=recruiter,
            limit=99,
        )
        assert len(result) == 5
        assert [item["job_id"] for item in result] == [
            jobs[5].id,
            jobs[0].id,
            jobs[1].id,
            jobs[2].id,
            jobs[3].id,
        ]
        assert result[1]["latest_stage_id"] == reopened_stage.id
        assert result[1]["stage"] == PipelineStage.screening
        assert set(result[0]) == {
            "job_id",
            "job_title",
            "client_id",
            "client_name",
            "latest_stage_id",
            "stage",
            "stage_label",
            "last_activity_at",
        }

        assert (
            await get_recent_recruitments(
                db,
                candidate_id=candidate.id,
                current_user=recruiter,
                limit=1,
            )
        )[0]["job_id"] == jobs[5].id
        assert (
            await get_recent_recruitments(
                db,
                candidate_id=empty_candidate.id,
                current_user=recruiter,
                limit=5,
            )
            == []
        )

        cv_snapshot = CandidateStageCV(
            candidate_stage_id=stages[5].id,
            candidate_id=candidate.id,
            job_id=jobs[4].id,
        )
        db.add(cv_snapshot)
        await db.flush()
        db.add(
            CVShareToken(
                token=f"profile-facts-{marker}",
                candidate_stage_cv_id=cv_snapshot.id,
                created_by=recruiter.id,
                created_at=base + timedelta(hours=12),
            )
        )
        await db.flush()
        after_cv_send = await get_recent_recruitments(
            db,
            candidate_id=candidate.id,
            current_user=recruiter,
            limit=5,
        )
        assert after_cv_send[0]["job_id"] == jobs[4].id

        jobs[5].recruiter_id = None
        await db.flush()
        after_membership_change = await get_recent_recruitments(
            db,
            candidate_id=candidate.id,
            current_user=recruiter,
            limit=5,
        )
        assert jobs[5].id not in {item["job_id"] for item in after_membership_change}
        admin_view = await get_recent_recruitments(
            db,
            candidate_id=candidate.id,
            current_user=admin,
            limit=5,
        )
        assert admin_view[0]["job_id"] == hidden_job.id

        tie_candidate = Candidate(name="Tie", lastname=f"Candidate-{marker}")
        tie_jobs = [
            Job(
                title=f"Tie {marker} {index}",
                client_id=client.id,
                recruiter_id=recruiter.id,
            )
            for index in range(2)
        ]
        db.add_all([tie_candidate, *tie_jobs])
        await db.flush()
        tie_stages = [
            CandidateStage(
                candidate_id=tie_candidate.id,
                job_id=job.id,
                stage=PipelineStage.new,
                moved_at=base,
            )
            for job in tie_jobs
        ]
        db.add_all(tie_stages)
        await db.flush()

        tied = await get_recent_recruitments(
            db,
            candidate_id=tie_candidate.id,
            current_user=recruiter,
            limit=5,
        )
        assert [item["latest_stage_id"] for item in tied] == [
            tie_stages[1].id,
            tie_stages[0].id,
        ]

        # Warm-cache p95 guard against the pre-redesign lightweight stage
        # lookup. The absolute 300 ms ceiling dominates on normal CI runners;
        # the relative arm catches an unexpectedly expensive query plan on a
        # slower database.
        await get_recent_recruitments(
            db,
            candidate_id=candidate.id,
            current_user=recruiter,
            limit=5,
        )
        recent_samples: list[float] = []
        baseline_samples: list[float] = []
        for _ in range(20):
            started = perf_counter()
            await db.execute(
                select(CandidateStage.id)
                .where(CandidateStage.candidate_id == candidate.id)
                .order_by(CandidateStage.moved_at.desc())
                .limit(5)
            )
            baseline_samples.append(perf_counter() - started)

            started = perf_counter()
            await get_recent_recruitments(
                db,
                candidate_id=candidate.id,
                current_user=recruiter,
                limit=5,
            )
            recent_samples.append(perf_counter() - started)

        p95_index = int(0.95 * len(recent_samples)) - 1
        recent_p95 = sorted(recent_samples)[p95_index]
        baseline_p95 = sorted(baseline_samples)[p95_index]
        allowed = max(0.300, baseline_p95 * 1.2)
        assert recent_p95 <= allowed, (
            f"recent-recruitments p95={recent_p95 * 1000:.1f}ms "
            f"baseline={baseline_p95 * 1000:.1f}ms "
            f"allowed={allowed * 1000:.1f}ms"
        )
        await db.rollback()
