"""Kalibracja progu plakietki „≈” (kod gałęzi, 30.09.2026) na bazie badania: podobne rekrutacje i przepięcia — czy wzór podobieństwa
wskazuje rekrutacje, z których zespół NAPRAWDĘ brał ludzi.

Zdarzenie „ponownego użycia”: osoba wysłana do klienta w rekrutacji A (cv_sent,
rozmowa, akceptacja; nie zatrudniona w A) trafia później w rekrutacji B co najmniej
do „zweryfikowany” (do 365 dni). Dla każdej rekrutacji B otwartej od `since`
porządkujemy wszystkie wcześniejsze rekrutacje różnymi miarami i patrzymy, czy
prawdziwe źródła A są w pierwszej piątce (tak działa panel „Podobne rekrutacje”).
Druga część: precyzja propozycji przepięcia (ludzie wysłani w podpowiedzianych
rekrutacjach) — ilu z nich zespół wziął do B.

Tylko odczyt. RESEARCH_ARGS: since=2025-01-01 window=365
"""
import ro_boot  # noqa: F401
import asyncio, json, math, os, random, statistics, time
from collections import defaultdict, Counter
import numpy as np

ARGS = dict(a.split("=", 1) for a in os.environ.get("RESEARCH_ARGS", "").split() if "=" in a)
SINCE = ARGS.get("since", "2025-01-01"); WINDOW = int(ARGS.get("window", 365))
SENT = ("cv_sent", "client_interview", "acceptance")


