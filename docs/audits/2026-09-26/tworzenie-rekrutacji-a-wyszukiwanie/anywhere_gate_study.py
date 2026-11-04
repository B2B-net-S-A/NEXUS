"""Pomiar v7 (kod produkcji) vs v8 (gałąź „must gdziekolwiek”, 27.09.2026).

Ten sam skrypt uruchamiany dwa razy: ``run.sh`` (kod /app = produkcja, v7)
i ``run_branch.sh`` (kod gałęzi zamontowany przed /app, v8). Baza tylko do
odczytu (ro_boot). Tryb w RESEARCH_ARGS:

  pairs   osoby wysłane do klienta (cv_sent+) i dodane przez zespół do
          rekrutacji z 25.09+: ilu bramki zostawiają widocznych, powody ukrycia
  full    cała baza dla kilku rekrutacji z 25.09: widoczni, powody, propozycje
          >= progu nocnego przeglądu (ile z danymi), dodani przez zespół,
          czas dołączania dowodów z notatek
  labels  (tylko v8) wszystkie etykiety must: bramkuje / powód pominięcia
"""

import ro_boot  # noqa: F401
import asyncio
import datetime
import json
import os
import random
import statistics
import time
from collections import Counter

import data

ARGS = (os.environ.get("RESEARCH_ARGS") or "pairs").split()
MODE = ARGS[0]
JOBS = [689430, 689431, 689433, 689440]
NEW_JOBS_SINCE = "2026-09-25"

try:
    from app.services.must_text_evidence import attach_gate_evidence

    VERSION = "v8"
except ImportError:  # kod produkcji
    attach_gate_evidence = None
    VERSION = "v7"


async def _gate(db, job, cands):
    """Bramki tak, jak liczy je ekran (dowody, weryfikacje rekrutera)."""
    from app.services.dealbreaker_filters import apply_dealbreakers
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.requirement_verification import load_verified_requirements

    inputs = search_dealbreaker_inputs(job)
    await load_verified_requirements(db, job, cands)
    t0 = time.perf_counter()
    if attach_gate_evidence is not None:
        await attach_gate_evidence(db, cands, inputs.must_skills)
    evidence_ms = (time.perf_counter() - t0) * 1000
    res = apply_dealbreakers(cands, inputs=inputs)
    return inputs, res, evidence_ms


async def _load(db, ids):
    from sqlalchemy import select

    from app.models.candidate import Candidate

    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 2000):
        batch = (
            (await db.execute(select(Candidate).where(Candidate.id.in_(ids[i : i + 2000]))))
            .scalars()
            .all()
        )
        for c in batch:
            db.expunge(c)
            out[c.id] = c
    return out


def _has_data(c):
    from app.services.scoring_service import candidate_known_skill_names

    return bool((c.raw_cv_text or "").strip()) or bool(candidate_known_skill_names(c))


async def pairs():
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    pos = await data.load_positives()
    jobs = {j.id: j for j in await data.load_jobs()}
    async with AsyncSessionLocal() as db:
        added_new = {}
        for jid, cid in (
            await db.execute(
                text(
                    "SELECT DISTINCT s.job_id, s.candidate_id FROM candidate_stages s "
                    "JOIN jobs j ON j.id = s.job_id WHERE j.created_at >= :since "
                    "AND j.external_source IS DISTINCT FROM 'traffit'"
                ),
                {"since": datetime.date.fromisoformat(NEW_JOBS_SINCE)},
            )
        ).all():
            added_new.setdefault(jid, set()).add(cid)
        cohorts = {
            "sent": {j: {c for c, r in p.items() if r >= 1} for j, p in pos.items()},
            "added_new_jobs": added_new,
        }
        need = set().union(*(s for co in cohorts.values() for s in co.values()))
        cands = await _load(db, need)
        report = {}
        for name, cohort in cohorts.items():
            reasons = Counter()
            per_job = []
            per_job_must = []
            n = kept_n = 0
            ev_ms = []
            for jid, people in cohort.items():
                job = jobs.get(jid)
                batch = [cands[c] for c in people if c in cands]
                if job is None or not batch:
                    continue
                inputs, res, ms = await _gate(db, job, batch)
                ev_ms.append(ms)
                kept = len(res.kept)
                n += len(batch)
                kept_n += kept
                per_job.append(kept / len(batch))
                if inputs.must_skills:
                    per_job_must.append(kept / len(batch))
                reasons.update(res.exclusion_reasons.values())
            report[name] = {
                "jobs": len(per_job),
                "people": n,
                "visible_micro": round(kept_n / max(1, n), 3),
                "visible_macro": round(statistics.mean(per_job), 3) if per_job else None,
                "jobs_with_must_gate": len(per_job_must),
                "visible_macro_must_jobs": round(statistics.mean(per_job_must), 3)
                if per_job_must
                else None,
                "hidden_reasons": dict(reasons.most_common()),
                "evidence_ms_median": round(statistics.median(ev_ms), 1) if ev_ms else None,
            }
            print(json.dumps({VERSION: {name: report[name]}}, ensure_ascii=False), flush=True)
    json.dump(report, open(f"/research/out_anywhere_pairs_{VERSION}.json", "w"), indent=1)


