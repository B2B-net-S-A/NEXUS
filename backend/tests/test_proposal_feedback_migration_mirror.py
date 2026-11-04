"""0405: źródło „Z portalu” i powód „Pomiń” — migracja, model, API i entrypoint
mówią to samo. Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

from app.api.job_proposals import ProposalSource
from app.models.job_proposal import JOB_PROPOSAL_SOURCES, JobProposal
from app.services import job_proposal_feedback_schema as schema

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_sources_agree_everywhere() -> None:
    assert tuple(JOB_PROPOSAL_SOURCES) == schema.SOURCES
    assert set(typing.get_args(ProposalSource)) == set(schema.SOURCES)
    model_checks = {
        c.name: _squash(str(c.sqltext))
        for c in JobProposal.__table__.constraints
        if getattr(c, "sqltext", None) is not None
    }
    for source in schema.SOURCES:
        assert f"'{source}'" in model_checks["ck_job_proposals_source"]
    for reason in schema.DISMISS_REASONS:
        assert f"'{reason}'" in model_checks["ck_job_proposals_dismiss_reason"]


def test_entrypoint_mirrors_the_migration() -> None:
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    assert "'reassign', 'trainee', 'job_board'" in entry
    assert "from app.services import job_proposal_feedback_schema" in entry
    assert "*_JOB_PROPOSAL_FEEDBACK_COLUMNS," in entry
    assert "*_JOB_PROPOSAL_FEEDBACK_CONSTRAINTS," in entry


def test_migration_uses_the_shared_ddl() -> None:
    source = (ROOT / "alembic/versions/0405_proposal_feedback_job_board.py").read_text()
    assert "job_proposal_feedback_schema" in source
    assert 'down_revision = "0404_application_screenings"' in source
    ddl = " ".join(schema.COLUMN_DDL + schema.CONSTRAINT_DDL)
    assert "dismiss_reason VARCHAR(32)" in ddl
    assert "dismiss_note VARCHAR(500)" in ddl
