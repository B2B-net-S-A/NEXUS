"""Study N: soft signals on top of the production fit — domain (from the client request, via Luna) and
seniority (production penalty on/off), combined with soft must coverage. Same simulation as Study K."""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, re, statistics, time
from collections import defaultdict
import data
from rank_study2 import metrics, names, WORD, END

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 70))
DOMAIN_FAMILIES = {
    "bank": r"bank|banking|bankow|finans|financial|płatnoś|payment|kart|cards|kredyt|lending|aml|kyc",
    "insurance": r"insurance|ubezpiecz",
    "telco": r"telco|telekom|telecom",
    "health": r"medyczn|health|zdrowi|szpital|pacjent",
    "public": r"administracj|public sector|sektor publiczn|ministerst|urzęd|e-?government",
    "energy": r"energ|utilities|oil|gas|paliw",
    "retail": r"e-?commerce|retail|handel",
}


async def main():
    await data.boot()
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import job_explicit_must_skills, ALIAS_MAP, candidate_known_skill_names, _canon_skill
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    from app.services.requirement_contract import alternatives
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    sample = json.load(open("/research/model_sample.json"))[:N]
    luna = json.load(open("/research/model_outputs_v1.json")).get("gpt-6-luna", {})
    rev = defaultdict(set)
    for a, c in ALIAS_MAP.items(): rev[c].add(a)
    random.seed(1234)
    async with AsyncSessionLocal() as db:
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        rnd = random.sample(all_ids, 3000)
        need = set(rnd)
        for jid in sample: need.update(c for c, r in pos[jid].items() if r >= 1)
        cobj = {}
        ids = sorted(need)
        for i in range(0, len(ids), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
    known = {cid: set(candidate_known_skill_names(c)) for cid, c in cobj.items()}
    canon = {cid: {_canon_skill(k) for k in s} for cid, s in known.items()}
    cvt = {cid: (c.raw_cv_text or "").lower() for cid, c in cobj.items()}
    rxc = {}
    def rx(l):
        if l not in rxc:
            forms = [f for f in ({l} | rev.get(l, set())) if len(f) >= 2]
            rxc[l] = re.compile("|".join(WORD + re.escape(f) + END for f in sorted(forms, key=len, reverse=True))) if forms else None
        return rxc[l]
    def has(label, cid):
        for o in alternatives(label):
            o2 = ALIAS_MAP.get(o.lower(), o)
            if o2 in known[cid] or _canon_skill(o2) in canon[cid]:
                return True
            r = rx(o2.lower())
            if cvt[cid] and r is not None and r.search(cvt[cid]):
                return True
        return False
    fam_rx = {k: re.compile(v) for k, v in DOMAIN_FAMILIES.items()}

    def job_families(jid):
        dom = " ".join(names((luna.get(str(jid)) or {}).get("domain"))).lower()
        return [k for k, r in fam_rx.items() if r.search(dom)]

    prof = _to_scoring_profile(DEFAULT_PROFILE)
    agg = defaultdict(lambda: defaultdict(list)); used = 0; t0 = time.time(); fams_seen = 0
    for n, jid in enumerate(sample):
        j = jobs[jid]
        rel = {c: r for c, r in pos[jid].items() if r >= 1 and c in cobj}
        if len(rel) < 3:
            continue
        pool = [cobj[c] for c in set(rnd) | set(rel)]
        ctx = build_request_context(j, prof)
        settings.CHAMPION_SENIORITY_PENALTY_ENABLED = True
        f_on = {f.breakdown.candidate_id: (f.fit_score if f.fit_score is not None else -1.0) for f in await score_candidates(None, ctx, pool)}
        settings.CHAMPION_SENIORITY_PENALTY_ENABLED = False
        f_off = {f.breakdown.candidate_id: (f.fit_score if f.fit_score is not None else -1.0) for f in await score_candidates(None, ctx, pool)}
        settings.CHAMPION_SENIORITY_PENALTY_ENABLED = True
        must = gate_eligible_must_skills(job_explicit_must_skills(j))
        cov = {c: (sum(has(l, c) for l in must) / len(must)) if must else 0 for c in f_on}
        fams = job_families(jid); fams_seen += bool(fams)
        dom = {c: (1.0 if fams and any(fam_rx[k].search(cvt[c]) for k in fams) else 0.0) for c in f_on}

        def rank(score):
            return sorted(score, key=lambda c: (-score[c], c))
        V = {
            "A_prod_fit_no_gate": rank(f_on),
            "A0_seniority_penalty_off": rank(f_off),
            "H_soft_must_w10": rank({c: f_on[c] + 10 * cov[c] for c in f_on}),
            "D5_domain_w5": rank({c: f_on[c] + 5 * dom[c] for c in f_on}),
            "D10_domain_w10": rank({c: f_on[c] + 10 * dom[c] for c in f_on}),
            "HD_must_w10+domain_w5": rank({c: f_on[c] + 10 * cov[c] + 5 * dom[c] for c in f_on}),
            "HD2_must_w10+domain_w10": rank({c: f_on[c] + 10 * cov[c] + 10 * dom[c] for c in f_on}),
        }
        used += 1
        for name, ranked in V.items():
            for k, x in metrics(ranked, rel).items():
                agg[name][k].append(x)
        if n % 10 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)
    summary = {v: {k: round(statistics.mean(x), 4) for k, x in d.items()} | {"jobs": len(d["R@20"])} for v, d in sorted(agg.items())}
    print(json.dumps({"jobs": used, "jobs_with_domain": fams_seen, "summary": summary}, indent=1))
    json.dump({"jobs": used, "jobs_with_domain": fams_seen, "summary": summary}, open("/research/out_rank3.json", "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main())
