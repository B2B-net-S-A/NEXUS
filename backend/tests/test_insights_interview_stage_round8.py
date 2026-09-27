"""R8-V2-2: „Interview” w raportach Insights = wyłącznie `client_interview`.

Od v5 kod `interview` to etap QC CV („Przepuszczony przez DZ”), czyli PRZED
wysłaniem CV. Decyzja właściciela 26.09.2026: rozmowy w KPI i Insights to
wyłącznie rozmowy u klienta. Widok Zespół i Mój miesiąc liczyły już
`client_interview`; raporty „Czas i konwersje”, „Aktywność zespołu” i wykres
roczny nadal brały QC.
"""

from __future__ import annotations

from app.api.insights_charts import YEARLY_CONVERSIONS, YEARLY_SERIES
from app.api.insights_recruitment import CONVERSIONS, FUNNEL_STAGES
from app.api.insights_team import STAGE_COLUMNS


def _operands(conversions: list[dict]) -> set[str]:
    return {c["numerator"] for c in conversions} | {
        c["denominator"] for c in conversions
    }


def test_funnel_conversions_use_client_interview():
    assert "interview" not in _operands(CONVERSIONS)
    assert "client_interview" in _operands(CONVERSIONS)
    (qc,) = [s for s in FUNNEL_STAGES if s["stage"] == "interview"]
    assert qc["label"] == "QC CV"


def test_team_table_interviews_column_is_client_interview():
    (column,) = [c for c in STAGE_COLUMNS if c["key"] == "interviews"]
    assert column["stage"] == "client_interview"
    assert column["label"] == "Rozmowy u klienta"


def test_yearly_chart_interview_series_is_client_interview():
    (series,) = [s for s in YEARLY_SERIES if s["key"] == "interview"]
    assert series["stage"] == "client_interview"
    assert "interview" not in _operands(YEARLY_CONVERSIONS)
