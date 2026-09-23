"""Przeniesienie snapshotów CV etapów z bazy do object storage (PROD-02).

Audyt 22.09 r2: ``candidate_stage_cvs.original_cv_content`` zajmował 2,35 GB
(28% bazy) przy 8947 wierszach i 3696 unikalnych plikach. Nowe snapshoty
trafiają do storage same (``candidate_stage_cv_service``); ten skrypt przenosi
stare.

Uruchomienie (w kontenerze backendu)::

    python -m app.cli.stage_cv_snapshot_offload            # na sucho: liczby
    python -m app.cli.stage_cv_snapshot_offload --apply    # przenieś
    python -m app.cli.stage_cv_snapshot_offload --apply --batch 200

Zasady:

* jeden upload na unikalny ``(kandydat, sha256)`` — klucz
  ``stage-cv/<candidate_id>/<sha256>``, ten sam co w nowych snapshotach;
* bajty w bazie są zerowane DOPIERO po ponownym pobraniu obiektu i zgodności
  skrótu — przerwany bieg niczego nie traci, kolejny bieg zaczyna od
  wierszy, które nadal mają bajty;
* paragon w ``app_settings['0351_stage_cv_offload']`` niesie wyłącznie liczniki
  (bez nazw plików i identyfikatorów osób).

Po ``--apply`` miejsce w pliku tabeli zwalnia dopiero ``VACUUM FULL
candidate_stage_cvs`` (okno serwisowe — blokuje tabelę).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

RECEIPT_KEY = "0351_stage_cv_offload"


async def summarize(db) -> dict[str, int]:
    row = (
        await db.execute(
            text(
                """
                SELECT count(*),
                       count(DISTINCT (candidate_id, md5(original_cv_content))),
                       COALESCE(sum(octet_length(original_cv_content)), 0)
                  FROM candidate_stage_cvs
                 WHERE original_cv_content IS NOT NULL
                """
            )
        )
    ).one()
    return {"rows": int(row[0]), "unique_files": int(row[1]), "bytes": int(row[2])}


async def _batch(db, after_id: int, size: int, row_ids: Optional[list[int]]):
    scope = "AND id = ANY(:ids)" if row_ids is not None else ""
    params: dict[str, Any] = {"after": after_id, "size": size}
    if row_ids is not None:
        params["ids"] = list(row_ids)
    return (
        await db.execute(
            text(
                f"""
                SELECT id, candidate_id, original_cv_filename, original_cv_content
                  FROM candidate_stage_cvs
                 WHERE original_cv_content IS NOT NULL
                   AND id > :after
                   {scope}
                 ORDER BY id
                 LIMIT :size
                """
            ),
            params,
        )
    ).fetchall()


async def offload(
    db,
    *,
    batch: int = 200,
    storage: Any = None,
    max_batches: Optional[int] = None,
    row_ids: Optional[list[int]] = None,
) -> dict[str, int]:
    """Przenieś bajty do storage. Zwraca liczniki.

    ``row_ids`` zawęża bieg do wskazanych wierszy (testy na wspólnej bazie).
    """
    from app.services import object_storage
    from app.services.candidate_stage_cv_service import snapshot_storage_key

    storage = storage or object_storage
    stats = {"rows": 0, "uploads": 0, "bytes_freed": 0, "failed": 0}
    uploaded: set[str] = set()
    after = 0
    done_batches = 0
    while True:
        rows = await _batch(db, after, max(1, int(batch)), row_ids)
        if not rows:
            break
        for row_id, candidate_id, filename, content in rows:
            after = int(row_id)
            data = bytes(content)
            digest = hashlib.sha256(data).hexdigest()
            key = snapshot_storage_key(candidate_id, digest)
            if key not in uploaded:
                try:
                    await run_in_threadpool(
                        storage.upload_cv, data, filename or "cv", storage_key=key
                    )
                    echoed = await run_in_threadpool(storage.download_cv, key)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("offload row=%s upload failed: %r", row_id, exc)
                    stats["failed"] += 1
                    continue
                if hashlib.sha256(echoed).hexdigest() != digest:
                    logger.warning("offload row=%s: storage echo mismatch", row_id)
                    stats["failed"] += 1
                    continue
                uploaded.add(key)
                stats["uploads"] += 1
            result = await db.execute(
                text(
                    """
                    UPDATE candidate_stage_cvs
                       SET original_cv_storage_key = :key,
                           original_cv_sha256 = :sha,
                           original_cv_content = NULL
                     WHERE id = :id AND original_cv_content IS NOT NULL
                    """
                ),
                {"key": key, "sha": digest, "id": row_id},
            )
            if result.rowcount:
                stats["rows"] += 1
                stats["bytes_freed"] += len(data)
        await db.commit()
        done_batches += 1
        if max_batches is not None and done_batches >= max_batches:
            break
    return stats


async def _write_receipt(db, payload: dict[str, Any]) -> None:
    await db.execute(
        text(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, CAST(:v AS jsonb), NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                                            updated_at = NOW()
            """
        ),
        {"k": RECEIPT_KEY, "v": json.dumps(payload)},
    )
    await db.commit()


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch", type=int, default=200)
    args = parser.parse_args(argv)

    from app.core.database import AsyncSessionLocal
    from app.services import object_storage

    async with AsyncSessionLocal() as db:
        before = await summarize(db)
        print(json.dumps({"before": before}, ensure_ascii=False))
        if not args.apply:
            print("Na sucho — nic nie zmieniono. Dodaj --apply.")
            return 0
        if not object_storage.is_available():
            print("Object storage nieskonfigurowany — przerywam.", file=sys.stderr)
            return 2
        stats = await offload(db, batch=args.batch)
        after = await summarize(db)
        receipt = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "before": before,
            "after": after,
            **stats,
        }
        await _write_receipt(db, receipt)
        print(json.dumps(receipt, ensure_ascii=False))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
