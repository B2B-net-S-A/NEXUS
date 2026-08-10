"""`candidates.cv_extracted_data` is a JSON column and is not always an object.

Observed on prod 2026-08-10, during the full Traffit reconcile: the
`candidates` phase finished with `errors: 39, blocking_errors: 39`, every
sample reading

    upsert candidate ext=<id>: AttributeError("'list' object has no attribute 'get'")

and the phase watermark refused to advance — so the nightly delta would have
re-scanned the same window forever.

The source is the `or {}` idiom:

    (candidate.cv_extracted_data or {}).get(...)

which rescues only FALSY values. `None` and `[]` are fine; a NON-EMPTY list is
truthy and sails straight into `.get()`. 39 of ~57k rows carry a list there.

That the column can hold a non-dict was already known in this codebase —
`cv_text_backfill._terminal_marker` guards it with `isinstance(..., dict)`.
Three callers did not, in two different shapes: `.get()` on a list
(AttributeError) and `dict(<list>)` (ValueError). All three are on paths the
Traffit sync walks for every candidate.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.services.candidate_location_writer import (
    apply_candidate_location_from_source,
)
from app.services.traffit.importer import TraffitImporter


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


# A shape really seen in the column: a bare list instead of an object.
_LIST_PAYLOAD = [{"skill": "Python"}, {"skill": "Go"}]


def test_manual_lock_survives_a_list_in_cv_extracted_data() -> None:
    """The exact prod failure, at its narrowest. `.get()` on a list."""
    candidate = Candidate(
        name="A", lastname="B", city=None, country=None, location=None
    )
    candidate.cv_extracted_data = _LIST_PAYLOAD

    changed = apply_candidate_location_from_source(
        candidate, city="Warszawa", country="PL", overwrite_existing=True
    )

    assert changed
    assert (candidate.city, candidate.country) == ("Warszawa", "PL")


def test_a_real_manual_override_is_still_honoured() -> None:
    """The guard must not become "ignore every lock" — a dict with the flag
    set still protects the field."""
    candidate = Candidate(name="A", lastname="B", city="Kraków", country="PL")
    candidate.cv_extracted_data = {"_manual_override_city": True}

    apply_candidate_location_from_source(
        candidate, city="Warszawa", country="PL", overwrite_existing=True
    )

    assert candidate.city == "Kraków"  # recruiter's value wins


def test_record_marker_survives_a_list(monkeypatch) -> None:
    """Second shape of the same bug: `dict(<list>)` raises ValueError."""
    from app.services.cv_text_backfill import _record_marker

    candidate = Candidate(name="A", lastname="B")
    candidate.cv_extracted_data = _LIST_PAYLOAD

    _record_marker(candidate, "empty", 0)

    assert isinstance(candidate.cv_extracted_data, dict)
    assert candidate.cv_extracted_data["_cv_text_extraction"]["outcome"] == "empty"


def test_cv_enrichment_survives_a_list() -> None:
    """`_apply_cv_enrichment` is on the sync path too — reached from the
    `candidates_enrich_names` phase via `cv_backfill.backfill_missing_names`,
    not by a direct import in `importer.py`. That phase targets rows whose name
    is still "?", i.e. precisely the messiest records, so it is the LAST place
    that should assume this column is an object."""
    from app.services.cv_enrichment import _apply_cv_enrichment

    candidate = Candidate(name="?", lastname="?")
    candidate.cv_extracted_data = _LIST_PAYLOAD

    _apply_cv_enrichment(candidate, {"first_name": "Jan", "last_name": "Kowalski"})

    assert candidate.name == "Jan"
    assert candidate.lastname == "Kowalski"
    assert isinstance(candidate.cv_extracted_data, dict)


class _OneEmployee:
    """Serves exactly one Traffit employee, with a city so the location writer
    (and therefore `_manual_lock`) is actually reached."""

    def __init__(self, ext: str):
        self.ext = ext

    async def total_count(self, path):
        return 1

    async def get_paginated(self, path, *, page_size=100, **kw):
        """`build_user_id_map` walks /users/ before the candidate loop."""
        return
        yield  # pragma: no cover — makes this an async generator

    async def get_pages(self, path, *, page_size=100, filter_=None, start_page=1, **kw):
        yield 1, [
            {
                "id": self.ext,
                "name": "Jan",
                "lastname": "Kowalski",
                "candidate_location": "Warszawa",
            }
        ]


@pytest.mark.asyncio
async def test_traffit_sync_no_longer_errors_on_such_a_candidate(db) -> None:
    """End-to-end through the phase that actually broke.

    Testing only `_manual_lock` would prove the helper and leave the question
    the prod incident asked — does the candidates phase still count this row as
    a blocking error? — unanswered.
    """
    ext = f"x{uuid.uuid4().hex[:10]}"
    await db.execute(
        text(
            """
            INSERT INTO candidates (
                external_id, external_source, name, lastname,
                cv_extracted_data, created_at, updated_at
            ) VALUES (
                :e, 'traffit', 'Jan', 'Kowalski',
                CAST(:d AS jsonb), NOW(), NOW()
            )
            """
        ),
        {"e": ext, "d": '[{"skill": "Python"}]'},
    )
    await db.commit()

    importer = TraffitImporter(_OneEmployee(ext), db, dry_run=False, batch_size=10)
    progress = await importer.import_candidates(since=None)

    assert progress.errors == 0, f"still failing: {progress.error_samples}"
    row = await db.execute(
        text("SELECT city FROM candidates WHERE external_id = :e"), {"e": ext}
    )
    assert row.scalar_one() == "Warszawa"
