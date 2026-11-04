"""Study I: is the candidate-side skill list the weak link? For must labels that SENT people 'lack',
check whether the full CV text mentions them. Then re-run gate policies with presence = known skills OR CV text."""
import ro_boot  # noqa: F401
import asyncio, json, math, random, re, statistics
from collections import Counter, defaultdict
import data
from sqlalchemy import text

WORD = r"(?<![a-z0-9ąćęłńóśźż])"
END = r"(?![a-z0-9ąćęłńóśźż])"


async def main():
    await data.boot()
    from app.core.database import AsyncSessionLocal
    from app.services.scoring_service import (job_explicit_must_skills, _champion_stack_must_names,
                                              canonical_skill_names, ALIAS_MAP, _alias_pattern, is_technology_mention)
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    rev = defaultdict(set)
    for a, c in ALIAS_MAP.items():
        rev[c].add(a)
    pat = _alias_pattern()
    random.seed(21)
    known_pool = [c.id for c in cands.values() if c.known]
    popsample = random.sample(known_pool, 1500)

    need = set(popsample)
    for jid, P in pos.items():
        need.update(c for c, r in P.items() if r >= 1)
    cv = {}
    async with AsyncSessionLocal() as db:
        ids = sorted(need)
        for i in range(0, len(ids), 2000):
            rs = (await db.execute(text("SELECT id, lower(coalesce(raw_cv_text,'')) AS txt, cv_extracted_data->>'traffit_technologie' AS ttech FROM candidates WHERE id = ANY(:ids)"), {"ids": ids[i:i+2000]})).all()
            for r in rs:
                cv[r.id] = (r.txt, r.ttech)

    cache_rx = {}
    def rx(label):
        if label not in cache_rx:
            forms = {label.lower()} | rev.get(label.lower(), set())
            forms = [f for f in forms if len(f) >= 2]
            cache_rx[label] = re.compile("|".join(WORD + re.escape(f) + END for f in sorted(forms, key=len, reverse=True))) if forms else None
        return cache_rx[label]

    def in_cv(label, cid):
        t = cv.get(cid, ("", None))[0]
        if not t:
            return False
        from app.services.requirement_contract import alternatives
        for opt in alternatives(label):
            opt = ALIAS_MAP.get(opt.lower(), opt.lower())
            r = rx(opt)
            if r is not None and r.search(t):
                return True
        return False

    stats = {"cand_known_source": Counter()}
    for cid in list(cv)[:20000]:
        t, tt = cv[cid]
        stats["cand_known_source"]["traffit_list" if tt else ("cv_text" if t else "none")] += 1

    cohorts = {
        "column_gate": lambda j: gate_eligible_must_skills(job_explicit_must_skills(j)),
        "stack_names": lambda j: gate_eligible_must_skills(canonical_skill_names(_champion_stack_must_names(j))),
    }
    report = {"stats": {k: dict(v) for k, v in stats.items()}}
    for cname, fn in cohorts.items():
        miss_total = miss_in_cv = miss_no_cv = 0
        per_label = Counter(); per_label_cv = Counter()
        pol = defaultdict(lambda: defaultdict(list))
        for jid, P in pos.items():
            j = jobs.get(jid)
            if not j:
                continue
            L = fn(j)
            sent = [c for c, r in P.items() if r >= 1 and c in cands and cands[c].known]
            if not L or len(sent) < 1:
                continue
            for cid in sent:
                c = cands[cid]
                for l in L:
                    if not data.present(l, c.canon, c.known):
                        miss_total += 1; per_label[l] += 1
                        if not cv.get(cid, ("",))[0]:
                            miss_no_cv += 1
                        elif in_cv(l, cid):
                            miss_in_cv += 1; per_label_cv[l] += 1
            for mode in ("known_only", "known_or_cv"):
                def has(l, cid, mode=mode):
                    c = cands[cid]
                    return data.present(l, c.canon, c.known) or (mode == "known_or_cv" and in_cv(l, cid))
                for pname, needf in (("all", lambda L: len(L)), ("half", lambda L: max(1, math.ceil(len(L) / 2))),
                                     ("first1", None), ("first2", None)):
                    LL = L[:1] if pname == "first1" else L[:2] if pname == "first2" else L
                    k = len(LL) if needf is None else needf(LL)
                    ok = lambda cid: sum(1 for l in LL if has(l, cid)) >= k
                    pol[f"{mode}:{pname}"]["rec"].append(sum(map(ok, sent)) / len(sent))
                    if len(pol[f"{mode}:{pname}"]["rec"]) % 4 == 1:  # base pass on a subsample of jobs (cost)
                        pol[f"{mode}:{pname}"]["pass"].append(sum(map(ok, popsample[:500])) / 500)
        report[cname] = {
            "missing_label_events": miss_total,
            "of_which_label_IS_in_CV_text": round(miss_in_cv / max(1, miss_total), 3),
            "of_which_candidate_has_no_CV_text": round(miss_no_cv / max(1, miss_total), 3),
            "top_missing_labels_found_in_cv": [(l, per_label[l], round(per_label_cv[l] / per_label[l], 2)) for l, _ in per_label.most_common(30)],
            "policies": {p: {"recall_sent": round(statistics.mean(d["rec"]), 3), "jobs_recall_lt50": round(sum(x < .5 for x in d["rec"]) / len(d["rec"]), 3),
                             "base_pass": round(statistics.mean(d["pass"]), 4), "jobs": len(d["rec"])} for p, d in pol.items()},
        }
        print(json.dumps({cname: report[cname]}, indent=1, ensure_ascii=False), flush=True)
    json.dump(report, open("/research/out_cv_presence.json", "w"), indent=1, ensure_ascii=False)


asyncio.run(main())
