from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.candidate_identity_quarantine import _serialize
from app.core.config import Settings
from app.models.index_outbox import IndexOutboxEvent
from app.models.note import Note
from app.models.user import User, UserRole
from app.services import candidate_identity_quarantine as quarantine


def test_identity_match_accepts_transliterated_polish_name() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Łukasz",
        candidate_last_name="Żółć",
        observed_first_name="Lukasz",
        observed_last_name="Zolc",
    )

    assert result.decision == "confirmed_match"
    assert result.evidence["first_name_match"] is True
    assert result.evidence["last_name_match"] is True


def test_identity_match_accepts_parser_name_order_swap() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Jan",
        candidate_last_name="Kowalski",
        observed_first_name="Kowalski",
        observed_last_name="Jan",
    )

    assert result.decision == "confirmed_match"
    assert result.evidence["name_order_swapped"] is True


def test_identity_match_without_observed_surname_is_inconclusive() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Jan",
        candidate_last_name="Kowalski",
        observed_first_name="Anna",
        observed_last_name=None,
    )

    assert result.decision == "inconclusive"
    assert result.evidence["observed_identity_complete"] is False


def test_identity_match_confirms_a_different_person_only_on_two_disagreements() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Jan",
        candidate_last_name="Kowalski",
        observed_first_name="Anna",
        observed_last_name="Nowak",
    )
    partial = quarantine.evaluate_identity_match(
        candidate_first_name="Jan",
        candidate_last_name="Kowalski",
        observed_first_name="Jan",
        observed_last_name="Nowak",
    )

    assert result.decision == "confirmed_mismatch"
    assert partial.decision == "inconclusive"


def test_identity_evidence_has_fingerprints_but_no_raw_names() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Sekretne",
        candidate_last_name="Nazwisko",
        observed_first_name="Inna",
        observed_last_name="Osoba",
    )
    serialized = json.dumps(result.evidence, ensure_ascii=False).lower()

    assert "sekretne" not in serialized
    assert "nazwisko" not in serialized
    assert len(result.evidence["candidate_identity_fingerprint"]) == 64


def test_identity_fingerprint_is_deterministic_but_not_an_unkeyed_name_hash() -> None:
    first = quarantine.normalize_person_name_part("Łukasz")
    last = quarantine.normalize_person_name_part("Żółć")

    one = quarantine._fingerprint(first, last)
    two = quarantine._fingerprint(first, last)
    unkeyed = hashlib.sha256(f"{first}\x1f{last}".encode()).hexdigest()

    assert one == two
    assert one != unkeyed


def test_production_identity_fingerprint_key_is_required_and_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jwt_key = "jwt-signing-key-that-is-long-enough-for-production-123456"
    monkeypatch.setenv("DEBUG", "false")

    with pytest.raises(ValidationError, match="is required in production"):
        Settings(
            _env_file=None,
            DEBUG=False,
            SECRET_KEY=jwt_key,
            CANDIDATE_IDENTITY_FINGERPRINT_KEY="",
        )

    with pytest.raises(ValidationError, match="is required in production"):
        Settings(
            _env_file=None,
            DEBUG=False,
            SECRET_KEY=jwt_key,
            CANDIDATE_IDENTITY_FINGERPRINT_KEY=(
                "change-me-to-a-different-long-random-string-min-48-chars"
            ),
        )

    with pytest.raises(ValidationError, match="must not equal SECRET_KEY"):
        Settings(
            _env_file=None,
            DEBUG=False,
            SECRET_KEY=jwt_key,
            CANDIDATE_IDENTITY_FINGERPRINT_KEY=jwt_key,
        )

    configured = Settings(
        _env_file=None,
        DEBUG=False,
        SECRET_KEY=jwt_key,
        CANDIDATE_IDENTITY_FINGERPRINT_KEY=(
            "candidate-identity-key-distinct-from-jwt-and-long-enough"
        ),
    )
    assert configured.CANDIDATE_IDENTITY_FINGERPRINT_KEY != configured.SECRET_KEY


def test_source_eligibility_is_a_correlated_not_exists_guard() -> None:
    clause = quarantine.source_is_eligible_clause(
        candidate_id_column=Note.candidate_id,
        source_id_column=Note.id,
        source_kind="note",
    )
    sql = str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "NOT (EXISTS" in sql
    assert "confirmed_mismatch" in sql
    assert "override_at IS NULL" in sql


class _FlushOnlyDB:
    def __init__(self, locked_candidate: object | None = None) -> None:
        self.locked_candidate = locked_candidate

    async def flush(self) -> None:
        return None

    async def execute(self, *_args, **_kwargs):
        return None

    async def scalar(self, *_args, **_kwargs):
        return self.locked_candidate


class _Rows:
    def __init__(self, rows: list | None = None):
        self.rows = rows or []

    def all(self) -> list:
        return self.rows


