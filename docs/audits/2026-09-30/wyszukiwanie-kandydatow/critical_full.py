"""Pełna baza (≈64 tys.) dla opublikowanych rekrutacji założonych w NEXUSIE od 25.09:
ile osób zostaje na liście i ile propozycji nocnego przeglądu (≥70, top 60) daje
obecna bramka v8 vs „krytyczne” (Luna / z tytułu / reguła historyczna) vs brak bramki must.
Tylko odczyt. RESEARCH_ARGS: jobs=1,2,3 (domyślnie wszystkie opublikowane od 25.09)
"""
import ro_boot  # noqa: F401
import asyncio, json, os, statistics, time
from collections import Counter
from dataclasses import replace
import data
from critical_study import luna_critical

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)


async def main():
    await data.boot()
    from sqlalchemy import select, text
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import apply_dealbreakers, missing_must_skills
    from app.services.must_text_evidence import attach_gate_evidence, has_any_data, evidence_for, mentions
    from app.services.must_gate_terms import gate_requirement
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    hist = json.load(open("/research/out_critical.json")).get("hist_labels", {})
    async with AsyncSessionLocal() as db:
        if ARGS.get("jobs"):
            jids = [int(x) for x in ARGS["jobs"].split(",")]
        else:
            jids = [r for (r,) in (await db.execute(text(
                "SELECT id FROM jobs WHERE created_at >= '2026-09-25' AND external_source IS DISTINCT FROM 'traffit' "
                "AND status='published' AND title NOT ILIKE '%test%' ORDER BY id"))).all()]
        jobs = {}
        for jid in jids:
            j = (await db.execute(select(Job).where(Job.id == jid))).scalar_one(); db.expunge(j); jobs[jid] = j
        must_of = {jid: list(search_dealbreaker_inputs(j).must_skills) for jid, j in jobs.items()}
        luna = await luna_critical(jobs, jids, must_of)
        ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        out = {}
        part = "/research/out_critical_full.jsonl"
        done = {}
        if os.path.exists(part):
            for line in open(part):
                done.update({int(k): v for k, v in json.loads(line).items()})
        out.update(done)
        for jid in jids:
            if jid in done:
                continue
            t0 = time.time(); j = jobs[jid]; must = must_of[jid]
            added = {c for (c,) in (await db.execute(text(
                "SELECT candidate_id FROM recruitment_processes WHERE job_id=:j AND entry_source IN ('added_manual','proposal','reassign')"), {"j": jid})).all()}
            inputs = search_dealbreaker_inputs(j)
            ctx = build_request_context(j, _to_scoring_profile(DEFAULT_PROFILE))
            fit, missing, base_vis, nodata = {}, {}, set(), set()
            for i in range(0, len(ids), 2000):
                batch = (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+2000])))).scalars().all()
                for c in batch:
                    db.expunge(c)
                if must:
                    await attach_gate_evidence(db, batch, must)
                for c in batch:
                    missing[c.id] = set(missing_must_skills(c, must)) if must else set()
                    if not has_any_data(c, evidence_for(c, must)):
                        nodata.add(c.id)
                kept = apply_dealbreakers(batch, inputs=replace(inputs, must_skills=())).kept
                base_vis |= {c.id for c in kept}
                for f in await score_candidates(None, ctx, kept):
                    fit[f.breakdown.candidate_id] = f.fit_score
            title = j.working_title or j.title or ""
            P = {"none": [], "all_v8": must, "luna": luna.get(jid, []),
                 "title": [l for l in must if gate_requirement(l) and mentions(gate_requirement(l), title)][:2],
                 "hist90": [l for l in must if (hist.get(l.lower()) or 0) >= 0.9],
                 "first1": must[:1]}
            res = {"title": title[:70], "must": must, "added": len(added), "critical": P, "policies": {}}
            for name, S in P.items():
                S = set(S)
                vis = [c for c in base_vis if not (missing[c] & S) and not (S and c in nodata)]
                ranked = sorted((c for c in vis if fit.get(c) is not None), key=lambda c: -fit[c])
                props = [c for c in ranked if fit[c] >= settings.AUTO_FULL_REVIEW_MIN_SCORE][: settings.AUTO_FULL_REVIEW_TOP_K]
                rank_of = {c: i + 1 for i, c in enumerate(ranked)}
                res["policies"][name] = {
                    "visible": len(vis), "props_ge70_top60": len(props),
                    "props_with_data": sum(1 for c in props if c not in nodata),
                    "added_visible": sum(1 for c in added if c in set(vis)),
                    "added_ranks": sorted(rank_of[c] for c in added if c in rank_of)[:10],
                }
            res["secs"] = round(time.time() - t0)
            out[jid] = res
            print(json.dumps({jid: res}, ensure_ascii=False), flush=True)
            with open(part, "a") as fh:
                fh.write(json.dumps({jid: res}, ensure_ascii=False) + "\n")
    json.dump(out, open("/research/out_critical_full.json", "w"), indent=1, ensure_ascii=False)


asyncio.run(main())
