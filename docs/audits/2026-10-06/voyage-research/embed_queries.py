"""Warianty zapytania dla rekrutacji z prawdą >=3. Tylko odczyt bazy; wektory do /vr/data/q_<wariant>.npy."""
import asyncio, json, os, sys
from types import SimpleNamespace
import numpy as np
from sqlalchemy import select, text

sys.path.insert(0, "/vr")
import voy

OUT = "/vr/data"


def labels_of(job):
    from app.services.requirement_contract import requirements_for_job, requirement_labels
    try:
        lab = requirement_labels(requirements_for_job(job))
        return lab.get("must") or [], lab.get("nice") or []
    except Exception:
        def names(v):
            return [x if isinstance(x, str) else (x or {}).get("name", "") for x in (v or []) if x]
        return names(job.must_skills), names(job.nice_skills)


async def main():
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.embedding_service import _build_job_text
    from app.services.requirement_contract import stored_contract, requirement_labels
    try:
        from app.services.scoring_service import refresh_alias_map
    except Exception:
        refresh_alias_map = None

    gt = json.load(open(f"{OUT}/gt.json"))
    ids = sorted(int(j) for j, v in gt.items() if len(v) >= 3)
    texts = {k: [] for k in ("prod", "title", "req_short", "req_long", "nochamp", "hyde")}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        if refresh_alias_map:
            try:
                await refresh_alias_map(db)
            except Exception as e:
                print("alias map:", repr(e))
        jobs = {j.id: j for j in (await db.execute(select(Job).where(Job.id.in_(ids)))).scalars().all()}
        ids = [i for i in ids if i in jobs]
        for jid in ids:
            j = jobs[jid]
            q = _build_job_text(j, max_field_chars=None)
            c = stored_contract(j)
            if c is not None:
                q += "\n" + "\n".join(f"{k}: {', '.join(v)}" for k, v in requirement_labels(c).items() if v)
            must, nice = labels_of(j)
            title = j.title or ""
            rs = title + ("\nWymagania: " + ", ".join(must) if must else "") + ("\nMile widziane: " + ", ".join(nice) if nice else "")
            ns = SimpleNamespace(**{k: getattr(j, k, None) for k in ("title", "description", "requirements", "seniority",
                                    "subcategory", "industry", "train_name", "must_skills", "nice_skills",
                                    "location", "work_mode", "remote_policy")})
            ns.champion_profile = None
            try:
                nochamp = _build_job_text(ns, max_field_chars=None)
            except Exception:
                nochamp = rs
            texts["prod"].append(q)
            texts["title"].append(title)
            texts["req_short"].append(rs)
            texts["req_long"].append(rs + ("\n" + (j.requirements or "")[:2000] if j.requirements else "") + ("\n" + (j.description or "")[:2000] if j.description else ""))
            texts["nochamp"].append(nochamp)
            texts["hyde"].append(f"{title}. Doświadczenie zawodowe: {title}. Umiejętności: {', '.join(must + nice)}.")
    np.save(f"{OUT}/q_ids.npy", np.array(ids, dtype=np.int64))
    json.dump({k: [len(t) for t in v] for k, v in texts.items()}, open(f"{OUT}/q_lens.json", "w"))
    only = sys.argv[1:] or list(texts)
    for k in only:
        path = f"{OUT}/q_{k}.npy"
        if os.path.exists(path):
            print("skip", k); continue
        it = "document" if k == "hyde" else "query"
        print("embed", k, len(texts[k]), sum(map(len, texts[k])), "chars", flush=True)
        np.save(path, await voy.embed_all(texts[k], input_type=it))
    # ten sam tekst produkcyjny jako document — rozdziela wpływ input_type od tekstu
    if not os.path.exists(f"{OUT}/q_prod_asdoc.npy"):
        np.save(f"{OUT}/q_prod_asdoc.npy", await voy.embed_all(texts["prod"], input_type="document"))
    print("done", len(ids))

asyncio.run(main())