class _ProjectionDB:
    def __init__(self, *scalars, language_batches: list[list] | None = None):
        self._scalars = list(scalars)
        self._language_batches = list(language_batches or [[], []])
        self.added: list[object] = []

    async def scalar(self, *_args, **_kwargs):
        return self._scalars.pop(0)

    async def scalars(self, *_args, **_kwargs):
        return _Rows(self._language_batches.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)


def _user(role: UserRole, user_id: int = 7) -> User:
    return User(
        id=user_id,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
    )


@pytest.mark.asyncio
async def test_override_rejects_every_non_admin_non_hor_role() -> None:
    for role in (
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.user,
    ):
        with pytest.raises(quarantine.IdentityQuarantineForbidden):
            await quarantine.override_identity_quarantine(
                _FlushOnlyDB(),  # type: ignore[arg-type]
                candidate_id=11,
                source_kind="note",
                source_id=22,
                actor=_user(role),
                reason="verified source owner",
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("overridden", [False, True])
async def test_parser_retry_never_clears_a_confirmed_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    overridden: bool,
) -> None:
    reviewed_at = datetime(2026, 7, 30, tzinfo=timezone.utc)
    row = SimpleNamespace(
        decision="confirmed_mismatch",
        provenance="cv_parser:document",
        reviewed_at=reviewed_at,
        override_at=datetime.now(timezone.utc) if overridden else None,
        is_quarantined=not overridden,
    )

    async def fake_get(*_args, **_kwargs):
        return row

    monkeypatch.setattr(quarantine, "get_identity_review", fake_get)
    candidate = SimpleNamespace(id=11, name="Jan", lastname="Kowalski")

    result = await quarantine.record_detected_identity(
        _FlushOnlyDB(candidate),  # type: ignore[arg-type]
        candidate=candidate,  # type: ignore[arg-type]
        source_kind="note",
        source_id=22,
        observed_first_name="Jan",
        observed_last_name="Kowalski",
        provenance="cv_parser:retry",
    )

    assert result is row
    assert row.decision == "confirmed_mismatch"
    assert row.provenance == "cv_parser:document"
    assert row.reviewed_at == reviewed_at


@pytest.mark.asyncio
async def test_detected_identity_uses_fresh_locked_candidate_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = SimpleNamespace(id=11, name="Jan", lastname="Kowalski")
    locked = SimpleNamespace(id=11, name="Anna", lastname="Nowak")
    captured: dict[str, object] = {}

    async def fake_get(*_args, **_kwargs):
        return SimpleNamespace(
            decision="confirmed_match",
            provenance="cv_parser:document",
            override_at=None,
            is_quarantined=False,
        )

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return quarantine.IdentityMatchResult("confirmed_match", {})

    monkeypatch.setattr(quarantine, "get_identity_review", fake_get)
    monkeypatch.setattr(quarantine, "evaluate_identity_match", fake_evaluate)

    await quarantine.record_detected_identity(
        _FlushOnlyDB(locked),  # type: ignore[arg-type]
        candidate=stale,  # type: ignore[arg-type]
        source_kind="document",
        source_id=22,
        observed_first_name="Anna",
        observed_last_name="Nowak",
        provenance="cv_parser:document",
    )

    assert captured["candidate_first_name"] == "Anna"
    assert captured["candidate_last_name"] == "Nowak"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.head_of_recruitment])
async def test_override_requires_reason_and_audits_only_its_hash(
    monkeypatch: pytest.MonkeyPatch,
    role: UserRole,
) -> None:
    row = SimpleNamespace(
        decision="confirmed_mismatch",
        override_reason=None,
        override_by_id=None,
        override_at=None,
    )

    async def fake_get(*_args, **_kwargs):
        return row

    captured: list[dict] = []
    monkeypatch.setattr(quarantine, "get_identity_review", fake_get)
    monkeypatch.setattr(
        quarantine.candidate_audit,
        "record_candidate_audit",
        lambda _db, **kwargs: captured.append(kwargs),
    )
    actor = _user(role)

    with pytest.raises(ValueError):
        await quarantine.override_identity_quarantine(
            _FlushOnlyDB(),  # type: ignore[arg-type]
            candidate_id=11,
            source_kind="document",
            source_id=22,
            actor=actor,
            reason=" ",
        )

    raw_reason = "Owner verified the document outside NEXUS"
    result = await quarantine.override_identity_quarantine(
        _FlushOnlyDB(),  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        actor=actor,
        reason=raw_reason,
    )

    assert result.override_by_id == actor.id
    assert result.override_reason == raw_reason
    assert captured[0]["details"]["reason_length"] == len(raw_reason)
    assert len(captured[0]["details"]["reason_sha256"]) == 64
    assert raw_reason not in json.dumps(captured[0])


