"""Ocena z GAŁĘZI (30.09.2026) na tej samej próbce co ablacja — „prod” = nowa ocena
(dowód z CV/notatek dołączony przed oceną, stawka neutralna). Ablacja warstw oceny (`canonical_fit`) na tle 3 000 losowych kandydatów, bez bramki must.

Warianty przeliczają `total` z punktów warstw breakdownu (semantyka, umiejętności, stawka,
lokalizacja): produkcja, sama semantyka, bez stawki, bez lokalizacji, umiejętności ×2/×3,
umiejętności z dowodem „gdziekolwiek” (must/nice z CV, profilu, notatek sprzed otwarcia).
Uwaga na przeciek: osoby wysłane mają stawkę w profilu w 96% (baza 11%) — wariant
„stawka neutralna” wyrównuje warstwę stawki do 0,65 × max u wszystkich.
Tylko odczyt. RESEARCH_ARGS: n=200 seed=7 since=2024-07-01 pool=3000
"""
import ro_boot  # noqa: F401
import asyncio, json, os, random, statistics, time
from collections import defaultdict
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 200)); SEED = int(ARGS.get("seed", 7)); SINCE = ARGS.get("since", "2024-07-01"); POOL = int(ARGS.get("pool", 3000))


def metrics(ranked, rel):
    n = len(rel)
    return {"R@20": len([c for c in ranked[:20] if c in rel]) / min(n, 20),
            "R@100": len([c for c in ranked[:100] if c in rel]) / min(n, 100),
            "P@10": len([c for c in ranked[:10] if c in rel]) / 10,
            "MRR": next((1 / (i + 1) for i, c in enumerate(ranked) if c in rel), 0.0)}


