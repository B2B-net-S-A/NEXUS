"""0797: weryfikacja od QC CV — lustro migracji w entrypoincie i kształt CTE.

Bez bazy; zachowanie na Postgresie sprawdza
``test_verification_from_qc_cv_db.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0797_verification_counts_from_qc_cv.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0797", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_follows_the_previous_head() -> None:
    module = _migration()
    assert module.revision == "0797_verification_counts_from_qc_cv"
    assert module.down_revision == "0796_screening_return_bells"


def test_entrypoint_mirrors_function_before_view() -> None:
    module = _migration()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    positions = [
        entrypoint.index(sql)
        for sql in (module.CREATE_FUNCTION, module.ADD_COLUMN, module.CREATE_VIEW)
    ]
    assert positions == sorted(positions)
    # Jedna definicja widoku — druga, starsza, nadpisałaby zmianę przy starcie.
    assert entrypoint.count("CREATE OR REPLACE VIEW analytics_first_milestones") == 1


def test_view_and_cte_share_the_board_rule() -> None:
    from app.services.verification_milestone import reaches_cv_qc_sql

    assert reaches_cv_qc_sql("later", "sd") in _migration().CREATE_VIEW
    assert reaches_cv_qc_sql("cs", "sd") in VERIFIER_ANCHORED_CTE


def test_counted_verification_waits_for_qc_but_anchor_does_not() -> None:
    cte = VERIFIER_ANCHORED_CTE
    counted = cte[cte.index("classified_mf AS") : cte.index("classified_verified AS")]
    assert "classified_qc" in counted
    anchor = cte[
        cte.index("classified_verified AS") : cte.index("classified_anchor AS")
    ]
    assert "FROM classified_first" in anchor
    # Autor kamieni bez kotwicy procesu: sama weryfikacja, nie wejście na QC.
    fallback = cte[
        cte.index("pair_first_verifier AS") : cte.index("classified_fallback AS")
    ]
    assert "FROM candidate_stages" in fallback
    assert "analytics_first_milestones" not in fallback
