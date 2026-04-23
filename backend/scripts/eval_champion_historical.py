"""Offline evaluation of the `historical_jobs` Champion Profile source.

Phase 15 / Phase C — hold-one-out on closed jobs with a populated
`champion_profile`. For each held-out job we call
`find_similar_historical_jobs` against the remaining corpus (same client
only by default; ``--cross-client true`` widens the pool) and measure:

    retrieval:
        P@5              — was at least one sibling surfaced in top-5?
        MRR              — reciprocal rank of the first sibling match
    content similarity (only when retrieval succeeded):
        project_context.about     — token Jaccard between held-out profile
                                    and the top-1 match's verbatim candidate
        sourcing.keywords         — token Jaccard
        sourcing.target_companies — token Jaccard

A "sibling" is any other closed job at the same client with a populated
Champion Profile — these are the only rows a realistic LLM could draw from.

Usage
-----
    python -m scripts.eval_champion_historical --sample 30
    python -m scripts.eval_champion_historical --sample 30 --cross-client
    python -m scripts.eval_champion_historical --client-id 123

The script writes a JSON report to `backend/.eval_reports/` so runs stay
comparable across iterations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.job import Job, JobStatus  # noqa: E402
from app.services.historical_jobs_retrieval import (  # noqa: E402
    find_similar_historical_jobs,
    skill_frequency,
)

logger = logging.getLogger("eval_champion_historical")


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class PerJobResult:
    job_id: int
    client_id: Optional[int]
    title: str
    sibling_count: int
    hit_rank: Optional[int]  # 1-based rank of first sibling hit; None if miss
    about_jaccard: Optional[float]
    keywords_jaccard: Optional[float]
    target_companies_jaccard: Optional[float]


@dataclass
class RunReport:
    started_at: str
    cross_client: bool
    sample: int
    client_id_filter: Optional[int]
    top_k: int
    metrics: dict[str, float]
    per_job: list[PerJobResult] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────


def _tokens(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    return {
        t.strip().lower()
        for t in text.replace(";", ",").replace("\n", ",").split(",")
        if t.strip()
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def _load_candidates(
    db: AsyncSession, *, client_id: Optional[int]
) -> list[Job]:
    """Closed jobs with a populated champion_profile — eligible corpus."""
    stmt = select(Job).where(
        Job.status == JobStatus.closed,
        Job.champion_profile.isnot(None),
        Job.champion_profile != {},
    )
    if client_id is not None:
        stmt = stmt.where(Job.client_id == client_id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


# ── Core ────────────────────────────────────────────────────────────────────


async def evaluate(
    *,
    sample: int,
    cross_client: bool,
    client_id: Optional[int],
    top_k: int,
    seed: int,
) -> RunReport:
    report = RunReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        cross_client=cross_client,
        sample=sample,
        client_id_filter=client_id,
        top_k=top_k,
        metrics={},
    )

    async with AsyncSessionLocal() as db:
        corpus = await _load_candidates(db, client_id=client_id)
        if not corpus:
            logger.warning(
                "eval: empty corpus (client_id=%s)", client_id
            )
            return report

        random.seed(seed)
        random.shuffle(corpus)
        sampled = corpus[:sample] if sample > 0 else corpus

        for held_out in sampled:
            sibling_ids = {
                other.id
                for other in corpus
                if other.id != held_out.id
                and (
                    cross_client
                    or other.client_id == held_out.client_id
                )
            }
            matches = await find_similar_historical_jobs(
                db,
                client_id=held_out.client_id,
                title=held_out.title or "",
                raw_description=held_out.description or "",
                train_name=getattr(held_out, "train_name", None),
                top_k=top_k,
                cross_client=cross_client,
                exclude_job_id=held_out.id,
            )
            hit_rank = None
            top_match = None
            for rank, match in enumerate(matches, start=1):
                if match.job_id in sibling_ids:
                    if hit_rank is None:
                        hit_rank = rank
                        top_match = match

            about_j = kw_j = tc_j = None
            if top_match is not None:
                held_profile = held_out.champion_profile or {}
                match_profile = top_match.champion_profile or {}
                about_j = _jaccard(
                    _tokens((held_profile.get("project_context") or {}).get("about")),
                    _tokens((match_profile.get("project_context") or {}).get("about")),
                )
                kw_j = _jaccard(
                    _tokens((held_profile.get("sourcing") or {}).get("keywords")),
                    _tokens((match_profile.get("sourcing") or {}).get("keywords")),
                )
                tc_j = _jaccard(
                    _tokens(
                        (held_profile.get("sourcing") or {}).get("target_companies")
                    ),
                    _tokens(
                        (match_profile.get("sourcing") or {}).get("target_companies")
                    ),
                )

            report.per_job.append(
                PerJobResult(
                    job_id=held_out.id,
                    client_id=held_out.client_id,
                    title=held_out.title or "",
                    sibling_count=len(sibling_ids),
                    hit_rank=hit_rank,
                    about_jaccard=about_j,
                    keywords_jaccard=kw_j,
                    target_companies_jaccard=tc_j,
                )
            )

    # Aggregate
    hits = [r.hit_rank for r in report.per_job if r.hit_rank is not None]
    total = len(report.per_job)
    eligible = [r for r in report.per_job if r.sibling_count > 0]
    eligible_count = len(eligible)
    report.metrics["n"] = total
    report.metrics["n_with_siblings"] = eligible_count
    report.metrics["P@K"] = (
        len([r for r in eligible if r.hit_rank is not None]) / eligible_count
        if eligible_count
        else 0.0
    )
    report.metrics["MRR"] = (
        statistics.mean(1.0 / rank for rank in hits) if hits else 0.0
    )
    report.metrics["about_jaccard_median"] = (
        statistics.median(r.about_jaccard for r in report.per_job if r.about_jaccard is not None)
        if hits
        else 0.0
    )
    report.metrics["keywords_jaccard_median"] = (
        statistics.median(r.keywords_jaccard for r in report.per_job if r.keywords_jaccard is not None)
        if hits
        else 0.0
    )
    report.metrics["target_companies_jaccard_median"] = (
        statistics.median(
            r.target_companies_jaccard
            for r in report.per_job
            if r.target_companies_jaccard is not None
        )
        if hits
        else 0.0
    )

    return report


def write_report(report: RunReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"champion_historical_{stamp}.json"
    path = output_dir / filename
    payload = asdict(report)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument(
        "--cross-client",
        action="store_true",
        help="Drop the same-client filter; evaluate against the full corpus.",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=None,
        help="Restrict the corpus to a single client (diagnostic).",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="backend/.eval_reports")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s — %(message)s",
    )

    report = asyncio.run(
        evaluate(
            sample=args.sample,
            cross_client=args.cross_client,
            client_id=args.client_id,
            top_k=args.top_k,
            seed=args.seed,
        )
    )
    path = write_report(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "report_path": str(path),
                "metrics": report.metrics,
                "n": len(report.per_job),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
