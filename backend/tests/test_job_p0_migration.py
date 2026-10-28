"""0525: P0 na rekrutacji — kolumny i typ dzwonka mają lustro w entrypoincie
(prod alembic bywa osierocony), a model zna te same kolumny."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.job import Job
from app.models.notification import NotificationType

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0525_job_p0.py"
REQUEST_MIGRATION = BACKEND / "alembic" / "versions" / "0609_job_p0_request.py"


def _migration_module(path: Path = MIGRATION):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _entrypoint() -> str:
    # Entrypoint skleja długie polecenia z sąsiednich literałów ("…" "…").
    return _squash(re.sub(r'"\s+"', "", (BACKEND / "entrypoint.sh").read_text()))


def test_columns_and_notification_type_are_mirrored() -> None:
    module = _migration_module()
    entry = _entrypoint()
    for statement in (*module.COLUMNS, module.ADD_NOTIFICATION_TYPE):
        assert _squash(statement) in entry, statement
    assert "ix_jobs_p0_until ON jobs (p0_until) WHERE p0_until IS NOT NULL" in entry


def test_model_knows_every_p0_column() -> None:
    columns = set(Job.__table__.columns.keys())
    assert {"p0_until", "p0_reason", "p0_set_at", "p0_set_by"} <= columns
    assert NotificationType.job_p0_set.value == "job_p0_set"


def test_p0_request_columns_and_notification_type_are_mirrored() -> None:
    """0609: prośba DL o P0 — to samo lustro w entrypoincie i w modelu."""
    module = _migration_module(REQUEST_MIGRATION)
    entry = _entrypoint()
    for statement in (*module.COLUMNS, module.ADD_NOTIFICATION_TYPE):
        assert _squash(statement) in entry, statement
    columns = set(Job.__table__.columns.keys())
    assert {
        "p0_request_reason",
        "p0_request_duration",
        "p0_requested_at",
        "p0_requested_by",
    } <= columns
    assert NotificationType.job_p0_requested.value == "job_p0_requested"
