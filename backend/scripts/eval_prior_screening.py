"""Pomiar warstwy ``prior_screening`` — etap 0: pokrycie (tylko odczyt).

Pytanie: u ilu osób WYSŁANYCH do klienta (``cv_sent`` z
``analytics_first_milestones``) była wcześniejsza odpowiedź na to samo pytanie
screeningowe — z arkusza innej rekrutacji wypełnionego PRZED otwarciem
rekrutacji docelowej (``COALESCE(opened_at, created_at)``), czyli bez przecieku.
No-go, gdy pokrycie < 5%.

Transakcja jest ``READ ONLY`` — skrypt nic nie zapisuje. Wynik: liczby par,
pokrycie (dopasowanie / ocenione / deal-breaker), histogram liczby
dopasowanych pytań i rozkład podobieństwa. Bez imion, nazwisk i treści
odpowiedzi.

    python -m scripts.eval_prior_screening --limit 2000 --months 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from types import SimpleNamespace

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import prior_screening as ps

COVERAGE_NO_GO = 0.05

_SENT_SQL = """
    SELECT m.candidate_id, m.job_id,
           COALESCE(j.opened_at, j.created_at) AS opened_at,
           j.champion_profile
    FROM analytics_first_milestones m
    JOIN jobs j ON j.id = m.job_id
    WHERE m.stage::text = 'cv_sent'
      AND m.first_reached_at > now() - make_interval(months => :months)
    ORDER BY md5(m.candidate_id::text || ':' || m.job_id::text || :seed)
    LIMIT :n
"""


async def run(limit: int, months: int, seed: str) -> dict:
    from app.services.skill_taxonomy_loader import refresh_alias_map

    # Warunek „te same technologie” potrzebuje słownika jak w aplikacji.
    await refresh_alias_map()
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        rows = (
            await db.execute(
                text(_SENT_SQL), {"months": months, "seed": seed, "n": limit}
            )
        ).all()
        by_job: dict[int, list] = defaultdict(list)
        for candidate_id, job_id, opened_at, profile in rows:
            by_job[job_id].append((candidate_id, opened_at, profile))

        counts = Counter()
        matched_questions = Counter()
        similarity = Counter()
        jobs_with_questions = 0
        for job_id, pairs in by_job.items():
            profile = pairs[0][2]
            job = SimpleNamespace(id=job_id, champion_profile=profile)
            if not ps.current_questions(job):
                counts["pairs_job_without_questions"] += len(pairs)
                continue
            jobs_with_questions += 1
            # Każda para ma ten sam `opened_at` (jedna rekrutacja).
            before = pairs[0][1]
            candidates = [SimpleNamespace(id=cid) for cid, _, _ in pairs]
            await ps.attach_prior_screening(db, job, candidates, before=before)
            for candidate in candidates:
                counts["pairs"] += 1
                result = ps.evaluate(candidate, job)
                if result is None:
                    counts["lookup_failed"] += 1
                    continue
                if getattr(candidate, "_prior_screening").answers:
                    counts["with_any_prior_answer"] += 1
                if result.matches:
                    counts["with_match"] += 1
                if result.scored:
                    counts["scored"] += 1
                if result.deal_breaker:
                    counts["deal_breaker"] += 1
                matched_questions[len(result.matches)] += 1
                for match in result.matches:
                    similarity[round(match.similarity, 1)] += 1
        await db.rollback()

    pairs = counts["pairs"] or 1
    coverage = counts["with_match"] / pairs
    return {
        "version": ps.VERSION,
        "threshold": ps.MATCH_THRESHOLD,
        "sent_pairs_sampled": len(rows),
        "jobs": len(by_job),
        "jobs_with_screening_questions": jobs_with_questions,
        "counts": dict(counts),
        "coverage_match": round(coverage, 4),
        "coverage_scored": round(counts["scored"] / pairs, 4),
        "matched_questions_histogram": dict(sorted(matched_questions.items())),
        "similarity_histogram": dict(sorted(similarity.items())),
        "verdict": "go" if coverage >= COVERAGE_NO_GO else "no-go",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--seed", default="7")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.limit, args.months, args.seed)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
