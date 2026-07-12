"""Integration tests for the Cortex traffit extractor (real DB via CI postgres).

Seeds a Skill (+alias) and a Candidate with ``traffit_technologie``, runs the
backfill, and asserts: fact upserted with evidence/NULL-observed_at, re-run is
idempotent (same row count), unmatched term recorded with occurrence count.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.cortex import CortexSkillFact, CortexUnmatchedTerm
from app.models.skill import Skill, SkillAlias
from app.services.cortex.extractor_traffit import run_traffit_backfill


@pytest.mark.asyncio
async def test_traffit_backfill_upserts_facts_idempotently(app_client: AsyncClient):
    unique = uuid.uuid4().hex[:8]
    canonical = f"cortextest-{unique}"
    alias = f"ctest-{unique}"
    unmatched_term = f"nieznana-technologia-{unique}"

    async with AsyncSessionLocal() as db:
        skill = Skill(canonical_name=canonical, category="test")
        db.add(skill)
        await db.flush()
        db.add(SkillAlias(skill_id=skill.id, alias=alias))
        candidate = Candidate(
            name="Cortex",
            lastname=f"Test-{unique}",
            email=f"cortex-{unique}@example.com",
            cv_extracted_data={
                # Alias (inna pisownia) + duplikat kanoniczny + termin spoza
                # taksonomii — jeden fakt + jeden unmatched.
                "traffit_technologie": (
                    f"{alias.upper()}, {canonical}, {unmatched_term}"
                )
            },
        )
        db.add(candidate)
        await db.commit()
        skill_id, candidate_id = skill.id, candidate.id

    try:
        async with AsyncSessionLocal() as db:
            # limit=None przetworzyłby całą bazę CI — celujemy w seedowanego
            # kandydata przez wysoki id (ORDER BY id) używając limitu na SQL?
            # Prosto: run bez limitu na bazie CI jest tani (mało kandydatów),
            # a idempotencja i tak jest sednem testu.
            stats1 = await run_traffit_backfill(db, limit=None)
        assert stats1["errors"] == 0

        async with AsyncSessionLocal() as db:
            facts = (
                (
                    await db.execute(
                        select(CortexSkillFact).where(
                            CortexSkillFact.candidate_id == candidate_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(facts) == 1  # alias + kanoniczny → jeden fakt
            fact = facts[0]
            assert fact.skill_id == skill_id
            assert fact.source == "traffit"
            assert fact.level is None
            assert fact.observed_at is None
            assert fact.confidence == pytest.approx(0.8)
            assert fact.evidence  # surowy token przed normalizacją

            term_row = (
                await db.execute(
                    select(CortexUnmatchedTerm).where(
                        CortexUnmatchedTerm.term == unmatched_term
                    )
                )
            ).scalar_one()
            assert term_row.occurrences >= 1
            assert term_row.status == "new"
            first_occurrences = term_row.occurrences

        # Re-run: ten sam kandydat → upsert zamiast duplikatu.
        async with AsyncSessionLocal() as db:
            await run_traffit_backfill(db, limit=None)

        async with AsyncSessionLocal() as db:
            count = (
                await db.execute(
                    select(CortexSkillFact).where(
                        CortexSkillFact.candidate_id == candidate_id
                    )
                )
            ).scalars().all()
            assert len(count) == 1

            term_row = (
                await db.execute(
                    select(CortexUnmatchedTerm).where(
                        CortexUnmatchedTerm.term == unmatched_term
                    )
                )
            ).scalar_one()
            assert term_row.occurrences == first_occurrences + 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CortexSkillFact).where(
                    CortexSkillFact.candidate_id == candidate_id
                )
            )
            await db.execute(
                delete(CortexUnmatchedTerm).where(
                    CortexUnmatchedTerm.term == unmatched_term
                )
            )
            await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
            await db.execute(
                delete(SkillAlias).where(SkillAlias.skill_id == skill_id)
            )
            await db.execute(delete(Skill).where(Skill.id == skill_id))
            await db.commit()
