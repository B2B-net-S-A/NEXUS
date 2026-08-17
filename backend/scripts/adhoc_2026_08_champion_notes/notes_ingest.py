"""Ingest faktów z notatek → cv_extracted_data._notes_insights + stawki (FILL_EMPTY)."""
import asyncio, json, sys
from datetime import datetime, timezone
from decimal import Decimal
sys.path.insert(0, "/app")
from pathlib import Path
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate

SRC = Path("/tmp/notes-extracted.jsonl")
COMMIT = "--commit" in sys.argv

async def main():
    best: dict[int, dict] = {}
    for line in SRC.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "parsed" in r:
            best[r["cid"]] = r["parsed"]  # ostatni wygrywa
    print(f"kandydatów z faktami: {len(best)}")

    from app.services.match_score_cache import mark_stale_for_candidate
    stats = {"updated": 0, "rate_written": 0, "vetoes": 0, "missing_candidate": 0}
    vetoes_report = []
    now = datetime.now(timezone.utc).isoformat()

    async with AsyncSessionLocal() as db:
        since = 0
        for cid, parsed in sorted(best.items()):
            cand = (await db.execute(select(Candidate).where(Candidate.id == cid))).scalar_one_or_none()
            if cand is None:
                stats["missing_candidate"] += 1
                continue
            extracted = cand.cv_extracted_data
            merged = dict(extracted) if isinstance(extracted, dict) else {}
            merged["_notes_insights"] = {**parsed, "_extracted_at": now,
                                         "_extractor": "notes_extract:v1:haiku-4.5"}
            if COMMIT:
                cand.cv_extracted_data = merged
            stats["updated"] += 1

            rate = (parsed.get("expected_rate") or {})
            val = rate.get("value")
            if (val and rate.get("period") == "h" and cand.expected_rate_hourly is None
                    and 0 < float(val) < 2000):
                if COMMIT:
                    cand.expected_rate_hourly = Decimal(str(val))
                    if not cand.expected_rate_currency:
                        cand.expected_rate_currency = (rate.get("currency") or "PLN")[:3]
                    await mark_stale_for_candidate(db, cid)
                stats["rate_written"] += 1

            for v in parsed.get("client_vetoes") or []:
                stats["vetoes"] += 1
                vetoes_report.append({"cid": cid, **v})

            since += 1
            if COMMIT and since >= 200:
                await db.commit(); since = 0
        if COMMIT:
            await db.commit()

    print(("ZAPISANO" if COMMIT else "DRY-RUN") + ": " + json.dumps(stats, ensure_ascii=False))
    Path("/tmp/notes-vetoes.json").write_text(
        json.dumps(vetoes_report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"veta zapisane do /tmp/notes-vetoes.json ({len(vetoes_report)})")

asyncio.run(main())
