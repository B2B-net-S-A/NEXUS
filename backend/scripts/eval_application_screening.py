"""Pomiar przeglądu zgłoszeń przez AI na danych produkcji — przed włączeniem.

Uruchamiany w kontenerze backendu przy WYŁĄCZONYM ``APPLICATION_SCREENING_ENABLED``:
woła tę samą funkcję ``application_screening.assess`` (z ``use_model=True``)
co pętla, ale nie zapisuje decyzji — jedyny zapis to telemetria kosztu AI.

Dwie grupy par (kandydat, rekrutacja) z CV i z must-have:

* ``verified`` — osoba, którą rekruter zweryfikował w tej rekrutacji.
  Warunek włączenia: ŻADNA nie może dostać ``not_fit``.
* ``posting`` — osoba, która aplikowała z ogłoszenia (etap „Ogłoszenia”
  z importu Traffita). Każde ``not_fit`` przegląda człowiek.

Wynik: liczby werdyktów per grupa + wiersze ``not_fit`` (id pary, pokrycie
must-have, powody). Bez imion i nazwisk.

    python -m scripts.eval_application_screening --per-group 40 --seed 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.application_screening import VERDICT_NOT_FIT, assess

_MIN_CV_CHARS = 500

# `must_skills` bywa skalarem JSON; `AND` w Postgresie nie gwarantuje
# kolejności, więc sprawdzenie typu musi siedzieć w CASE.
_HAS_MUST = (
    "(CASE WHEN jsonb_typeof(j.must_skills) = 'array' "
    "THEN jsonb_array_length(j.must_skills) ELSE 0 END) > 0"
)

_SAMPLE_SQL = {
    "verified": f"""
        SELECT m.candidate_id, m.job_id
        FROM analytics_first_milestones m
        JOIN candidates c ON c.id = m.candidate_id
        JOIN jobs j ON j.id = m.job_id
        WHERE m.stage::text = 'verified'
          AND m.first_reached_at > now() - interval '12 months'
          AND length(coalesce(c.raw_cv_text, '')) > :min_cv
          AND {_HAS_MUST}
        ORDER BY md5(m.candidate_id::text || ':' || m.job_id::text || :seed)
        LIMIT :n
    """,
    "posting": f"""
        SELECT candidate_id, job_id FROM (
            SELECT DISTINCT cs.candidate_id, cs.job_id
            FROM candidate_stages cs
            JOIN candidates c ON c.id = cs.candidate_id
            JOIN jobs j ON j.id = cs.job_id
            WHERE cs.stage::text = 'posting'
              AND cs.created_at > now() - interval '12 months'
              AND length(coalesce(c.raw_cv_text, '')) > :min_cv
              AND {_HAS_MUST}
        ) p
        ORDER BY md5(candidate_id::text || ':' || job_id::text || :seed)
        LIMIT :n
    """,
}


async def _pairs(group: str, n: int, seed: str) -> list[tuple[int, int]]:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        params = {"min_cv": _MIN_CV_CHARS, "n": n, "seed": seed}
        rows = (await db.execute(text(_SAMPLE_SQL[group]), params)).all()
        await db.rollback()
    return [(int(r[0]), int(r[1])) for r in rows]


async def _assess(candidate_id: int, job_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        job = await db.get(Job, job_id)
        result = await assess(
            db,
            job=job,
            candidate=candidate,
            cv_text=candidate.raw_cv_text or "",
            use_model=True,
        )
        await db.rollback()
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "verdict": result.verdict,
        "must": f"{result.must_found}/{result.must_total}",
        "error": result.error,
        "reasons": [r.get("text") for r in result.reasons],
    }


async def main(per_group: int, seed: str) -> None:
    summary: dict[str, Counter] = {}
    rejected: list[dict] = []
    for group in ("verified", "posting"):
        counts: Counter = Counter()
        for candidate_id, job_id in await _pairs(group, per_group, seed):
            row = await _assess(candidate_id, job_id)
            counts[row["verdict"]] += 1
            if row["error"]:
                counts[f"error:{row['error']}"] += 1
            if row["verdict"] == VERDICT_NOT_FIT:
                rejected.append({"group": group, **row})
        summary[group] = counts
    print(json.dumps({g: dict(c) for g, c in summary.items()}, ensure_ascii=False))
    for row in rejected:
        print(json.dumps(row, ensure_ascii=False))
    false_rejections = summary["verified"][VERDICT_NOT_FIT]
    print(
        "WARUNEK WŁĄCZENIA:",
        "SPEŁNIONY" if false_rejections == 0 else f"NIESPEŁNIONY ({false_rejections})",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-group", type=int, default=40)
    parser.add_argument("--seed", default="7")
    args = parser.parse_args()
    asyncio.run(main(args.per_group, args.seed))
