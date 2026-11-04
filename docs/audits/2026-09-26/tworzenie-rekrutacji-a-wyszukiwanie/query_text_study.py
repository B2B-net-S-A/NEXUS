"""Study J: which job information, put into the query text, ranks the people the team SENT highest?
Fixed candidate set per job = its sent people + 3000 random candidates; cosine via Qdrant exact search."""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, statistics
from collections import defaultdict
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)


def names(raw):
    out = []
    for x in raw or []:
        s = x.get("name") if isinstance(x, dict) else x
        if isinstance(s, str) and s.strip():
            out.append(s.strip())
    return out


async def main():
    await data.boot()
    from app.services.full_search_measurement import request_vector, _exact_search
    from app.services.request_matching_context import build_request_context
    from app.services.embedding_service import _build_job_text
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    from app.services.scoring_service import _champion_stack_must_names
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    sample = json.load(open("/research/model_sample.json"))
    luna = json.load(open("/research/model_outputs_v1.json")).get("gpt-6-luna", {})
    random.seed(1234)
    rnd = random.sample(list(cands), 3000)

    def variants(j):
        cp = j.champion_profile if isinstance(j.champion_profile, dict) else {}
        proj = cp.get("project") if isinstance(cp.get("project"), dict) else {}
        must = names(j.must_skills); nice = names(j.nice_skills); stack = _champion_stack_must_names(j)
        L = luna.get(str(j.id), {})
        core = names(L.get("core")); rest = names(L.get("rest_must")); dom = names(L.get("domain"))
        about = " ".join(str(proj.get(k) or "") for k in ("about", "responsibilities")).strip()
        v = {}
        v["prod_full_review"] = build_request_context(j, _to_scoring_profile(DEFAULT_PROFILE)).query_text
        v["prod_capped_1200"] = _build_job_text(j)
        v["title"] = j.title or ""
        v["title+must_lines"] = f"{j.title}\n" + "\n".join(must)
        v["title+stack"] = f"{j.title}\n" + ", ".join(stack)
        v["title+must+nice"] = f"{j.title}\nMust have: " + "; ".join(must) + ("\nNice to have: " + "; ".join(nice) if nice else "")
        v["title+must+nice+project"] = v["title+must+nice"] + ("\n" + about if about else "")
        if L and "_error" not in L:
            yrs = L.get("min_years")
            v["structured_core"] = (f"Rola: {j.title}\n" + (f"Doświadczenie: {yrs}+ lat\n" if yrs else "")
                                    + ("Kluczowe technologie: " + ", ".join(core) + "\n" if core else "")
                                    + ("Wymagane: " + ", ".join(rest) + "\n" if rest else "")
                                    + ("Dziedzina: " + ", ".join(dom) if dom else ""))
            v["structured_core+project"] = v["structured_core"] + ("\n" + about if about else "")
            v["core_only"] = f"{j.title}\n" + ", ".join(core)
        return {k: t for k, t in v.items() if t and t.strip()}

    agg = defaultdict(lambda: defaultdict(list)); used = 0
    for jid in sample:
        j = jobs[jid]
        rel = {c: r for c, r in pos[jid].items() if r >= 1 and c in cands}
        if len(rel) < 3:
            continue
        ids = list(set(rnd) | set(rel))
        V = variants(j)
        res = {}
        for name, qt in V.items():
            vec = await request_vector(qt)
            if vec is None:
                continue
            hits = await asyncio.to_thread(_exact_search, vec, ids)
            scored = {int(h.id): h.score for h in hits}
            ranked = sorted(scored, key=lambda c: -scored[c])
            posin = [c for c in rel if c in scored]
            if not posin:
                continue
            r20 = len([c for c in ranked[:20] if c in rel]) / min(len(posin), 20)
            r100 = len([c for c in ranked[:100] if c in rel]) / min(len(posin), 100)
            mrr = next((1 / (i + 1) for i, c in enumerate(ranked) if c in rel), 0)
            medrank = statistics.median(ranked.index(c) + 1 for c in posin)
            res[name] = dict(R20=r20, R100=r100, MRR=mrr, med_rank=medrank)
        if "prod_full_review" not in res:
            continue
        used += 1
        for name, m in res.items():
            for k, x in m.items():
                agg[name][k].append(x)
            agg[name]["win_vs_prod_R100"].append(1 if m["R100"] > res["prod_full_review"]["R100"] else (0 if m["R100"] == res["prod_full_review"]["R100"] else -1))
    summary = {n: {k: round(statistics.mean(v), 4) if k != "med_rank" else round(statistics.median(v), 1) for k, v in d.items()} | {"jobs": len(d["R20"])} for n, d in agg.items()}
    print(json.dumps({"jobs": used, "summary": summary}, indent=1, ensure_ascii=False))
    json.dump({"jobs": used, "summary": summary}, open("/research/out_query_text.json", "w"), indent=1, ensure_ascii=False)


asyncio.run(main())
