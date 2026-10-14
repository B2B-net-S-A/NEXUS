"""Dwa równoległe zapisy tego samego e-maila — 409 albo pominięty adres, nie 500.

Audyt 13.10.2026: dwa równoległe `/from-cv` z tym samym adresem przechodzą
oba sprawdzenie duplikatu (drugi nie widzi jeszcze niezacommitowanego wiersza),
a unikalny indeks `ix_candidates_email` wywraca drugi zapis błędem 500. To samo
grozi ścieżce CV z maila (M365) i wspólnej ścieżce po odczycie CV.

Bez bazy: atrapa sesji rzuca ``IntegrityError`` tak jak Postgres, gdy zapis
niesie adres zajęty przez wiersz, który „wygrał wyścig”. Wariant z prawdziwą
bazą: ``test_fix48_ws10_email_race_db.py`` (wymaga CI). Dane fikcyjne.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.candidate import Candidate

TAKEN = "jan.testowy@example.com"
WINNER_ID = 77
WINNER_ROW = {
    "candidate_id": WINNER_ID,
    "name": "Jan",
    "lastname": "Testowy",
    "email": TAKEN,
    "match_score": 1.0,
    "match_reasons": ["email"],
}


def _unique_violation() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO candidates …",
        {},
        Exception(
            'duplicate key value violates unique constraint "ix_candidates_email"\n'
            f"DETAIL:  Key (email)=({TAKEN}) already exists."
        ),
    )


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _RacingSession:
    """Atrapa: adres ``TAKEN`` zajął równoległy zapis, którego sesja nie widzi."""

    def __init__(self) -> None:
        self.added: list = []
        self._next_id = 500
        self.stored_email: dict[int, object] = {}

    async def scalar(self, *_a, **_kw):
        return None  # sito „e-mail zajęty” nie widzi niezacommitowanego wiersza

    def add(self, obj) -> None:
        self.added.append(obj)

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def flush(self) -> None:
        for obj in list(self.added):
            if getattr(obj, "email", None) == TAKEN:
                if isinstance(obj, Candidate) and getattr(obj, "id", None) is None:
                    self.added.remove(obj)  # savepoint cofa INSERT
                raise _unique_violation()
        for obj in self.added:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if hasattr(obj, "email"):
                self.stored_email[id(obj)] = obj.email

    async def refresh(self, obj, *_a, **_kw) -> None:
        # Po cofnięciu savepointu wiersz wraca do stanu z bazy.
        obj.email = self.stored_email.get(id(obj))


def _find_by_email_racing():
    """Pierwsze pytanie nie widzi zwycięzcy wyścigu, drugie (po błędzie) widzi."""
    calls: list = []

    async def _find(_db, email, **_kw):
        calls.append(email)
        return [] if len(calls) == 1 else [dict(WINNER_ROW)]

    return _find, calls


# ── /from-cv ────────────────────────────────────────────────────────────────


async def _post_from_cv(monkeypatch, tmp_path, *, force: bool):
    from app.api import candidates as candidates_api

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    finder, calls = _find_by_email_racing()
    monkeypatch.setattr(candidates_api, "find_candidate_by_email", finder)
    monkeypatch.setattr(
        candidates_api,
        "_read_cv_for_new_candidate",
        AsyncMock(
            return_value=(
                "tekst CV",
                {"first_name": "Jan", "last_name": "Testowy", "email": TAKEN},
            )
        ),
    )
    monkeypatch.setattr(
        candidates_api,
        "_store_candidate_cv_document",
        AsyncMock(return_value=SimpleNamespace(id=1, content_sha256="h")),
    )
    monkeypatch.setattr(
        candidates_api, "_parsed_source_is_quarantined", AsyncMock(return_value=False)
    )
    db = _RacingSession()
    with pytest.raises(HTTPException) as caught:
        await candidates_api.create_candidate_from_cv(
            current_user=SimpleNamespace(id=7),
            db=db,
            file=UploadFile(file=io.BytesIO(b"%PDF-1.4 cv"), filename="cv.pdf"),
            force=force,
            name=None,
            lastname=None,
            email=None,
            phone=None,
            city=None,
            linkedin=None,
            candidate_fields=None,
            cleared=None,
        )
    return caught.value, db, calls


@pytest.mark.asyncio
async def test_from_cv_losing_the_email_race_is_a_409_with_the_existing_profile(
    monkeypatch, tmp_path
):
    error, db, calls = await _post_from_cv(monkeypatch, tmp_path, force=False)
    assert error.status_code == 409
    assert error.detail["existing_candidate_id"] == WINNER_ID
    assert [m["candidate_id"] for m in error.detail["matches"]] == [WINNER_ID]
    assert calls == [TAKEN, TAKEN]
    # Drugiego profilu nie ma — INSERT cofnął savepoint.
    assert not [obj for obj in db.added if isinstance(obj, Candidate)]


@pytest.mark.asyncio
async def test_from_cv_with_force_losing_the_race_gets_the_field_sentence(
    monkeypatch, tmp_path
):
    error, _db, _calls = await _post_from_cv(monkeypatch, tmp_path, force=True)
    assert error.status_code == 409
    assert error.detail == "Kandydat z tym adresem e-mail już istnieje."


# ── CV z maila (M365) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mail_cv_losing_the_email_race_goes_to_the_existing_profile(
    monkeypatch, tmp_path
):
    from app.services import dedup_service
    from app.services.m365 import attachment_handler

    monkeypatch.setattr(settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(settings, "M365_AUTO_CREATE_CANDIDATE_FROM_CV", True)
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 cv")
    monkeypatch.setattr(
        attachment_handler,
        "_extract_and_parse",
        AsyncMock(
            return_value=(
                "tekst CV",
                {"first_name": "Jan", "last_name": "Testowy", "email": TAKEN},
            )
        ),
    )
    finder, _calls = _find_by_email_racing()
    monkeypatch.setattr(dedup_service, "find_candidate_by_email", finder)
    parse = AsyncMock()
    monkeypatch.setattr(attachment_handler, "try_parse_cv", parse)

    email_row = SimpleNamespace(
        id=55,
        user_id=3,
        is_private_filtered=False,
        candidate_id=None,
        matched_by_user_id=None,
    )
    attachment = SimpleNamespace(
        id=66,
        is_cv_candidate=True,
        storage_path="cv.pdf",
        parse_error=None,
        sha256=None,
        filename="cv.pdf",
        parsed_candidate_id=None,
    )
    db = _RacingSession()

    result = await attachment_handler.try_create_candidate_from_cv(
        db, attachment, email_row
    )

    assert result == WINNER_ID
    assert email_row.candidate_id == WINNER_ID
    assert parse.await_args.kwargs["candidate_id"] == WINNER_ID
    assert attachment.parse_error is None
    assert not [obj for obj in db.added if isinstance(obj, Candidate)]


# ── wspólna ścieżka po odczycie CV ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_skips_an_email_taken_in_parallel_and_keeps_the_profile(
    monkeypatch,
):
    from app.services import (
        auto_match_outbox,
        cv_ingest_service,
        index_outbox_service,
        match_score_cache,
        profile_projection,
    )
    from app.services.cv_enrichment import CvWritePolicy

    monkeypatch.setattr(
        "app.services.cv_enrichment.apply_candidate_location_from_source",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(profile_projection, "replace_skill_usage", AsyncMock())
    monkeypatch.setattr(
        index_outbox_service, "schedule_or_embed_candidate", AsyncMock()
    )
    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", AsyncMock())
    monkeypatch.setattr(auto_match_outbox, "enqueue_candidate", AsyncMock())
    monkeypatch.setattr(cv_ingest_service, "assign_primary_cc_if_empty", AsyncMock())

    candidate = SimpleNamespace(
        id=11,
        cv_extracted_data={},
        experience=[],
        skills=[],
        education=[],
        years_it_experience=None,
        ai_summary=None,
        linkedin=None,
        name="Jan",
        lastname="Testowy",
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        cv_parsed_at=None,
    )
    db = _RacingSession()
    db.stored_email[id(candidate)] = None
    db.added.append(candidate)

    await cv_ingest_service.finish_cv_ingest(
        db,
        candidate=candidate,
        parsed={
            "_source": "claude:cv_enrichment:v7",
            "email": TAKEN,
            "phone": "+48 500 600 700",
            "skills": [{"name": "Python", "level": "senior"}],
        },
        source_document_id=5,
        source_hash="hash-abc",
        policy=CvWritePolicy.FILL_EMPTY,
        trigger="email",
    )

    assert candidate.email is None
    # Reszta odczytu zostaje zapisana — kolizja zabiera tylko adres.
    assert candidate.phone == "+48 500 600 700"
    assert [skill["name"] for skill in candidate.skills] == ["Python"]
