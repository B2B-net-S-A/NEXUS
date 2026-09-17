"""Jedna ścieżka po odczycie CV (`cv_ingest_service.finish_cv_ingest`).

Kontrakty:

- nikt poza wspólną ścieżką (i dwoma biegami masowymi) nie woła
  `_apply_cv_enrichment` — inaczej kolejne wejście CV znowu pomija wektor,
  kategorię albo auto-dopasowanie;
- kroki po zapisie pól są dodatkami: awaria indeksu technologii, wektora
  czy kolejki nie cofa zapisu profilu;
- zdarzenie auto-dopasowania trafia do kolejki raz na wersję pliku CV.
"""

from __future__ import annotations

import ast
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services import cv_ingest_service
from app.services.cv_enrichment import CvWritePolicy
from app.services.cv_parser import _normalize_cv_output

APP = Path(__file__).resolve().parents[1] / "app"

# Biegi masowe na starych profilach świadomie NIE zgłaszają auto-dopasowania:
# nocny sync Traffita dodawałby do pipeline'ów tysiące historycznych kandydatów
# (decyzja Artura z 17.09.2026: bogaty profil i auto-match tylko dla nowych CV).
_ALLOWED_DIRECT_CALLERS = {
    "services/cv_ingest_service.py",
    "services/cv_backfill.py",
    "services/cv_field_backfill.py",
}


def test_only_the_shared_path_applies_cv_enrichment():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in _ALLOWED_DIRECT_CALLERS or rel == "services/cv_enrichment.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "_apply_cv_enrichment":
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "Wejście CV z pominięciem `finish_cv_ingest` (wektor, kategoria, "
        f"auto-match): {offenders}"
    )


def _parse():
    return _normalize_cv_output(
        {
            "_source": "claude:cv_enrichment:v7",
            "first_name": "Ola",
            "last_name": "Testowa",
            "experience": [
                {
                    "company": "Acme",
                    "role": "Dev",
                    "start": "2022-01",
                    "end": "present",
                    "technologies": ["Python", "Kafka"],
                }
            ],
            "skills": [{"name": "Python", "level": "senior"}],
        }
    )


@pytest.mark.asyncio
async def test_enrichment_extras_are_best_effort(monkeypatch):
    from types import SimpleNamespace

    from app.services import (
        auto_match_outbox,
        candidate_language_writer,
        index_outbox_service,
        match_score_cache,
        profile_projection,
    )

    candidate = SimpleNamespace(
        id=11,
        cv_extracted_data={},
        experience=[],
        skills=[],
        education=[],
        years_it_experience=None,
        ai_summary=None,
        linkedin=None,
        name="?",
        lastname=None,
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        cv_parsed_at=None,
    )
    monkeypatch.setattr(
        "app.services.cv_enrichment.apply_candidate_location_from_source",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        candidate_language_writer, "sync_candidate_languages_from_source", AsyncMock()
    )
    monkeypatch.setattr(
        profile_projection, "replace_skill_usage", AsyncMock(side_effect=RuntimeError("x"))
    )
    monkeypatch.setattr(
        index_outbox_service,
        "schedule_or_embed_candidate",
        AsyncMock(side_effect=RuntimeError("voyage down")),
    )
    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", AsyncMock())
    enqueue = AsyncMock()
    monkeypatch.setattr(auto_match_outbox, "enqueue_candidate", enqueue)
    monkeypatch.setattr(cv_ingest_service, "assign_primary_cc_if_empty", AsyncMock())
    monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", True)

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    db = SimpleNamespace(flush=AsyncMock(), begin_nested=lambda: _Nested())

    outcome = await cv_ingest_service.finish_cv_ingest(
        db,
        candidate=candidate,
        parsed=_parse(),
        source_document_id=5,
        source_hash="hash-abc",
        policy=CvWritePolicy.REFRESH,
        trigger="cv_upload",
    )

    assert candidate.experience[0]["technologies"] == ["Python", "Kafka"]
    assert outcome.embedded is False
    assert outcome.skill_usage_rows == 0
    assert outcome.auto_match_queued is True
    enqueue.assert_awaited_once_with(
        db, candidate_id=11, trigger="cv_upload", profile_revision="hash-abc"
    )


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
async def test_ingest_queues_auto_match_once_per_cv_version(monkeypatch):
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_auto_match import CandidateMatchOutbox
    from app.models.candidate_skill_usage import CandidateSkillUsage
    from app.services import index_outbox_service

    monkeypatch.setattr(settings, "AUTO_MATCH_ENABLED", True)
    monkeypatch.setattr(
        index_outbox_service, "schedule_or_embed_candidate", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(cv_ingest_service, "assign_primary_cc_if_empty", AsyncMock())
    source_hash = uuid.uuid4().hex

    async with AsyncSessionLocal() as db:
        try:
            candidate = Candidate(name="Ola", lastname="Testowa")
            db.add(candidate)
            await db.flush()
            for _ in range(2):
                await cv_ingest_service.finish_cv_ingest(
                    db,
                    candidate=candidate,
                    parsed=_parse(),
                    source_document_id=None,
                    source_hash=source_hash,
                    policy=CvWritePolicy.REFRESH,
                    trigger="cv_upload",
                )
            queued = await db.scalar(
                select(func.count())
                .select_from(CandidateMatchOutbox)
                .where(CandidateMatchOutbox.candidate_id == candidate.id)
            )
            usage = await db.scalar(
                select(func.count())
                .select_from(CandidateSkillUsage)
                .where(CandidateSkillUsage.candidate_id == candidate.id)
            )
            assert queued == 1
            assert usage == 2
        finally:
            await db.rollback()
