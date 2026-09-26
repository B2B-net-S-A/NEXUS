"""Mail z kilkoma CV różnych osób (runda 6 audytu, M365-7).

Pierwsze CV maila od nieznanego nadawcy zakładało/wskazywało kandydata A
i podpinało do niego mail. Drugie CV szło potem zwykłą kolejką do A i lądowało
w kwarantannie tożsamości A zamiast założyć kandydata B. Teraz każdy załącznik
CV maila podpiętego po tożsamości z CV rozstrzyga osobę z WŁASNEJ treści.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.models.m365 import EmailMatchMethod
from app.services.m365 import attachment_handler
from app.tasks import m365_cv_parse


def _inputs(tmp_path):
    (tmp_path / "cv2.pdf").write_bytes(b"cv")
    attachment = SimpleNamespace(
        id=8,
        is_cv_candidate=True,
        storage_path="cv2.pdf",
        filename="cv2.pdf",
        parse_error=None,
        cv_parse_attempted_at=None,
        parsed_candidate_id=None,
    )
    email = SimpleNamespace(
        id=9,
        candidate_id=41,  # osoba z pierwszego CV
        is_private_filtered=False,
        user_id=3,
        match_method=EmailMatchMethod.cv_identity,
        match_confidence=1.0,
        matched_at=None,
        matched_by_user_id=None,
    )
    return attachment, email


def _patch(monkeypatch, tmp_path, duplicates):
    from app.services import dedup_service

    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(
        attachment_handler.settings, "M365_AUTO_CREATE_CANDIDATE_FROM_CV", True
    )
    monkeypatch.setattr(
        attachment_handler,
        "_extract_and_parse",
        AsyncMock(
            return_value=(
                "tekst",
                {"first_name": "Ewa", "last_name": "Druga", "email": "ewa@example.com"},
            )
        ),
    )
    monkeypatch.setattr(
        dedup_service, "find_candidate_duplicates", AsyncMock(return_value=duplicates)
    )
    parse = AsyncMock()
    monkeypatch.setattr(attachment_handler, "try_parse_cv", parse)
    return parse


async def test_second_cv_goes_to_the_person_from_its_own_content(
    monkeypatch, tmp_path
) -> None:
    parse = _patch(
        monkeypatch,
        tmp_path,
        [{"candidate_id": 77, "match_score": 1.0, "match_reasons": ["email_exact"]}],
    )
    attachment, email = _inputs(tmp_path)

    target = await attachment_handler.try_parse_cv_by_identity(
        AsyncMock(), attachment, email
    )

    assert target == 77
    assert parse.await_args.kwargs["candidate_id"] == 77
    # Mail zostaje przy pierwszej osobie.
    assert email.candidate_id == 41
    assert attachment.cv_parse_attempted_at is not None


async def test_second_cv_of_new_person_creates_candidate(monkeypatch, tmp_path) -> None:
    parse = _patch(monkeypatch, tmp_path, [])
    attachment, email = _inputs(tmp_path)
    db = AsyncMock()
    db.add = MagicMock()

    async def _flush():
        created = db.add.call_args_list[0].args[0]
        created.id = 88

    db.flush.side_effect = _flush

    target = await attachment_handler.try_parse_cv_by_identity(db, attachment, email)

    assert target == 88
    assert parse.await_args.kwargs["candidate_id"] == 88
    assert email.candidate_id == 41


async def test_unresolved_second_cv_is_terminal(monkeypatch, tmp_path) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        [{"candidate_id": 5, "match_score": 0.9, "match_reasons": ["name_exact"]}],
    )
    attachment, email = _inputs(tmp_path)
    assert (
        await attachment_handler.try_parse_cv_by_identity(
            AsyncMock(), attachment, email
        )
        is None
    )
    assert attachment.parse_error == "possible_duplicate_name"
    assert attachment.cv_parse_attempted_at is not None


async def test_worker_routes_cv_identity_mail_by_content(monkeypatch) -> None:
    attachment = SimpleNamespace(id=8, email_id=9, parsed_candidate_id=None)
    email = SimpleNamespace(
        id=9, candidate_id=41, match_method=EmailMatchMethod.cv_identity
    )
    db = AsyncMock()
    db.scalar.return_value = attachment
    db.get.return_value = email

    @asynccontextmanager
    async def _session():
        yield db

    async def _by_identity(_db, claimed, _email):
        claimed.parsed_candidate_id = 77
        return 77

    plain = AsyncMock()
    monkeypatch.setattr(m365_cv_parse, "AsyncSessionLocal", _session)
    monkeypatch.setattr(
        m365_cv_parse.attachment_handler, "try_parse_cv_by_identity", _by_identity
    )
    monkeypatch.setattr(m365_cv_parse.attachment_handler, "try_parse_cv", plain)
    outcome = MagicMock()
    monkeypatch.setattr(m365_cv_parse, "record_job_outcome", outcome)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_AUTO_PARSE_CV", True)

    assert await m365_cv_parse.run_m365_cv_parse_once() is True
    plain.assert_not_awaited()
    # Załącznik zostaje przy osobie ze swojej treści (nie jest zerowany).
    assert attachment.parsed_candidate_id == 77
    assert outcome.call_args.args[1] is True
    claim_sql = str(db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "emails.match_method !=" in claim_sql
