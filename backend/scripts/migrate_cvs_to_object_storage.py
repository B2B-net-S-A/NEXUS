"""Migrate candidate_documents.file_content (BYTEA) → Hetzner Object Storage.

audit-2026-05-07 Faza 3 — `candidate_documents` w postgres ma 13 GB blob
content (CV PDF/DOCX). Migracja przenosi zawartość do object storage,
zostawiając klucz w `storage_key`. Po weryfikacji (--finalize-delete-bytea)
file_content w bazie jest zerowane → DB skurczy się o ~13 GB.

2-fazowe podejście (bezpieczne):
    1. COPY:    file_content (BYTEA) → upload do S3 → save storage_key.
                file_content NADAL w bazie do czasu weryfikacji.
    2. VERIFY:  manualne smoke testy (download CV przez UI), 24h obserwacja.
    3. DELETE:  --finalize-delete-bytea ustawia file_content=NULL dla rekordów
                które mają storage_key.
    4. VACUUM:  postgres VACUUM FULL candidate_documents (uwolni dysk).

Idempotent: pomija rekordy które już mają storage_key.

Usage:
    python -m scripts.migrate_cvs_to_object_storage --dry-run
    python -m scripts.migrate_cvs_to_object_storage --commit --batch 200
    python -m scripts.migrate_cvs_to_object_storage --finalize-delete-bytea
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select, update  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate_document import CandidateDocument  # noqa: E402
from app.services.object_storage import is_available, upload_cv  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)


async def _count_remaining(session) -> int:
    return (
        await session.scalar(
            select(func.count(CandidateDocument.id))
            .where(CandidateDocument.storage_key.is_(None))
            .where(CandidateDocument.file_content.isnot(None))
        )
        or 0
    )


async def copy_phase(commit: bool, batch: int) -> int:
    """Walk through all candidate_documents bez storage_key ale z file_content
    → upload do S3 → save storage_key. Idempotent."""
    if commit and not is_available():
        log.error(
            "Object storage env not configured. Set OBJECT_STORAGE_ENDPOINT, "
            "OBJECT_STORAGE_ACCESS_KEY, OBJECT_STORAGE_SECRET_KEY in Coolify."
        )
        return 0

    inserted = 0
    async with AsyncSessionLocal() as session:
        total = await _count_remaining(session)
        log.info("Documents pending migration: %d", total)
        if not commit:
            log.info("Dry-run: would migrate %d documents", total)
            return 0

        while True:
            stmt = (
                select(CandidateDocument)
                .where(CandidateDocument.storage_key.is_(None))
                .where(CandidateDocument.file_content.isnot(None))
                .order_by(CandidateDocument.id)
                .limit(batch)
            )
            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                break
            for doc in rows:
                try:
                    key = upload_cv(
                        content=doc.file_content,
                        filename=doc.filename,
                        content_type=doc.content_type,
                    )
                    doc.storage_key = key
                    inserted += 1
                except Exception as e:
                    log.exception(
                        "Failed to upload doc id=%s candidate=%s: %s",
                        doc.id,
                        doc.candidate_id,
                        e,
                    )
                    # Rollback całego batcha: bezpieczne, retry z lepszym ENV.
                    await session.rollback()
                    return inserted
            await session.commit()
            log.info("Committed batch: %d uploaded so far", inserted)

    log.info("Copy phase done: %d documents migrated", inserted)
    return inserted


async def finalize_delete_bytea() -> int:
    """Po sprawdzeniu że storage działa — zerujemy file_content dla
    rekordów które mają storage_key (= zostały wcześniej zmigrowane)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(CandidateDocument)
            .where(CandidateDocument.storage_key.isnot(None))
            .where(CandidateDocument.file_content.isnot(None))
            .values(file_content=None)
        )
        await session.commit()
        n = result.rowcount or 0
        log.info("Cleared file_content for %d documents", n)
        log.info(
            "NEXT: docker exec postgres-... psql -U nexus -d nexus -c "
            "'VACUUM FULL candidate_documents;' "
            "(takes ~5-10 min, exclusive lock — schedule for low-traffic window)"
        )
        return n


async def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run", action="store_true", help="Preview counts without writes"
    )
    group.add_argument(
        "--commit",
        action="store_true",
        help="Apply: upload BYTEA → S3 + save storage_key",
    )
    group.add_argument(
        "--finalize-delete-bytea",
        action="store_true",
        help="After verification: set file_content=NULL for migrated rows",
    )
    parser.add_argument(
        "--batch", type=int, default=200, help="Documents per transaction (default 200)"
    )
    args = parser.parse_args()

    if args.finalize_delete_bytea:
        await finalize_delete_bytea()
    else:
        await copy_phase(commit=args.commit, batch=args.batch)


if __name__ == "__main__":
    asyncio.run(main())
