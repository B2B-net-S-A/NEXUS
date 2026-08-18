"""Champion (zweryfikowany z klientem) nadpisuje ubogie auto-must — odwracalnie."""
import asyncio, json, sys
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.job import Job
from sqlalchemy.orm.attributes import flag_modified

SRC = Path("/tmp/champ-parsed-v3.jsonl")
COMMIT = "--commit" in sys.argv

async def main():
    best: dict[int, dict] = {}
    for line in SRC.open(encoding="utf-8"):
        r = json.loads(line)
        if "parsed" in r and (r["parsed"].get("must_skills") or []):
            if r["rid"] not in best or r["file"] > best[r["rid"]]["file"]:
                best[r["rid"]] = r
    from app.services.index_outbox_service import JOB, record_bulk_reindex
    from app.services.match_score_cache import mark_stale_for_job
    stats = {"checked": 0, "superseded": 0, "kept_empty_or_filled_by_ingest": 0,
             "kept_richer": 0}
    async with AsyncSessionLocal() as db:
        touched = []
        for rid, r in sorted(best.items()):
            job = (await db.execute(select(Job).where(
                Job.external_source == "traffit", Job.external_id == str(rid)
            ))).scalar_one_or_none()
            if job is None:
                continue
            stats["checked"] += 1
            existing = job.must_skills if isinstance(job.must_skills, list) else []
            champ_must = [{"name": s["name"], "level": None}
                          for s in r["parsed"]["must_skills"] if s.get("name")]
            # nadpisujemy TYLKO ubogie listy (1-3 wpisy) bogatszym Championem;
            # puste wypełnił już ingest (FILL_EMPTY); bogatsze (>3) zostają.
            if not existing or existing == champ_must:
                stats["kept_empty_or_filled_by_ingest"] += 1
                continue
            if len(existing) > 3 or len(champ_must) <= len(existing):
                stats["kept_richer"] += 1
                continue
            if COMMIT:
                champion = dict(job.champion_profile) if isinstance(job.champion_profile, dict) else {}
                champion["_superseded_must_skills"] = existing
                job.champion_profile = champion
                flag_modified(job, "champion_profile")
                job.must_skills = champ_must
                touched.append(job.id)
            stats["superseded"] += 1
        if COMMIT and touched:
            await record_bulk_reindex(db, JOB, touched)
            for jid in touched:
                await mark_stale_for_job(db, jid)
            await db.commit()
    print(("ZAPISANO" if COMMIT else "DRY-RUN") + ": " + json.dumps(stats))
asyncio.run(main())
