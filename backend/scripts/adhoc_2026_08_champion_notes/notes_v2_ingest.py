"""Ingest v2: potwierdzone skills (APPEND+dedup), years w puste, insights v2."""
import asyncio, json, sys
from datetime import datetime, timezone
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.cv_enrichment import normalize_llm_skills

SRC = Path("/tmp/notes-extracted-v2.jsonl")
COMMIT = "--commit" in sys.argv
V2_KEYS = ("skills_evidenced", "skills_gaps_observed", "certifications",
           "years_confirmed", "contract_form_preference", "rate_flexibility",
           "current_engagement", "not_looking_until", "relocation",
           "work_permit_status", "security_clearance")

async def main():
    best = {}
    for line in SRC.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "parsed" in r:
            best[r["cid"]] = r["parsed"]
    print(f"kandydatów: {len(best)}")
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex
    from app.services.match_score_cache import mark_stale_for_candidate
    stats = {"touched": 0, "skills_added": 0, "cands_with_new_skills": 0,
             "years_filled": 0, "locked_skills": 0}
    now = datetime.now(timezone.utc).isoformat()

    async with AsyncSessionLocal() as db:
        touched = []
        since = 0
        for cid, parsed in sorted(best.items()):
            cand = (await db.execute(select(Candidate).where(Candidate.id == cid))).scalar_one_or_none()
            if cand is None:
                continue
            changed = False
            extracted = dict(cand.cv_extracted_data) if isinstance(cand.cv_extracted_data, dict) else {}
            insights = dict(extracted.get("_notes_insights") or {})

            # ── skills APPEND z dedupem, przez kanoniczny normalizator ──
            evidenced = parsed.get("skills_evidenced") or []
            locked = bool(extracted.get("_manual_override_skills"))
            if evidenced and locked:
                stats["locked_skills"] += 1
            elif evidenced:
                names = [s.get("name") for s in evidenced
                         if isinstance(s, dict) and s.get("name")]
                normalized = normalize_llm_skills(names) or []
                existing = cand.skills if isinstance(cand.skills, list) else []
                have = {str(s.get("name", "")).casefold()
                        for s in existing if isinstance(s, dict)}
                new_items = [s for s in normalized if s["name"].casefold() not in have]
                if new_items:
                    if COMMIT:
                        cand.skills = existing + new_items
                    stats["skills_added"] += len(new_items)
                    stats["cands_with_new_skills"] += 1
                    changed = True

            # ── years_confirmed w puste ──
            yc = parsed.get("years_confirmed")
            if (cand.years_it_experience is None and isinstance(yc, (int, float))
                    and not isinstance(yc, bool) and 0 < yc <= 60):
                if COMMIT:
                    cand.years_it_experience = int(yc)
                stats["years_filled"] += 1
                changed = True

            # ── insights v2 (merge, bez nadpisywania v1) ──
            for k in V2_KEYS:
                if parsed.get(k) not in (None, [], {}):
                    insights[k] = parsed[k]
            insights["_v2_extracted_at"] = now
            extracted["_notes_insights"] = insights
            if COMMIT:
                cand.cv_extracted_data = extracted
                flag_modified(cand, "cv_extracted_data")

            if changed:
                stats["touched"] += 1
                if COMMIT:
                    touched.append(cid)
            since += 1
            if COMMIT and since >= 300:
                await db.commit(); since = 0
        if COMMIT:
            if touched:
                await record_bulk_reindex(db, CANDIDATE, touched)
                for c in touched:
                    await mark_stale_for_candidate(db, c)
            await db.commit()
    print(("ZAPISANO" if COMMIT else "DRY-RUN") + ": " + json.dumps(stats))
asyncio.run(main())
