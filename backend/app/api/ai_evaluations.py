"""Admin-run, recruiter-reviewed blind AI evaluations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import AIError, AIRequest, ai_gateway
from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.ai_evaluation import (
    AIEvalCase,
    AIEvalLabel,
    AIEvalOutput,
    AIEvalRun,
    AIEvalSet,
)
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.user import User
from app.services.ai_evaluation import (
    blind_variants,
    decrypt_output,
    encrypt_output,
    ensure_encryption_configured,
    output_expiry,
    parser_metrics,
    purge_expired_outputs,
)
from app.services.cv_parser import openai_cv_parse_json_schema, validate_cv_parse
from app.services.llm_prompts import CV_ENRICHMENT


router = APIRouter(tags=["ai-evaluations"])


class EvalSetCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    candidate_ids: list[int] = Field(min_length=1, max_length=500)
    slice_metadata: dict[str, Any] = Field(default_factory=dict)
    model_config = {"extra": "forbid"}


class EvalRunCreate(BaseModel):
    eval_set_id: int
    reviewer_ids: list[int] = Field(min_length=1, max_length=20)
    mode: Literal["offline", "shadow"] = "offline"
    model_config = {"extra": "forbid"}


class EvalLabelSubmit(BaseModel):
    preferred_variant: Literal["A", "B"]
    rating_a: int = Field(ge=1, le=5)
    rating_b: int = Field(ge=1, le=5)
    metrics: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)
    model_config = {"extra": "forbid"}


def _http_error(exc: AIError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
    )


def _messages(cv_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CV_ENRICHMENT.system_prompt or ""},
        {"role": "user", "content": CV_ENRICHMENT.render(cv_text=cv_text[:8000])},
    ]


@router.post("/admin/ai-evals/sets", status_code=201)
async def create_eval_set(
    payload: EvalSetCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    candidate_ids = list(dict.fromkeys(payload.candidate_ids))
    rows = (
        await db.execute(
            select(Candidate.id, Candidate.raw_cv_text).where(
                Candidate.id.in_(candidate_ids)
            )
        )
    ).all()
    available = {row.id for row in rows if row.raw_cv_text and row.raw_cv_text.strip()}
    missing = sorted(set(candidate_ids) - available)
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cases require an existing CV source reference",
                "candidate_ids": missing,
            },
        )
    eval_set = AIEvalSet(
        name=payload.name.strip(),
        feature=AIFeatureKey.cv_parser.value,
        description=payload.description,
        created_by=admin.id,
    )
    db.add(eval_set)
    await db.flush()
    for candidate_id in candidate_ids:
        db.add(
            AIEvalCase(
                eval_set_id=eval_set.id,
                candidate_id=candidate_id,
                source_ref="candidate.raw_cv_text",
                slice_metadata=payload.slice_metadata,
            )
        )
    await db.commit()
    return {"id": eval_set.id, "cases": len(candidate_ids), "stores_cv_copies": False}


@router.post("/admin/ai-evals/runs", status_code=201)
async def create_eval_run(
    payload: EvalRunCreate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    eval_set = await db.get(AIEvalSet, payload.eval_set_id)
    if eval_set is None or eval_set.feature != AIFeatureKey.cv_parser.value:
        raise HTTPException(status_code=404, detail="Evaluation set not found")
    if payload.mode == "shadow":
        completed_offline = await db.scalar(
            select(func.count(AIEvalRun.id)).where(
                AIEvalRun.eval_set_id == eval_set.id,
                AIEvalRun.mode == "offline",
                AIEvalRun.status == "completed",
            )
        )
        if not completed_offline:
            raise HTTPException(
                status_code=409,
                detail="Shadow requires a completed offline run for this set",
            )
    reviewer_ids = list(dict.fromkeys(payload.reviewer_ids))
    found_reviewers = set(
        (await db.scalars(select(User.id).where(User.id.in_(reviewer_ids)))).all()
    )
    if found_reviewers != set(reviewer_ids):
        raise HTTPException(status_code=422, detail="Unknown reviewer")
    cases = (
        await db.scalars(
            select(AIEvalCase).where(AIEvalCase.eval_set_id == eval_set.id)
        )
    ).all()
    if not cases:
        raise HTTPException(status_code=422, detail="Evaluation set is empty")
    run = AIEvalRun(
        eval_set_id=eval_set.id,
        feature=AIFeatureKey.cv_parser.value,
        mode=payload.mode,
        status="draft",
        champion_provider="anthropic",
        champion_model="active-route",
        challenger_provider="openai",
        challenger_model="gpt-5.6-terra",
        created_by=admin.id,
    )
    db.add(run)
    await db.flush()
    for case in cases:
        for reviewer_id in reviewer_ids:
            db.add(AIEvalLabel(run_id=run.id, case_id=case.id, reviewer_id=reviewer_id))
    eval_set.frozen = True
    await db.commit()
    return {
        "id": run.id,
        "status": run.status,
        "cases": len(cases),
        "reviewers": len(reviewer_ids),
    }


@router.post("/admin/ai-evals/runs/{run_id}/execute")
async def execute_eval_run(
    run_id: int,
    admin: AdminUser,
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del admin
    try:
        ensure_encryption_configured()
    except AIError as exc:
        raise _http_error(exc) from exc
    run = await db.get(AIEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    if run.status in {"completed", "review"}:
        return {"id": run.id, "status": run.status, "processed": 0}

    cases = (
        await db.scalars(
            select(AIEvalCase)
            .where(AIEvalCase.eval_set_id == run.eval_set_id)
            .where(
                ~select(AIEvalOutput.id)
                .where(
                    and_(
                        AIEvalOutput.run_id == run.id,
                        AIEvalOutput.case_id == AIEvalCase.id,
                    )
                )
                .exists()
            )
            .order_by(AIEvalCase.id)
            .limit(limit)
        )
    ).all()
    run.status = "running"
    run.started_at = run.started_at or datetime.now(timezone.utc)
    await db.commit()
    processed = 0
    for case in cases:
        candidate = await db.get(Candidate, case.candidate_id)
        if candidate is None or not candidate.raw_cv_text:
            run.status = "failed"
            await db.commit()
            raise HTTPException(
                status_code=409, detail="Referenced CV source disappeared"
            )
        common = dict(
            user_id=run.created_by,
            subject_type="candidate",
            subject_id=candidate.id,
            messages=_messages(candidate.raw_cv_text),
            prompt_version=f"{CV_ENRICHMENT.name}_v{CV_ENRICHMENT.version}",
            schema_version="cv_parse_v2",
            structured_validator=validate_cv_parse,
            pii=True,
        )
        try:
            champion = await ai_gateway.call(
                AIRequest(
                    feature=AIFeatureKey.cv_parser,
                    metadata={"evaluation": True},
                    **common,
                )
            )
            challenger = await ai_gateway.call(
                AIRequest(
                    feature=AIFeatureKey.cv_parser_challenger,
                    metadata={
                        "evaluation": True,
                        "shadow": run.mode == "shadow",
                        "response_format": {
                            "type": "json_schema",
                            "name": "nexus_cv_parse_v2",
                            "strict": True,
                            "schema": openai_cv_parse_json_schema(),
                        },
                    },
                    **common,
                )
            )
        except AIError as exc:
            run.status = "failed"
            await db.commit()
            raise _http_error(exc) from exc
        for variant, result in (("champion", champion), ("challenger", challenger)):
            ciphertext, nonce, output_hash = encrypt_output(
                result.content, run_id=run.id, case_id=case.id, variant=variant
            )
            db.add(
                AIEvalOutput(
                    run_id=run.id,
                    case_id=case.id,
                    variant=variant,
                    provider=result.provider,
                    model=result.model,
                    ciphertext=ciphertext,
                    nonce=nonce,
                    output_hash=output_hash,
                    deterministic_metrics=parser_metrics(result.content),
                    expires_at=output_expiry(),
                )
            )
        await db.commit()
        processed += 1

    remaining = await db.scalar(
        select(func.count(AIEvalCase.id))
        .where(AIEvalCase.eval_set_id == run.eval_set_id)
        .where(
            ~select(AIEvalOutput.id)
            .where(
                and_(
                    AIEvalOutput.run_id == run.id, AIEvalOutput.case_id == AIEvalCase.id
                )
            )
            .exists()
        )
    )
    if not remaining:
        run.status = "review"
        await db.commit()
    return {
        "id": run.id,
        "status": run.status,
        "processed": processed,
        "remaining": int(remaining or 0),
    }


@router.get("/ai-evals/assignments")
async def my_eval_assignments(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    await purge_expired_outputs(db)
    await db.commit()
    rows = (
        await db.execute(
            select(AIEvalLabel, AIEvalRun, AIEvalCase)
            .join(AIEvalRun, AIEvalRun.id == AIEvalLabel.run_id)
            .join(AIEvalCase, AIEvalCase.id == AIEvalLabel.case_id)
            .where(AIEvalLabel.reviewer_id == current_user.id)
            .order_by(AIEvalLabel.id.desc())
        )
    ).all()
    response: list[dict[str, Any]] = []
    for label, run, case in rows:
        outputs = (
            await db.scalars(
                select(AIEvalOutput).where(
                    AIEvalOutput.run_id == run.id, AIEvalOutput.case_id == case.id
                )
            )
        ).all()
        by_variant = {row.variant: row for row in outputs}
        blind = blind_variants(run.id, case.id)
        item: dict[str, Any] = {
            "assignment_id": label.id,
            "run_id": run.id,
            "case_id": case.id,
            "candidate_id": case.candidate_id,
            "status": run.status,
            "submitted": label.submitted_at is not None,
            "outputs_ready": len(by_variant) == 2,
        }
        if len(by_variant) == 2:
            try:
                item["variant_a"] = decrypt_output(by_variant[blind["A"]])
                item["variant_b"] = decrypt_output(by_variant[blind["B"]])
            except AIError as exc:
                item["outputs_ready"] = False
                item["output_error"] = exc.code
        if run.status == "completed":
            item["unblinded"] = {
                letter: {
                    "provider": by_variant[variant].provider,
                    "model": by_variant[variant].model,
                }
                for letter, variant in blind.items()
                if variant in by_variant
            }
        response.append(item)
    return response


@router.post("/ai-evals/assignments/{assignment_id}/label")
async def submit_eval_label(
    assignment_id: int,
    payload: EvalLabelSubmit,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    label = await db.scalar(
        select(AIEvalLabel).where(
            AIEvalLabel.id == assignment_id,
            AIEvalLabel.reviewer_id == current_user.id,
        )
    )
    if label is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    run = await db.get(AIEvalRun, label.run_id)
    if run is None or run.status not in {"review", "running"}:
        raise HTTPException(status_code=409, detail="Run is not open for review")
    label.preferred_variant = payload.preferred_variant
    label.rating_a = payload.rating_a
    label.rating_b = payload.rating_b
    label.metrics = payload.metrics
    label.comment = payload.comment
    label.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"assignment_id": label.id, "submitted": True}


@router.post("/admin/ai-evals/runs/{run_id}/complete")
async def complete_eval_run(
    run_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del admin
    run = await db.get(AIEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    pending = await db.scalar(
        select(func.count(AIEvalLabel.id)).where(
            AIEvalLabel.run_id == run.id, AIEvalLabel.submitted_at.is_(None)
        )
    )
    if pending:
        raise HTTPException(
            status_code=409,
            detail={"message": "Reviews are incomplete", "pending": int(pending)},
        )
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": run.id, "status": run.status, "unblinded": True}
