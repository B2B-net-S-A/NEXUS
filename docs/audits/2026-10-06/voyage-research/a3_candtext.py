"""Etap 3: wariant tekstu kandydata i model — przeliczenie wektorów na próbce (300 rekrutacji z 2026 + tło).
Teksty powstają w pamięci i idą tylko do Voyage; na dysk trafiają wyłącznie wektory."""
import asyncio, json, os, sys
import numpy as np
from sqlalchemy import select, text
sys.path.insert(0, "/vr")
import voy
from common import *

OUTD = "/vr/data/a3"
os.makedirs(OUTD, exist_ok=True)


class NoName:
    def __init__(self, c, **over):
        self._c = c; self._o = over
    def __getattr__(self, k):
        if k in self._o:
            return self._o[k]
        return getattr(self._c, k)


async def main():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services import embedding_service as es
    from app.services.canonical_text import build_candidate_text_v2
    from app.services.requirement_contract import stored_contract, requirement_labels

    cids, C, pos, gt, t0, _ = load()
    rng = np.random.default_rng(1)
    test = sorted(j for j in gt if split_of(t0[j]) == "test")
    jobs = sorted(rng.choice(test, size=min(300, len(test)), replace=False).tolist())
    gt_idx = sorted(set(int(i) for j in jobs for i in gt[j]))
    others = np.setdiff1d(np.arange(len(cids)), gt_idx)
    distr = sorted(np.random.default_rng(2).choice(others, 10000, replace=False).tolist())
    meta = json.load(open(f"{D}/cand_meta.json"))
    alive = np.array([str(int(c)) in meta for c in cids])
    print("sieroty w Qdrancie (punkt bez kandydata):", int((~alive).sum()), flush=True)
    gt_idx = [i for i in gt_idx if alive[i]]
    others = np.setdiff1d(np.flatnonzero(alive), gt_idx)
    distr = sorted(np.random.default_rng(2).choice(others, 10000, replace=False).tolist())
    sub = np.array(gt_idx + distr)
    sub_ids = cids[sub]
    np.save(f"{OUTD}/sub_idx.npy", sub); json.dump(jobs, open(f"{OUTD}/jobs.json", "w"))
    print("jobs", len(jobs), "gt cands", len(gt_idx), "subset", len(sub), flush=True)

    texts = {k: [] for k in ("v1", "v1_noname", "v1_noname_nosen", "v2", "nocv", "cv_first")}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        rows = {}
        for s in range(0, len(sub_ids), 1000):
            part = [int(x) for x in sub_ids[s:s + 1000]]
            for c in (await db.execute(select(Candidate).where(Candidate.id.in_(part)))).scalars():
                rows[c.id] = c
        for cid in sub_ids:
            c = rows[int(cid)]
            texts["v1"].append(es._build_candidate_text_v1(c))
            texts["v1_noname"].append(es._build_candidate_text_v1(NoName(c, name=None, lastname=None)))
            texts["v1_noname_nosen"].append(es._build_candidate_text_v1(NoName(c, name=None, lastname=None, years_it_experience=None)))
            texts["v2"].append(build_candidate_text_v2(c) or " ")
            texts["nocv"].append(es._build_candidate_text_v1(NoName(c, name=None, lastname=None, raw_cv_text=None)))
            nn = es._build_candidate_text_v1(NoName(c, name=None, lastname=None, raw_cv_text=None))
            texts["cv_first"].append(((c.raw_cv_text or "")[:3000] + "\n" + nn).strip())
        qtexts = []
        jl = {j.id: j for j in (await db.execute(select(Job).where(Job.id.in_(jobs)))).scalars()}
        for jid in jobs:
            j = jl[jid]
            q = es._build_job_text(j, max_field_chars=None)
            cc = stored_contract(j)
            if cc is not None:
                q += "\n" + "\n".join(f"{k}: {', '.join(v)}" for k, v in requirement_labels(cc).items() if v)
            qtexts.append(q)
    json.dump({k: int(np.mean([len(t) for t in v])) for k, v in texts.items()}, open(f"{OUTD}/lens.json", "w"))
    plan = [("voyage-3", k) for k in texts] + [("voyage-3.5", "v1"), ("voyage-4-large", "v1"), ("voyage-3.5", "v1_noname")]
    for model in sorted(set(m for m, _ in plan)):
        p = f"{OUTD}/q__{model}.npy"
        if not os.path.exists(p):
            np.save(p, await voy.embed_all(qtexts, input_type="query", model=model))
    for model, k in plan:
        p = f"{OUTD}/c__{model}__{k}.npy"
        if os.path.exists(p):
            continue
        print("embed", model, k, sum(map(len, texts[k])), "chars", flush=True)
        np.save(p, await voy.embed_all(texts[k], input_type="document", model=model))
    print("done", flush=True)

asyncio.run(main())