async def main():
    import datetime
    from sqlalchemy import select, text
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import job_similarity as js
    from app.services.skill_taxonomy_loader import refresh_alias_map
    from app.services.embedding_service import JOBS_COLLECTION
    from app.core.config import settings
    await refresh_alias_map()
    try:
        from app.services.skill_normalize import refresh as _r  # noqa
    except Exception:
        pass
    since = datetime.datetime.fromisoformat(SINCE).replace(tzinfo=datetime.timezone.utc)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Job.id, Job.title, Job.client_id, Job.reference_number, Job.status,
                                        Job.competence_category_id, Job.must_skills, Job.champion_profile,
                                        Job.created_at, Job.opened_at).where(Job.client_id.is_not(None)))).all()
        ms = (await db.execute(text("SELECT candidate_id, job_id, stage::text, first_reached_at FROM analytics_first_milestones "
                                    "WHERE job_id IS NOT NULL"))).all()
    pool = js._build_pool(rows)
    print(f"pool jobs={len(pool.jobs)} with skills={sum(1 for j in pool.jobs.values() if j.skills)}", flush=True)
    opened = {j.id: (j.opened_at or j.created_at) for j in pool.jobs.values()}

    first = defaultdict(dict)  # (c,j) -> stage -> ts
    for c, j, s, t in ms:
        if j in pool.jobs and t is not None:
            first[(c, j)][s] = t
    sent_at = {}; hired = set(); ver_at = {}; sent_b = {}
    for (c, j), st in first.items():
        ts = [st[s] for s in SENT if s in st]
        if ts:
            sent_at[(c, j)] = min(ts)
        if "hired" in st:
            hired.add((c, j))
        vt = [st[s] for s in ("verified", "cv_sent", "client_interview", "acceptance", "hired") if s in st]
        if vt:
            ver_at[(c, j)] = min(vt)
    by_cand_sent = defaultdict(list)
    for (c, j), t in sent_at.items():
        if (c, j) not in hired:
            by_cand_sent[c].append((j, t))
    # zdarzenia ponownego użycia
    reuse = defaultdict(lambda: defaultdict(set))  # B -> A -> {c}
    for (c, b), tb in ver_at.items():
        ob = opened.get(b)
        if ob is None or ob < since:
            continue
        for a, ta in by_cand_sent.get(c, []):
            if a != b and ta < tb and (tb - ta).days <= WINDOW and (opened.get(a) or ta) <= (ob or tb):
                reuse[b][a].add(c)
    targets = sorted(reuse)
    n_events = sum(len(cs) for d in reuse.values() for cs in d.values())
    n_people = len({c for d in reuse.values() for cs in d.values() for c in cs})
    all_ver_b = Counter(b for (c, b) in ver_at if opened.get(b) and opened[b] >= since)
    print(f"targets={len(targets)} events={n_events} people={n_people}", flush=True)

    # wektory rekrutacji
    from qdrant_client import QdrantClient
    qc = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=120)
    ids = list(pool.jobs)
    vec = {}
    for i in range(0, len(ids), 256):
        for p in qc.retrieve(collection_name=JOBS_COLLECTION, ids=ids[i:i+256], with_vectors=True, with_payload=False):
            v = p.vector if not isinstance(p.vector, dict) else next(iter(p.vector.values()))
            if v is not None:
                vec[int(p.id)] = np.asarray(v, dtype=np.float32)
    print(f"job vectors={len(vec)}", flush=True)
    vid = [j for j in ids if j in vec]
    M = np.stack([vec[j] for j in vid]); M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    vpos = {j: i for i, j in enumerate(vid)}

    def prod_score(a, b):
        A, B = pool.jobs[a], pool.jobs[b]
        return js.similarity_score(B.skills, B.tokens, B.competence_category_id, A.skills, A.tokens, A.competence_category_id,
                                   a_client=B.client_id, b_client=A.client_id)

    # źródła „z kogo można przepiąć”: rekrutacje z ≥1 wysłaną, nie zatrudnioną osobą
    sent_people = defaultdict(set)
    for c, lst in by_cand_sent.items():
        for a, ta in lst:
            sent_people[a].add((c, ta))
    variants = ["prod", "prod_ge55", "vec", "vec_client", "prod+vec", "same_client_recent"]
    agg = defaultdict(lambda: defaultdict(list))
    true_scores = []; top1_scores = []; top5_min = []
    prop = defaultdict(lambda: defaultdict(list))
    t0 = time.time()
    for n, b in enumerate(targets):
        ob = opened[b]
        cand_a = [a for a in sent_people if a != b and (opened.get(a) or ob) <= ob
                  and any(ta < ob + datetime.timedelta(days=90) and (ob - ta).days <= WINDOW for _, ta in sent_people[a])]
        if not cand_a:
            continue
        truth = set(reuse[b])
        ps = {a: prod_score(a, b) for a in cand_a}
        vs = {}
        if b in vpos:
            sims = M[[vpos[a] for a in cand_a if a in vpos]] @ M[vpos[b]]
            k = 0
            for a in cand_a:
                if a in vpos:
                    vs[a] = float(sims[k]); k += 1
        B = pool.jobs[b]
        orders = {}
        orders["prod"] = sorted(cand_a, key=lambda a: (-ps[a], -(opened.get(a) or ob).timestamp()))
        orders["prod_ge55"] = [a for a in orders["prod"] if ps[a] >= js.MIN_SCORE]
        if vs:
            orders["vec"] = sorted(cand_a, key=lambda a: -vs.get(a, -1))
            vc = lambda a: vs.get(a, -1) + (0.08 if pool.jobs[a].client_id == B.client_id else 0)
            orders["vec_client"] = sorted(cand_a, key=lambda a: -vc(a))
            true_scores.extend(vc(a) for a in truth if a in vs)
            top1_scores.append(vc(orders["vec_client"][0]))
            if len(orders["vec_client"]) >= 5:
                top5_min.append(vc(orders["vec_client"][4]))
            orders["prod+vec"] = sorted(cand_a, key=lambda a: -(ps[a] / 100 + vs.get(a, -1)))
        orders["same_client_recent"] = sorted([a for a in cand_a if pool.jobs[a].client_id == B.client_id],
                                              key=lambda a: -(opened.get(a) or ob).timestamp())
        for name, order in orders.items():
            top5 = order[:5]
            hit_jobs = truth & set(top5)
            people_total = {c for a in truth for c in reuse[b][a]}
            people_hit = {c for a in hit_jobs for c in reuse[b][a]}
            agg[name]["job_recall@5"].append(len(hit_jobs) / len(truth))
            agg[name]["people_recall@5"].append(len(people_hit) / len(people_total))
            agg[name]["any_source_in_top5"].append(1.0 if hit_jobs else 0.0)
            agg[name]["suggested"].append(len(top5))
            # propozycje przepięcia: wysłani (nie zatrudnieni) w top5, wysłani do 365 dni przed otwarciem B
            props = {c for a in top5 for (c, ta) in sent_people[a] if ta < ob and (ob - ta).days <= WINDOW}
            if props:
                taken = {c for c in props if (c, b) in ver_at}
                prop[name]["proposals"].append(len(props))
                prop[name]["precision"].append(len(taken) / len(props))
                prop[name]["taken"].append(len(taken))
        if n % 200 == 0:
            print(f"{n}/{len(targets)} {time.time()-t0:.0f}s", flush=True)
    # tło: ile wszystkich weryfikacji w B to ponowne użycie
    reuse_share = n_events / max(1, sum(all_ver_b.values()))
    summary = {k: {m: round(statistics.mean(v), 4) for m, v in d.items()} | {"targets": len(d["job_recall@5"])} for k, d in agg.items()}
    psum = {k: {m: round(statistics.mean(v), 4) for m, v in d.items()} | {"jobs_with_props": len(d["precision"])} for k, d in prop.items()}
    # jak często ponowne źródło ma wynik prod >= 55
    src_scores = [prod_score(a, b) for b in targets for a in reuse[b]]
    out = {"targets": len(targets), "events": n_events, "people": n_people, "reuse_share_of_verified_in_targets": round(reuse_share, 4),
           "sources_prod_ge55": round(sum(s >= 55 for s in src_scores) / len(src_scores), 4),
           "sources_same_client": round(sum(pool.jobs[a].client_id == pool.jobs[b].client_id for b in targets for a in reuse[b]) / len(src_scores), 4),
           "sources_prod_score_quartiles": [float(x) for x in np.percentile(src_scores, [25, 50, 75])],
           "ranking": summary, "proposals": psum,
           "vec_client_true_source_pct": {p: round(float(np.percentile(true_scores, p)), 4) for p in (5, 10, 25, 50)},
           "vec_client_top1_pct": {p: round(float(np.percentile(top1_scores, p)), 4) for p in (10, 25, 50, 75)},
           "vec_client_5th_pct": {p: round(float(np.percentile(top5_min, p)), 4) for p in (10, 25, 50)}}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    json.dump(out, open("/research/out_similar_calib.json", "w"), indent=1, ensure_ascii=False)


asyncio.run(main())