async def main():
    await data.boot()
    import datetime
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.must_text_evidence import text_met_labels
    from app.services.must_gate_terms import gate_requirement
    from app.services.scoring_service import candidate_skill_names, skill_present, job_skill_requirements, UNKNOWN_NEUTRAL_FRACTION
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    pos = await data.load_positives(); jobs = {j.id: j for j in await data.load_jobs()}
    since = datetime.date.fromisoformat(SINCE)
    elig = [jid for jid, P in pos.items() if jid in jobs and jobs[jid].external_source != "manual"
            and sum(1 for r in P.values() if r >= 1) >= 3 and (jobs[jid].opened_at or jobs[jid].created_at).date() >= since]
    random.seed(SEED); random.shuffle(elig); sample = sorted(elig[:N])
    async with AsyncSessionLocal() as db:
        all_ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        random.seed(1234); rnd = set(random.sample(all_ids, POOL))
        need = set(rnd)
        for jid in sample:
            need.update(c for c, r in pos[jid].items() if r >= 1)
        ids = sorted(need); cobj = {}; notes = defaultdict(list)
        for i in range(0, len(ids), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
            for cid, at, content in (await db.execute(text(
                "SELECT candidate_id, created_at, content FROM notes WHERE candidate_id = ANY(:ids) AND source_deleted_at IS NULL "
                "AND note_type::text = ANY(:t)"), {"ids": ids[i:i+1000], "t": ["call", "meeting", "general", "interview"]})).all():
                notes[cid].append((at, content or ""))
    prof = _to_scoring_profile(DEFAULT_PROFILE)
    agg = defaultdict(lambda: defaultdict(list)); t0 = time.time(); used = 0
    per_job = defaultdict(dict)
    for n, jid in enumerate(sample):
        j = jobs[jid]; rel = {c for c, r in pos[jid].items() if r >= 1 and c in cobj}
        if len(rel) < 3:
            continue
        pool = [cobj[c] for c in rnd | rel]
        from app.services.dealbreaker_filters import dealbreaker_inputs_for_job
        from app.services.must_text_evidence import MustTextEvidence
        labels = dealbreaker_inputs_for_job(j).gate_evidence_labels
        cut = j.opened_at or j.created_at
        for c in pool:
            nts = [t for (at, t) in notes.get(c.id, ()) if cut is None or at < cut]
            c._must_text_evidence = MustTextEvidence(key=tuple(labels), met=text_met_labels(c, labels, nts), has_notes=bool(nts))
        fits = await score_candidates(None, build_request_context(j, prof), pool)
        L = {}
        for f in fits:
            b = f.breakdown
            if f.fit_score is None:
                continue
            L[b.candidate_id] = (b.semantic.points, b.skills.points, b.skills.max_points, b.salary.points, b.salary.max_points,
                                 b.location.points, b.location.max_points, b.total)
        reqs = job_skill_requirements(j)
        must = [l for l in reqs.get("must", []) if gate_requirement(l)]
        nice = [l for l in reqs.get("nice", []) if gate_requirement(l)]
        cutoff = j.opened_at or j.created_at
        anyw = {}
        for cid in L:
            c = cobj[cid]; sk = candidate_skill_names(c)
            nts = [t for (at, t) in notes.get(cid, ()) if cutoff is None or at < cutoff]
            tm = text_met_labels(c, must + nice, nts)
            fm = sum(1 for l in must if l in tm or skill_present(l, sk)) / len(must) if must else 1.0
            fn = sum(1 for l in nice if l in tm or skill_present(l, sk)) / len(nice) if nice else 0.0
            anyw[cid] = (fm, fn)
        def rank(fn):
            return sorted(L, key=lambda c: (-fn(c), c))
        V = {
            "prod": lambda c: L[c][7],
            "semantic_only": lambda c: L[c][0],
            "no_salary": lambda c: L[c][7] - L[c][3],
            "salary_neutral": lambda c: L[c][7] - L[c][3] + UNKNOWN_NEUTRAL_FRACTION * L[c][4],
            "no_location": lambda c: L[c][7] - L[c][5],
            "skills_x2": lambda c: L[c][7] + L[c][1],
            "skills_x3": lambda c: L[c][7] + 2 * L[c][1],
            "skills_anywhere": lambda c: L[c][7] - L[c][1] + L[c][2] * (2 / 3 * anyw[c][0] + 1 / 3 * anyw[c][1]),
            "skills_anywhere_x2": lambda c: L[c][7] - L[c][1] + 2 * L[c][2] * (2 / 3 * anyw[c][0] + 1 / 3 * anyw[c][1]),
            "salary_neutral+skills_anywhere": lambda c: L[c][7] - L[c][3] + UNKNOWN_NEUTRAL_FRACTION * L[c][4] - L[c][1] + L[c][2] * (2 / 3 * anyw[c][0] + 1 / 3 * anyw[c][1]),
        }
        used += 1
        for name, fn in V.items():
            m = metrics(rank(fn), rel)
            per_job[name][jid] = m
            for k, x in m.items():
                agg[name][k].append(x)
        if n % 20 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)
    summary = {v: {k: round(statistics.mean(x), 4) for k, x in d.items()} for v, d in agg.items()}
    # 95% przedział (bootstrap po rekrutacjach) dla różnicy względem produkcji
    rng = random.Random(2026); jids = sorted(per_job["prod"]); ci = {}
    for name in per_job:
        if name == "prod":
            continue
        ci[name] = {}
        for k in ("R@20", "R@100", "P@10", "MRR"):
            d = [per_job[name][j][k] - per_job["prod"][j][k] for j in jids]
            boots = sorted(statistics.mean(rng.choice(d) for _ in d) for _ in range(2000))
            ci[name][k] = [round(statistics.mean(d), 4), round(boots[50], 4), round(boots[1949], 4)]
    out = {"jobs": used, "summary": summary, "diff_vs_prod_mean_ci95": ci}
    print(json.dumps(out, indent=1))
    json.dump(out, open("/research/out_ablation_branch.json", "w"), indent=1)


asyncio.run(main())
