"""Study K: the list a recruiter sees after a full-base review, simulated on (sent people + 3000 random
candidates) with the PRODUCTION canonical fit, then different must-have policies:
 hard gates (all / core from a model) with candidate skills from the skill list only or also from CV text,
 and soft re-ranking by must coverage instead of hiding."""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, re, statistics, time
from collections import defaultdict
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
WORD = r"(?<![a-z0-9ąćęłńóśźż])"; END = r"(?![a-z0-9ąćęłńóśźż])"


def names(raw):
    out = []
    for x in raw or []:
        s = x.get("name") if isinstance(x, dict) else x
        if isinstance(s, str) and s.strip():
            out.append(s.strip())
    return out


def metrics(ranked, rel):
    pos = [c for c in rel]
    n = len(pos)
    r20 = len([c for c in ranked[:20] if c in rel]) / min(n, 20)
    r100 = len([c for c in ranked[:100] if c in rel]) / min(n, 100)
    p10 = len([c for c in ranked[:10] if c in rel]) / 10
    mrr = next((1 / (i + 1) for i, c in enumerate(ranked) if c in rel), 0.0)
    return {"R@20": r20, "R@100": r100, "P@10": p10, "MRR": mrr}


async def main():
    await data.boot()
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import (job_explicit_must_skills, canonical_skill_names, ALIAS_MAP,
                                              candidate_known_skill_names, _canon_skill)
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    from app.services.requirement_contract import alternatives
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    sample = json.load(open("/research/model_sample.json"))
    outs = json.load(open("/research/model_outputs_v1.json"))
    luna = outs.get("gpt-6-luna", {}); sonnet = outs.get("claude-sonnet-5", {})
    rev = defaultdict(set)
    for a, c in ALIAS_MAP.items():
        rev[c].add(a)

    random.seed(1234)
    async with AsyncSessionLocal() as db:
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        rnd = random.sample(all_ids, 3000)
        need = set(rnd)
        for jid in sample:
            need.update(c for c, r in pos[jid].items() if r >= 1)
        cobj = {}
        ids = sorted(need)
        for i in range(0, len(ids), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
    print(f"loaded {len(cobj)} candidates", flush=True)
    known = {cid: set(candidate_known_skill_names(c)) for cid, c in cobj.items()}
    canon = {cid: {_canon_skill(k) for k in s} for cid, s in known.items()}
    cvt = {cid: (c.raw_cv_text or "").lower() for cid, c in cobj.items()}
    rxc = {}

    def rx(label):
        if label not in rxc:
            forms = [f for f in ({label.lower()} | rev.get(label.lower(), set())) if len(f) >= 2]
            rxc[label] = re.compile("|".join(WORD + re.escape(f) + END for f in sorted(forms, key=len, reverse=True))) if forms else None
        return rxc[label]

    def has(label, cid, cv):
        opts = alternatives(label)
        for o in opts:
            o2 = ALIAS_MAP.get(o.lower(), o)
            if o2 in known[cid] or _canon_skill(o2) in canon[cid]:
                return True
            if cv and cvt[cid]:
                r = rx(o2.lower())
                if r is not None and r.search(cvt[cid]):
                    return True
        return False

    agg = defaultdict(lambda: defaultdict(list)); t0 = time.time(); used = 0
    for n, jid in enumerate(sample):
        j = jobs[jid]
        rel = {c: r for c, r in pos[jid].items() if r >= 1 and c in cobj}
        if len(rel) < 3:
            continue
        pool = [cobj[c] for c in set(rnd) | set(rel)]
        ctx = build_request_context(j, _to_scoring_profile(DEFAULT_PROFILE))
        fits = await score_candidates(None, ctx, pool)
        fit = {f.breakdown.candidate_id: (f.fit_score if f.fit_score is not None else -1.0) for f in fits}
        base_rank = sorted(fit, key=lambda c: (-fit[c], c))
        must = gate_eligible_must_skills(job_explicit_must_skills(j))
        L1 = names((luna.get(str(jid)) or {}).get("core")); S1 = names((sonnet.get(str(jid)) or {}).get("core"))
        L1 = canonical_skill_names(L1) if L1 else []; S1 = canonical_skill_names(S1) if S1 else []
        rest_l = canonical_skill_names(names((luna.get(str(jid)) or {}).get("rest_must")))
        V = {}

        def gate(labels, need_all=True, cv=False):
            def ok(cid):
                if not labels or not known[cid]:
                    return True
                hits = sum(1 for l in labels if has(l, cid, cv))
                return hits >= (len(labels) if need_all else max(1, math.ceil(len(labels) / 2)))
            return [c for c in base_rank if ok(c)]

        def soft(labels, w, cv=True):
            if not labels:
                return base_rank
            sc = {c: fit[c] + w * (sum(1 for l in labels if has(l, c, cv)) / len(labels)) for c in base_rank}
            return sorted(base_rank, key=lambda c: (-sc[c], c))

        V["A_no_gate"] = base_rank
        from app.services import champion_view as _cv
        _my = _cv.basics(j).get("seniority_min_years")
        _my = _my if isinstance(_my, (int, float)) and not isinstance(_my, bool) and _my > 0 else None
        def _yrs_ok(cid, slack):
            y = getattr(cobj[cid], "years_it_experience", None)
            return _my is None or y is None or y >= _my - slack
        V["S1_gate_years_min-1"] = [c for c in base_rank if _yrs_ok(c, 1)]
        V["S2_gate_years_min-2"] = [c for c in base_rank if _yrs_ok(c, 2)]
        V["B_prod_gate_all_must"] = gate(must)
        V["C_gate_all_must_cvtext"] = gate(must, cv=True)
        V["D_gate_half_must_cvtext"] = gate(must, need_all=False, cv=True)
        V["E_gate_core_luna"] = gate(L1)
        V["F_gate_core_luna_cvtext"] = gate(L1, cv=True)
        V["G_gate_core_sonnet_cvtext"] = gate(S1, cv=True)
        V["H_soft_must_w10"] = soft(must, 10)
        V["I_soft_must_w20"] = soft(must, 20)
        V["J_soft_core_w15"] = soft(L1, 15)
        if True:
            V["K_gate_core_cv+soft_rest_w10"] = [c for c in soft(rest_l or must, 10) if c in set(V["F_gate_core_luna_cvtext"])]
        used += 1
        for name, ranked in V.items():
            m = metrics(ranked, rel); m["visible"] = len(ranked) / len(base_rank)
            for k, x in m.items():
                agg[name][k].append(x)
        if n % 10 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)
    summary = {v: {k: round(statistics.mean(x), 4) for k, x in d.items()} | {"jobs": len(d["R@20"])} for v, d in sorted(agg.items())}
    print(json.dumps({"jobs": used, "summary": summary}, indent=1))
    json.dump({"jobs": used, "summary": summary}, open("/research/out_rank2_clean.json", "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main())
