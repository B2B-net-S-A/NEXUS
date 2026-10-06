"""0419: stawki linii MD z trzema miejscami i podział zejść wspólnej puli MD.

Lustro w entrypoincie (prod alembic bywa osierocony), skala kolumn zgodna
z modelem i z kwantyzacją w kodzie, który te kolumny pisze.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0419_md_rate_scale_pool_breakdown.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0419", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_rate_changes() -> None:
    module = _migration_module()
    assert module.revision == "0419_md_rate_scale_pool_breakdown"
    assert module.down_revision == "0418_candidate_rate_changes"


def test_entrypoint_imports_the_single_ddl_source() -> None:
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import md_order_precision_schema" in text
    assert "*_MD_PRECISION_DDL," in text
    # Świeża baza bez alembica: kolumny powstają od razu w nowej skali.
    assert "ADD COLUMN IF NOT EXISTS md_rate_cost NUMERIC(12, 3) NULL" in text
    assert "ADD COLUMN IF NOT EXISTS md_rate_revenue NUMERIC(12, 3) NULL" in text
    assert "NUMERIC(12, 2)" not in text.split("md_rate_cost", 1)[1][:80]
    assert "ADD COLUMN IF NOT EXISTS breakdown JSONB NULL" in text


def test_ddl_only_alters_on_a_type_difference() -> None:
    from app.services.md_order_precision_schema import (
        CONSUMPTION_BREAKDOWN_DDL,
        MD_RATE_SCALE_DDL,
    )

    # ALTER TYPE bierze zamek tabeli — tylko przy różnicy, nie przy każdym starcie.
    assert "numeric_scale IS DISTINCT FROM 3" in MD_RATE_SCALE_DDL
    assert (
        "to_regclass('client_order_group_md_consumptions')" in CONSUMPTION_BREAKDOWN_DDL
    )


def test_model_scale_matches_the_code_quantization() -> None:
    from app.models.client_order import ClientOrder
    from app.services.multi_consultant_orders import MD_RATE_SCALE

    for column in ("md_rate_cost", "md_rate_revenue"):
        col_type = ClientOrder.__table__.c[column].type
        assert (col_type.precision, col_type.scale) == (12, 3)
    assert MD_RATE_SCALE == Decimal("0.001")
