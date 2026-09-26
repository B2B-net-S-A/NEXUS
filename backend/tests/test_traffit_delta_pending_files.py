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


@pytest.mark.asyncio
async def test_delta_cv_targets_include_pending_candidates_without_pointer() -> None:
    """Runda 6 audytu (T6-8): faza `candidates_cv` w delcie brała tylko
    `updated_at >= since`, więc kandydat z przerwanego biegu dostawał pliki
    (zaległe pliki), ale nigdy wskaźnika `cv_storage_key` — a z niego czytają
    fazy tekstu CV i imion."""
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.importer import TraffitImporter

    ids = await _seed()
    run_start = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        importer = TraffitImporter(None, db, dry_run=True)  # type: ignore[arg-type]
        targets = {row.id for row in await importer._delta_cv_targets(run_start)}

    assert ids["pending"] in targets
    # Plik już pobrany, ale wskaźnika nadal brak — też cel (inaczej niż pliki).
    assert ids["has_doc"] in targets
    assert ids["no_cv_name"] not in targets
    assert ids["too_old"] not in targets


@pytest.mark.asyncio
async def test_delta_cv_targets_skip_candidates_with_a_pointer() -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.traffit.importer import TraffitImporter

    ids = await _seed()
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE candidates SET cv_storage_key = 'cv/x.pdf' WHERE id = :id"),
            {"id": ids["pending"]},
        )
        await db.commit()
        importer = TraffitImporter(None, db, dry_run=True)  # type: ignore[arg-type]
        targets = {
            row.id
            for row in await importer._delta_cv_targets(datetime.now(timezone.utc))
        }

    assert ids["pending"] not in targets


def test_candidates_cv_delta_uses_the_pending_scope() -> None:
    """Bez bazy: delta fazy `candidates_cv` idzie przez `_delta_cv_targets`."""
    import asyncio

    from app.services.traffit.importer import TraffitImporter

    seen: dict = {}

    class _Importer(TraffitImporter):
        async def _delta_cv_targets(self, since):
            seen["since"] = since
            return []

    class _Db:
        async def execute(self, *a, **k):  # pragma: no cover — nie powinno paść
            raise AssertionError("delta nie może pytać własnym zapytaniem")

    since = datetime.now(timezone.utc)
    importer = _Importer(None, _Db(), dry_run=True)  # type: ignore[arg-type]
    progress = asyncio.run(importer.import_candidates_cv(since=since))
    assert seen["since"] == since
    assert progress.total_source == 0
