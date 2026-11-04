"""„Ludzie w NEXUSIE” (0455): lustro migracji w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu. Migracja
i entrypoint czytają ten sam moduł (``hr_foundation_schema``); test pilnuje,
że agregator go wpina, model zgadza się z DDL, a sonda ``/api/health/deep``
i rejestr modeli znają tabele.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.hr_ops import HrAuditEvent, HrImportBatch, HrImportIdMap, HrImportUpload, HrJobRun
from app.models.hr_profile import CompanyDayOff, EmployeeProfile, LeaveEntitlement
from app.services import hr_foundation_schema as schema
from app.services import hr_schema_bundle as bundle

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic/versions"

MODELS = {
    "employee_profiles": EmployeeProfile,
    "leave_entitlements": LeaveEntitlement,
    "company_days_off": CompanyDayOff,
    "hr_audit_events": HrAuditEvent,
    "hr_job_runs": HrJobRun,
    "hr_import_batches": HrImportBatch,
    "hr_import_uploads": HrImportUpload,
    "hr_import_id_map": HrImportIdMap,
}


def _migration_path() -> Path:
    (path,) = VERSIONS.glob("*_hr_foundation.py")
    return path


def _ddl_for(table: str) -> str:
    for ddl in schema.TABLE_DDL:
        if f"CREATE TABLE IF NOT EXISTS {table} (" in ddl:
            return ddl
    raise AssertionError(table)


def test_migration_reads_the_shared_module() -> None:
    source = _migration_path().read_text(encoding="utf-8")
    assert "from app.services import hr_foundation_schema as schema" in source
    assert "for stmt in schema.ALL_DDL:" in source


def test_bundle_carries_every_statement_and_entrypoint_splices_it() -> None:
    for statement in (*schema.TABLE_DDL, *schema.INDEX_DDL):
        assert statement in bundle.COLUMN_DDL
    for statement in schema.DATA_DDL:
        assert statement in bundle.DATA_DDL
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import hr_schema_bundle as _hr_bundle" in entry
    columns = entry.index("_COLUMN_STATEMENTS = [")
    data = entry.index("_DATA_STATEMENTS = [")
    constraints = entry.index("_CONSTRAINT_STATEMENTS = [")
    assert columns < entry.index("    *_HR_COLUMN_DDL,") < data
    assert data < entry.index("    *_HR_DATA_DDL,") < constraints
    assert constraints < entry.index("    *_HR_CONSTRAINT_DDL,")


def test_models_match_migration_columns_and_constraints() -> None:
    assert set(MODELS) == set(schema.TABLES)
    for table, model in MODELS.items():
        ddl = _ddl_for(table)
        declared = {
            match.group(1)
            for match in re.finditer(r"^\s+([a-z_0-9]+) [A-Z]", ddl, re.MULTILINE)
        } - {"constraint"}
        assert set(model.__table__.columns.keys()) == declared, table
        named = {
            constraint.name
            for constraint in model.__table__.constraints
            if constraint.name and not constraint.name.startswith(f"{table}_pkey")
        }
        in_ddl = set(re.findall(r"CONSTRAINT (\w+)", ddl))
        assert in_ddl <= named, (table, in_ddl - named)
    for statement in schema.INDEX_DDL:
        name = re.search(r"IF NOT EXISTS (\w+)", statement).group(1)
        assert any(
            index.name == name
            for model in MODELS.values()
            for index in model.__table__.indexes
        ), name


def test_modules_start_switched_off() -> None:
    (statement,) = schema.DATA_DDL
    assert "ON CONFLICT (key) DO NOTHING" in statement
    for key in schema.HR_MODULE_KEYS:
        assert f"'{key}', false" in statement


def test_tables_are_probed_by_deep_health_and_registered() -> None:
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    block = main[main.index("    core_checks = [") :]
    block = block[: block.index("\n    ]")]
    for table in (
        "employee_profiles",
        "leave_entitlements",
        "company_days_off",
        "hr_audit_events",
        "hr_job_runs",
        "hr_import_batches",
    ):
        assert re.search(rf'\("{table}",\s*\w+\)', block), table
    models_init = (ROOT / "app/models/__init__.py").read_text(encoding="utf-8")
    assert "from app.models.hr_profile import" in models_init
    assert "from app.models.hr_ops import" in models_init
