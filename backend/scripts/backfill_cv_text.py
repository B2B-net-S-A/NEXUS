"""Extract raw_cv_text for candidates whose CV file is in object storage
but `raw_cv_text` is NULL/empty.

Closes the retrieval blind spot: 10K+ candidates have a `cv_storage_key`
pointing to a PDF/DOCX in Hetzner Object Storage but the text was never
extracted — so they're invisible to Qdrant semantic search.

Pipeline per candidate:
    1. download_cv(storage_key) → bytes
    2. write to /tmp/<id>.<ext>
    3. cv_text_extractor.extract_text() — pdfplumber → tesseract OCR fallback
    4. UPDATE candidates SET raw_cv_text = ... (committed every batch)

Idempotent — only touches rows where raw_cv_text is empty AND storage_key
is present, so safe to interrupt and resume after a container restart.

Run:
    python -m scripts.backfill_cv_text --commit --limit 50  # smoke test
    python -m scripts.backfill_cv_text --commit             # full run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.services.cv_text_extractor import (  # noqa: E402
    UnsupportedCvFormat,
    extract_text,
)
from app.services.object_storage import download_cv, is_available  # noqa: E402

logger = logging.getLogger("backfill_cv_text")


def _ext_from_filename(filename: str | None, key: str) -> str:
    """Use filename's extension if present, else infer from storage key."""
    for src in (filename or "", key or ""):
        _, ext = os.path.splitext(src)
        if ext.lower() in (".pdf", ".docx", ".doc", ".txt"):
            return ext.lower()
    return ".pdf"  # default — most stored files are PDFs


def _is_garbage_text(text: str) -> bool:
    """Detect pdfplumber CID-glyph fallback strings like '(cid:42)(cid:7)...'.

    pdfplumber emits these when the PDF uses a font without a Unicode CMap;
    the resulting text is unusable and would only pollute embeddings.
    Heuristic: >30% of the body looks like '(cid:NN)' tokens.
    """
    if not text or len(text) < 100:
        return False
    cid_chars = sum(text.count(s) for s in ("(cid:",))
    # Each (cid:NN) token is ~7-8 chars; rough density check.
    return (cid_chars * 8) / len(text) > 0.3


def _sanitize(text: str) -> str:
    """Strip NULL bytes and control chars Postgres TEXT won't accept."""
    if not text:
        return ""
    # Drop \x00 and other ASCII control chars except \t, \n, \r.
    return "".join(
        c for c in text if c == "\t" or c == "\n" or c == "\r" or c >= " "
    )


def _process_one_sync(storage_key: str, filename: str | None) -> str:
    """Download + extract in a thread (heavy IO + tesseract)."""
    blob = download_cv(storage_key)
    if not blob:
        return ""
    ext = _ext_from_filename(filename, storage_key)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        text = extract_text(path, filename or os.path.basename(storage_key))
    except UnsupportedCvFormat:
        return ""
    except Exception as e:  # noqa: BLE001
        logger.warning("[extract] %s: %s", storage_key, e)
        return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if _is_garbage_text(text):
        return ""
    return _sanitize(text)


async def _run(*, commit: bool, limit: int | None, log_every: int, batch_size: int) -> int:
    if not is_available():
        logger.error("Object storage not configured — set R2 env vars first")
        return 1

    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                Candidate.id,
                Candidate.cv_storage_key,
                Candidate.cv_filename,
            )
            .where(
                Candidate.cv_storage_key.is_not(None),
                Candidate.cv_storage_key != "",
                or_(Candidate.raw_cv_text.is_(None), Candidate.raw_cv_text == ""),
            )
            .order_by(Candidate.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).all()

    total = len(rows)
    logger.info(
        "Found %s candidates with cv file but empty raw_cv_text (commit=%s)",
        total,
        commit,
    )
    if total == 0:
        return 0

    extracted = empty = failed = 0
    for i in range(0, total, batch_size):
        chunk = rows[i : i + batch_size]
        # Per-candidate sync extraction in a thread (download + OCR are blocking).
        results = await asyncio.gather(
            *[
                asyncio.to_thread(_process_one_sync, r[1], r[2])
                for r in chunk
            ],
            return_exceptions=True,
        )

        if commit:
            async with AsyncSessionLocal() as db:
                for (cid, _key, _fn), res in zip(chunk, results, strict=True):
                    if isinstance(res, Exception):
                        failed += 1
                        continue
                    text = (res or "").strip()
                    if not text:
                        empty += 1
                        continue
                    cand = await db.scalar(
                        select(Candidate).where(Candidate.id == cid)
                    )
                    if cand is None:
                        continue
                    cand.raw_cv_text = text
                    extracted += 1
                await db.commit()
        else:
            for res in results:
                if isinstance(res, Exception):
                    failed += 1
                elif (res or "").strip():
                    extracted += 1
                else:
                    empty += 1

        done = i + len(chunk)
        if done % log_every == 0 or done >= total:
            logger.info(
                "[%s/%s] extracted=%s empty=%s failed=%s",
                done,
                total,
                extracted,
                empty,
                failed,
            )

    logger.info(
        "DONE total=%s extracted=%s empty=%s failed=%s",
        total,
        extracted,
        empty,
        failed,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--log-every", type=int, default=50)
    args = p.parse_args()
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    return asyncio.run(
        _run(
            commit=args.commit,
            limit=args.limit,
            log_every=args.log_every,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
