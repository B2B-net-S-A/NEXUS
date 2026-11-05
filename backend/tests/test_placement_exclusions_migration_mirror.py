"""0343: wykluczone placementy mają lustro w entrypoincie.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Widok
``analytics_first_milestones`` i ``VERIFIER_ANCHORED_CTE`` czytają tabelę
``placement_exclusions``, więc brak lustra = KPI i Insights 500 na prodzie przy
zielonym CI (gdzie działa migracja). Brak filtra w lustrze widoku = każdy
restart przywraca widok bez wykluczeń.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services import placement_exclusions as pe

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0343_placement_exclusions.py"
).read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_table_ddl_is_mirrored_verbatim():
    flat = _collapse(ENTRYPOINT)
    table, index = pe.TABLE_DDL
    assert _collapse(table) in flat
    # Indeks stoi w dwóch sklejanych literałach — sprawdzamy obie połowy.
    assert "CREATE INDEX IF NOT EXISTS ix_placement_exclusions_job_id" in index
    assert "CREATE INDEX IF NOT EXISTS ix_placement_exclusions_job_id" in flat
    assert "ON placement_exclusions (job_id)" in flat


def test_view_mirror_filters_excluded_hired():
    flat = _collapse(re.sub(r"--[^\n]*", "", ENTRYPOINT))
    view = flat[flat.index("CREATE OR REPLACE VIEW analytics_first_milestones") :]
    view = view[: view.index("WHERE rn = 1")]
    assert "FROM placement_exclusions pe" in view
    assert "cs.stage <> 'hired'" in view


def test_table_is_created_before_the_view():
    assert ENTRYPOINT.index(
        "CREATE TABLE IF NOT EXISTS placement_exclusions"
    ) < ENTRYPOINT.index("CREATE OR REPLACE VIEW analytics_first_milestones")


def test_seed_phase_runs_the_service():
    assert 'startup_phase "seed-placement-exclusions"' in ENTRYPOINT
    assert "from app.services.placement_exclusions import run_seed" in ENTRYPOINT


def test_cte_filters_excluded_hired_in_the_classified_branch():
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    ranked = VERIFIER_ANCHORED_CTE[
        VERIFIER_ANCHORED_CTE.index(
            "classified_stage_ranked AS"
        ) : VERIFIER_ANCHORED_CTE.index("classified_mf AS")
    ]
    assert "placement_exclusions" in ranked


def test_rule_sql_has_no_hardcoded_ids():
    """Seria rozpoznawana regułą — w SQL-u nie ma ani jednego ID."""
    for sql in (pe.RULE_SQL, pe.HISTORICAL_SERIES_SQL):
        assert not re.search(
            r"(moved_by|candidate_id|job_id|user_id)\s*(=|IN)\s*\(?\d", sql
        )


def test_migration_chains_and_uses_the_service():
    assert 'revision = "0343_placement_exclusions"' in MIGRATION
    assert "from app.services.placement_exclusions import" in MIGRATION


def test_manual_reason_check_is_mirrored_and_migrated():
    """0650: CHECK z powodem ``manual`` w migracji i w entrypoincie.

    Bez lustra produkcja z osieroconym alembikiem odrzuci ręczne wykluczenie
    błędem CHECK, choć CI (migracja) jest zielone.
    """
    flat = _collapse(ENTRYPOINT)
    drop, add = pe.REASON_CHECK_DDL
    assert _collapse(drop) in flat
    assert _collapse(add) in flat
    assert "'manual'" in add
    migration = (
        BACKEND / "alembic" / "versions" / "0650_manual_placement_exclusions.py"
    ).read_text()
    assert "REASON_CHECK_DDL" in migration


def test_model_check_matches_service_reasons():
    from app.models.placement_exclusion import PlacementExclusion

    check = next(
        c
        for c in PlacementExclusion.__table__.constraints
        if c.name == "ck_placement_exclusions_reason"
    )
    assert all(f"'{reason}'" in str(check.sqltext) for reason in pe.REASONS)
