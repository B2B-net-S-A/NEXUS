"""Study A: must-have gate — recall of people the team actually sent/hired vs how much of the base it hides."""
import ro_boot  # noqa: F401
import asyncio, json, math, random, statistics, sys
from collections import Counter, defaultdict
import data

random.seed(7)


def policies(M):
    ps = {"none": 0, "current_all": M}
    for k in (1, 2, 3):
        ps[f"first{k}"] = ("first", k)
    ps["half"] = max(1, math.ceil(M / 2))
    ps["all_but_1"] = max(1, M - 1)
    ps["70pct"] = max(1, math.ceil(0.7 * M))
    return ps


def passes(labels, cand, pol):
    if not labels or not cand.known:  # unknown passes (current semantics)
        return True
    if pol == 0:
        return True
    if isinstance(pol, tuple):
        sub = labels[: pol[1]]
        return all(data.present(l, cand.canon, cand.known) for l in sub)
    hit = sum(1 for l in labels if data.present(l, cand.canon, cand.known))
    return hit >= min(pol, len(labels))


async def main():
    await data.boot()
    from app.services.scoring_service import job_explicit_must_skills, _champion_stack_must_names, canonical_skill_names, ALIAS_MAP
    from app.services.dealbreaker_filters import gate_eligible_must_skills
    cands = await data.load_candidates()
    pos = await data.load_positives()
    jobs = await data.load_jobs()
    known_pool = [c for c in cands.values() if c.known]
    pop = random.sample(known_pool, 4000)
    taxonomy = set(ALIAS_MAP.keys()) | set(ALIAS_MAP.values())
    print(f"candidates={len(cands)} with_known_skills={len(known_pool)} ({100*len(known_pool)/len(cands):.0f}%) jobs={len(jobs)} jobs_with_pos={len(pos)}")

    cohorts = {
        "A_job_column_as_is": lambda j: gate_eligible_must_skills(job_explicit_must_skills(j)),
        "B_champion_stack_names": lambda j: gate_eligible_must_skills(canonical_skill_names(_champion_stack_must_names(j))),
        "C_stack_taxonomy_only": lambda j: [l for l in gate_eligible_must_skills(canonical_skill_names(_champion_stack_must_names(j))) if l.lower() in taxonomy],
    }
    report = {}
    for cname, fn in cohorts.items():
        agg = defaultdict(lambda: {"rec": [], "srec": [], "pass": [], "micro_hit": 0, "micro_n": 0})
        Ms = []
        fail_labels = Counter(); label_seen = Counter()
        njobs = 0
        for j in jobs:
            labels = fn(j)
            P = pos.get(j.id) or {}
            ppos = [cands[c] for c, r in P.items() if r >= 1 and c in cands]
            ppos_known = [c for c in ppos if c.known]
            if not labels or len(ppos_known) < 1:
                continue
            njobs += 1
            Ms.append(len(labels))
            for c in ppos_known:
                for l in labels:
                    label_seen[l] += 1
                    if not data.present(l, c.canon, c.known):
                        fail_labels[l] += 1
            strong = [c for c in ppos_known if P[c.id] >= 2]
            for pname, pol in policies(len(labels)).items():
                a = agg[pname]
                hits = sum(passes(labels, c, pol) for c in ppos_known)
                a["rec"].append(hits / len(ppos_known))
                a["micro_hit"] += hits; a["micro_n"] += len(ppos_known)
                if strong:
                    a["srec"].append(sum(passes(labels, c, pol) for c in strong) / len(strong))
                sample = pop[:800]
                a["pass"].append(sum(passes(labels, c, pol) for c in sample) / len(sample))
        rows = {}
        for pname, a in agg.items():
            rec = statistics.mean(a["rec"]); pr = statistics.mean(a["pass"])
            rows[pname] = {
                "jobs": len(a["rec"]),
                "recall_sent_macro": round(rec, 3),
                "recall_sent_micro": round(a["micro_hit"] / max(1, a["micro_n"]), 3),
                "recall_strong_macro": round(statistics.mean(a["srec"]), 3) if a["srec"] else None,
                "jobs_recall_below_50pct": round(sum(r < 0.5 for r in a["rec"]) / len(a["rec"]), 3),
                "base_pass_rate": round(pr, 4),
                "lift": round(rec / pr, 1) if pr else None,
            }
        worst = [(l, label_seen[l], round(fail_labels[l] / label_seen[l], 2)) for l, _ in label_seen.most_common(400) if label_seen[l] >= 30]
        worst.sort(key=lambda x: -x[2])
        report[cname] = {"jobs": njobs, "M_median": statistics.median(Ms) if Ms else None,
                         "M_dist": dict(Counter(min(m, 10) for m in Ms)), "policies": rows,
                         "labels_most_missed_by_sent_people": worst[:25]}
        print(json.dumps({cname: report[cname]}, ensure_ascii=False, indent=1))
    json.dump(report, open("/research/out_gate_study.json", "w"), ensure_ascii=False, indent=1)


asyncio.run(main())
