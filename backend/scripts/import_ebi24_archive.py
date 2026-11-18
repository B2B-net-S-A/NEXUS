"""Import paczek archiwum eBI24 w kontenerze workera, bez HTTP (E5, 16.11.2026).

Tak weszło 49 728 dokumentów 16.11.2026 (decyzja Artura „SSH do workera”):
jeden proces, każda paczka to osobna sesja i commit jak ``POST /import``.
Idempotentny po id eBI24, więc przerwany bieg można powtórzyć.
Wypisuje tylko liczby i nazwy paczek, bez danych dokumentów.

Uruchom w kontenerze (z ``/app``, jako użytkownik aplikacji)::

    docker exec -u 10001 -w /app <worker> python -m scripts.import_ebi24_archive <katalog paczek> <id admina>

Kod wyjścia: 0 bez błędów, 1 są błędy wierszy, 2 paczka odrzucona w całości.
Procedura przyrostu: ``docs/claude/finanse-insights/archiwum-ebi24-przyrost-i-kopia.md``.
"""

from __future__ import annotations

import asyncio
import glob
import os
import resource
import sys
import time

from app.core.database import AsyncSessionLocal
from app.services.finance_ledger import archive


async def run(folder: str, actor_id: int) -> int:
    packages = sorted(glob.glob(os.path.join(folder, "paczka-*.zip")))
    print(f"paczek: {len(packages)}", flush=True)
    totals = {"created": 0, "skipped": 0, "errors": 0}
    started = time.time()
    for index, path in enumerate(packages, start=1):
        with open(path, "rb") as handle:
            content = handle.read()
        t0 = time.time()
        async with AsyncSessionLocal() as db:
            try:
                result = await archive.import_package(db, content, actor_id=actor_id)
            except archive.ArchiveError as exc:
                await db.rollback()
                print(f"{os.path.basename(path)}: ODRZUCONA ({exc})", flush=True)
                return 2
            await db.commit()
        del content
        totals["created"] += result.created
        totals["skipped"] += result.skipped
        totals["errors"] += len(result.errors)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        print(
            f"{index:3d}/{len(packages)} {os.path.basename(path)} "
            f"nowe={result.created} pominiete={result.skipped} bledy={len(result.errors)} "
            f"{time.time() - t0:.1f}s maxrss={rss}MB",
            flush=True,
        )
        for line in result.errors[:5]:
            print(f"    blad: {line}", flush=True)
    print(
        f"RAZEM nowe={totals['created']} pominiete={totals['skipped']} "
        f"bledy={totals['errors']} czas={time.time() - started:.0f}s",
        flush=True,
    )
    return 0 if totals["errors"] == 0 else 1


def main() -> None:
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        sys.exit(__doc__)
    sys.exit(asyncio.run(run(sys.argv[1], int(sys.argv[2]))))


if __name__ == "__main__":
    main()
