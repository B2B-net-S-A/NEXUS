"""0441: `client_cv_rules.cv_text_align` ma lustro w entrypoincie i w modelu.

Alembic na produkcji bywa osierocony — wtedy wdrożeniem schematu jest
`entrypoint.sh`. Kolumna i CHECK muszą być te same w migracji, entrypoincie
i modelu (decyzja J1, 14.10.2026: CV domyślnie wyjustowane).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0441_cv_text_align.py"

COLUMN_DDL = (
    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS cv_text_align "
    "VARCHAR(8) NOT NULL DEFAULT 'justify'"
)
CHECK = "CHECK (cv_text_align IN ('justify', 'left'))"


def _flat(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('" "', "").replace('"\n    "', ""))


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0441", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_revision_chain() -> None:
    module = _migration_module()
    assert module.revision == MIGRATION.stem
    assert module.down_revision == "0440_cv_ready_notification"


def test_migration_and_entrypoint_carry_the_same_ddl() -> None:
    module = _migration_module()
    entrypoint = _flat((BACKEND / "entrypoint.sh").read_text(encoding="utf-8"))
    assert _flat(module.ADD_COLUMN) == COLUMN_DDL
    assert COLUMN_DDL in entrypoint
    assert CHECK in _flat(module.ADD_CHECK)
    assert CHECK in entrypoint


def test_model_column_and_check() -> None:
    from app.models.client_cv_rule import ClientCvRule

    column = ClientCvRule.__table__.columns["cv_text_align"]
    assert not column.nullable
    assert column.server_default.arg == "justify"
    checks = {
        c.name: str(c.sqltext)
        for c in ClientCvRule.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert (
        checks["ck_client_cv_rules_text_align"]
        == "cv_text_align IN ('justify', 'left')"
    )


def test_snapshot_freezes_text_align() -> None:
    from app.models.client_cv_rule import ClientCvRule
    from app.services.cv_generator_b2b.client_rules import snapshot_rule
    from app.services.cv_text_align import cv_text_align

    for stored, expected in (
        ("left", "left"),
        ("justify", "justify"),
        (None, "justify"),
    ):
        rule = ClientCvRule(
            client_id=1,
            version=1,
            spaces_to_underscores=False,
            requires_en_copy=False,
            requires_rodo_consent_block=False,
            cv_text_align=stored,
        )
        snapshot = snapshot_rule(rule)
        assert snapshot.text_align == expected
        from dataclasses import asdict

        assert cv_text_align({"client_rule_snapshot": asdict(snapshot)}) == expected
