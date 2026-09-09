"""Evaluate a saved full-search snapshot against frozen recruiter judgments.

python -m scripts.eval_full_search_quality --run-id UUID --labels labels.json --output report.json
python -m scripts.eval_full_search_quality --run-id UUID --prepare-labels --candidate-ids 123 456 --output labels.json

Labels: {"schema":"search-quality-labels-v1", "request_data_fingerprint":"...",
"judgments":[{"candidate_id":123,"candidate_version":"...",
"verdict":"relevant|not_relevant|unknown","reviewer":"...",
"reviewed_at":"2026-09-09T10:00:00+00:00"}]}

No model calls or database writes. Judgments are supplied by a reviewer, never
inferred from scores or pipeline stages. Metrics describe the archived snapshot;
live freshness and cross-screen parity require separate production checks.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
from datetime import datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun


def request_data_fingerprint(run):
    """Freeze business facts independently of the algorithm/weight version."""
    return hashlib.sha256(
        json.dumps(
            run.request_context["job_data"], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def prepare_labels(run, rows, candidate_ids=()):
    """Export an unjudged review sheet, never synthetic human judgments."""
    if run.state not in {"complete", "partial"}:
        raise ValueError("Search has not finished")
    by_id = {row.candidate_id: row for row in rows}
    if len(rows) != run.population_size or len(by_id) != len(rows):
        raise ValueError("Incomplete population snapshot")
    visible = [row for row in rows if row.state == "evaluated" and row.eligible is True]
    visible.sort(
        key=lambda row: (row.fit_score is None, -(row.fit_score or 0), row.candidate_id)
    )
    selected = {row.candidate_id for row in visible[:20]} | set(candidate_ids)
    if selected - by_id.keys():
        raise ValueError("Requested review candidate is outside the run population")
    return {
        "schema": "search-quality-labels-v1",
        "request_data_fingerprint": request_data_fingerprint(run),
        "judgments": [
            {
                "candidate_id": cid,
                "candidate_version": by_id[cid].candidate_version,
                "verdict": "unknown",
                "reviewer": "",
                "reviewed_at": "",
            }
            for cid in sorted(selected)
        ],
    }


def evaluate(run, rows, labels):
    if run.state not in {"complete", "partial"}:
        raise ValueError("Search has not finished")
    if labels.get("schema") != "search-quality-labels-v1" or labels.get(
        "request_data_fingerprint"
    ) != request_data_fingerprint(run):
        raise ValueError("Labels refer to different request facts")
    by_id = {row.candidate_id: row for row in rows}
    if len(by_id) != len(rows) or len(rows) != run.population_size:
        raise ValueError("Population snapshot is incomplete or duplicated")
    judgments = {}
    for item in labels["judgments"]:
        cid = item["candidate_id"]
        if type(cid) is not int or cid <= 0 or cid in judgments:
            raise ValueError("Invalid or duplicate judgment candidate ID")
        if item["verdict"] not in {"relevant", "not_relevant", "unknown"}:
            raise ValueError("Invalid reviewer verdict")
        reviewed_at = datetime.fromisoformat(item["reviewed_at"])
        if not item["reviewer"].strip() or reviewed_at.utcoffset() is None:
            raise ValueError("Reviewer and timezone-aware review date are required")
        if (
            not isinstance(item["candidate_version"], str)
            or not item["candidate_version"]
        ):
            raise ValueError("Judgment requires the reviewed candidate version")
        if cid in by_id and by_id[cid].candidate_version != item["candidate_version"]:
            raise ValueError(
                "Judged candidate version differs from the search snapshot"
            )
        judgments[cid] = item["verdict"]
    if not judgments:
        raise ValueError("No recruiter judgments supplied")
    ranked = [row for row in rows if row.state == "evaluated" and row.eligible is True]
    for row in ranked:
        if row.fit_score is not None and (
            type(row.fit_score) not in {int, float}
            or not math.isfinite(row.fit_score)
            or not 0 <= row.fit_score <= 100
            or row.measurement != "measured"
        ):
            raise ValueError("Invalid archived score")
    ranked.sort(
        key=lambda row: (row.fit_score is None, -(row.fit_score or 0), row.candidate_id)
    )
    top = [row.candidate_id for row in ranked[:20]]
    ranked_ids = {row.candidate_id for row in ranked}
    positives = {cid for cid, verdict in judgments.items() if verdict == "relevant"}
    judged_top = [
        cid for cid in top if judgments.get(cid) in {"relevant", "not_relevant"}
    ]
    hits = len(positives.intersection(top))
    failed = sum(row.state != "evaluated" for row in rows)
    unknown = sum(
        row.fit_score is None or row.measurement != "measured" for row in ranked
    )
    return {
        "schema": "full-search-quality-v1",
        "run_id": run.id,
        "request_fingerprint": run.request_fingerprint,
        "request_data_fingerprint": request_data_fingerprint(run),
        "weights": run.request_context["weights"],
        "label_fingerprint": hashlib.sha256(
            json.dumps(labels, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "scope": "archived full-search snapshot, default filters and zero score threshold",
        "label_source": "supplied recruiter judgments; authenticity not independently verified",
        "population": len(rows),
        "failed": failed,
        "unknown_measurements": unknown,
        "coverage_complete": failed == 0,
        "ranking_complete": failed == 0 and unknown == 0 and run.state == "complete",
        "known_positives": len(positives),
        "known_positive_recall_at_20": hits / len(positives) if positives else None,
        "known_positive_recall_all_results": len(positives & ranked_ids)
        / len(positives)
        if positives
        else None,
        "known_positive_outside_population": len(positives - by_id.keys()),
        "known_positive_excluded": sum(
            cid in by_id
            and by_id[cid].state == "evaluated"
            and by_id[cid].eligible is False
            for cid in positives
        ),
        "top20_size": len(top),
        "top20_judged": len(judged_top),
        "top20_judgment_coverage": len(judged_top) / len(top) if top else None,
        "precision_among_judged_top20": hits / len(judged_top) if judged_top else None,
        "precision_at_20": hits / len(top)
        if top and len(judged_top) == len(top)
        else None,
        "quality_review_complete": bool(top)
        and len(judged_top) == len(top)
        and bool(positives)
        and not (positives - by_id.keys())
        and failed == 0
        and unknown == 0
        and run.state == "complete",
        # No names, evidence text, reviewer identities or raw CVs in output.
        "top20_candidate_ids": top,
        "missing_positive_candidate_ids": sorted(positives - ranked_ids),
    }


async def report(run_id, labels, candidate_ids=()):
    async with AsyncSessionLocal() as db:
        run = await db.get(CandidateSearchRun, run_id)
        if run is None:
            raise ValueError("Search run does not exist")
        rows = (
            await db.execute(
                select(
                    CandidateSearchResult.candidate_id,
                    CandidateSearchResult.candidate_version,
                    CandidateSearchResult.state,
                    CandidateSearchResult.eligible,
                    CandidateSearchResult.fit_score,
                    CandidateSearchResult.measurement,
                ).where(CandidateSearchResult.run_id == run_id)
            )
        ).all()
        if labels is None:
            return prepare_labels(run, rows, candidate_ids)
        result = evaluate(run, rows, labels)
        result["versions"] = run.version_trace
        result["recorded_run_metrics"] = run.metrics
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--labels")
    mode.add_argument("--prepare-labels", action="store_true")
    parser.add_argument("--candidate-ids", type=int, nargs="*", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.labels:
        if args.candidate_ids:
            parser.error("--candidate-ids is only for --prepare-labels")
        with open(args.labels) as source:
            labels = json.load(source)
    else:
        labels = None
    result = asyncio.run(report(args.run_id, labels, args.candidate_ids))
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