async def full():
    from sqlalchemy import select, text

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile

    jobs = [int(x) for x in ARGS[1].split(",")] if len(ARGS) > 1 else JOBS
    out = {}
    async with AsyncSessionLocal() as db:
        ids = [r for (r,) in (await db.execute(select(Candidate.id))).all()]
        for jid in jobs:
            t0 = time.time()
            job = (await db.execute(select(Job).where(Job.id == jid))).scalar_one()
            db.expunge(job)
            added = {
                c
                for (c,) in (
                    await db.execute(
                        text("SELECT DISTINCT candidate_id FROM candidate_stages WHERE job_id=:j"),
                        {"j": jid},
                    )
                ).all()
            }
            ctx = build_request_context(job, _to_scoring_profile(DEFAULT_PROFILE))
            reasons = Counter()
            visible = {}
            data_ids = set()
            ev_ms = []
            for i in range(0, len(ids), 2000):
                batch = list((await _load(db, ids[i : i + 2000])).values())
                inputs, res, ms = await _gate(db, job, batch)
                ev_ms.append(ms)
                reasons.update(res.exclusion_reasons.values())
                kept = res.kept
                for f in await score_candidates(None, ctx, kept):
                    visible[f.breakdown.candidate_id] = f.fit_score
                data_ids |= {c.id for c in kept if _has_data(c)}
            ranked = sorted((c for c, s in visible.items() if s is not None), key=lambda c: -visible[c])
            proposals = [c for c in ranked if visible[c] >= settings.AUTO_FULL_REVIEW_MIN_SCORE][
                : settings.AUTO_FULL_REVIEW_TOP_K
            ]
            rank_of = {c: i + 1 for i, c in enumerate(ranked)}
            out[jid] = {
                "title": (job.working_title or job.title)[:60],
                "must": list(inputs.must_skills),
                "base": len(ids),
                "visible": len(visible),
                "hidden": dict(reasons.most_common()),
                "proposals_ge_threshold": len(proposals),
                "proposals_with_data": sum(1 for c in proposals if c in data_ids),
                "added": len(added),
                "added_visible": sum(1 for c in added if c in visible),
                "added_ranks": sorted(rank_of[c] for c in added if c in rank_of)[:15],
                "added_in_proposals": sum(1 for c in added if c in set(proposals)),
                "evidence_ms_per_2000": round(statistics.median(ev_ms), 1),
                "secs": round(time.time() - t0),
            }
            print(json.dumps({VERSION: {jid: out[jid]}}, ensure_ascii=False), flush=True)
    json.dump(out, open(f"/research/out_anywhere_full_{VERSION}.json", "w"), indent=1, ensure_ascii=False)


async def labels():
    from app.services.must_gate_terms import gate_requirement, ignored_reason
    from app.services.scoring_service import job_explicit_must_skills

    jobs = await data.load_jobs()
    seen = Counter()
    for j in jobs:
        for label in job_explicit_must_skills(j):
            seen[label] += 1
    gated = Counter()
    split = Counter()
    examples = {}
    for label, n in seen.items():
        req = gate_requirement(label)
        if req is None:
            reason = ignored_reason(label)
            gated[f"ignored:{reason}"] += n
            examples.setdefault(reason, []).append(label)
        else:
            gated["gates"] += n
            if len(req.options) > 1:
                split["any_of"] += n
            if req.options != (label,):
                split["normalized"] += n
    total = sum(seen.values())
    report = {
        "labels_total": total,
        "distinct": len(seen),
        "share": {k: round(v / total, 3) for k, v in gated.most_common()},
        "normalized_share": {k: round(v / total, 3) for k, v in split.items()},
        "examples": {k: random.Random(1).sample(v, min(12, len(v))) for k, v in examples.items()},
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    json.dump(report, open("/research/out_anywhere_labels.json", "w"), indent=1, ensure_ascii=False)


async def main():
    await data.boot()
    print("version", VERSION, "mode", MODE, flush=True)
    await {"pairs": pairs, "full": full, "labels": labels}[MODE]()


asyncio.run(main())
