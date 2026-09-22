"""Delta fazy plików obejmuje „zaległe pliki" z przerwanych biegów.

`files_since` w delcie to start BIEŻĄCEGO biegu. Deploy zabijający dzienny bieg
przed fazą plików (prod 22.09.2026: dzienna delta nie skończyła się od 21.09,
ok. 25 deployów na dobę) zostawiał kandydatów z nazwą CV i bez pliku — każdy
kolejny bieg miał nowy start, więc `updated_at >= since` już ich nie łapało.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text


async def _seed() -> dict[str, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    tag = uuid.uuid4().hex[:10]
    long_ago = datetime.now(timezone.utc) - timedelta(days=3)

    def cand(key: str, *, cv: str | None) -> Candidate:
        return Candidate(
            name="Traffit",
            lastname=f"{key}-{tag}",
            external_source="traffit",
            external_id=f"pending-{key}-{tag}",
            cv_filename=cv,
        )

    async with AsyncSessionLocal() as db:
        rows = {
            "pending": cand("pending", cv="cv.pdf"),
            "has_doc": cand("has_doc", cv="cv.pdf"),
            "no_cv_name": cand("no_cv_name", cv=None),
            "too_old": cand("too_old", cv="cv.pdf"),
        }
        db.add_all(rows.values())
        await db.flush()
        db.add(
            CandidateDocument(
                candidate_id=rows["has_doc"].id,
                filename="cv.pdf",
                document_kind=CandidateDocumentKind.cv,
                external_source="traffit",
                external_id=f"doc-{tag}",
            )
        )
        await db.flush()
        ids = {key: c.id for key, c in rows.items()}
        # Upsert z przerwanego biegu: updated_at sprzed startu bieżącego biegu.
        await db.execute(
            text("UPDATE candidates SET updated_at = :t WHERE id = ANY(:ids)"),
            {"t": long_ago, "ids": list(ids.values())},
        )
        await db.execute(
            text("UPDATE candidates SET created_at = :t WHERE id = :id"),
            {"t": datetime.now(timezone.utc) - timedelta(days=90), "id": ids["too_old"]},
        )
        await db.commit()
    return ids


@pytest.mark.asyncio
async def test_delta_targets_include_candidates_left_without_files() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.importer import TraffitImporter

    ids = await _seed()
    run_start = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        importer = TraffitImporter(None, db, dry_run=True)  # type: ignore[arg-type]
        targets = {row.id for row in await importer._delta_file_targets(run_start)}

    assert ids["pending"] in targets
    # Ma już plik, nie ma nazwy CV albo zaległość jest poza oknem — bez zmian.
    assert ids["has_doc"] not in targets
    assert ids["no_cv_name"] not in targets
    assert ids["too_old"] not in targets


@pytest.mark.asyncio
async def test_pending_catch_up_is_capped(monkeypatch) -> None:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.importer import TraffitImporter

    ids = await _seed()
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_PENDING_FILES_LIMIT", 0)

    async with AsyncSessionLocal() as db:
        importer = TraffitImporter(None, db, dry_run=True)  # type: ignore[arg-type]
        targets = {
            row.id
            for row in await importer._delta_file_targets(datetime.now(timezone.utc))
        }

    assert ids["pending"] not in targets
