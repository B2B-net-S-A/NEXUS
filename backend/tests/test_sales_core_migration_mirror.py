"""Sprzedaż (0601): lustro migracji w entrypoint.sh, model zgodny z DDL, rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu. Migracja
i entrypoint czytają ten sam moduł (``sales_schema``); test pilnuje, że
entrypoint go wpina we właściwych fazach, model zgadza się z DDL, a sonda
``/api/health/deep`` i rejestr modeli znają tabele.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesCompanyContact,
    SalesContact,
    SalesFile,
    SalesLead,
    SalesOpportunity,
    SalesOpportunityContact,
    SalesOpportunityEvent,
    SalesPipeline,
    SalesPipelineStage,
)
from app.services import sales_schema as schema

ROOT = Path(__file__).resolve().parents[1]

MODELS = {
    "sales_pipelines": SalesPipeline,
    "sales_pipeline_stages": SalesPipelineStage,
    "sales_companies": SalesCompany,
    "sales_contacts": SalesContact,
    "sales_opportunities": SalesOpportunity,
    "sales_opportunity_contacts": SalesOpportunityContact,
    "sales_activities": SalesActivity,
    "sales_files": SalesFile,
    "sales_leads": SalesLead,
    "sales_company_contacts": SalesCompanyContact,
    "sales_opportunity_events": SalesOpportunityEvent,
}


def _added_columns(table: str) -> set[str]:
    """Kolumny dołożone przez ``ALTER TABLE … ADD COLUMN`` (0614)."""
    return {
        match.group(1)
        for statement in schema.GAPS_DDL
        for match in re.finditer(
            rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS (\w+)", statement
        )
    }


def _ddl_for(table: str) -> str:
    for ddl in (
        *schema.TABLE_DDL,
        *schema.LEAD_TABLE_DDL,
        *schema.GAPS_DDL,
        *schema.HISTORY_DDL,
    ):
        if f"CREATE TABLE IF NOT EXISTS {table} (" in ddl:
            return ddl
    raise AssertionError(table)


def test_migration_reads_the_shared_module() -> None:
    source = (ROOT / "alembic/versions/0601_sales_core.py").read_text(encoding="utf-8")
    assert "from app.services import sales_schema as schema" in source
    assert "for stmt in schema.ALL_DDL:" in source
    leads = (ROOT / "alembic/versions/0602_sales_leads.py").read_text(encoding="utf-8")
    assert "for stmt in schema.LEADS_DDL:" in leads
    gaps = (ROOT / "alembic/versions/0614_sales_atlas_gaps.py").read_text(
        encoding="utf-8"
    )
    assert "for stmt in schema.GAPS_DDL:" in gaps
    history = (ROOT / "alembic/versions/0617_sales_opportunity_events.py").read_text(
        encoding="utf-8"
    )
    assert "for stmt in schema.HISTORY_DDL:" in history
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "*_sales_schema.LEADS_DDL," in entry
    assert "*_sales_schema.GAPS_DDL," in entry
    assert "*_sales_schema.HISTORY_DDL," in entry


def test_entrypoint_splices_tables_before_data() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import sales_schema as _sales_schema" in entry
    columns = entry.index("_COLUMN_STATEMENTS = [")
    data = entry.index("_DATA_STATEMENTS = [")
    constraints = entry.index("_CONSTRAINT_STATEMENTS = [")
    assert columns < entry.index("    *_SALES_TABLE_DDL,") < data
    assert data < entry.index("    *_SALES_DATA_DDL,") < constraints


def test_models_match_migration_columns_and_constraints() -> None:
    assert set(MODELS) == {
        *schema.TABLES,
        "sales_leads",
        "sales_company_contacts",
        "sales_opportunity_events",
    }
    for table, model in MODELS.items():
        ddl = _ddl_for(table)
        declared = {
            match.group(1)
            for match in re.finditer(r"^\s+([a-z_0-9]+) [A-Z]", ddl, re.MULTILINE)
        }
        declared |= _added_columns(table)
        assert set(model.__table__.columns.keys()) == declared, table
        named = {
            constraint.name
            for constraint in model.__table__.constraints
            if constraint.name
        }
        in_ddl = set(re.findall(r"CONSTRAINT (\w+)", ddl))
        assert in_ddl <= named, (table, in_ddl - named)
    gap_indexes = tuple(
        s
        for s in (*schema.GAPS_DDL, *schema.HISTORY_DDL)
        if s.startswith("CREATE INDEX")
    )
    for statement in (*schema.INDEX_DDL, *schema.LEAD_INDEX_DDL, *gap_indexes):
        name = re.search(r"IF NOT EXISTS (\w+)", statement).group(1)
        assert any(
            index.name == name
            for model in MODELS.values()
            for index in model.__table__.indexes
        ), name


def test_default_pipeline_seed_is_idempotent_and_has_one_outcome_each() -> None:
    pipeline, stages = schema.DATA_DDL
    assert "ON CONFLICT (key) DO NOTHING" in pipeline
    assert "NOT EXISTS (" in stages
    outcomes = [outcome for _k, _n, _p, outcome, _q in schema.DEFAULT_STAGES]
    assert outcomes.count("won") == 1
    assert sum(1 for *_rest, qualifies in schema.DEFAULT_STAGES if qualifies) == 1


def test_tables_are_probed_by_deep_health_and_registered() -> None:
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    block = main[main.index("    core_checks = [") :]
    block = block[: block.index("\n    ]")]
    for table in (
        "sales_companies",
        "sales_pipeline_stages",
        "sales_opportunities",
        "sales_activities",
    ):
        assert re.search(rf'\("{table}",\s*\w+\)', block), table
    models_init = (ROOT / "app/models/__init__.py").read_text(encoding="utf-8")
    assert "from app.models import sales as _sales_models" in models_init
