"""Study O: the nightly full-base review, re-computed read-only on the WHOLE base for a few 25.09 jobs:
production gates (all rubrics) vs the same without the must-have gate. Counts proposals >= threshold
(AUTO_FULL_REVIEW_MIN_SCORE, top AUTO_FULL_REVIEW_TOP_K) and where the people the team added land."""
import ro_boot  # noqa: F401
import asyncio, json, os, time
from collections import defaultdict
import data

JOBS = [int(x) for x in (os.environ.get("RESEARCH_ARGS") or "jobs=689430,689431,689433,689440").split("=")[1].split(",")]


async def main():
    await data.boot()
    from dataclasses import replace
    from sqlalchemy import select, text
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import apply_dealbreakers
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    import inspect
    print("apply_dealbreakers", inspect.signature(apply_dealbreakers), flush=True)
    out = {}
    async with AsyncSessionLocal() as db:
        ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        for jid in JOBS:
            t0 = time.time()
            job = (await db.execute(select(Job).where(Job.id == jid))).scalar_one()
            added = {c for (c,) in (await db.execute(text("SELECT DISTINCT candidate_id FROM candidate_stages WHERE job_id=:j"), {"j": jid})).all()}
            ctx = build_request_context(job, _to_scoring_profile(DEFAULT_PROFILE))
            fit = {}
            cands = {}
            for i in range(0, len(ids), 2000):
                batch = (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+2000])))).scalars().all()
                for c in batch:
                    cands[c.id] = c
                for f in await score_candidates(None, ctx, batch):
                    fit[f.breakdown.candidate_id] = f.fit_score
                for c in batch:
                    db.expunge(c)
            res = {}
            for name, inputs, extra in (("prod_all_gates", search_dealbreaker_inputs(job), {}),
                                 ("without_must_gate", search_dealbreaker_inputs(job, exclude_missing_must=False), {}),
                                 ("without_must_and_office_gates", search_dealbreaker_inputs(job, exclude_missing_must=False),
                                  {"exclude_office_city_mismatch": False, "exclude_office_days_exceeded": False})):
                r = apply_dealbreakers(list(cands.values()), inputs=inputs, **extra)
                visible_ids = {c.id for c in r.kept}
                ranked = sorted((c for c in visible_ids if fit.get(c) is not None), key=lambda c: -fit[c])
                ge = [c for c in ranked if fit[c] >= settings.AUTO_FULL_REVIEW_MIN_SCORE][: settings.AUTO_FULL_REVIEW_TOP_K]
                ranks = sorted(ranked.index(c) + 1 for c in added if c in set(ranked))
                res[name] = {"visible": len(visible_ids), "hidden_missing_must": r.hidden_missing_must, "hidden_over_budget": r.hidden_over_budget, "hidden_city": r.hidden_office_city_mismatch, "proposals_ge_threshold": len(ge),
                             "added_visible": f"{len(ranks)}/{len(added)}", "added_ranks": ranks[:15],
                             "added_in_proposals": len([c for c in added if c in set(ge)])}
            out[jid] = {"title": (job.working_title or job.title)[:60], "added": len(added), **res, "secs": round(time.time() - t0)}
            print(json.dumps({jid: out[jid]}, ensure_ascii=False), flush=True)
    json.dump(out, open("/research/out_full_base2.json", "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
