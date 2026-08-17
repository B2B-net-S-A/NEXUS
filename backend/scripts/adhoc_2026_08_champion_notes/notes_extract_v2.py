"""Ekstrakcja v2 z notatek — schemat docelowy (ostatni pełny przebieg), wznawialna."""
import asyncio, json, sys
sys.path.insert(0, "/app")
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

OUT = Path("/tmp/notes-extracted-v2.jsonl")

PROMPT = """Z wewnętrznych notatek rekruterów o kandydacie wyciągnij FAKTY do struktury JSON (dane do dopasowywania kandydata do projektów — nic nie trafia do klienta):
{
 "skills_evidenced": [{"name": str, "evidence": str}],
   // umiejętności POTWIERDZONE w rozmowie/screeningu/odpowiedziach; evidence = krótki cytat
   // lub parafraza Z NOTATKI dowodząca kompetencji. NIE przepisuj skilli, które są tylko
   // wspomniane jako "w CV" — tylko realnie zademonstrowane/potwierdzone.
 "skills_gaps_observed": [{"name": str, "evidence": str}],
   // WYŁĄCZNIE nazwane wprost braki techniczne (np. "braki w Springu na interview u X");
   // ZERO opinii personalnych i ocen miękkich.
 "certifications": [str],
 "years_confirmed": int|null,          // łączny staż potwierdzony wprost w notatce
 "contract_form_preference": "b2b"|"uop"|"any"|null,
 "rate_flexibility": str|null,         // np. "zejdzie do 140 przy dłuższym projekcie"
 "current_engagement": {"employer": str|null, "project": str|null, "ends_at": str|null, "raw": str|null},
   // gdzie teraz pracuje i KIEDY KOŃCZY SIĘ kontrakt (data lub opis)
 "not_looking_until": str|null,        // "nie szukam do końca roku" → "2026-12-31" lub opis
 "relocation": {"willing": bool|null, "targets": [str]},
 "work_permit_status": str|null,       // karta pobytu, pozwolenie na pracę itp.
 "security_clearance": str|null       // poświadczenie bezpieczeństwa, dostęp do informacji niejawnych
}
Zasady: WYŁĄCZNIE fakty z notatek — nic z domysłów; brak informacji = null/pusta lista.
Daty notatek w nagłówkach [YYYY-MM-DD] — najnowsza wzmianka wygrywa przy sprzecznościach.
Zwróć SAM JSON.

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
        cids = (await db.execute(text(
            "SELECT candidate_id FROM notes WHERE candidate_id IS NOT NULL "
            "GROUP BY candidate_id ORDER BY max(created_at) DESC"
        ))).scalars().all()
    todo = [c for c in cids if c not in done]
    print(f"do przemielenia: {len(todo)} (gotowe: {len(done)})")
    sem = asyncio.Semaphore(2)
    lock = asyncio.Lock()
    n_done = {"n": 0}

    async def one(cid: int):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text(
                "SELECT created_at::date, content FROM notes WHERE candidate_id = :c "
                "ORDER BY created_at DESC LIMIT 20"
            ), {"c": cid})).all()
        blob = "\n\n".join(f"[{d}]\n{c}" for d, c in rows if c)[:12000]
        if len(blob) < 60:
            return {"cid": cid, "error": "no_content"}
        try:
            msg = await run_in_threadpool(
                call_claude,
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
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
            n_done["n"] += 1
            if n_done["n"] % 200 == 0:
                print(f"postęp: {n_done['n']}/{len(todo)}")

    BATCH = 500
    for i in range(0, len(todo), BATCH):
        await asyncio.gather(*(worker(c) for c in todo[i:i + BATCH]))
    print("KONIEC EKSTRAKCJI V2")

asyncio.run(main())
