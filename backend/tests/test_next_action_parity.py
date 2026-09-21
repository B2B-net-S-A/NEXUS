"""Reguła „następna akcja / kto ma ruch" — parytet z frontem.

Czyta TEN SAM plik przypadków co
``frontend/src/lib/__tests__/pipeline-next-action.fixtures.test.ts``. Reguła
żyje w dwóch językach (TS na karcie, Python w agregatach listy rekrutacji),
więc pilnuje jej jedna tabela, a nie dwa zestawy asercji.
"""

import json
from pathlib import Path

import pytest

from app.services import pipeline_next_action as rule
from app.services.pipeline_next_action import StageColumn

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "frontend/src/lib/__fixtures__/next-action-cases.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_CASES = _DATA["cases"]


def test_thresholds_match_the_shared_fixture():
    assert _DATA["nudge_days"] == rule.NUDGE_DAYS
    assert _DATA["stuck_days"] == rule.STUCK_DAYS


def test_fixture_is_not_empty():
    # Pusta lista przypadków przechodziłaby parametryzację bez jednej asercji.
    assert len(_CASES) >= 20


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_next_action_matches_frontend(case):
    action = rule.next_action_for(
        StageColumn.from_meta(case["column"]),
        days_in_stage=case["item"]["days_in_stage"],
        screening_done=case["item"]["screening_done"],
        hm_veto=bool(case["item"]["hm_veto"]),
        group=case["group"],
        sla_days=case["sla_days"],
    )
    assert {
        "label": action.label,
        "tone": action.tone,
        "kind": action.kind,
        "owner": action.owner,
    } == case["expected"]


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_aggregate_owner_mode_agrees_with_the_card_rule(case):
    """Tryb kolumny (bez karty) daje tego samego właściciela co reguła karty.

    Jedyny świadomy wyjątek: weto HM na etapie klienta przed ``NUDGE_DAYS``.
    """
    col = StageColumn.from_meta(case["column"])
    mode = rule.recruiter_owner_mode(col, case["group"])
    days = case["item"]["days_in_stage"] or 0
    by_mode = mode == "always" or (mode == "after_nudge" and days >= rule.NUDGE_DAYS)
    expected = case["expected"]["owner"] == "recruiter"
    veto_exception = (
        bool(case["item"]["hm_veto"])
        and mode == "after_nudge"
        and days < rule.NUDGE_DAYS
    )
    if veto_exception:
        assert expected and not by_mode
    else:
        assert by_mode == expected


def _col(stage="new", category="internal", terminal_type=None, name=None):
    return StageColumn(
        stage=stage, category=category, terminal_type=terminal_type, name=name
    )


def test_default_b2b_positional_grouping():
    """Korekty pozycyjne `groupKanbanColumns` na układzie „Default B2B"."""
    columns = [
        _col("posting", name="Ogłoszenia"),
        _col("new", name="Nowi"),
        _col("screening", name="Screening"),
        _col("new", name="Przepuszczony przez DZ"),
        _col("verified", name="Zweryfikowany"),
        _col("cv_sent", name="CV Wysłane"),
        _col("new", name="Preparation Meeting"),
        _col("client_interview", "external", name="Interview Klient"),
        _col("new", name="Umowa wysłana"),
        _col("new", name=" umowa PODPISANA "),
        _col("hired", "terminal", "hired", "Zatrudniony"),
        _col("new", "terminal", "rejected", "Odrzucony (własny)"),
        _col("withdrawn", "terminal", None, "Wycofany"),
    ]
    assert rule.group_keys_for_columns(columns) == [
        "posting",
        "intake",
        "screening",
        "verification",
        "verification",
        "client",
        "client",
        "client",
        "contract",
        "contract",
        "contract",
        "closed",
        "closed",
    ]
    assert rule.owner_modes_for_columns(columns) == [
        # Stos wejściowy to „Do przejrzenia", nie „wymaga ruchu" (21.09.2026).
        "review",
        "review",
        "always",
        "always",
        "always",
        "after_nudge",
        "after_nudge",
        "after_nudge",
        "always",
        "always",
        "never",
        "never",
        "never",
    ]


def test_without_a_screening_column_internal_stages_stay_intake():
    columns = [_col("new", name="A"), _col("new", name="B")]
    assert rule.group_keys_for_columns(columns) == ["intake", "intake"]


def test_count_recruiter_owned():
    assert (
        rule.count_recruiter_owned(
            ["always", "after_nudge", "never"], [(3, 1), (4, 2), (9, 9)]
        )
        == 5
    )
