"""Runda 10 (F09): automat karty nie przeskakuje „CV wysłane”.

Czyste reguły ``needs_sent_cv`` / ``has_sent_cv`` z ``pipeline_auto_move`` —
bez bazy. Test ścieżki z bazą (terminy od klienta) jest w
``test_pipeline_v4_auto_moves.py``.
"""

from __future__ import annotations

import pytest

from app.models.pipeline_template import PipelineStageDef, StageCategoryEnum
from app.models.recruitment_pipeline import PipelineStage
from app.services.pipeline_auto_move import has_sent_cv, needs_sent_cv

TEMPLATE = 41


def _def(name: str, order: int, legacy: str | None, template_id: int = TEMPLATE):
    return PipelineStageDef(
        id=order,
        template_id=template_id,
        name=name,
        order=order,
        category=StageCategoryEnum.internal,
        is_terminal=False,
        legacy_enum_value=legacy,
    )


CV_DEF = _def("CV wysłane", 5, "cv_sent")


@pytest.mark.parametrize(
    "target,expected",
    [
        (PipelineStage.client_interview, True),
        (PipelineStage.acceptance, True),
        (PipelineStage.hired, True),
        (PipelineStage.cv_sent, False),
        (PipelineStage.verified, False),
        (PipelineStage.rejected, False),
    ],
)
def test_needs_sent_cv_only_for_targets_past_cv_sent(target, expected):
    assert needs_sent_cv(target, None) is expected


@pytest.mark.parametrize(
    "stage",
    [
        PipelineStage.posting,
        PipelineStage.new,
        PipelineStage.screening,
        PipelineStage.verified,
        PipelineStage.interview,
    ],
)
def test_enum_stages_before_cv_sent_have_no_sent_cv(stage):
    assert not has_sent_cv(
        stage=stage, stage_def=None, cv_sent_def=CV_DEF, template_id=TEMPLATE
    )


@pytest.mark.parametrize("stage", [PipelineStage.cv_sent, PipelineStage.acceptance])
def test_cv_sent_column_and_later_pass(stage):
    assert has_sent_cv(
        stage=stage, stage_def=None, cv_sent_def=CV_DEF, template_id=TEMPLATE
    )


def test_qc_and_cpro_queue_stages_are_not_a_sent_cv():
    # „Przepuszczony przez DZ” ma kod `interview`, a jest kolumną QC CV;
    # kolejka Cpro u Nordei też — obie przed wysłaniem.
    for name, legacy in (
        ("Przepuszczony przez DZ", "interview"),
        ("QC CV", "interview"),
        ("NORDEA: Wysłać do Cpro", "screening"),
    ):
        stage_def = _def(name, 7, legacy)
        assert not has_sent_cv(
            stage=PipelineStage(legacy),
            stage_def=stage_def,
            cv_sent_def=CV_DEF,
            template_id=TEMPLATE,
        ), name


def test_own_template_stage_uses_template_position():
    before = _def("Własny wczesny", 2, None)
    after = _def("Własny po wysłaniu", 6, None)
    assert not has_sent_cv(
        stage=PipelineStage.new,
        stage_def=before,
        cv_sent_def=CV_DEF,
        template_id=TEMPLATE,
    )
    assert has_sent_cv(
        stage=PipelineStage.new,
        stage_def=after,
        cv_sent_def=CV_DEF,
        template_id=TEMPLATE,
    )
    # Etap własny z INNEGO szablonu (import) — pozycja nic nie znaczy.
    foreign = _def("Własny obcy", 9, None, template_id=TEMPLATE + 1)
    assert not has_sent_cv(
        stage=PipelineStage.new,
        stage_def=foreign,
        cv_sent_def=CV_DEF,
        template_id=TEMPLATE,
    )
