"""Eksport do badania: wektory z Qdranta, metadane kandydatów (bez tekstów), prawda per rekrutacja.
Tylko odczyt. Wyniki w /vr/data."""
import asyncio, hashlib, json, os, time
import numpy as np
from sqlalchemy import select, text

OUT = "/vr/data"
os.makedirs(OUT, exist_ok=True)


def scroll_all(client, coll):
    ids, vecs, payloads = [], [], []
    offset = None
    while True:
        pts, offset = client.scroll(collection_name=coll, limit=2000, offset=offset,
                                    with_payload=["content_hash", "embedding_model", "status"], with_vectors=True)
        for p in pts:
            v = p.vector
            if isinstance(v, dict):
                v = next(iter(v.values()))
            ids.append(int(p.id)); vecs.append(v); payloads.append(p.payload or {})
        if offset is None:
            break
    return np.array(ids, dtype=np.int64), np.array(vecs, dtype=np.float32), payloads


async def main():
    from app.core.database import AsyncSessionLocal
    from app.services import embedding_service as es
    from app.models.candidate import Candidate

    client = es._get_qdrant_client()
    t = time.time()
    cids, cvecs, cpay = scroll_all(client, es.candidates_collection_name())
    np.save(f"{OUT}/cand_ids.npy", cids); np.save(f"{OUT}/cand_vecs.npy", cvecs)
    jids, jvecs, jpay = scroll_all(client, es.jobs_collection_name())
    np.save(f"{OUT}/jobdoc_ids.npy", jids); np.save(f"{OUT}/jobdoc_vecs.npy", jvecs)
    print("qdrant", len(cids), len(jids), round(time.time() - t), "s", flush=True)
    payhash = {int(i): (p.get("content_hash"), p.get("embedding_model")) for i, p in zip(cids, cpay)}

    meta = {}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        res = await db.stream(select(Candidate).execution_options(yield_per=1000))
        n = 0
        async for (c,) in res:
            txt = es._build_candidate_text_v1(c)
            skills = c.skills if isinstance(c.skills, list) else []
            exp = c.experience if isinstance(c.experience, list) else []
            ph = payhash.get(c.id)
            name_part = " ".join(p for p in (c.name, c.lastname) if p)
            meta[c.id] = {
                "created": c.created_at.timestamp() if c.created_at else None,
                "cv_len": len(c.raw_cv_text or ""),
                "n_skills": len(skills),
                "n_exp": len(exp),
                "has_summary": bool(c.ai_summary),
                "txt_len": len(txt),
                "txt_wo_name_len": max(0, len(txt) - len(name_part)),
                "cc": c.competence_category_id,
                "src": c.external_source,
                "status": str(getattr(c.status, "value", c.status)),
                "indexed": ph is not None,
                "fresh": (ph is not None and ph[0] == hashlib.sha256(txt.encode()).hexdigest()),
                "model": ph[1] if ph else None,
            }
            n += 1
            if n % 10000 == 0:
                print("cands", n, flush=True)
        json.dump(meta, open(f"{OUT}/cand_meta.json", "w"), default=float)

        rows = (await db.execute(text("""
          SELECT job_id, candidate_id, max(CASE stage::text
              WHEN 'hired' THEN 4 WHEN 'onboarding' THEN 3 WHEN 'negotiation' THEN 3 WHEN 'acceptance' THEN 3
              WHEN 'client_interview' THEN 2 WHEN 'interview' THEN 1 WHEN 'cv_sent' THEN 1 WHEN 'verified' THEN 1 END) rel,
            extract(epoch from min(moved_at)) first_at
          FROM candidate_stages
          WHERE stage::text IN ('verified','cv_sent','interview','client_interview','acceptance','negotiation','onboarding','hired')
          GROUP BY 1,2"""))).all()
        gt = {}
        for j, c, rel, fa in rows:
            gt.setdefault(int(j), []).append([int(c), int(rel), float(fa)])
        json.dump(gt, open(f"{OUT}/gt.json", "w"), default=float)
        # słabszy sygnał: ktokolwiek dodany do pipeline'u (wszystkie etapy) — do eksperymentów kolaboracyjnych
        rows = (await db.execute(text("""
          SELECT job_id, candidate_id, extract(epoch from min(moved_at)) FROM candidate_stages GROUP BY 1,2"""))).all()
        anyp = {}
        for j, c, fa in rows:
            anyp.setdefault(int(j), []).append([int(c), float(fa)])
        json.dump(anyp, open(f"{OUT}/any_pipeline.json", "w"), default=float)
        jrows = (await db.execute(text("""
          SELECT id, title, client_id, competence_category_id, status::text,
                 extract(epoch from coalesce(opened_at, created_at)) opened, external_source,
                 champion_profile IS NOT NULL AND champion_profile::text <> '{}' has_champ,
                 coalesce(jsonb_array_length(CASE WHEN jsonb_typeof(must_skills)='array' THEN must_skills END),0) n_must,
                 length(coalesce(description,'')) dlen, length(coalesce(requirements,'')) rlen
          FROM jobs"""))).all()
        jm = {int(r[0]): {"title": r[1], "client": r[2], "cc": r[3], "status": r[4], "opened": r[5],
                          "src": r[6], "champ": r[7], "n_must": r[8], "dlen": r[9], "rlen": r[10]} for r in jrows}
        json.dump(jm, open(f"{OUT}/jobs_meta.json", "w"), default=float)
    print("done", len(meta), len(gt), len(jm), flush=True)

asyncio.run(main())
