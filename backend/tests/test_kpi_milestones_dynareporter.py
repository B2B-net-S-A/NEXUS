"""0454: statystyki 1.01–11.10.2026 z DynaReportera — granice i lustro.

Widok ``analytics_kpi_milestones`` i CTE ``credited`` (``VERIFIER_ANCHORED_CTE``)
muszą ciąć w tych samych dniach co rozliczenie wyników
(``competition_history``), a migracja ma lustro w ``entrypoint.sh`` (alembic
na produkcji bywa osierocony). Bez bazy — testy z Postgresem są w
``test_kpi_milestones_dynareporter_db.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services import competition_history as history
from app.services.kpi_panel import PRECISION_COHORT_CTE, VERIFIER_ANCHORED_CTE

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0454_kpi_milestones_dynareporter.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0454", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _boundaries() -> tuple[str, str]:
    return history.DR_HISTORY_START.isoformat(), history.RESULTS_CUTOVER.isoformat()


def test_migration_follows_the_previous_head() -> None:
    module = _migration_module()
    assert module.revision == "0454_kpi_milestones_dynareporter"
    assert module.down_revision == "0453_prep_candidate_responses"


def test_entrypoint_mirrors_the_view_right_after_the_milestones_view() -> None:
    module = _migration_module()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert module.CREATE_VIEW in entrypoint
    # Widok czyta `analytics_first_milestones`, więc w entrypoincie stoi po nim.
    assert entrypoint.index(module.CREATE_VIEW) > entrypoint.index(
        "CREATE OR REPLACE VIEW analytics_first_milestones AS"
    )


MIGRATION_0455 = (
    BACKEND / "alembic" / "versions" / "0455_kpi_milestones_history_only_dr.py"
)


def _module_0455():
    spec = importlib.util.spec_from_file_location("m0455", MIGRATION_0455)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_view_and_credited_cut_on_the_settlement_days() -> None:
    start, cutover = _boundaries()
    view = _migration_module().CREATE_VIEW
    assert f"TIMESTAMP '{start} 00:00' AT TIME ZONE 'Europe/Warsaw'" in view
    assert f"k.report_date >= DATE '{start}'" in view
    assert f"k.report_date < DATE '{cutover}'" in view
    # 0455 (18.10.2026): ruchy Tablicy tylko od 12.10 — także przed 2026.
    for sql in (_module_0455().CREATE_VIEW, VERIFIER_ANCHORED_CTE):
        assert f"TIMESTAMP '{cutover} 00:00' AT TIME ZONE 'Europe/Warsaw'" in sql
        assert f"TIMESTAMP '{start} 00:00'" not in sql
    assert start == "2026-01-01"
    assert cutover == "2026-10-12"


def test_0455_takes_company_placements_before_2026_from_the_board_report() -> None:
    view = _module_0455().CREATE_VIEW
    assert "FROM dr_board_monthly_report b" in view
    assert "WHERE b.report_month < DATE '2026-01-01'" in view
    assert "'dynareporter_board'::text AS source" in view
    # Bez osoby — raport Rady nie zna rekrutera.
    assert "NULL::integer AS first_moved_by" in view


def test_entrypoint_runs_0455_after_0454() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    old, new = _migration_module().CREATE_VIEW, _module_0455().CREATE_VIEW
    assert new in entrypoint
    assert entrypoint.index(new) > entrypoint.index(old)
    assert _module_0455().down_revision == "0454_kpi_milestones_dynareporter"


def test_view_maps_each_dynareporter_counter_to_one_stage() -> None:
    view = _migration_module().CREATE_VIEW
    for stage, column in (
        ("verified", "verifications"),
        ("cv_sent", "recommendations"),
        # Rozmowy w DynaReporterze to rozmowy u klienta, nie QC CV (`interview`).
        ("client_interview", "interviews"),
        ("hired", "placements"),
    ):
        assert f"('{stage}', k.{column})" in view
    assert "k.is_draft IS FALSE" in view


def test_credited_reads_history_rows_and_keeps_raw_moves_apart() -> None:
    assert "credited_nexus AS (" in VERIFIER_ANCHORED_CTE
    assert "FROM analytics_kpi_milestones dr" in VERIFIER_ANCHORED_CTE
    assert "dr.source <> 'nexus'" in VERIFIER_ANCHORED_CTE


def test_precision_cohort_pairs_only_board_rows() -> None:
    # Kohorta par działa na ruchach Tablicy; wpisy DynaReportera (bez pary)
    # wchodzą osobno jako rekomendacje / weryfikacje, obcięte do 100%.
    assert PRECISION_COHORT_CTE.count("AND candidate_id IS NOT NULL") == 2
    assert "WHERE candidate_id IS NULL" in PRECISION_COHORT_CTE
    assert "LEAST(sent_n, verified_n)" in PRECISION_COHORT_CTE
