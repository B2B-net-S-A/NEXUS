"""Etap „QC CV” do seedów testów weryfikacji (0797, decyzja Artura 27.11.2026).

Od 0797 weryfikacja liczy się w chwili wejścia pary na QC CV albo dalej, a
kolumnę QC CV poznaje się po nazwie etapu (kod ruchu to `interview`). Test,
który potrzebuje weryfikacji bez rekomendacji („QC CV”, ale bez „CV
wysłane”), dokłada ruch na ten etap.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


async def qc_cv_stage_def_id(db) -> int:
    """Nowy szablon z etapem „QC CV”; zwraca id etapu (sesja po `flush`)."""
    template = PipelineTemplate(name=f"QC CV {uuid.uuid4().hex[:8]}")
    db.add(template)
    await db.flush()
    stage_def = PipelineStageDef(
        template_id=template.id,
        name="QC CV",
        order=1,
        category=StageCategoryEnum.internal,
        legacy_enum_value="interview",
    )
    db.add(stage_def)
    await db.flush()
    return stage_def.id


def qc_cv_move(
    *,
    candidate_id: int,
    job_id: int,
    moved_at: datetime,
    moved_by: int | None,
    stage_def_id: int,
) -> CandidateStage:
    """Ruch pary na „QC CV” — od 0797 to on jest chwilą weryfikacji."""
    return CandidateStage(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=PipelineStage.interview,
        stage_def_id=stage_def_id,
        moved_at=moved_at,
        moved_by=moved_by,
    )
