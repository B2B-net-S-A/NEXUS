from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet

from fastapi import HTTPException

from app.api.phase4 import (
    SavedSearchCreate,
    SavedSearchUpdate,
    create_saved_search,
    update_saved_search,
)
from app.services.candidate_monthly_rate_retirement import (
    retire_candidate_saved_searches,
    sanitize_candidate_saved_search,
)
from scripts import retire_candidate_monthly_salary as cleanup


class _FakeResult:
    def __init__(self, *, rows: list[Any] | None = None, rowcount: int = 0):
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self) -> list[Any]:
        return self._rows


class _FakeCleanupSession:
    def __init__(
        self,
        *,
        rows: list[Any],
        update_rowcount: int | None = None,
        remaining: int = 0,
        lock_error: Exception | None = None,
    ):
        self.rows = rows
        self.update_rowcount = len(rows) if update_rowcount is None else update_rowcount
        self.remaining = remaining
        self.lock_error = lock_error
        self.events: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, statement):
        statement_type = type(statement).__name__
        if (
            statement_type == "TextClause"
            and statement.text == cleanup._CANDIDATE_WRITE_LOCK_SQL
        ):
            self.events.append("lock")
            if self.lock_error:
                raise self.lock_error
            return _FakeResult()
        if statement_type == "Select":
            self.events.append("snapshot")
            return _FakeResult(rows=self.rows)
        if statement_type == "Update":
            self.events.append("update")
            return _FakeResult(rowcount=self.update_rowcount)
        raise AssertionError(f"Unexpected statement type: {statement_type}")

    async def scalar(self, _statement):
        self.events.append("remaining")
        return self.remaining

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


class _FakeSavedSearchSession:
    def __init__(self, saved_search: SimpleNamespace):
        self.saved_search = saved_search
        self.commits = 0

    async def scalar(self, _statement):
        return self.saved_search

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        return None


class _CountResult:
    def scalar(self):
        return 0


class _SavedSearchCreateSession:
    def __init__(self):
        self.added = []

    async def execute(self, _statement):
        return _CountResult()

    def add(self, row):
        self.added.append(row)


