"""Move the contract's candidate through signing-related pipeline stages.

When a B2B contract is sent for signature the candidate advances to
``Umowa wysłana``; when the signed PDF comes back, to ``Umowa podpisana``;
and when it comes back signed by BOTH parties (fully executed), to
``Zatrudniony``. The first two live in the Default B2B template
(``Umowa wysłana`` already existed; ``Umowa podpisana`` is added by migration
0135); ``Zatrudniony`` is the pre-existing terminal hired stage.

Best-effort + graceful: if the contract has no job, or the job's template has
no such stage, we skip silently — a pipeline move must never break signing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage, PipelineStage

logger = logging.getLogger(__name__)

STAGE_SENT = "Umowa wysłana"
STAGE_SIGNED = "Umowa podpisana"
# Fully-executed (signed by BOTH the consultant and our company side) → hired.
# "Zatrudniony" already exists in Default B2B (template 1) with
# legacy_enum_value="hired", so the generic move below resolves PipelineStage.hired
# — which every hired/employment/KPI query keys off (e.g. candidates.py "U klienta").
STAGE_HIRED = "Zatrudniony"


async def move_candidate_for_signing(
    db: AsyncSession,
    contract: Contract | None,
    *,
    stage_name: str,
    moved_by: int,
) -> None:
    """Advance the contract's candidate to ``stage_name`` (best-effort)."""
    if contract is None or contract.candidate_id is None or contract.job_id is None:
        return

    template_id: int | None = None
    job = await db.get(Job, contract.job_id)
    if job is not None:
        template_id = job.pipeline_template_id
    if template_id is None:
        template_id = await db.scalar(
            select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
        )
    if template_id is None:
        return

    stage_def = await db.scalar(
        select(PipelineStageDef).where(
            PipelineStageDef.template_id == template_id,
            PipelineStageDef.name == stage_name,
        )
    )
    if stage_def is None:
        logger.info(
            "signing pipeline move: stage %r not in template %s — skip",
            stage_name,
            template_id,
        )
        return

    legacy = PipelineStage.new
    if stage_def.legacy_enum_value:
        try:
            legacy = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy = PipelineStage.new
    # Belt-and-suspenders: hire detection ("U klienta", placements, KPI) keys
    # strictly off the legacy `stage` enum == PipelineStage.hired. In Default
    # B2B "Zatrudniony" carries legacy_enum_value="hired", but a custom template
    # could mis-seed it — force the hire signal so the placement always lands.
    if stage_name == STAGE_HIRED and legacy is not PipelineStage.hired:
        legacy = PipelineStage.hired

    db.add(
        CandidateStage(
            candidate_id=contract.candidate_id,
            job_id=contract.job_id,
            stage=legacy,
            stage_def_id=stage_def.id,
            moved_at=datetime.now(timezone.utc),
            moved_by=moved_by,
            notes=f"Auto: {stage_name} (podpis umowy)",
        )
    )
    logger.info(
        "signing pipeline move: candidate %s → %r (job %s)",
        contract.candidate_id,
        stage_name,
        contract.job_id,
    )
