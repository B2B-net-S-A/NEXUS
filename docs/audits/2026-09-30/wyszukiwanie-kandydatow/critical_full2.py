"""Doprecyzowana reguła krytycznych na pełnej bazie (nowe rekrutacje z NEXUSA):
najwyżej 2 pozycje, tylko technologie ze słownika, porównanie z historią po NAZWIE KANONICZNEJ
(„React.js 18+” → react), próg ≥90% wysłanych z dowodem (tabela z `gate_rule_variants.py`).
Liczy ocenę tylko dla osób widocznych przy tej regule (reszta wariantów jest w critical_full).
Wznawialne: /research/out_critical_full2.jsonl. Tylko odczyt.
"""
import ro_boot  # noqa: F401
import asyncio, json, os, time
from dataclasses import replace
import data


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
    from app.services.must_text_evidence import attach_gate_evidence, has_any_data, evidence_for
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of, is_taxonomy_technology
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile

    rows = json.load(open("/research/out_gate_rules.json"))["label_hit_rate_top80"]
    hist = {}
    for label, rate, n in rows:
        r = gate_requirement(label)
        for o in (r.options if r else (label,)):
            hist[canonical_of(o)] = max(hist.get(canonical_of(o), 0), rate)

    def crit2(must):
        scored = []
        for l in must:
            r = gate_requirement(l)
            if not r or not all(is_taxonomy_technology(o) for o in r.options):
                continue
            rate = max(hist.get(canonical_of(o), 0) for o in r.options)
            if rate >= 0.9:
                scored.append((rate, l))
        return [l for _, l in sorted(scored, key=lambda x: -x[0])[:2]]

    part = "/research/out_critical_full2.jsonl"
    done = set()
    if os.path.exists(part):
        for line in open(part):
            done |= {int(k) for k in json.loads(line)}
    async with AsyncSessionLocal() as db:
        jids = [r for (r,) in (await db.execute(text(
            "SELECT id FROM jobs WHERE created_at >= '2026-09-25' AND external_source IS DISTINCT FROM 'traffit' "
            "AND status='published' AND title NOT ILIKE '%test%' ORDER BY id"))).all()]
        ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        for jid in jids:
            if jid in done:
                continue
            t0 = time.time()
            j = (await db.execute(select(Job).where(Job.id == jid))).scalar_one(); db.expunge(j)
            inputs = search_dealbreaker_inputs(j); must = list(inputs.must_skills); S = set(crit2(must))
            ctx = build_request_context(j, _to_scoring_profile(DEFAULT_PROFILE))
            fit = {}; vis = 0
            for i in range(0, len(ids), 2000):
                batch = (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i:i+2000])))).scalars().all()
                for c in batch:
                    db.expunge(c)
                if S:
                    await attach_gate_evidence(db, batch, must)
                kept = []
                for c in apply_dealbreakers(batch, inputs=replace(inputs, must_skills=())).kept:
                    if S and (set(missing_must_skills(c, must)) & S or not has_any_data(c, evidence_for(c, must))):
                        continue
                    kept.append(c)
                vis += len(kept)
                for f in await score_candidates(None, ctx, kept):
                    fit[f.breakdown.candidate_id] = f.fit_score
            ranked = sorted((c for c, s in fit.items() if s is not None), key=lambda c: -fit[c])
            props = [c for c in ranked if fit[c] >= settings.AUTO_FULL_REVIEW_MIN_SCORE][: settings.AUTO_FULL_REVIEW_TOP_K]
            res = {jid: {"title": (j.working_title or j.title or "")[:70], "must": must, "crit2": sorted(S),
                         "visible": vis, "props_ge70_top60": len(props), "secs": round(time.time() - t0)}}
            print(json.dumps(res, ensure_ascii=False), flush=True)
            with open(part, "a") as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
    open("/research/out_critical_full2.done", "w").write("ok")


asyncio.run(main())
