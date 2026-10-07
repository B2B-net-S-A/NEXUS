"""Dlaczego wektory części nowych kandydatów są nieaktualne: który składnik tekstu zmienił się po indeksacji."""
import asyncio, hashlib, json, collections
from sqlalchemy import select, text

class Over:
    def __init__(self, c, **o): self._c, self._o = c, o
    def __getattr__(self, k): return self._o[k] if k in self._o else getattr(self._c, k)

async def main():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.services import embedding_service as es
    meta = json.load(open("/vr/data/cand_meta.json"))
    stale = [int(k) for k, m in meta.items() if m["indexed"] and not m["fresh"]]
    client = es._get_qdrant_client()
    pts = client.retrieve(es.candidates_collection_name(), ids=stale, with_payload=["content_hash"], with_vectors=False)
    ph = {int(p.id): (p.payload or {}).get("content_hash") for p in pts}
    why = collections.Counter(); created = collections.Counter(); upd_gap = []
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        for c in (await db.execute(select(Candidate).where(Candidate.id.in_(stale)))).scalars():
            target = ph.get(c.id)
            h = lambda cc: hashlib.sha256(es._build_candidate_text_v1(cc).encode()).hexdigest()
            found = None
            for name, over in (("kategoria", dict(competence_category=None)),
                               ("podsumowanie AI", dict(ai_summary=None)),
                               ("umiejętności", dict(skills=None)),
                               ("staż (lata)", dict(years_it_experience=None)),
                               ("kategoria+staż", dict(competence_category=None, years_it_experience=None)),
                               ("tagi", dict(tags=None)), ("verified_tech", dict(verified_tech=None))):
                if h(Over(c, **over)) == target:
                    found = name; break
            why[found or "inne/kilka pól"] += 1
            created[(c.external_source, c.created_at.strftime("%Y-%m"))] += 1
    print("przyczyna rozjazdu:", why.most_common())
    print("źródło i miesiąc powstania:", sorted(created.items()))
asyncio.run(main())
