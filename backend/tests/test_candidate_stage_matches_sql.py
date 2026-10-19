"""Podpis przejścia przy wierszu listy (`stage_match`) — SQL bez bazy.

19.10.2026 CI: filtr „klient etapu” razem z podpisem dawał 500 — zapytanie
podpisu dołącza `jobs`, a warunek klienta (`EXISTS … FROM jobs`) korelował
się z tym złączeniem i zostawał bez FROM. Kompilacja pod Postgresa łapie to
bez bazy.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.api.candidates import (
    CandidateFilterSpec,
    _stage_matches_statement,
    _StageFilter,
)
from app.models.recruitment_pipeline import PipelineStage
from app.services.candidate_stage_column import StageColumnRule


def _compile(stage_filter: _StageFilter) -> str:
    stmt = _stage_matches_statement(stage_filter, [1, 2, 3])
    return str(stmt.compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("current_only", [True, False])
@pytest.mark.parametrize(
    "column_rule",
    [None, StageColumnRule(def_groups=(((7,), None),), null_def_codes=("interview",))],
)
def test_podpis_z_filtrem_klienta_kompiluje_sie(current_only, column_rule) -> None:
    spec = CandidateFilterSpec(
        pipeline_stage=[PipelineStage.verified],
        stage_client_id=[12],
        stage_moved_by=[0, 5],
        stage_current_only=current_only,
        recruitment_id=[44],
        recruitment_client_id=[12],
    )
    stage_filter = _StageFilter(
        spec=spec,
        stage_values=(PipelineStage.verified,),
        column_rule=column_rule,
        moved_after_dt=None,
        moved_before_dt=None,
    )
    sql = _compile(stage_filter)
    # Warunek klienta to osobne EXISTS na `jobs`, nie skorelowane ze złączeniem.
    assert "EXISTS (SELECT 1" in sql
    assert "client_id IN" in sql
