"""Ingest sparsowanych profili Championa v3 → jobs (FILL_EMPTY) + reindeks + stale."""
import asyncio, json, sys
from datetime import datetime, timezone
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.job import Job

SRC = Path("/tmp/champ-parsed-v3.jsonl")
COMMIT = "--commit" in sys.argv

def champion_dict(p: dict, file_id: int) -> dict:
    basics = p.get("basics") or {}
    return {
        "basics": {
            "onsite_days_per_week": basics.get("onsite_days_per_week"),
            "candidate_location_pref": basics.get("candidate_location_pref") or p.get("location"),
            "language": basics.get("language"),
        },
        "project_context": p.get("project_context") or {},
        "screening_questions": p.get("screening_questions") or [],
        "sourcing": p.get("sourcing") or {},
        # rozszerzenia poza schemat (czytelne przez .get, nie psują walidatorów):
        "role_name": p.get("role_name"),
        "seniority_min_years": p.get("seniority_min_years"),
        "rate_value": p.get("rate_value"),
        "rate_raw": p.get("rate_raw"),
        "work_mode": p.get("work_mode"),
        "start_date": p.get("start_date"),
        "contract_length": p.get("contract_length"),
        "sectors": p.get("sectors") or [],
        "disqualifiers": p.get("disqualifiers") or [],
        "client_standards": p.get("client_standards") or {},
        "_source": f"traffit_recruitment_file:{file_id}",
        "_parsed_at": datetime.now(timezone.utc).isoformat(),
        "_parser": "champion_parse:v3:haiku-4.5",
    }

def is_empty_skills(v) -> bool:
    return not (isinstance(v, list) and len(v) > 0)

async def main():
    rows = [json.loads(l) for l in SRC.open(encoding="utf-8")]
    best: dict[int, dict] = {}
    for r in rows:
        if "parsed" not in r:
            continue
        rid = r["rid"]
        if rid not in best or r["file"] > best[rid]["file"]:
            best[rid] = r
    print(f"sparsowane rekrutacje: {len(best)} (wierszy: {len(rows)})")

    stats = {"matched": 0, "no_job": 0, "champion_written": 0, "champion_skipped_nonempty": 0,
             "must_written": 0, "nice_written": 0, "reindex": 0}
    from app.services.index_outbox_service import JOB, record_bulk_reindex
    from app.services.match_score_cache import mark_stale_for_job

    async with AsyncSessionLocal() as db:
        touched: list[int] = []
        for rid, r in sorted(best.items()):
            job = (await db.execute(select(Job).where(
                Job.external_source == "traffit", Job.external_id == str(rid)
            ))).scalar_one_or_none()
            if job is None:
                stats["no_job"] += 1
                continue
            stats["matched"] += 1
            p = r["parsed"]
            changed = False

            existing = job.champion_profile
            if isinstance(existing, dict) and existing:
                stats["champion_skipped_nonempty"] += 1
            else:
                if COMMIT:
                    job.champion_profile = champion_dict(p, r["file"])
                stats["champion_written"] += 1
                changed = True

            if is_empty_skills(job.must_skills) and (p.get("must_skills") or []):
                if COMMIT:
                    job.must_skills = [{"name": s["name"], "level": None}
                                       for s in p["must_skills"] if s.get("name")]
                stats["must_written"] += 1
                changed = True
            if is_empty_skills(job.nice_skills) and (p.get("nice_skills") or []):
                if COMMIT:
                    job.nice_skills = [{"name": s["name"], "level": None}
                                       for s in p["nice_skills"] if s.get("name")]
                stats["nice_written"] += 1
                changed = True

            if changed and COMMIT:
                touched.append(job.id)

        if COMMIT and touched:
            enq = await record_bulk_reindex(db, JOB, touched)
            stats["reindex"] = int(enq or 0)
            for jid in touched:
                # outbox NIE robi tego dla ofert (robi tylko dla kandydatów) —
                # bez tego cache score'ów serwowałby wyniki liczone na ofercie
                # sprzed Championa.
                await mark_stale_for_job(db, jid)
            await db.commit()
        print(("ZAPISANO" if COMMIT else "DRY-RUN") + ": " + json.dumps(stats, ensure_ascii=False))

asyncio.run(main())