def _record(
    candidate_id: int = 7,
    *,
    amount: str = "15000",
    currency: str | None = "PLN",
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = updated_at or datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    return {
        "candidate_id": candidate_id,
        "salary_expectation": amount,
        "salary_currency": currency,
        "updated_at": timestamp.isoformat(),
    }


def _row(
    candidate_id: int = 7,
    *,
    amount: str = "15000",
    currency: str | None = "PLN",
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=candidate_id,
        salary_expectation=Decimal(amount),
        salary_currency=currency,
        updated_at=updated_at or datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
    )


def _encrypted_export(
    tmp_path: Path,
    monkeypatch,
    records: list[dict[str, Any]],
    *,
    filename: str = "candidate-monthly-rates.bin",
) -> tuple[Path, str]:
    monkeypatch.setenv(
        "CANDIDATE_SALARY_EXPORT_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    path = tmp_path / filename
    ciphertext = cleanup._fernet().encrypt(cleanup._canonical_payload(records))
    cleanup._write_exclusive_private(path, ciphertext)
    return path, cleanup._ciphertext_sha256(ciphertext)


def test_saved_search_monthly_criteria_are_removed_without_converting_ranges():
    original = {
        "qs": "?q=python&salary_min=15000&rate_min=120&salary_max=25000",
        "api": {
            "q": "python",
            "salary_min": 15000,
            "salary_max": 25000,
            "rate_hourly_min": 120,
        },
        "ui": {"salaryMin": 15000, "expanded": True},
    }

    sanitized, changed = sanitize_candidate_saved_search(original)

    assert changed is True
    assert sanitized["qs"] == "?q=python&rate_min=120"
    assert sanitized["api"] == {"q": "python", "rate_hourly_min": 120}
    assert sanitized["ui"] == {"expanded": True}
    assert original["api"]["salary_min"] == 15000


def test_saved_search_without_monthly_criteria_is_unchanged():
    filters = {"qs": "?q=python&rate_min=120", "api": {"min_rate": 120}}
    sanitized, changed = sanitize_candidate_saved_search(filters)
    assert changed is False
    assert sanitized == filters


def test_saved_search_removes_monthly_preferences_but_keeps_other_preferences():
    filters = {
        "preferences": {
            "rate_min": 10_000,
            "rate_currency": "PLN",
            "work_mode": "remote",
        }
    }

    sanitized, changed = sanitize_candidate_saved_search(filters)

    assert changed is True
    assert sanitized == {"preferences": {"work_mode": "remote"}}


def test_saved_search_removes_only_monthly_v3_rates_and_preserves_hourly():
    filters = {
        "hard_filters": {
            "rates": [
                {"unit": "month", "min": 15_000, "currency": "PLN"},
                {"unit": "hour", "min": 150, "currency": "PLN"},
            ],
            "locations": ["Warszawa"],
        }
    }

    sanitized, changed = sanitize_candidate_saved_search(filters)

    assert changed is True
    assert sanitized == {
        "hard_filters": {
            "rates": [{"unit": "hour", "min": 150, "currency": "PLN"}],
            "locations": ["Warszawa"],
        }
    }


class _SavedSearchRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SavedSearchSweepSession:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    async def scalars(self, _statement):
        return _SavedSearchRows(self.rows)

    async def commit(self):
        self.commits += 1


async def test_runtime_sweep_disables_alerts_and_requires_reapproval():
    monthly = SimpleNamespace(
        id=1,
        entity="candidates",
        filters={
            "hard_filters": {
                "rates": [
                    {"unit": "month", "min": 15_000},
                    {"unit": "hour", "min": 150},
                ]
            }
        },
        notify_new_matches=True,
        requires_reapproval=False,
    )
    hourly = SimpleNamespace(
        id=2,
        entity="candidate",
        filters={"hard_filters": {"rates": [{"unit": "hour", "min": 120}]}},
        notify_new_matches=True,
        requires_reapproval=False,
    )
    session = _SavedSearchSweepSession([monthly, hourly])

    changed = await retire_candidate_saved_searches(session)

    assert changed == 1
    assert monthly.filters["hard_filters"]["rates"] == [{"unit": "hour", "min": 150}]
    assert monthly.notify_new_matches is False
    assert monthly.requires_reapproval is True
    assert hourly.notify_new_matches is True
    assert hourly.requires_reapproval is False
    assert session.commits == 1


async def test_saved_search_api_rejects_new_monthly_v3_rate():
    session = _SavedSearchCreateSession()

    with pytest.raises(HTTPException) as exc:
        await create_saved_search(
            data=SavedSearchCreate(
                name="Nieaktualna stawka",
                entity="candidates",
                filters={"hard_filters": {"rates": [{"unit": "month", "min": 15_000}]}},
            ),
            current_user=SimpleNamespace(id=9),
            db=session,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "candidate_monthly_rate_retired"
    assert session.added == []


def test_migration_sanitizer_matches_runtime_for_mixed_v3_and_preferences():
    import importlib.util

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0208_retire_candidate_monthly_rate.py"
    )
    spec = importlib.util.spec_from_file_location("candidate_rate_0207", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    filters = {
        "preferences": {"rate_min": 10_000, "work_mode": "remote"},
        "hard_filters": {
            "rates": [
                {"unit": "monthly", "max": 20_000},
                {"unit": "hour", "max": 200},
            ]
        },
    }

    assert migration._sanitize(filters) == sanitize_candidate_saved_search(filters)


async def test_saved_search_reapproval_requires_explicit_confirmation():
    saved_search = SimpleNamespace(
        id=71,
        user_id=9,
        name="Backend po migracji",
        entity="candidates",
        filters={"q": "python"},
        shared=False,
        description=None,
        pinned_to_job_id=None,
        notify_new_matches=False,
        requires_reapproval=True,
        unseen_count=0,
        last_viewed_at=None,
        created_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
    )
    session = _FakeSavedSearchSession(saved_search)
    user = SimpleNamespace(id=9)

    unchanged = await update_saved_search(
        search_id=71,
        data=SavedSearchUpdate(name="Po migracji"),
        current_user=user,
        db=session,
    )
    assert unchanged["requires_reapproval"] is True

    approved = await update_saved_search(
        search_id=71,
        data=SavedSearchUpdate(confirm_reapproval=True),
        current_user=user,
        db=session,
    )
    assert approved["requires_reapproval"] is False
    assert session.commits == 2


def test_cleanup_export_is_private_encrypted_and_integrity_checked(
    tmp_path, monkeypatch
):
    records = [_record()]
    path, digest = _encrypted_export(tmp_path, monkeypatch, records)

    assert path.read_bytes() != cleanup._canonical_payload(records)
    assert path.stat().st_mode & 0o077 == 0
    manifest, actual_digest = cleanup._read_manifest(path, digest)
    assert manifest["records"] == records
    assert actual_digest == digest

    with pytest.raises(cleanup.CleanupSafetyError, match="SHA-256"):
        cleanup._read_manifest(path, "0" * 64)


def test_cleanup_rejects_relative_repo_local_linked_and_over_permissive_paths(
    tmp_path, monkeypatch
):
    _, digest = _encrypted_export(
        tmp_path,
        monkeypatch,
        [_record()],
        filename="private.bin",
    )
    private_path = tmp_path / "private.bin"

    with pytest.raises(cleanup.CleanupSafetyError, match="absolute"):
        cleanup._read_manifest(Path("private.bin"), digest)

    repo_path = Path(__file__).resolve().parents[1] / "private-export.bin"
    with pytest.raises(cleanup.CleanupSafetyError, match="outside"):
        cleanup._write_exclusive_private(repo_path, b"secret")

    linked_path = tmp_path / "linked.bin"
    linked_path.symlink_to(private_path)
    with pytest.raises(cleanup.CleanupSafetyError, match="symbolic link"):
        cleanup._read_manifest(linked_path, digest)

    private_path.chmod(0o640)
    with pytest.raises(cleanup.CleanupSafetyError, match="permissions"):
        cleanup._read_manifest(private_path, digest)


def test_cleanup_rejects_duplicate_candidate_ids(tmp_path, monkeypatch):
    path, digest = _encrypted_export(
        tmp_path,
        monkeypatch,
        [_record(), _record(amount="16000")],
    )

    with pytest.raises(cleanup.CleanupSafetyError, match="duplicate candidate ids"):
        cleanup._read_manifest(path, digest)


async def test_cleanup_rejects_export_count_before_opening_database(
    tmp_path, monkeypatch
):
    path, digest = _encrypted_export(tmp_path, monkeypatch, [_record()])
    monkeypatch.setattr(
        cleanup,
        "AsyncSessionLocal",
        lambda: pytest.fail("database must not be opened after count mismatch"),
    )

    with pytest.raises(cleanup.CleanupSafetyError, match="export count"):
        await cleanup.apply_cleanup(
            path=path,
            expected_count=2,
            expected_sha256=digest,
            approval=cleanup._APPROVAL_PHRASE,
        )


async def test_cleanup_rolls_back_when_database_drifted_after_export(
    tmp_path, monkeypatch
):
    path, digest = _encrypted_export(tmp_path, monkeypatch, [_record()])
    session = _FakeCleanupSession(rows=[_row(amount="16000")])
    monkeypatch.setattr(cleanup, "AsyncSessionLocal", lambda: session)

    with pytest.raises(cleanup.CleanupSafetyError, match="changed after export"):
        await cleanup.apply_cleanup(
            path=path,
            expected_count=1,
            expected_sha256=digest,
            approval=cleanup._APPROVAL_PHRASE,
        )

    assert session.events == ["lock", "snapshot", "rollback"]


async def test_cleanup_rolls_back_when_updated_count_does_not_match(
    tmp_path, monkeypatch
):
    path, digest = _encrypted_export(tmp_path, monkeypatch, [_record()])
    session = _FakeCleanupSession(rows=[_row()], update_rowcount=0)
    monkeypatch.setattr(cleanup, "AsyncSessionLocal", lambda: session)

    with pytest.raises(cleanup.CleanupSafetyError, match="updated row count"):
        await cleanup.apply_cleanup(
            path=path,
            expected_count=1,
            expected_sha256=digest,
            approval=cleanup._APPROVAL_PHRASE,
        )

    assert session.events == ["lock", "snapshot", "update", "rollback"]


async def test_cleanup_locks_out_concurrent_writers_for_the_entire_mutation(
    tmp_path, monkeypatch
):
    path, digest = _encrypted_export(tmp_path, monkeypatch, [_record()])
    session = _FakeCleanupSession(rows=[_row()])
    monkeypatch.setattr(cleanup, "AsyncSessionLocal", lambda: session)

    result = await cleanup.apply_cleanup(
        path=path,
        expected_count=1,
        expected_sha256=digest,
        approval=cleanup._APPROVAL_PHRASE,
    )

    assert result == {
        "mode": "apply",
        "changed": 1,
        "remaining": 0,
        "sha256": digest,
    }
    assert session.events == [
        "lock",
        "snapshot",
        "update",
        "remaining",
        "commit",
    ]


async def test_cleanup_fails_closed_when_candidate_writer_holds_a_lock(
    tmp_path, monkeypatch
):
    path, digest = _encrypted_export(tmp_path, monkeypatch, [_record()])
    session = _FakeCleanupSession(
        rows=[_row()],
        lock_error=cleanup.SQLAlchemyError("lock unavailable"),
    )
    monkeypatch.setattr(cleanup, "AsyncSessionLocal", lambda: session)

    with pytest.raises(cleanup.CleanupSafetyError, match="being modified"):
        await cleanup.apply_cleanup(
            path=path,
            expected_count=1,
            expected_sha256=digest,
            approval=cleanup._APPROVAL_PHRASE,
        )

    assert session.events == ["lock", "rollback"]


async def test_export_result_never_discloses_artifact_path(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CANDIDATE_SALARY_EXPORT_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setattr(cleanup, "_current_rows", lambda: _async_value([_row()]))
    path = tmp_path / "sensitive-location.bin"

    result = await cleanup.export_encrypted(path)

    assert "path" not in result
    assert str(path) not in str(result)


async def _async_value(value):
    return value


def test_candidate_monthly_column_has_no_unapproved_runtime_consumers():
    """Keep legacy columns quarantined to explicitly preserved boundaries."""

    app_root = Path(__file__).resolve().parents[1] / "app"
    allowed = {
        Path("models/candidate.py"),
        Path("models/screening_note.py"),
        Path("api/screenings.py"),
        Path("services/cv_generator_b2b/standalone_service.py"),
        # These boundaries only reject/report the retired field by name.
        Path("api/candidates.py"),
        Path("api/import_export.py"),
        Path("schemas/candidate.py"),
        Path("services/candidate_monthly_rate_retirement.py"),
        Path("services/candidate_activity_summary_service.py"),
    }
    offenders = []
    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root)
        if relative in allowed:
            continue
        if "salary_expectation" in path.read_text(encoding="utf-8"):
            offenders.append(str(relative))

    assert offenders == []


def test_candidate_monthly_columns_have_no_unapproved_runtime_attribute_access():
    """Prevent retired Candidate fields from returning through a broad allowlist.

    String mentions remain legitimate for validation, DLP and import error
    reporting. Runtime attribute access is limited to the deprecated model,
    the separately-owned screening record, and the explicit cleanup tool.
    """

    backend_root = Path(__file__).resolve().parents[1]
    allowed = {
        Path("app/models/candidate.py"),
        Path("app/models/screening_note.py"),
        Path("app/api/screenings.py"),
        Path("app/services/cv_generator_b2b/standalone_service.py"),
        Path("scripts/retire_candidate_monthly_salary.py"),
    }
    retired_attributes = {"salary_expectation", "salary_currency"}
    offenders: list[str] = []

    for source_root in (backend_root / "app", backend_root / "scripts"):
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(backend_root)
            if relative in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in retired_attributes:
                    offenders.append(f"{relative}:{node.lineno}:{node.attr}")

    assert offenders == []
