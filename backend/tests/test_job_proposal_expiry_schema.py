"""0422: status „wygasła” i otwarcia skrzynki — migracja, model i entrypoint
mówią to samo (audyt 06.10.2026, R6). Prod alembic bywa osierocony —
entrypoint JEST wdrożeniem schematu.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.job_proposal import (
    JOB_PROPOSAL_STATUSES,
    JobProposal,
    JobProposalInboxOpen,
)
from app.services import job_proposal_expiry_schema as schema

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_statuses_agree_everywhere() -> None:
    assert tuple(JOB_PROPOSAL_STATUSES) == schema.STATUSES
    checks = {
        c.name: _squash(str(c.sqltext))
        for c in JobProposal.__table__.constraints
        if getattr(c, "sqltext", None) is not None
    }
    for status in schema.STATUSES:
        assert f"'{status}'" in checks["ck_job_proposals_status"]
        assert f"'{status}'" in schema.STATUS_CHECK_SQL


def test_entrypoint_mirrors_the_migration() -> None:
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    assert "from app.services import job_proposal_expiry_schema" in entry
    assert "*_JOB_PROPOSAL_EXPIRY_TABLES," in entry
    assert "*_JOB_PROPOSAL_EXPIRY_CONSTRAINTS," in entry
    # Świeża instalacja zakłada tabelę od razu z nowym statusem.
    assert "status IN ('proposed', 'dismissed', 'added', 'expired')" in entry
    assert "run_closed_job_proposal_expiry" in entry


def test_migration_uses_the_shared_ddl() -> None:
    source = (ROOT / "alembic/versions/0422_job_proposal_expiry.py").read_text()
    assert "job_proposal_expiry_schema" in source
    assert 'down_revision = "0421_recommendation_card_assist"' in source
    ddl = _squash(" ".join(schema.TABLE_DDL))
    assert "UNIQUE (job_id, user_id, opened_on)" in ddl
    table = JobProposalInboxOpen.__table__
    assert {c.name for c in table.columns} == {
        "id",
        "job_id",
        "user_id",
        "opened_on",
        "opened_at",
    }
