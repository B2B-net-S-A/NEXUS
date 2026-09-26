"""Study L: which part of the job/Champion data carries the semantic signal? Remove one part at a time
from the production query text and measure how the SENT people drop (same fixed sets as Study J)."""
import ro_boot  # noqa: F401
import asyncio, copy, json, random, statistics
from collections import defaultdict
import data


async def main():
    await data.boot()
    from app.services.full_search_measurement import request_vector, _exact_search
    from app.services.request_matching_context import build_request_context
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    sample = json.load(open("/research/model_sample.json"))
    random.seed(1234); rnd = random.sample(list(cands), 3000)
    prof = _to_scoring_profile(DEFAULT_PROFILE)

    def mutate(j, what):
        from types import SimpleNamespace
        from app.services.request_matching_context import _JOB_FIELDS
        j2 = SimpleNamespace(**{f: getattr(j, f, None) for f in _JOB_FIELDS})
        cp = copy.deepcopy(j.champion_profile) if isinstance(j.champion_profile, dict) else {}
        if what == "full":
            pass
        elif what == "-screening":
            cp.pop("screening_questions", None)
        elif what == "-search":
            cp.pop("search", None)
        elif what == "-project":
            cp.pop("project", None)
        elif what == "-client":
            cp.pop("client", None)
        elif what == "-stack":
            cp.pop("stack", None)
        elif what == "-must_nice_columns":
            j2.must_skills = []; j2.nice_skills = []
        elif what == "-champion_all":
            cp = {}
        elif what == "-title":
            j2.title = ""
        j2.champion_profile = cp
        return j2

    parts = ["full", "-screening", "-search", "-project", "-client", "-stack", "-must_nice_columns", "-champion_all", "-title"]
    agg = defaultdict(lambda: defaultdict(list)); lens = defaultdict(list)
    for jid in sample:
        rel = {c: r for c, r in pos[jid].items() if r >= 1 and c in cands}
        if len(rel) < 3:
            continue
        ids = list(set(rnd) | set(rel))
        base = None
        for p in parts:
            try:
                qt = build_request_context(mutate(jobs[jid], p), prof).query_text
            except Exception as e:
                print(p, type(e).__name__); continue
            lens[p].append(len(qt))
            vec = await request_vector(qt)
            if vec is None:
                continue
            hits = await asyncio.to_thread(_exact_search, vec, ids)
            sc = {int(h.id): h.score for h in hits}
            ranked = sorted(sc, key=lambda c: -sc[c])
            posin = [c for c in rel if c in sc]
            r20 = len([c for c in ranked[:20] if c in rel]) / min(len(posin), 20)
            r100 = len([c for c in ranked[:100] if c in rel]) / min(len(posin), 100)
            agg[p]["R20"].append(r20); agg[p]["R100"].append(r100)
    out = {p: {k: round(statistics.mean(v), 4) for k, v in d.items()} | {"jobs": len(d["R20"]), "avg_chars": round(statistics.mean(lens[p]))} for p, d in agg.items()}
    print(json.dumps(out, indent=1))
    json.dump(out, open("/research/out_ablation.json", "w"), indent=1)


asyncio.run(main())
