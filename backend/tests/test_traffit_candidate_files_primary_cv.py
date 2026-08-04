"""Regression: candidate_files must not freeze the whole sync on the
one-active-primary-CV invariant.

Prod (2026-07-31+): emp 57740 had two Traffit files both flagged primary; the
second insert violated ``ux_candidate_documents_active_primary_cv``. That
IntegrityError is unattributable, so it permanently froze the ``__daily__``
watermark → ``checks.traffit=degraded``. The fix stores the colliding file as
NON-primary (keeping the existing primary) instead of raising, so the phase
completes with no blocking error.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.traffit.importer import TraffitImporter

_PRIMARY_CV_CONSTRAINT = (
    "duplicate key value violates unique constraint "
    '"ux_candidate_documents_active_primary_cv"'
)


class _Nested:
    """Stand-in for AsyncSession.begin_nested(): a savepoint context manager
    that propagates (does not swallow) exceptions raised inside it."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDB:
    def __init__(
        self, *, fail_primary: bool, orig_message: str = _PRIMARY_CV_CONSTRAINT
    ):
        self.fail_primary = fail_primary
        self.orig_message = orig_message
        self.doc_inserts: list[bool] = []  # is_primary of each doc upsert executed
        self.demotes = 0

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt, params=None):
        p = params or {}
        if "external_source" in p:  # a candidate_documents upsert
            if p.get("is_primary") and self.fail_primary:
                self.fail_primary = False  # only the first primary attempt fails
                raise IntegrityError("INSERT ...", p, Exception(self.orig_message))
            self.doc_inserts.append(bool(p.get("is_primary")))
        else:  # the demote UPDATE
            self.demotes += 1
        return None


def _doc(is_primary: bool) -> dict:
    return {
        "candidate_id": 123,
        "filename": "cv.pdf",
        "storage_key": "s3://k",
        "content_type": "application/pdf",
        "size_bytes": 10,
        "document_kind": "cv",
        "is_primary": is_primary,
        "uploaded_at": None,
        "external_id": "57740-9",
        "external_source": "traffit",
    }


def _importer(db: _FakeDB) -> TraffitImporter:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.db = db
    return imp


@pytest.mark.asyncio
async def test_primary_cv_collision_stores_non_primary() -> None:
    db = _FakeDB(fail_primary=True)
    imp = _importer(db)

    # Must NOT raise — the whole sync used to freeze here.
    await imp._upsert_candidate_document(_doc(True))

    # Control-flow assertions: the demote was ATTEMPTED once (inside the doomed
    # SAVEPOINT), then the file was stored exactly once, as NON-primary. NOTE:
    # this fake does not model SAVEPOINT rollback, so db.demotes == 1 reflects
    # the call made, not that it persisted — the real demote is rolled back with
    # the savepoint on collision (verified against real Postgres on prod).
    assert db.demotes == 1
    assert db.doc_inserts == [False]


@pytest.mark.asyncio
async def test_clean_primary_insert_stays_primary() -> None:
    db = _FakeDB(fail_primary=False)
    imp = _importer(db)

    await imp._upsert_candidate_document(_doc(True))

    assert db.demotes == 1  # demote existing primary before inserting the new one
    assert db.doc_inserts == [True]  # inserted as primary, no collision


@pytest.mark.asyncio
async def test_unrelated_integrity_error_propagates() -> None:
    db = _FakeDB(
        fail_primary=True,
        orig_message='violates unique constraint "some_other_constraint"',
    )
    imp = _importer(db)

    # A different constraint is a real problem — it must surface, not be
    # silently downgraded to a non-primary insert.
    with pytest.raises(IntegrityError):
        await imp._upsert_candidate_document(_doc(True))
    assert db.doc_inserts == []