def test_api_projection_never_exposes_name_fingerprints_or_override_reason() -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        candidate_id=1,
        source_kind="document",
        source_id=2,
        decision="confirmed_mismatch",
        provenance="cv_parser:document",
        detector_version=quarantine.IDENTITY_DETECTOR_VERSION,
        evidence={
            "candidate_identity_complete": True,
            "candidate_identity_fingerprint": "a" * 64,
        },
        reviewed_by_id=None,
        reviewed_at=now,
        is_quarantined=True,
        override_reason="PII can be typed here",
        override_by_id=None,
        override_at=None,
    )

    payload = _serialize(row).model_dump()

    assert payload["evidence"] == {"candidate_identity_complete": True}
    assert "override_reason" not in payload


def test_cv_language_source_refs_match_every_writer_contract() -> None:
    assert quarantine._quarantined_cv_language_source_refs(
        candidate_id=11,
        source_kind="legacy_cv",
        source_id=11,
    ) == ("legacy-cv:11",)
    assert quarantine._quarantined_cv_language_source_refs(
        candidate_id=11,
        source_kind="document",
        source_id=22,
        document_hash="a" * 64,
    ) == ("document:22", "a" * 64)


@pytest.mark.asyncio
async def test_document_quarantine_clears_only_matching_cv_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted = {
        "skills": [{"name": "Wrong Person Skill"}],
        "education": [{"school": "Wrong School"}],
        "companies": ["Wrong Company"],
        "years_it_experience": 9,
        "email": "wrong@example.com",
        "phone": "+48 123",
        "city": "Wrong City",
        "career_summary": "wrong summary",
        "cv_highlights": {"source_document_id": 22},
        "_manual_override_experience": True,
    }
    manually_curated_experience = [
        {"company": "Keep", "role": "Lead", "start": None, "end": None, "desc": None}
    ]
    candidate = SimpleNamespace(
        id=11,
        cv_extracted_data=extracted,
        raw_cv_text="wrong raw text",
        cv_filename="wrong.pdf",
        cv_parsed_at=datetime.now(timezone.utc),
        ai_summary="wrong summary",
        skills=extracted["skills"],
        education=extracted["education"],
        experience=manually_curated_experience,
        years_it_experience=9,
        email="wrong@example.com",
        phone="+48 123",
        city="Wrong City",
        country="PL",
        location="Wrong City, PL",
        linkedin=None,
        languages_version=1,
        languages=[],
    )
    document = SimpleNamespace(
        id=22,
        filename="wrong.pdf",
        content_sha256="a" * 64,
        is_primary=True,
    )
    language = SimpleNamespace(
        language_code="en",
        language_name="English",
        cefr_level="B2",
        is_native=False,
        is_level_unknown=False,
        deleted_at=None,
        version=1,
    )

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )

    db = _ProjectionDB(
        candidate,
        document,
        language_batches=[[language], []],
    )
    result = await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
    )

    assert document.is_primary is False
    assert candidate.raw_cv_text is None
    assert candidate.cv_filename is None
    assert candidate.ai_summary is None
    assert candidate.skills == []
    assert candidate.education == []
    assert candidate.years_it_experience is None
    assert candidate.email is None
    assert candidate.phone is None
    assert candidate.city is None
    assert candidate.country == "PL"
    assert candidate.location == "PL"
    assert candidate.experience == manually_curated_experience
    assert language.deleted_at is not None
    assert language.version == 2
    assert candidate.cv_extracted_data == {
        "_manual_override_experience": True,
        "_identity_quarantine_source": {"kind": "document", "id": 22},
    }
    assert result["cleared_fields"] >= 10
    assert result["tombstoned_languages"] == 1
    assert len(db.added) == 1
    assert isinstance(db.added[0], IndexOutboxEvent)
    assert db.added[0].operation == "delete"


@pytest.mark.asyncio
async def test_stale_legacy_quarantine_never_clears_newer_document_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = SimpleNamespace(
        id=11,
        cv_extracted_data={
            "skills": [{"name": "Current"}],
            "cv_highlights": {"source_document_id": 99},
        },
        raw_cv_text="current document",
        cv_filename="current.pdf",
        cv_parsed_at=datetime.now(timezone.utc),
        ai_summary="current summary",
        skills=[{"name": "Current"}],
        education=[],
        experience=[],
        years_it_experience=3,
        email=None,
        phone=None,
        city="Warszawa",
        country="PL",
        location="Warszawa, PL",
        linkedin=None,
        languages_version=1,
        languages=[],
    )

    async def unexpected(*_args, **_kwargs):
        pytest.fail("a non-owning legacy source must not invalidate current facts")

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate",
        unexpected,
    )
    db = _ProjectionDB(candidate)

    result = await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="legacy_cv",
        source_id=11,
    )

    assert result == {"cleared_fields": 0, "tombstoned_languages": 0}
    assert candidate.raw_cv_text == "current document"
    assert candidate.ai_summary == "current summary"
    assert candidate.skills == [{"name": "Current"}]
    assert db.added == []
