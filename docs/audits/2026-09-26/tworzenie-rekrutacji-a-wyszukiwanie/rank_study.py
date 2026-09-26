"""Study C: end-to-end ranking — pool (Qdrant+BM25, as eval_matching) -> canonical fit (C2 screens)
-> must-gate variants. Measures where people the team actually SENT/placed land on the list.

Env RESEARCH_ARGS: "n=150 seed=11 pool=300 variants_file=/research/core_sets.json"
Outputs /research/out_rank_<tag>.json (aggregates only) + per-job rows (ids hashed) for later joins.
"""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, statistics, sys, hashlib, time
from collections import defaultdict
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 150)); SEED = int(ARGS.get("seed", 11)); POOL = int(ARGS.get("pool", 300))
TAG = ARGS.get("tag", "base")


def ndcg(ranked, rel, k=10):
    dcg = sum((2 ** rel.get(c, 0) - 1) / math.log2(i + 2) for i, c in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def metrics(ranked, rel):
    pos = set(rel)
    r20 = len([c for c in ranked[:20] if c in pos]) / min(len(pos), 20)
    p10 = len([c for c in ranked[:10] if c in pos]) / 10
    mrr = next((1 / (i + 1) for i, c in enumerate(ranked) if c in pos), 0.0)
    r100 = len([c for c in ranked[:100] if c in pos]) / min(len(pos), 100)
    return {"R@20": r20, "P@10": p10, "MRR": mrr, "nDCG@10": ndcg(ranked, rel), "R@100": r100}


async def main():
    await data.boot()
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.retrieval_pool import retrieve_candidate_pool
    from app.services.embedding_service import _build_job_text
    from app.services.canonical_text import build_job_query_variants
    from app.services.hybrid_search import build_job_bm25_query, build_job_must_groups
    from app.services.scoring_service import job_explicit_must_skills, _champion_stack_must_names, canonical_skill_names
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    from scripts.eval_matching import _rank_canonical, DEFAULT_PROFILE

    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    core_sets = json.load(open(ARGS["variants_file"])) if ARGS.get("variants_file") else {}

    eligible = []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j or j.external_source == "manual":
            continue
        sent = [c for c, r in P.items() if r >= 1 and c in cands and cands[c].known]
        if len(sent) >= 3 and gate_eligible_must_skills(job_explicit_must_skills(j)):
            eligible.append(jid)
    if ARGS.get("only"):
        eligible = [int(x) for x in ARGS["only"].split(",")]
    random.seed(SEED); random.shuffle(eligible)
    sample = sorted(eligible[:N])
    print(f"eligible_jobs={len(eligible)} sample={len(sample)} tag={TAG}", flush=True)

    per_job = []
    agg = defaultdict(lambda: defaultdict(list))
    t0 = time.time()
    for n, jid in enumerate(sample):
        job = jobs[jid]
        P = pos[jid]
        rel = {c: r for c, r in P.items() if r >= 1}
        async with AsyncSessionLocal() as db:
            qt = _build_job_text(job)
            hits = await retrieve_candidate_pool(db, qt, top_k=POOL, query_variants=build_job_query_variants(job, qt),
                                                 bm25_query=build_job_bm25_query(job), must_groups=build_job_must_groups(job))
            ids = [h["candidate_id"] for h in hits]
            if not ids:
                continue
            cs = (await db.execute(select(Candidate).where(Candidate.id.in_(ids)))).scalars().all()
            fits = await _rank_canonical(job, cs, db, profile=DEFAULT_PROFILE)
        ranked = [f.breakdown.candidate_id for f in fits]  # measured desc, then unmeasured
        in_pool = len([c for c in rel if c in set(ids)]) / len(rel)
        column_must = gate_eligible_must_skills(job_explicit_must_skills(job))
        stack_must = gate_eligible_must_skills(canonical_skill_names(_champion_stack_must_names(job)))
        variants = {"no_gate": (None, 0)}
        variants["current_all"] = (column_must, len(column_must))
        variants["current_first2"] = (column_must[:2], 2)
        variants["current_half"] = (column_must, max(1, math.ceil(len(column_must) / 2)))
        if stack_must:
            variants["stack_all"] = (stack_must, len(stack_must))
            variants["stack_half"] = (stack_must, max(1, math.ceil(len(stack_must) / 2)))
            variants["stack_first2"] = (stack_must[:2], 2)
        for key, cs_ in core_sets.get(str(jid), {}).items():
            if cs_:
                variants[f"core_{key}"] = (cs_, len(cs_))
        row = {"job": hashlib.sha1(str(jid).encode()).hexdigest()[:8], "npos": len(rel), "in_pool": in_pool, "M": len(column_must), "Mstack": len(stack_must)}
        for vname, (labels, need) in variants.items():
            def ok(cid):
                c = cands.get(cid)
                if labels is None or c is None or not c.known:
                    return True
                hit = sum(1 for l in labels if data.present(l, c.canon, c.known))
                return hit >= min(need, len(labels))
            vis = [c for c in ranked if ok(c)]
            m = metrics(vis, rel)
            m["visible_share"] = len(vis) / len(ranked)
            row[vname] = m
            for k, v in m.items():
                agg[vname][k].append(v)
        per_job.append(row)
        if n % 10 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)
    summary = {v: {k: round(statistics.mean(xs), 4) for k, xs in d.items()} | {"jobs": len(d["R@20"])} for v, d in agg.items()}
    summary["_pool_recall_mean"] = round(statistics.mean(r["in_pool"] for r in per_job), 4)
    print(json.dumps(summary, indent=1))
    json.dump({"summary": summary, "per_job": per_job}, open(f"/research/out_rank_{TAG}.json", "w"), indent=1)


asyncio.run(main())
