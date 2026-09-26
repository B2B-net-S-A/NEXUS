"""Study M: the 23 recruitments created in NEXUS on 25.09 from real client e-mails. Positives = people the
team has already put into each recruitment. Core chosen by models straight from the e-mail."""
import ro_boot  # noqa: F401
import asyncio, json, math, random, re, statistics
from collections import defaultdict
import httpx
import data
from model_study import SYSTEM, call, parse, names
from rank_study2 import metrics, WORD, END


async def main():
    await data.boot()
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.scoring_service import job_explicit_must_skills, canonical_skill_names, ALIAS_MAP, candidate_known_skill_names, _canon_skill
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    from app.services.requirement_contract import alternatives
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    async with AsyncSessionLocal() as db:
        jobs = (await db.execute(select(Job).where(Job.external_source == "manual", Job.created_at >= __import__("datetime").datetime(2026, 9, 25, tzinfo=__import__("datetime").timezone.utc)))).scalars().all()
        for j in jobs: db.expunge(j)
        added = defaultdict(set)
        for jid, cid in (await db.execute(text("SELECT job_id, candidate_id FROM candidate_stages WHERE job_id = ANY(:ids)"), {"ids": [j.id for j in jobs]})).all():
            added[jid].add(cid)
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        random.seed(1234); rnd = random.sample(all_ids, 3000)
        need = set(rnd) | set().union(*added.values())
        cobj = {}
        for c in (await db.execute(select(Candidate).where(Candidate.id.in_(list(need))))).scalars().all():
            db.expunge(c); cobj[c.id] = c
    known = {cid: set(candidate_known_skill_names(c)) for cid, c in cobj.items()}
    canon = {cid: {_canon_skill(k) for k in s} for cid, s in known.items()}
    cvt = {cid: (c.raw_cv_text or "").lower() for cid, c in cobj.items()}
    rev = defaultdict(set)
    for a, c in ALIAS_MAP.items(): rev[c].add(a)
    rxc = {}
    def rx(l):
        if l not in rxc:
            forms = [f for f in ({l} | rev.get(l, set())) if len(f) >= 2]
            rxc[l] = re.compile("|".join(WORD + re.escape(f) + END for f in sorted(forms, key=len, reverse=True))) if forms else None
        return rxc[l]
    def has(label, cid, cv=True):
        for o in alternatives(label):
            o2 = ALIAS_MAP.get(o.lower(), o)
            if o2 in known[cid] or _canon_skill(o2) in canon[cid]:
                return True
            if cv and cvt[cid] and rx(o2.lower()) is not None and rx(o2.lower()).search(cvt[cid]):
                return True
        return False

    cores = {}
    async with httpx.AsyncClient() as client:
        for model in ("gpt-6-luna", "claude-opus-5-5"):
            for j in jobs:
                u = f"Tytuł: {j.title}\n\nZapytanie klienta (mail):\n{(j.description or '')[:12000]}"
                try:
                    txt, _ = await call(client, model, SYSTEM["v1"], u)
                    cores[(model, j.id)] = canonical_skill_names(names(parse(txt).get("core")))
                except Exception as e:
                    cores[(model, j.id)] = []
    agg = defaultdict(lambda: defaultdict(list)); rows = []
    prof = _to_scoring_profile(DEFAULT_PROFILE)
    for j in jobs:
        rel = {c: 1 for c in added.get(j.id, set()) if c in cobj}
        must = gate_eligible_must_skills(job_explicit_must_skills(j))
        row = {"job": j.id, "title": (j.working_title or j.title)[:50], "must_n": len(must),
               "core_luna": cores[("gpt-6-luna", j.id)], "core_opus": cores[("claude-opus-5-5", j.id)], "added": len(rel)}
        def vis_share(labels, need_all=True, cv=True):
            base = [c for c in rnd if known[c]]
            ok = [c for c in base if (not labels) or sum(has(l, c, cv) for l in labels) >= (len(labels) if need_all else max(1, math.ceil(len(labels)/2)))]
            return round(len(ok) / len(base), 4)
        row["visible_prod_gate_knownonly"] = vis_share(must, cv=False)
        row["visible_core_luna_cv"] = vis_share(row["core_luna"])
        row["visible_core_opus_cv"] = vis_share(row["core_opus"])
        rows.append(row)
        if len(rel) < 2:
            continue
        pool = [cobj[c] for c in set(rnd) | set(rel)]
        fits = await score_candidates(None, build_request_context(j, prof), pool)
        fit = {f.breakdown.candidate_id: (f.fit_score if f.fit_score is not None else -1.0) for f in fits}
        base_rank = sorted(fit, key=lambda c: (-fit[c], c))
        def gate(labels, cv):
            return [c for c in base_rank if (not labels) or (not known[c]) or all(has(l, c, cv) for l in labels)]
        def soft(labels, w):
            if not labels: return base_rank
            sc = {c: fit[c] + w * sum(has(l, c) for l in labels) / len(labels) for c in base_rank}
            return sorted(base_rank, key=lambda c: (-sc[c], c))
        V = {"A_no_gate": base_rank, "B_prod_gate": gate(must, False), "F_core_luna_cv": gate(row["core_luna"], True),
             "O_core_opus_cv": gate(row["core_opus"], True), "H_soft_must_w10": soft(must, 10), "I_soft_must_w20": soft(must, 20)}
        for name, ranked in V.items():
            m = metrics(ranked, rel)
            m["added_people_visible"] = len([c for c in rel if c in set(ranked)]) / len(rel)
            for k, x in m.items(): agg[name][k].append(x)
    summary = {v: {k: round(statistics.mean(x), 4) for k, x in d.items()} | {"jobs": len(d["R@20"])} for v, d in agg.items()}
    print(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False))
    json.dump({"summary": summary, "rows": rows}, open("/research/out_new_jobs.json", "w"), indent=1, ensure_ascii=False)


asyncio.run(main())
