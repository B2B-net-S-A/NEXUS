"""Bounded, metered synthetic factual-gate evaluation (no candidate/document writes).

Run validation without credentials: python -m scripts.eval_cv_factual_gate --validate-only
Real evaluation: python -m scripts.eval_cv_factual_gate --models all --output /tmp/cv-gate.json
The real run honors the normal AI master switch and quota, writes AI usage records,
and needs the application's provider credentials. It never queries candidate data.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.ai_metering import AIProviderCall
from app.models.app_setting import AppSetting
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.cv_generator_b2b.factual_verification import (
    FactualVerificationError,
    VERIFICATION_PROMPT,
    REVIEW_RESPONSE_SCHEMA_SHA256,
    verify_final_cv,
)
from app.services.cv_generator_b2b.provider import (
    CVGeneratorAIError,
    _fallback_models,
    _model,
)


CORPUS_PATH = Path(__file__).parents[1] / "app/data/cv_quality/factual_gate_v1.json"


def load_cases() -> tuple[list[dict], str]:
    raw = CORPUS_PATH.read_bytes()
    corpus = json.loads(raw)
    cases = corpus["cases"]
    if corpus["schema_version"] != 1 or len(cases) != 40:
        raise ValueError("Unexpected corpus version/size")
    if len({case["id"] for case in cases}) != 40:
        raise ValueError("Duplicate case identifiers")
    if sum(case["expected_supported"] is True for case in cases) != 20:
        raise ValueError("Expected twenty positive controls")
    if {case["language"] for case in cases} != {"pl", "en"}:
        raise ValueError("Both document languages are required")
    for case in cases:
        if not isinstance(case["document"], dict) or not case["cv_text"].strip():
            raise ValueError("Empty source/document")
    return cases, hashlib.sha256(raw).hexdigest()


def score(expected: bool, outcome: str) -> bool:
    # A broken protocol/provider is never counted as a correct hallucination rejection.
    return outcome == ("accepted" if expected else "semantic_rejection")


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run_key(value: str) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,2}", value):
        raise ValueError("Invalid evaluation run identity")
    return "cv_quality_eval:" + value


async def claim_run(key: str, report: dict) -> dict | None:
    """A receipt survives application restarts; a cron tick cannot bill twice."""
    async with AsyncSessionLocal() as db:
        claimed = await db.scalar(
            insert(AppSetting)
            .values(key=key, value=report)
            .on_conflict_do_nothing(index_elements=[AppSetting.key])
            .returning(AppSetting.key)
        )
        await db.commit()
        if claimed:
            return None
        return (await db.get(AppSetting, key)).value


async def checkpoint(output: Path, report: dict, key: str | None) -> None:
    write_report(output, report)
    if key:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(AppSetting).where(AppSetting.key == key).values(value=report)
            )
            await db.commit()


async def evaluate(
    output: Path,
    models: str,
    limit: int,
    identity: str | None = None,
    expected_sha: str | None = None,
) -> int:
    if expected_sha and os.environ.get("GIT_SHA") != expected_sha:
        write_report(
            output,
            {
                "complete": False,
                "stop_reason": "runtime_revision_mismatch",
                "results": [],
            },
        )
        return 2
    cases, corpus_hash = load_cases()
    requested_models = list(
        dict.fromkeys([_model(), *(_fallback_models() if models == "all" else [])])
    )
    original_env = {
        name: os.environ.get(name)
        for name in ("CV_B2B_MODEL", "CV_B2B_FALLBACK_MODELS")
    }
    report = {
        "scope": "synthetic final-verifier diagnostics, not complete CV generation",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runtime_sha": os.environ.get("GIT_SHA", "unknown"),
        "run_identity": identity,
        "corpus_sha256": corpus_hash,
        "prompt_sha256": hashlib.sha256(VERIFICATION_PROMPT.encode()).hexdigest(),
        "response_schema_sha256": REVIEW_RESPONSE_SCHEMA_SHA256,
        "requested_models": requested_models,
        "cases_per_model": limit,
        "complete": False,
        "results": [],
    }
    key = run_key(identity) if identity else None
    if key:
        previous = await claim_run(key, report)
        if previous is not None:
            # Never restart an unfinished run based on a missing local file.
            write_report(output, {**previous, "replayed_receipt": True})
            return 2
    await checkpoint(output, report, key)
    deadline = time.monotonic() + 1800
    try:
        for model in requested_models:
            # Process-local overrides only. Never mutate production configuration.
            # Test each configured model independently, without hidden fallback.
            os.environ["CV_B2B_MODEL"] = model
            os.environ["CV_B2B_FALLBACK_MODELS"] = ""
            for case in cases[:limit]:
                if time.monotonic() > deadline:
                    report["stop_reason"] = "deadline"
                    return 2
                started = time.monotonic()
                outcome = "provider_error"
                operation_id = None
                async with AsyncSessionLocal() as db:
                    try:
                        async with ai_feature(db, AIFeatureKey.cv_generator) as state:
                            operation_id = state.operation_id
                            await asyncio.to_thread(
                                verify_final_cv,
                                case["document"],
                                cv_text=case["cv_text"],
                                screening_notes=case["screening_notes"],
                                identity=case["identity"],
                                request_id=f"cv-gate-eval:{case['id']}",
                            )
                            outcome = "accepted"
                    except FactualVerificationError as error:
                        outcome = error.reason
                    except AIQuotaExceeded:
                        report["stop_reason"] = "quota_or_feature_disabled"
                        return 2
                    except CVGeneratorAIError:
                        outcome = "provider_error"
                async with AsyncSessionLocal() as db:
                    calls = (
                        list(
                            (
                                await db.scalars(
                                    select(AIProviderCall).where(
                                        AIProviderCall.operation_id == operation_id
                                    )
                                )
                            ).all()
                        )
                        if operation_id
                        else []
                    )
                costs = [call.estimated_cost_usd for call in calls]
                report["results"].append(
                    {
                        "case_id": case["id"],
                        "requested_model": model,
                        "actual_models": sorted({call.model for call in calls}),
                        "operation_id": operation_id,
                        "expected_supported": case["expected_supported"],
                        "outcome": outcome,
                        "passed": score(case["expected_supported"], outcome),
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                        "provider_calls": len(calls),
                        "metering_complete": bool(calls)
                        and all(
                            call.model == model and call.estimated_cost_usd is not None
                            for call in calls
                        ),
                        "input_tokens": sum(call.input_tokens for call in calls)
                        if calls
                        and all(call.input_tokens is not None for call in calls)
                        else None,
                        "output_tokens": sum(call.output_tokens for call in calls)
                        if calls
                        and all(call.output_tokens is not None for call in calls)
                        else None,
                        "estimated_cost_usd": str(sum(costs))
                        if costs and all(cost is not None for cost in costs)
                        else None,
                    }
                )
                await checkpoint(output, report, key)
        report["complete"] = True
        return (
            0
            if all(
                row["passed"] and row["metering_complete"] for row in report["results"]
            )
            else 1
        )
    finally:
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = sum(row["passed"] for row in report["results"])
        report["evaluated"] = len(report["results"])
        await checkpoint(output, report, key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--models", choices=("primary", "all"), default="all")
    parser.add_argument("--limit", type=int, choices=range(1, 41), default=40)
    parser.add_argument("--output", type=Path, default=Path("/tmp/cv-gate-eval.json"))
    parser.add_argument(
        "--run-key",
        help="GitHub run ID and attempt; repeat reads receipt without calling AI",
    )
    parser.add_argument(
        "--expected-sha", help="Refuse provider calls on a different deployment"
    )
    args = parser.parse_args()
    if args.validate_only:
        cases, fingerprint = load_cases()
        print(json.dumps({"cases": len(cases), "corpus_sha256": fingerprint}))
        return 0
    return asyncio.run(
        evaluate(args.output, args.models, args.limit, args.run_key, args.expected_sha)
    )


if __name__ == "__main__":
    raise SystemExit(main())
