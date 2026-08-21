"""Ekstrakcja faktów ze WSZYSTKICH notatek kandydatów — pełny korpus, wznawialna."""
import asyncio, json, sys
sys.path.insert(0, "/app")
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

OUT = Path("/tmp/notes-extracted.jsonl")

PROMPT = """Z wewnętrznych notatek rekruterów o kandydacie wyciągnij FAKTY do struktury JSON (dane do lepszego dopasowywania kandydata do projektów — nic nie trafia do klienta):
{
 "expected_rate": {"value": float|null, "currency": str|null, "period": "h"|"md"|"month"|null, "raw": str|null, "as_of": "YYYY-MM"|null},
 "availability": {"raw": str|null, "notice_period": str|null, "available_from": str|null},
 "preferences": {"remote_only": bool|null, "locations": [str], "sectors_prefer": [str], "sectors_avoid": [str], "other": str|null},
 "languages_observed": [{"name": str, "level": str|null}],
 "client_vetoes": [{"client": str, "reason": str}],
 "matching_facts": str|null
}
Zasady: WYŁĄCZNIE fakty z notatek; brak informacji = null/pusta lista. NAJNOWSZA wzmianka
o stawce wygrywa (daty w nagłówkach [YYYY-MM-DD] → "as_of"). "matching_facts": 2-3 zdania
samych faktów istotnych przy doborze, BEZ opinii i ocen personalnych. Zwróć SAM JSON.

NOTATKI (od najnowszej):
"""

async def main():
    from app.services.claude_client import call_claude
    done: set[int] = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["cid"])
            except Exception:
                pass
    async with AsyncSessionLocal() as db:
        cids = (await db.execute(text("""
            SELECT candidate_id FROM notes
            WHERE candidate_id IS NOT NULL
            GROUP BY candidate_id ORDER BY max(created_at) DESC
        """))).scalars().all()
    todo = [c for c in cids if c not in done]
    print(f"kandydatów do przemielenia: {len(todo)} (gotowe wcześniej: {len(done)})")

    sem = asyncio.Semaphore(2)
    lock = asyncio.Lock()
    counter = {"n": 0}

    async def one(cid: int):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT created_at::date, content FROM notes
                WHERE candidate_id = :c ORDER BY created_at DESC LIMIT 15
            """), {"c": cid})).all()
        blob = "\n\n".join(f"[{d}]\n{c}" for d, c in rows if c)[:9000]
        if len(blob) < 60:
            return {"cid": cid, "error": "no_content"}
        try:
            msg = await run_in_threadpool(
                call_claude,
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                temperature=0,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": PROMPT + blob}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            parsed = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            return {"cid": cid, "parsed": parsed,
                    "usage": {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}}
        except Exception as e:
            return {"cid": cid, "error": repr(e)[:180]}

    async def worker(cid: int):
        async with sem:
            row = await one(cid)
        async with lock:
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            counter["n"] += 1
            if counter["n"] % 200 == 0:
                print(f"postęp: {counter['n']}/{len(todo)}")

    BATCH = 500
    for i in range(0, len(todo), BATCH):
        await asyncio.gather(*(worker(c) for c in todo[i:i + BATCH]))
    print("KONIEC EKSTRAKCJI NOTATEK")

asyncio.run(main())
