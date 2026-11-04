"""„Dodany na etap” po kolumnach Tablicy — zamiana kolumny na etapy szablonu.

Bez bazy: fikcyjne etapy szablonów i SQL skompilowany dla Postgresa. Testy
z bazą (filtr na liście, `stage_match`) są w `test_candidates_stage_filter.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.board_stage_badges import board_column_for
from app.services.candidate_stage_column import (
    STAGE_COLUMNS,
    StageDefFacts,
    column_clause,
    column_rule,
    row_column,
)

ALL_CODES = tuple(stage.value for stage in PipelineStage)

QC = StageDefFacts(id=1, name="QC CV", category="internal")
DZ = StageDefFacts(id=2, name="Przepuszczony przez DZ", category="internal")
CPRO = StageDefFacts(id=3, name="NORDEA: Wysłać do Cpro", category="internal")
TECH = StageDefFacts(id=4, name="Rozmowa techniczna", category="internal")
REJECTED = StageDefFacts(
    id=5, name="Odrzucony", category="terminal", terminal_type="rejected"
)
HIRED = StageDefFacts(
    id=6, name="Zatrudniony", category="terminal", terminal_type="hired"
)
QC_TERMINAL = StageDefFacts(id=7, name="QC odrzucone", category="terminal")
DEFS = (QC, DZ, CPRO, TECH, REJECTED, HIRED, QC_TERMINAL)


def _matches(rule, def_id, code) -> bool:
    """Czy wiersz (etap szablonu, kod) spełnia regułę — interpretacja list z SQL."""

    if def_id is None:
        return code in rule.null_def_codes
    for ids, codes in rule.def_groups:
        if def_id in ids:
            return codes is None or code in codes
    return False


def test_qc_cv_to_etap_szablonu_po_nazwie_nie_kod_interview() -> None:
    rule = column_rule(["cv_qc"], DEFS)
    # „QC CV”, dawne „Przepuszczony przez DZ” i kolejka Cpro — każdy kod wiersza.
    assert rule.def_groups[0] == ((1, 2, 3), None)
    # Rozmowa techniczna z kodem `interview` to „Zweryfikowany”, nie QC CV.
    assert not _matches(rule, TECH.id, "interview")
    # Wiersz bez etapu szablonu: sam kod nie daje QC CV.
    assert rule.null_def_codes == ()
    assert not _matches(rule, None, "interview")


def test_zweryfikowany_bierze_kod_interview_bez_nazwy_qc() -> None:
    rule = column_rule(["verified"], DEFS)
    assert _matches(rule, TECH.id, "interview")
    assert _matches(rule, TECH.id, "verified")
    assert _matches(rule, None, "interview")
    assert not _matches(rule, QC.id, "interview")
    assert not _matches(rule, CPRO.id, "screening")


def test_etap_konczacy_z_qc_w_nazwie_to_zamkniecie() -> None:
    assert not _matches(column_rule(["cv_qc"], DEFS), QC_TERMINAL.id, "interview")
    assert _matches(column_rule(["closed"], DEFS), QC_TERMINAL.id, "interview")


def test_zatrudniony_z_typu_konca_i_z_kodu() -> None:
    rule = column_rule(["hired"], DEFS)
    assert _matches(rule, HIRED.id, "rejected")  # typ końca rozstrzyga
    assert _matches(rule, REJECTED.id, "hired")  # kod `hired` wygrywa z kategorią
    assert not _matches(rule, REJECTED.id, "rejected")
    assert _matches(rule, None, "onboarding")


def test_regula_jest_lustrem_board_column_for_dla_kazdej_pary() -> None:
    """Każda para (etap szablonu albo brak, kod) — ten sam wynik co Tablica."""

    for wanted in STAGE_COLUMNS:
        rule = column_rule([wanted], DEFS)
        for sd in (*DEFS, None):
            for code in ALL_CODES:
                expected = (
                    board_column_for(
                        sd.name if sd else None,
                        code,
                        category=sd.category if sd else None,
                        terminal_type=sd.terminal_type if sd else None,
                    )
                    == wanted
                )
                got = _matches(rule, sd.id if sd else None, code)
                assert got == expected, (wanted, sd, code)


def test_kilka_kolumn_to_lub_a_nieznana_kolumna_nic_nie_daje() -> None:
    rule = column_rule(["cv_qc", "cv_sent"], DEFS)
    assert _matches(rule, QC.id, "interview")
    assert _matches(rule, None, "cv_sent")
    empty = column_rule(["nie-ma-takiej"], DEFS)
    assert empty.is_empty


def test_row_column_czyta_enumy() -> None:
    from app.models.pipeline_template import StageCategoryEnum

    assert row_column("QC CV", PipelineStage.interview) == "cv_qc"
    assert (
        row_column(None, PipelineStage.rejected, category=StageCategoryEnum.terminal)
        == "closed"
    )


def _sql(rule) -> str:
    stmt = select(CandidateStage.id).where(
        column_clause(rule, CandidateStage.stage_def_id, CandidateStage.stage)
    )
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_sql_ma_grupy_etapow_i_wiersze_bez_etapu_szablonu() -> None:
    sql = _sql(column_rule(["verified"], DEFS))
    assert "stage_def_id IN (4)" in sql
    assert "stage_def_id IS NULL" in sql
    assert "'interview'" in sql and "'verified'" in sql


def test_pusta_regula_daje_falsz_nie_cala_baze() -> None:
    sql = _sql(column_rule([], DEFS))
    assert "false" in sql.lower()


@pytest.mark.parametrize("columns", [["cv_qc"], ["closed", "new"]])
def test_regula_jest_deterministyczna(columns) -> None:
    assert column_rule(columns, DEFS) == column_rule(columns, tuple(reversed(DEFS)))
