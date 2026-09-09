"""Metered full-pipeline synthetic CV evaluation; never writes candidate records.

Requires the normal application database, AI feature admission and provider
credentials. Every run has a durable identity; interrupted runs are not replayed.
Generated artifacts remain explicitly pending human quality review.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import unicodedata
import re
import os
from pathlib import Path
import time

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.ai_metering import AIProviderCall
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.provider import _fallback_models, _model
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    UploadGenerationInput,
    generate_cv_from_uploads,
)
from scripts.eval_cv_factual_gate import checkpoint, claim_run, run_key, write_report
from scripts.prepare_cv_document_corpus import prepare


def generate_case(case, directory):
    """Use the ordinary extraction → editing → final review → DOCX pipeline."""
    source = directory / case["input_file"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != case["input_sha256"]:
        raise ValueError("Corpus input changed")
    rule = CvRuleSnapshot(
        filename_pattern=None,
        spaces_to_underscores=True,
        cv_language=None,
        requires_en_copy=False,
        requires_rodo_consent_block=False,
        generator_instructions=case["client_instructions"] or None,
        max_roles=1 if case["scenario"] == "display_limit" else None,
    )
    result = generate_cv_from_uploads(
        UploadGenerationInput(
            cv_bytes=source.read_bytes(),
            cv_filename=source.name,
            language=case["language"],
            content_mode=case["content_mode"],
            screening_notes=case["screening_notes"],
            client_rule=rule,
        )
    )
    output = directory / f"{case['id']}-generated.docx"
    output.write_bytes(result.docx_bytes)
    payload_path = directory / f"{case['id']}-payload.json"
    write_report(payload_path, result.render_payload)
    actual_months = (
        (result.render_payload.get("source_facts") or {})
        .get("tenure", {})
        .get("career_months")
    )
    source_document = (result.render_payload.get("source_facts") or {}).get(
        "document"
    ) or {}
    source_roles = source_document.get("experience")
    actual_roles = len(source_roles) if isinstance(source_roles, list) else None
    expected = case["expected"]["career_months"]

    # These are source-ledger checks, not translated presentation checks.
    # A matching role count alone cannot prove that named source facts survived.
    def normalized(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    source_text = normalized(json.dumps(source_document, ensure_ascii=False))
    missing_source_facts = [
        fact
        for fact in case["expected"].get("must_preserve", [])
        if normalized(fact) not in source_text
    ]
    return {
        "outcome": "generated",
        "artifact": output.name,
        "payload_artifact": payload_path.name,
        "artifact_sha256": hashlib.sha256(result.docx_bytes).hexdigest(),
        "career_months": actual_months,
        "source_roles": actual_roles,
        "source_role_count_matches": actual_roles == case["expected"]["source_roles"],
        "missing_required_source_facts": missing_source_facts,
        "required_source_facts_preserved": not missing_source_facts,
        "tenure_matches": actual_months == expected if expected is not None else None,
        "warnings_count": len(result.warnings),
        "human_accepted": None,
    }


async def run(
    output: Path,
    *,
    identity: str,
    expected_sha: str,
    limit: int,
    models: str,
    offset: int = 0,
):
    if (
        not 1 <= limit <= 40
        or not 0 <= offset < 40
        or offset + limit > 40
        or models not in {"primary", "all"}
    ):
        raise ValueError("Invalid bounded evaluation request")
    key = run_key(identity).replace("cv_quality_eval:", "cv_document_eval:", 1)
    if (
        not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
        or os.environ.get("GIT_SHA") != expected_sha
    ):
        raise ValueError("Runtime revision mismatch")
    output.mkdir(parents=True, exist_ok=True)
    manifest = prepare(output / "inputs")
    requested = list(
        dict.fromkeys([_model(), *(_fallback_models() if models == "all" else [])])
    )
    report_path = output / "report.json"
    report = {
        "scope": "synthetic complete CV generation; human acceptance required",
        "runtime_sha": expected_sha,
        "run_identity": identity,
        "corpus_sha256": manifest["corpus_sha256"],
        "requested_models": requested,
        "case_offset": offset,
        "case_limit": limit,
        "requested_case_ids": [
            case["id"] for case in manifest["cases"][offset : offset + limit]
        ],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "complete": False,
        "human_accepted": None,
        "results": [],
    }
    previous = await claim_run(key, report)
    if previous is not None:
        write_report(report_path, {**previous, "replayed_receipt": True})
        return 2
    original = {
        name: os.environ.get(name)
        for name in ("CV_B2B_MODEL", "CV_B2B_FALLBACK_MODELS")
    }
    deadline = time.monotonic() + 1800
    try:
        for index, model in enumerate(requested):
            os.environ["CV_B2B_MODEL"] = model
            os.environ["CV_B2B_FALLBACK_MODELS"] = ""
            directory = output / f"model-{index}"
            # Separate immutable source copies keep each model's artifacts distinct.
            current = prepare(directory)
            for case in current["cases"][offset : offset + limit]:
                if time.monotonic() >= deadline:
                    report["stop_reason"] = "deadline"
                    return 2
                started = time.monotonic()
                operation = None
                row = {
                    "case_id": case["id"],
                    "requested_model": model,
                    "human_accepted": None,
                }
                report["in_progress"] = {
                    "case_id": case["id"],
                    "requested_model": model,
                    "operation_id": None,
                }
                await checkpoint(report_path, report, key)
                async with AsyncSessionLocal() as db:
                    try:
                        async with ai_feature(db, AIFeatureKey.cv_generator) as state:
                            operation = state.operation_id
                            report["in_progress"]["operation_id"] = operation
                            await checkpoint(report_path, report, key)
                            row.update(
                                await asyncio.to_thread(generate_case, case, directory)
                            )
                            # Paths in the root report must resolve to this
                            # model's output, not an ambiguous shared basename.
                            for field in ("artifact", "payload_artifact"):
                                row[field] = str(
                                    (directory / row[field]).relative_to(output)
                                )
                    except AIQuotaExceeded:
                        report["stop_reason"] = "quota_or_feature_disabled"
                        return 2
                    except StandaloneGenerationError as error:
                        row["outcome"] = "generation_failed"
                        row["failure_code"] = error.code
                    except (
                        Exception
                    ):  # Preserve accounting even after an unexpected pipeline failure.
                        row["outcome"] = "internal_error"
                        report["stop_reason"] = "unexpected_pipeline_failure"
                async with AsyncSessionLocal() as db:
                    calls = (
                        list(
                            (
                                await db.scalars(
                                    select(AIProviderCall).where(
                                        AIProviderCall.operation_id == operation
                                    )
                                )
                            ).all()
                        )
                        if operation
                        else []
                    )
                costs = [call.estimated_cost_usd for call in calls]
                row.update(
                    {
                        "operation_id": operation,
                        "provider_calls": len(calls),
                        "actual_models": sorted({call.model for call in calls}),
                        "metering_complete": bool(calls)
                        and all(
                            call.model == model and call.estimated_cost_usd is not None
                            for call in calls
                        ),
                        "estimated_cost_usd": str(sum(costs))
                        if costs and all(cost is not None for cost in costs)
                        else None,
                        "input_tokens": sum(call.input_tokens for call in calls)
                        if calls
                        and all(call.input_tokens is not None for call in calls)
                        else None,
                        "output_tokens": sum(call.output_tokens for call in calls)
                        if calls
                        and all(call.output_tokens is not None for call in calls)
                        else None,
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                    }
                )
                report["results"].append(row)
                report.pop("in_progress", None)
                await checkpoint(report_path, report, key)
                if row["outcome"] == "internal_error":
                    return 2
        report["complete"] = True
        # Completion here means measurement finished, never human quality acceptance.
        return (
            0
            if all(
                row["outcome"] == "generated"
                and row["metering_complete"]
                and row.get("tenure_matches") is not False
                and row.get("source_role_count_matches") is True
                and row.get("required_source_facts_preserved") is True
                for row in report["results"]
            )
            else 1
        )
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        await checkpoint(report_path, report, key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 41), default=2)
    parser.add_argument("--offset", type=int, choices=range(40), default=0)
    parser.add_argument("--models", choices=["primary", "all"], default="primary")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                args.output,
                identity=args.run_key,
                expected_sha=args.expected_sha,
                limit=args.limit,
                models=args.models,
                offset=args.offset,
            )
        )
    )
