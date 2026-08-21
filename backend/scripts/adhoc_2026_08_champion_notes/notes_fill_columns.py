"""Fakty z _notes_insights → kolumny kandydata (FILL_EMPTY, wszystkie notatki)."""
import asyncio, json, re, sys
from datetime import date
sys.path.insert(0, "/app")
from sqlalchemy import select, or_, text
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, AvailabilityStatus

COMMIT = "--commit" in sys.argv
NOTICE = re.compile(r"(\d+)\s*(tydz|tyg|week|mies|miesiąc|miesiec|month|dni|dzień|dzien|day|mc)", re.I)
ASAP = re.compile(r"od zaraz|asap|natychmiast|od ręki|immediately", re.I)
ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

def parse_notice(raw):
    if not isinstance(raw, str):
        return None
    m = NOTICE.search(raw)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("tydz", "tyg", "week")):
        return n, "weeks"
    if unit.startswith(("mies", "month", "mc")):
        return n, "months"
    return n, "days"

async def main():
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex
    from app.services.match_score_cache import mark_stale_for_candidate
    stats = {"scanned": 0, "notice": 0, "avail_date": 0, "status": 0, "touched": 0}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Candidate).where(
            text("cv_extracted_data ? '_notes_insights'")
        ))).scalars().all()
        touched = []
        for cand in rows:
            stats["scanned"] += 1
            ins = (cand.cv_extracted_data or {}).get("_notes_insights") or {}
            av = ins.get("availability") if isinstance(ins.get("availability"), dict) else {}
            changed = False

            if cand.notice_period is None:
                parsed = parse_notice(av.get("notice_period")) or parse_notice(av.get("raw"))
                if parsed:
                    if COMMIT:
                        cand.notice_period, cand.notice_period_unit = parsed
                    stats["notice"] += 1
                    changed = True

            if cand.availability_date is None:
                m = ISO.search(str(av.get("available_from") or ""))
                if m:
                    try:
                        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        if COMMIT:
                            cand.availability_date = d
                        stats["avail_date"] += 1
                        changed = True
                    except ValueError:
                        pass

            raw_txt = " ".join(str(av.get(k) or "") for k in ("raw", "notice_period", "available_from"))
            if (getattr(cand.availability_status, "value", cand.availability_status) == "unknown"
                    and ASAP.search(raw_txt)):
                if COMMIT:
                    cand.availability_status = AvailabilityStatus.actively_looking
                stats["status"] += 1
                changed = True

            if changed:
                stats["touched"] += 1
                if COMMIT:
                    touched.append(cand.id)
            if COMMIT and len(touched) % 300 == 299:
                await db.commit()
        if COMMIT and touched:
            await record_bulk_reindex(db, CANDIDATE, touched)
            for cid in touched:
                await mark_stale_for_candidate(db, cid)
            await db.commit()
    print(("ZAPISANO" if COMMIT else "DRY-RUN") + ": " + json.dumps(stats))
asyncio.run(main())
