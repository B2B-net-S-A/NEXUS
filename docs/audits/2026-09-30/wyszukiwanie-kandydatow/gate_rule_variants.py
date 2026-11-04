"""Reguły wyboru must, które ukrywają — na CAŁEJ historii (rekrutacje z ≥3 wysłanymi).

Dla każdej reguły: odsetek wysłanych ukrytych przez must, odsetek rekrutacji tracących >50%
wysłanych, odsetek bazy (600 losowych kandydatów) zostający na liście, średnio ile etykiet
bramkuje. Reguła historyczna liczona bez danej rekrutacji (leave-one-out) i dla etykiet
z ≥5 rekrutacji. Dowód v8, notatki tylko sprzed otwarcia rekrutacji. Tylko odczyt.
"""
import ro_boot  # noqa: F401
import asyncio, json, random, statistics, time
from collections import defaultdict
import data


async def main():
    await data.boot()
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import missing_must_skills
    from app.services.must_text_evidence import MustTextEvidence, text_met_labels
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import is_taxonomy_technology

    pos = await data.load_positives(); jobs = {j.id: j for j in await data.load_jobs()}
    work = []
    for jid, P in pos.items():
        j = jobs.get(jid)
        if not j or j.external_source == "manual":
            continue
        sent = [c for c, r in P.items() if r >= 1]
        if len(sent) >= 3:
            must = list(search_dealbreaker_inputs(j).must_skills)
            if must:
                work.append((jid, must, sent))
    async with AsyncSessionLocal() as db:
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        random.seed(77); rnd = random.sample(all_ids, 600)
        need = sorted({c for _, _, s in work for c in s} | set(rnd))
        cobj, notes = {}, defaultdict(list)
        for i in range(0, len(need), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(need[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
            for cid, at, content in (await db.execute(text(
                "SELECT candidate_id, created_at, content FROM notes WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
                "AND note_type::text = ANY(:t)"), {"ids": need[i:i+1000], "t": ["call", "meeting", "general", "interview"]})).all():
                notes[cid].append((at, content or ""))
    print(f"jobs={len(work)} loaded={len(cobj)}", flush=True)
    per = {}
    t0 = time.time()
    for n, (jid, must, sent) in enumerate(work):
        j = jobs[jid]; cutoff = j.opened_at or j.created_at
        def miss_of(cid):
            c = cobj[cid]
            nts = [t for (at, t) in notes.get(cid, ()) if cutoff is None or at < cutoff]
            c._must_text_evidence = MustTextEvidence(key=tuple(must), met=text_met_labels(c, must, nts), has_notes=bool(nts))
            return set(missing_must_skills(c, must))
        sm = {c: miss_of(c) for c in sent if c in cobj}
        rm = {c: miss_of(c) for c in rnd if c in cobj}
        cov = {l: sum(1 for m in sm.values() if l not in m) / max(1, len(sm)) for l in must}
        per[jid] = (must, sm, rm, cov)
        if n % 200 == 0:
            print(f"{n}/{len(work)} {time.time()-t0:.0f}s", flush=True)
    lab = defaultdict(list)
    for jid, (must, sm, rm, cov) in per.items():
        for l in must:
            lab[l.lower()].append((jid, cov[l]))

    def hist(l, jid):
        xs = [c for j2, c in lab[l.lower()] if j2 != jid]
        return statistics.mean(xs) if len(xs) >= 5 else None

    def tech(l):
        r = gate_requirement(l)
        return bool(r) and all(is_taxonomy_technology(o) for o in r.options)

    rules = {
        "v8_all_must": lambda jid, must, cov: must,
        "tech_only": lambda jid, must, cov: [l for l in must if tech(l)],
        "hist90": lambda jid, must, cov: [l for l in must if (hist(l, jid) or 0) >= 0.9],
        "hist85": lambda jid, must, cov: [l for l in must if (hist(l, jid) or 0) >= 0.85],
        "hist80": lambda jid, must, cov: [l for l in must if (hist(l, jid) or 0) >= 0.8],
        "hist90_tech": lambda jid, must, cov: [l for l in must if tech(l) and (hist(l, jid) or 0) >= 0.9],
        "first_tech": lambda jid, must, cov: [l for l in must if tech(l)][:1],
        "oracle1": lambda jid, must, cov: sorted(must, key=lambda l: -cov[l])[:1],
        "none": lambda jid, must, cov: [],
    }
    out = {}
    for name, rule in rules.items():
        hid, tot, bad, base_vis, k, jobs_gated = 0, 0, 0, [], [], 0
        for jid, (must, sm, rm, cov) in per.items():
            S = set(rule(jid, must, cov))
            k.append(len(S)); jobs_gated += bool(S)
            h = sum(1 for m in sm.values() if m & S)
            hid += h; tot += len(sm)
            bad += (h / max(1, len(sm)) > 0.5)
            base_vis.append(sum(1 for m in rm.values() if not (m & S)) / max(1, len(rm)))
        out[name] = {"sent_hidden": round(hid / tot, 4), "jobs_losing_gt50pct": round(bad / len(per), 4),
                     "base_visible": round(statistics.mean(base_vis), 4), "avg_gating_labels": round(statistics.mean(k), 2),
                     "jobs_with_gate": round(jobs_gated / len(per), 3)}
        print(name, out[name], flush=True)
    top = sorted(((l, round(statistics.mean(c for _, c in xs), 3), len(xs)) for l, xs in lab.items() if len(xs) >= 8),
                 key=lambda x: -x[2])[:80]
    res = {"jobs": len(per), "rules": out, "label_hit_rate_top80": top}
    json.dump(res, open("/research/out_gate_rules.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps(res, ensure_ascii=False, indent=1))


asyncio.run(main())
