"""Backfill profili Championa z plików rekrutacji Traffita (GPT Luna, 22.09.2026).

Po co: Integration API Traffita nie wystawia plików rekrutacji, więc od
sierpniowego importu (1005 ofert, parser v3 na Haiku) żaden nowy profil nie
wszedł — wrzesień miał 0 profili na 92 nowe rekrutacje. Pliki pobiera sesja
przeglądarki zalogowana do Traffita (``scripts/champion_bundle_collector.js``)
i zapisuje je jako JEDEN plik JSONL; ten skrypt biegnie w kontenerze backendu::

    docker cp bundle.jsonl <backend>:/tmp/champ.jsonl
    docker exec <backend> python -m scripts.champion_backfill \\
        --bundle /tmp/champ.jsonl --report /tmp/champ-report.jsonl --dry-run

Paczka może być skompresowana (``.jsonl.gz``). Wiersz paczki: ``{"rid": 4979, "file": 123, "name": "Profil.docx", "b64": "…"}``.

Zasady zapisu (te same co endpoint collectora, ``admin_champion_ingest``):

* oferta bez profilu → pełny profil + FILL_EMPTY kolumn (must/nice, budżet,
  tryb pracy, miasto biura), reindeks wektora, stale cache wyników;
* oferta z profilem (``--merge-existing``) → uzupełniane są WYŁĄCZNIE puste
  pola; profil edytowany przez człowieka jest pomijany bez wywołania AI;
* ``--dry-run`` liczy wszystko (także odczyt AI) i wycofuje transakcję.

Raport niesie wyłącznie numery, wyniki i listy pól — bez treści dokumentów.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger("champion_backfill")

DEFAULT_MODEL = "gpt-5.6-luna"


def read_bundle(path: Path) -> list[dict[str, Any]]:
    """Wiersze paczki; ostatni wiersz na dany ``rid`` wygrywa (nowszy plik)."""
    by_rid: dict[int, dict[str, Any]] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rid = int(row["rid"])
            by_rid[rid] = {
                "rid": rid,
                "file": int(row["file"]) if row.get("file") is not None else None,
                "name": str(row.get("name") or f"champion_{rid}.docx"),
                "b64": row.get("b64") or "",
            }
    return [by_rid[rid] for rid in sorted(by_rid)]


async def process_one(
    row: dict[str, Any],
    *,
    model: str,
    merge_existing: bool,
    dry_run: bool,
) -> dict[str, Any]:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.champion_intake import preview_document
    from app.services.champion_profile_ingest import (
        extract_document_text,
        has_human_edit,
        ingest_parsed_profile,
        validate_upload,
    )

    rid = row["rid"]
    base = {"rid": rid, "file": row["file"]}
    try:
        content = base64.b64decode(row["b64"])
    except ValueError:
        return {**base, "outcome": "bad_bundle_row"}
    error = validate_upload(row["name"], len(content), str(rid))
    if error:
        return {**base, "outcome": "invalid_file", "detail": error}

    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(
                select(Job).where(
                    Job.external_source == "traffit", Job.external_id == str(rid)
                )
            )
        ).scalar_one_or_none()
        if job is None:
            return {**base, "outcome": "no_job"}
        base["job_id"] = job.id
        present = isinstance(job.champion_profile, dict) and bool(job.champion_profile)
        if present and not merge_existing:
            return {**base, "outcome": "champion_skipped_nonempty"}
        if present and await has_human_edit(db, job.id):
            return {**base, "outcome": "champion_human_edited"}

        text = extract_document_text(content, row["name"])
        if not text or len(text) < 200:
            return {**base, "outcome": "no_text"}
        try:
            parsed = (await preview_document(content, row["name"], db=db, model=model))[
                "champion_profile"
            ]
        except ValueError as exc:
            return {**base, "outcome": "parse_failed", "detail": str(exc)[:200]}

        result = await ingest_parsed_profile(
            db,
            external_rid=rid,
            file_id=row["file"] or 0,
            parsed=parsed,
            merge_existing=merge_existing,
            model=model,
            commit=not dry_run,
        )
        if dry_run:
            await db.rollback()
        stack = parsed.get("stack") or {}
        result["must"] = [s.get("name") for s in (stack.get("must") or [])][:15]
        result["dry_run"] = dry_run
        return {**base, **result}


async def run(
    bundle: Path,
    report: Path,
    *,
    model: str,
    merge_existing: bool,
    dry_run: bool,
    limit: Optional[int],
    only_rids: Optional[set[int]],
    concurrency: int,
) -> dict[str, int]:
    rows = read_bundle(bundle)
    if only_rids:
        rows = [row for row in rows if row["rid"] in only_rids]
    if limit:
        rows = rows[:limit]
    gate = asyncio.Semaphore(max(1, concurrency))
    counts: dict[str, int] = {}

    async def guarded(row: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            try:
                return await process_one(
                    row, model=model, merge_existing=merge_existing, dry_run=dry_run
                )
            except Exception as exc:  # jeden plik nie zatrzymuje przebiegu
                logger.exception("champion_backfill: rid=%s padł", row["rid"])
                return {
                    "rid": row["rid"],
                    "outcome": "error",
                    "detail": type(exc).__name__,
                }

    with report.open("w", encoding="utf-8") as out:
        done = 0
        for coro in asyncio.as_completed([guarded(row) for row in rows]):
            result = await coro
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            done += 1
            if done % 25 == 0:
                print(f"postęp {done}/{len(rows)} {counts}", flush=True)
    print(f"KONIEC {len(rows)} {json.dumps(counts, ensure_ascii=False)}", flush=True)
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--merge-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rids", help="lista rid po przecinku (próbka)")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    only = {int(x) for x in args.rids.split(",")} if args.rids else None
    asyncio.run(
        run(
            args.bundle,
            args.report,
            model=args.model,
            merge_existing=args.merge_existing,
            dry_run=args.dry_run,
            limit=args.limit,
            only_rids=only,
            concurrency=args.concurrency,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
