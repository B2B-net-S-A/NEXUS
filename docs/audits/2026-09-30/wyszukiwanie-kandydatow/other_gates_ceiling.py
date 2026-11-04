"""(1) Bramki poza must: które ukrywają osoby wysłane do klienta i o ile przekroczony budżet.
(2) Sufit puli wektorowej: jaki odsetek wysłanych jest w top-K najbliższych wektorowo
(cała kolekcja Qdranta, wektor zapytania jak `canonical_fit`) — K=60 (panel Moich ludzi),
200 (Moi ludzie, dzwonek), 300 (auto-dopasowanie), 1000 (/ai-matches), 3000.
Tylko odczyt. RESEARCH_ARGS: n=250 seed=11 since=2024-07-01
"""
import ro_boot  # noqa: F401
import asyncio, json, os, random, statistics, time
from collections import Counter, defaultdict
from dataclasses import replace
import data

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
N = int(ARGS.get("n", 250)); SEED = int(ARGS.get("seed", 11)); SINCE = ARGS.get("since", "2024-07-01")
KS = (60, 200, 300, 1000, 3000)


async def main():
    await data.boot()
    import datetime
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services.requirement_contract import search_dealbreaker_inputs
    from app.services.dealbreaker_filters import apply_dealbreakers, _candidate_rate_pln_hourly
    from app.services.request_matching_context import build_request_context
    from app.services.full_search_measurement import request_vector
    from app.services.embedding_service import _collection
    from app.core.config import settings
    from qdrant_client import QdrantClient
    from scripts.eval_matching import DEFAULT_PROFILE, _to_scoring_profile
    pos = await data.load_positives(); jobs = {j.id: j for j in await data.load_jobs()}
    since = datetime.date.fromisoformat(SINCE)
    # (1) bramki poza must — wszystkie rekrutacje z wysłanymi
    work = [(jid, [c for c, r in P.items() if r >= 1]) for jid, P in pos.items()
            if jid in jobs and jobs[jid].external_source != "manual" and any(r >= 1 for r in P.values())]
    need = sorted({c for _, s in work for c in s})
    cobj = {}
    async with AsyncSessionLocal() as db:
        for i in range(0, len(need), 1000):
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(need[i:i+1000])))).scalars().all():
                db.expunge(c); cobj[c.id] = c
    recent = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
    reasons = Counter(); total = 0; ratios = []; jobs_with_budget = 0
    r_reasons = Counter(); r_total = 0; r_ratios = []
    for jid, sent in work:
        j = jobs[jid]; inputs = replace(search_dealbreaker_inputs(j), must_skills=())
        batch = [cobj[c] for c in sent if c in cobj]
        if inputs.budget_hourly:
            jobs_with_budget += 1
        res = apply_dealbreakers(batch, inputs=inputs)
        total += len(batch)
        reasons.update(res.exclusion_reasons.values())
        is_recent = (j.opened_at or j.created_at) >= recent
        if is_recent:
            r_total += len(batch); r_reasons.update(res.exclusion_reasons.values())
        for cid, why in res.exclusion_reasons.items():
            if why == "over_budget":
                r = _candidate_rate_pln_hourly(cobj[cid])
                if r and inputs.budget_hourly:
                    ratios.append(r / float(inputs.budget_hourly))
                    if is_recent:
                        r_ratios.append(r / float(inputs.budget_hourly))
    gates = {"pairs": total, "jobs": len(work), "jobs_with_budget": jobs_with_budget,
             "hidden_share": {k: round(v / total, 4) for k, v in reasons.most_common()},
             "over_budget_ratio_quartiles": [round(x, 3) for x in statistics.quantiles(ratios, n=4)] if len(ratios) > 4 else None,
             "over_budget_within_10pct": round(sum(r <= 1.10 for r in ratios) / len(ratios), 3) if ratios else None,
             "recent_since_2026_03": {"pairs": r_total, "hidden_share": {k: round(v / max(1, r_total), 4) for k, v in r_reasons.most_common()},
                                       "over_budget_ratio_quartiles": [round(x, 3) for x in statistics.quantiles(r_ratios, n=4)] if len(r_ratios) > 4 else None}}
    print(json.dumps(gates, indent=1), flush=True)
    # (2) sufit puli
    elig = [jid for jid, P in pos.items() if jid in jobs and jobs[jid].external_source != "manual"
            and sum(1 for r in P.values() if r >= 1) >= 3 and (jobs[jid].opened_at or jobs[jid].created_at).date() >= since]
    random.seed(SEED); random.shuffle(elig); sample = elig[:N]
    qc = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=120)
    prof = _to_scoring_profile(DEFAULT_PROFILE)
    hits = defaultdict(list); t0 = time.time()
    for n, jid in enumerate(sample):
        ctx = build_request_context(jobs[jid], prof)
        vec = await request_vector(ctx.query_text)
        if vec is None:
            continue
        res = qc.query_points(collection_name=_collection(), query=list(vec), limit=max(KS), with_payload=False).points
        order = [int(p.id) for p in res]
        rel = {c for c, r in pos[jid].items() if r >= 1}
        for k in KS:
            hits[k].append(len(rel & set(order[:k])) / len(rel))
        if n % 50 == 0:
            print(f"{n}/{len(sample)} {time.time()-t0:.0f}s", flush=True)
    ceiling = {k: round(statistics.mean(v), 4) for k, v in hits.items()}
    out = {"gates": gates, "ceiling_sent_in_topK": ceiling, "jobs": len(hits[KS[0]])}
    print(json.dumps(out, indent=1))
    json.dump(out, open("/research/out_other_gates_ceiling.json", "w"), indent=1)


asyncio.run(main())
