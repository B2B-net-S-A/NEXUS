"""Panel „Ranking kandydatów”: ważności ↔ wagi silnika, walidacja, lustro 0501.

Bez bazy. Ważności panelu muszą dawać dokładnie te udziały w „Dop.”, które
liczy ``base_fit_profile`` — inaczej podgląd na ekranie kłamałby o rankingu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import ranking_weights as rw
from app.services.request_matching_context import base_fit_profile
from app.services.scoring_service import DEFAULT_PROFILE, WeightProfile

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0501_scoring_weight_changes.py"


def _panel(semantic=60, skills=10, location=5, threshold=70) -> rw.PanelWeights:
    return rw.PanelWeights(
        semantic=semantic, skills=skills, location=location, threshold=threshold
    )


def _engine_shares(profile: WeightProfile) -> dict[str, float]:
    base = base_fit_profile(profile)
    return {name: getattr(base, name) for name in rw.BASE_LAYERS}


def test_built_in_weights_read_as_60_10_5():
    panel = rw.panel_from_profile(DEFAULT_PROFILE, threshold=70)
    assert (panel.semantic, panel.skills, panel.location) == (60, 10, 5)


def test_publishing_built_in_importances_changes_no_score():
    weights = rw.engine_weights(_panel())
    profile = WeightProfile(**weights)
    for name, share in _engine_shares(DEFAULT_PROFILE).items():
        assert _engine_shares(profile)[name] == pytest.approx(share, abs=1e-3)
    assert sum(weights.values()) == pytest.approx(100.0, abs=1e-3)
    assert weights["availability"] == 0
    assert weights["champion_fit"] == rw.CHAMPION_RESERVE


@pytest.mark.parametrize(
    "values", [(60, 30, 5), (60, 10, 20), (100, 0, 0), (0, 0, 5), (35, 35, 35)]
)
def test_panel_shares_equal_what_the_engine_scores_with(values):
    panel = _panel(*values)
    profile = WeightProfile.from_record(
        SimpleNamespace(id=9, name="x", weights=rw.engine_weights(panel))
    )
    engine = _engine_shares(profile)
    for name, share in rw.panel_shares(panel).items():
        assert engine[name] == pytest.approx(share, abs=0.01)
    total = sum(values) + rw.FIXED_SALARY
    assert rw.panel_shares(panel)["semantic"] == pytest.approx(
        values[0] * 100 / total, abs=0.01
    )


@pytest.mark.parametrize("values", [(60, 30, 5), (45, 25, 10), (100, 0, 0)])
def test_round_trip_panel_engine_panel(values):
    panel = _panel(*values, threshold=75)
    profile = WeightProfile(**rw.engine_weights(panel))
    assert rw.panel_from_profile(profile, threshold=75) == panel


def test_profile_without_salary_reads_as_shares():
    profile = WeightProfile(
        semantic=50, skills=30, salary=0, location=20, availability=0, champion_fit=0
    )
    panel = rw.panel_from_profile(profile, threshold=70)
    assert (panel.semantic, panel.skills, panel.location) == (50, 30, 20)


@pytest.mark.parametrize(
    ("panel", "fragment"),
    [
        (_panel(semantic=101), "od 0 do 100"),
        (_panel(skills=-5), "od 0 do 100"),
        (_panel(0, 0, 0), "co najmniej jedną"),
        (_panel(threshold=45), "od 50 do 90"),
        (_panel(threshold=95), "od 50 do 90"),
    ],
)
def test_validation_rejects_with_polish_message(panel, fragment):
    message = rw.validation_error(panel)
    assert message and fragment in message


def test_validation_accepts_slider_range():
    assert rw.validation_error(_panel(0, 0, 5, 50)) is None
    assert rw.validation_error(_panel(100, 100, 100, 90)) is None


def test_migration_uses_the_single_ddl_source():
    spec = importlib.util.spec_from_file_location("m0501", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    from app.services.ranking_weights_schema import TABLE_DDL

    assert module.revision == "0501_scoring_weight_changes"
    assert module.TABLE_DDL is TABLE_DDL


def test_entrypoint_imports_the_single_ddl_source():
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import ranking_weights_schema" in text
    assert "*_RANKING_WEIGHT_CHANGES_DDL," in text


def test_ddl_is_idempotent_and_kinds_match_the_model():
    from app.models.scoring_weight_change import ScoringWeightChange
    from app.services.ranking_weights_schema import CHANGE_KINDS, TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement
    ddl = " ".join(TABLE_DDL)
    check = next(
        str(c.sqltext)
        for c in ScoringWeightChange.__table__.constraints
        if c.name == "ck_scoring_weight_changes_kind"
    )
    for kind in CHANGE_KINDS:
        assert f"'{kind}'" in ddl
        assert f"'{kind}'" in check


def test_deep_health_probes_the_history_table():
    text = (BACKEND / "app" / "main.py").read_text()
    assert '("scoring_weight_changes", ScoringWeightChange)' in text
    assert '("scoring_weight_measurements", ScoringWeightMeasurement)' in text


def test_measurement_statuses_match_the_model():
    from app.models.scoring_weight_change import ScoringWeightMeasurement
    from app.services.ranking_weights_schema import MEASUREMENT_STATUSES

    check = next(
        str(c.sqltext)
        for c in ScoringWeightMeasurement.__table__.constraints
        if c.name == "ck_scoring_weight_measurements_status"
    )
    for status in MEASUREMENT_STATUSES:
        assert f"'{status}'" in check


def test_nightly_proposals_read_the_panel_threshold():
    source = (BACKEND / "app" / "services" / "auto_full_review.py").read_text()
    assert "settings.AUTO_FULL_REVIEW_MIN_SCORE" not in source
    assert "await nightly_min_score(db)" in source
