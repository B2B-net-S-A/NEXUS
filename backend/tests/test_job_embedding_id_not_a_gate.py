"""#403 — `jobs.embedding_id` NIE JEST bramką „ma wektor".

`embed_job` upsertuje wektor do Qdranta, DOPIERO POTEM stempluje kolumnę
i commituje (embedding_service.py). Gdy commit padnie po udanym upsercie,
wektor zostaje, kolumna zostaje pusta, a wołający dostaje `False`, którego
nikt nie ponawia. Trzy miejsca czytały tę kolumnę jako predykat i cicho
przerywały pracę, którą dało się wykonać poprawnie.

Te testy pilnują, że żadne z tych trzech miejsc już tego nie robi.
"""

from __future__ import annotations

import logging

import pytest

from app.models.job import Job, JobStatus, RecruitmentType
from app.services.marketplace_service import _should_scan_job

pytestmark = pytest.mark.asyncio


class _FakeResult:
    def all(self):
        return []


class _FakeDb:
    """Minimalny stub — tiery robią zapytania o CC przed/po Qdrancie."""

    async def execute(self, *a, **kw):
        return _FakeResult()


def _job(**kw) -> Job:
    base = dict(
        title="Senior Python Engineer",
        must_skills=[{"name": "Python"}],
        nice_skills=[{"name": "FastAPI"}],
        status=JobStatus.published,
        recruitment_type=RecruitmentType.body_leasing,
        embedding_id=None,
    )
    base.update(kw)
    return Job(**base)


# ── Bramka 1: marketplace ──────────────────────────────────────────────────


async def test_marketplace_scans_job_with_empty_embedding_id():
    """Pusta kolumna NIE MOŻE już wycinać skanu.

    Skan nie używa wektora oferty — warstwa semantyczna powstaje z embeddingu
    TEKSTU oferty jako zapytania do kolekcji KANDYDATÓW.
    """
    assert _should_scan_job(_job(embedding_id=None)) is None


async def test_marketplace_still_skips_on_real_reasons():
    """Zdjęliśmy JEDEN człon, nie całą bramkę — reszta musi działać."""
    assert _should_scan_job(_job(status=JobStatus.closed)) == "status=closed"
    assert _should_scan_job(_job(must_skills=[], nice_skills=[])) == "no_skills"


# ── Bramki 2 i 3: question_suggestions ─────────────────────────────────────


async def test_both_suggestion_tiers_reach_qdrant_with_empty_column(monkeypatch):
    """Oba tiery muszą DOPYTAĆ Qdranta, zamiast wierzyć kolumnie.

    `search_similar_jobs_by_job_id` adresuje wektor przez PK oferty
    (`retrieve(ids=[job_id])`) i sam zwraca [] gdy wektora nie ma — jest więc
    autorytetem, przed którym stał słabszy predykat.
    """
    from app.services import question_suggestions as qs

    calls: list[int] = []

    async def spy(job_id, **kw):
        calls.append(job_id)
        return []

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", spy)

    job = _job(embedding_id=None)
    job.id = 4242
    job.competence_category_id = 7
    job.client_id = 1

    await qs._tier_same_cc_similar(_FakeDb(), job)
    assert calls == [4242], "tier 1 nadal ucina przed Qdrantem"

    # Tier 2 robi jedno zapytanie o secondary CC PRZED Qdrantem — stąd fake db.
    await qs._tier_secondary_cc(_FakeDb(), job)
    assert calls == [4242, 4242], "tier 2 nadal ucina przed Qdrantem"


async def test_tier1_still_requires_competence_category(monkeypatch):
    """Człon `not job.competence_category_id` MUSI zostać.

    Filtr niżej to `Job.competence_category_id == job.competence_category_id`,
    co przy None degeneruje do IS NULL i dopasowałoby oferty bez CC.
    """
    from app.services import question_suggestions as qs

    calls: list[int] = []

    async def spy(job_id, **kw):
        calls.append(job_id)
        return []

    monkeypatch.setattr(qs, "search_similar_jobs_by_job_id", spy)

    job = _job(embedding_id="7")
    job.id = 99
    job.competence_category_id = None

    assert await qs._tier_same_cc_similar(_FakeDb(), job) == []
    assert calls == [], "brak CC musi ucinać PRZED Qdrantem"


# ── Głośny log zamiast cichego return ──────────────────────────────────────


async def test_missing_vector_is_logged_at_warning(monkeypatch, caplog):
    """„Brak wektora" musi być widoczny na prodzie (root logger = INFO)."""
    from app.services import embedding_service as es

    class _Client:
        def retrieve(self, **kw):
            return []  # Qdrant ODPOWIEDZIAŁ: wektora nie ma.

    monkeypatch.setattr(es, "QdrantClient", _Client, raising=False)
    monkeypatch.setattr(
        "qdrant_client.QdrantClient", lambda *a, **kw: _Client()
    )

    with caplog.at_level(logging.WARNING, logger=es.logger.name):
        hits = await es.search_similar_jobs_by_job_id(4242)

    assert hits == []
    warnings = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    ]
    assert any("has no vector" in m for m in warnings), (
        f"brak WARNING o braku wektora; rekordy={warnings}"
    )
