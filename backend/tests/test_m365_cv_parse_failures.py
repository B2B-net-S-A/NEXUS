"""Pętla CV z maila nie może kręcić się na jednym załączniku (runda 6 audytu).

- wyjątek w odczycie CV (np. UNIQUE e-maila przy zapisie profilu) cofał
  transakcję razem ze znacznikiem próby — ten sam załącznik wracał co kilka
  sekund na płatny ``parse_cv``, a reszta kolejki stała;
- nieudana próba po rematchu (``parsed_candidate_id`` = poprzedni kandydat)
  zostawała w kolejce na zawsze;
- ``finish_cv_ingest`` nie wpisuje e-maila z CV, który ma już inna osoba.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.m365 import EmailMatchMethod
from app.services import cv_ingest_service
from app.services.cv_enrichment import CvWritePolicy
from app.tasks import m365_cv_parse


def _wire(monkeypatch, parse, *, mark_row=None):
    attachment = SimpleNamespace(id=91, email_id=72, parsed_candidate_id=None)
    email = SimpleNamespace(id=72, candidate_id=37, match_method=EmailMatchMethod.strict)
    work_db = AsyncMock()
    work_db.scalar.return_value = attachment
    work_db.get.return_value = email
    mark_db = AsyncMock()
    mark_db.get.return_value = mark_row
    sessions = iter([work_db, mark_db])

    @asynccontextmanager
    async def _session():
        yield next(sessions)

    outcome = MagicMock()
    monkeypatch.setattr(m365_cv_parse, "AsyncSessionLocal", _session)
    monkeypatch.setattr(m365_cv_parse.attachment_handler, "try_parse_cv", parse)
    monkeypatch.setattr(m365_cv_parse, "record_job_outcome", outcome)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_AUTO_PARSE_CV", True)
    return attachment, work_db, mark_db, outcome


async def test_exception_marks_attempt_in_own_transaction(monkeypatch) -> None:
    async def _boom(_db, claimed, _email):
        claimed.cv_parse_attempted_at = "set-in-rolled-back-tx"
        raise IntegrityError("UPDATE candidates", {}, Exception("uq email"))

    mark_row = SimpleNamespace(
        cv_parse_attempted_at=None, parsed_candidate_id=12, parse_error=None
    )
    _att, work_db, mark_db, outcome = _wire(monkeypatch, _boom, mark_row=mark_row)

    assert await m365_cv_parse.run_m365_cv_parse_once() is True
    work_db.rollback.assert_awaited_once()
    work_db.commit.assert_not_awaited()
    mark_db.commit.assert_awaited_once()
    assert mark_row.cv_parse_attempted_at is not None
    assert mark_row.parsed_candidate_id is None
    assert mark_row.parse_error == "parse_failed: IntegrityError"
    assert outcome.call_args.args[1] is False


async def test_failed_rematch_is_terminal(monkeypatch) -> None:
    async def _fails_quietly(_db, claimed, _email):
        # Rematch: stary kandydat 12, próba dla 37 nie powiodła się.
        claimed.parsed_candidate_id = 12
        claimed.parse_error = "text_extraction_empty"

    attachment, work_db, _mark_db, _outcome = _wire(monkeypatch, _fails_quietly)

    assert await m365_cv_parse.run_m365_cv_parse_once() is True
    work_db.commit.assert_awaited_once()
    # Znacznik próby jest ustawiony, a pusty ``parsed_candidate_id`` wyjmuje
    # wiersz z warunku kolejki (``attempted_at IS NULL OR parsed IS NOT NULL``).
    assert attachment.parsed_candidate_id is None


def _candidate(email=None):
    return SimpleNamespace(
        id=11,
        cv_extracted_data={},
        experience=[],
        skills=[],
        education=[],
        years_it_experience=None,
        ai_summary=None,
        linkedin=None,
        name="Ola",
        lastname="Testowa",
        email=email,
        phone=None,
        city=None,
        country=None,
        location=None,
        cv_parsed_at=None,
    )


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.parametrize("taken", [True, False])
async def test_ingest_skips_email_owned_by_another_candidate(
    monkeypatch, taken: bool
) -> None:
    from app.services import (
        auto_match_outbox,
        index_outbox_service,
        match_score_cache,
        profile_projection,
    )

    monkeypatch.setattr(
        "app.services.cv_enrichment.apply_candidate_location_from_source",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(profile_projection, "replace_skill_usage", AsyncMock(return_value=0))
    monkeypatch.setattr(index_outbox_service, "schedule_or_embed_candidate", AsyncMock())
    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", AsyncMock())
    monkeypatch.setattr(auto_match_outbox, "enqueue_candidate", AsyncMock())
    monkeypatch.setattr(cv_ingest_service, "assign_primary_cc_if_empty", AsyncMock())

    candidate = _candidate()
    db = SimpleNamespace(
        flush=AsyncMock(),
        begin_nested=lambda: _Nested(),
        scalar=AsyncMock(return_value=55 if taken else None),
    )
    await cv_ingest_service.finish_cv_ingest(
        db,
        candidate=candidate,
        parsed={"email": "Ola@Firma.pl", "first_name": "Ola"},
        source_document_id=5,
        source_hash="h",
        policy=CvWritePolicy.FILL_EMPTY,
        trigger="email",
    )
    assert candidate.email == (None if taken else "ola@firma.pl")
