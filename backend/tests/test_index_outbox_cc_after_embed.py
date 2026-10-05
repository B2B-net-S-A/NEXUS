"""Kategoria kompetencji po policzeniu wektora w kolejce indeksu (05.10.2026).

Przy włączonym outboxie `finish_cv_ingest` klasyfikuje kandydata, zanim worker
policzy wektor — bez wektora klasyfikator prawie nigdy nie przekracza progu
kategorii głównej (produkcja: 122 z 661 nowych kandydatów z CV w 7 dni).
Worker po udanym zapisie wektora uzupełnia więc kategorię, ale tylko
kandydatowi bez żadnej kategorii, i nigdy nie psuje oznaczenia intencji.

Voyage i Qdrant są zaślepione: `embed_candidate` zwraca sukces, klasyfikator
zwraca gotowe wyniki. Baza prawdziwa (CI Postgres).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.competence_category import (
    CandidateCcCategorySource,
    CandidateCompetenceCategory,
    CompetenceCategory,
)
from app.models.index_outbox import IndexOutboxEvent
from app.services import index_outbox_service as outbox
from app.services.cc_classifier import CcScore

_created: list[int] = []


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    if not _created:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM match_index_outbox "
                "WHERE entity_type = 'candidate' AND entity_id = ANY(:ids)"
            ),
            {"ids": list(_created)},
        )
        await db.execute(
            text("DELETE FROM candidates WHERE id = ANY(:ids)"),
            {"ids": list(_created)},
        )
        await db.commit()
    _created.clear()


async def _category(slug: str) -> CompetenceCategory:
    async with AsyncSessionLocal() as db:
        cc = await db.scalar(
            select(CompetenceCategory).where(CompetenceCategory.slug == slug)
        )
    assert cc is not None, f"brak kategorii {slug} w bazie testowej"
    return cc


async def _candidate(**kw) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Kasia",
            lastname=f"Wektor-{uuid.uuid4().hex[:6]}",
            email=f"cc-embed-{uuid.uuid4().hex[:8]}@example.com",
            **kw,
        )
        db.add(cand)
        await db.commit()
        _created.append(cand.id)
        return cand.id


def _score(cc: CompetenceCategory, score: float = 0.9) -> CcScore:
    return CcScore(
        cc_id=cc.id,
        slug=cc.slug,
        name_pl=cc.name_pl,
        score=score,
        keyword_ratio=0.5,
        embedding_score=0.9,
        keywords_matched=[],
    )


def _stub_embed(monkeypatch) -> None:
    async def _embed(_cid, _db, *, record_intent=True):
        return True

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _embed)


@pytest.mark.asyncio
async def test_candidate_without_category_gets_one_after_embed(monkeypatch):
    dev = await _category("software_development")
    cand_id = await _candidate()
    _stub_embed(monkeypatch)
    seen: list[int] = []

    async def _classify(candidate, _db):
        seen.append(candidate.id)
        return [_score(dev)]

    monkeypatch.setattr(
        "app.services.cc_classifier.classify_candidate_to_cc", _classify
    )

    ok = await outbox._default_reindex(outbox.CANDIDATE, cand_id, "upsert")

    assert ok is True
    assert seen == [cand_id]
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        rows = (
            (
                await db.execute(
                    select(CandidateCompetenceCategory).where(
                        CandidateCompetenceCategory.candidate_id == cand_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert cand.competence_category_id == dev.id
    assert cand.competence_category == "software_development"
    assert [(r.competence_category_id, r.is_primary) for r in rows] == [(dev.id, True)]


@pytest.mark.asyncio
async def test_manually_curated_candidate_is_left_alone(monkeypatch):
    dev = await _category("software_development")
    qa = await _category("security_quality")
    cand_id = await _candidate(
        competence_category="security_quality", competence_category_id=qa.id
    )
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateCompetenceCategory(
                candidate_id=cand_id,
                competence_category_id=qa.id,
                is_primary=True,
                confidence_score=1.0,
                source=CandidateCcCategorySource.manual,
            )
        )
        await db.commit()
    _stub_embed(monkeypatch)
    calls: list[int] = []

    async def _classify(candidate, _db):
        calls.append(candidate.id)
        return [_score(dev)]

    monkeypatch.setattr(
        "app.services.cc_classifier.classify_candidate_to_cc", _classify
    )

    ok = await outbox._default_reindex(outbox.CANDIDATE, cand_id, "upsert")

    assert ok is True
    # Tanie sprawdzenie w SQL idzie pierwsze — klasyfikator w ogóle nie rusza.
    assert calls == []
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        rows = (
            (
                await db.execute(
                    select(CandidateCompetenceCategory).where(
                        CandidateCompetenceCategory.candidate_id == cand_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert cand.competence_category_id == qa.id
    assert [(r.competence_category_id, r.source) for r in rows] == [
        (qa.id, CandidateCcCategorySource.manual)
    ]


@pytest.mark.asyncio
async def test_failed_embed_does_not_classify(monkeypatch):
    cand_id = await _candidate()

    async def _embed(_cid, _db, *, record_intent=True):
        return False

    monkeypatch.setattr("app.services.embedding_service.embed_candidate", _embed)
    calls: list[int] = []

    async def _classify(candidate, _db):
        calls.append(candidate.id)
        return []

    monkeypatch.setattr(
        "app.services.cc_classifier.classify_candidate_to_cc", _classify
    )

    ok = await outbox._default_reindex(outbox.CANDIDATE, cand_id, "upsert")

    assert ok is False
    assert calls == []


@pytest.mark.asyncio
async def test_classifier_error_still_marks_the_intent_done(monkeypatch):
    cand_id = await _candidate()
    _stub_embed(monkeypatch)

    async def _boom(_candidate, _db):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("app.services.cc_classifier.classify_candidate_to_cc", _boom)

    async with AsyncSessionLocal() as db:
        ev = IndexOutboxEvent(
            entity_type="candidate",
            entity_id=cand_id,
            entity_revision=1,
            desired_hash="h-cc-after-embed",
            operation="upsert",
            status="processing",
            attempts=0,
        )
        db.add(ev)
        await db.commit()
        ev_id = ev.id

    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id)
        status = await outbox.process_event(db, ev)
        await db.commit()

    assert status == "done"
    async with AsyncSessionLocal() as db:
        ev = await db.get(IndexOutboxEvent, ev_id)
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
    assert ev.status == "done"
    assert ev.attempts == 0
    assert cand.competence_category_id is None


@pytest.mark.asyncio
async def test_assign_after_embed_never_raises(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("baza padła")

    monkeypatch.setattr(
        "app.services.cv_ingest_service.assign_primary_cc_if_empty", _boom
    )
    cand_id = await _candidate()

    # Ani wyjątek wołanego kroku, ani brak kandydata nie wychodzą na zewnątrz.
    await outbox.assign_cc_after_embed(cand_id)
    await outbox.assign_cc_after_embed(2_000_000_000)
