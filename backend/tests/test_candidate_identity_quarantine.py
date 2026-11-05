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
from app.services.cv_enrichment import _apply_cv_enrichment, normalize_llm_skills
from app.services.proxycurl import normalize_linkedin_url


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


@pytest.mark.parametrize(
    ("first", "last", "unreadable"),
    [
        ("Іван", "Петренко", True),
        ("Jan", "Петренко", True),
        ("Łukasz", "Żółć", False),
        ("Jan", None, False),
        ("nieznany", "Kowalski", False),
    ],
)
def test_identity_unreadable_flags_names_that_normalize_to_nothing(
    first, last, unreadable
) -> None:
    # Cyrylica po normalizacji znika, więc bramka zawsze daje `inconclusive`
    # (kandydat z 4 361 cudzymi mailami, 20.10.2026).
    assert quarantine.identity_unreadable(first, last) is unreadable


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

    async def flush(self) -> None:
        self.flushes = getattr(self, "flushes", 0) + 1


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
        UserRole.recruiter,
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


def _noop(*_args, **_kwargs) -> None:
    return None


class _NewReviewDB(_FlushOnlyDB):
    """Bramka zapisuje nowy wiersz przeglądu; test czyta go z `added`."""

    def __init__(self, locked_candidate: object) -> None:
        super().__init__(locked_candidate)
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


async def _review_of_new_source(
    monkeypatch: pytest.MonkeyPatch,
    *,
    observed: tuple[str, str],
    **gate_kwargs,
) -> tuple[object, AsyncMock]:
    async def no_review(*_args, **_kwargs):
        return None

    clear = AsyncMock(return_value={"cleared_fields": 0, "tombstoned_languages": 0})
    monkeypatch.setattr(quarantine, "get_identity_review", no_review)
    monkeypatch.setattr(quarantine, "_clear_quarantined_cv_projection", clear)
    monkeypatch.setattr(quarantine, "_purge_candidate_summary_cache", AsyncMock())
    monkeypatch.setattr(quarantine.candidate_audit, "record_candidate_audit", _noop)
    candidate = SimpleNamespace(id=11, name="Jan", lastname="Kowalski")

    review = await quarantine.record_detected_identity(
        _NewReviewDB(candidate),  # type: ignore[arg-type]
        candidate=candidate,  # type: ignore[arg-type]
        source_kind="document",
        source_id=22,
        observed_first_name=observed[0],
        observed_last_name=observed[1],
        provenance="cv_parser:document",
        **gate_kwargs,
    )
    return review, clear


@pytest.mark.asyncio
async def test_name_from_cv_header_alone_never_quarantines_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 05.11.2026: 9 z 9 przejrzanych plików to fałszywe alarmy, w 7 nazwa pasuje
    # do reguły nagłówka, a w 4 linia nie była nazwą osoby. Profil tracił fakty.
    review, clear = await _review_of_new_source(
        monkeypatch,
        observed=("Fikcyjny", "Inzynier"),
        observed_name_from_header=True,
    )

    assert review.decision == "inconclusive"
    assert review.is_quarantined is False
    assert review.evidence["observed_name_from_header"] is True
    clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_from_model_other_than_profile_still_quarantines_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review, clear = await _review_of_new_source(monkeypatch, observed=("Anna", "Nowak"))

    assert review.decision == "confirmed_mismatch"
    assert review.is_quarantined is True
    assert review.evidence["observed_name_from_header"] is False
    clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_name_from_cv_header_equal_to_profile_stays_a_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review, _ = await _review_of_new_source(
        monkeypatch,
        observed=("Jan", "Kowalski"),
        observed_name_from_header=True,
    )

    assert review.decision == "confirmed_match"


@pytest.mark.asyncio
@pytest.mark.parametrize("from_header", [False, True])
async def test_candidate_cv_routes_tell_the_gate_where_the_name_came_from(
    monkeypatch: pytest.MonkeyPatch, from_header: bool
) -> None:
    from app.api import candidates as candidates_api

    gate = AsyncMock(return_value=SimpleNamespace(is_quarantined=False))
    monkeypatch.setattr(candidates_api, "record_detected_identity", gate)
    parsed = {"first_name": "Fikcyjny", "last_name": "Inzynier"}
    if from_header:
        parsed["_name_from_header"] = True

    await candidates_api._parsed_source_is_quarantined(
        object(),  # type: ignore[arg-type]
        candidate=SimpleNamespace(id=11),  # type: ignore[arg-type]
        parsed=parsed,
        source_kind="document",
        source_id=22,
        provenance="cv_parser:document",
    )

    assert gate.await_args.kwargs["observed_name_from_header"] is from_header


@pytest.mark.asyncio
async def test_earlier_confirmed_mismatch_stays_when_reread_name_is_from_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        decision="confirmed_mismatch",
        provenance="cv_parser:document",
        override_at=None,
        is_quarantined=True,
    )

    async def fake_get(*_args, **_kwargs):
        return row

    monkeypatch.setattr(quarantine, "get_identity_review", fake_get)
    monkeypatch.setattr(quarantine, "_purge_candidate_summary_cache", AsyncMock())
    monkeypatch.setattr(quarantine, "_clear_quarantined_cv_projection", AsyncMock())
    candidate = SimpleNamespace(id=11, name="Jan", lastname="Kowalski")

    result = await quarantine.record_detected_identity(
        _FlushOnlyDB(candidate),  # type: ignore[arg-type]
        candidate=candidate,  # type: ignore[arg-type]
        source_kind="document",
        source_id=22,
        observed_first_name="Fikcyjny",
        observed_last_name="Inzynier",
        provenance="cv_parser:retry",
        observed_name_from_header=True,
    )

    assert result is row
    assert row.decision == "confirmed_mismatch"


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
        # Runda 9 (R9-N8-3): fakty z notatek i pochodzenie importu nie są z CV.
        "_notes_insights": {"rate": {"amount": 150}},
        "legacy_source": "tr_legacy",
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
        # Trzecie zapytanie: kopie CV etapu z tym plikiem (13.10.2026) — brak.
        language_batches=[[language], [], []],
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
        "_notes_insights": {"rate": {"amount": 150}},
        "legacy_source": "tr_legacy",
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


def _profile_with_cv_facts(**overrides) -> SimpleNamespace:
    """Profil z faktami z CV; `cv_filename` wskazuje już plik „nowe.pdf”."""
    fields = dict(
        id=11,
        cv_extracted_data={
            "skills": [{"name": "Python"}],
            "email": "osoba@example.com",
            "cv_highlights": {"source_document_id": None},
            "_manual_override_ai_summary": True,
        },
        raw_cv_text="tekst CV właściwej osoby",
        cv_filename="nowe.pdf",
        cv_parsed_at=datetime.now(timezone.utc),
        ai_summary="Podsumowanie rekrutera.",
        skills=[{"name": "Python"}],
        education=[],
        experience=[],
        years_it_experience=7,
        email="osoba@example.com",
        phone=None,
        city="Warszawa",
        country="PL",
        location="Warszawa, PL",
        linkedin=None,
        languages_version=1,
        languages=[],
        embedding_id="wektor-1",
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _fresh_upload() -> SimpleNamespace:
    return SimpleNamespace(
        id=22, filename="nowe.pdf", content_sha256="b" * 64, is_primary=True
    )


def _forbid_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(*_args, **_kwargs):
        pytest.fail("profil właściwej osoby nie może tracić faktów ani wektora")

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate", unexpected
    )
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding", unexpected
    )


def _assert_profile_untouched(candidate: SimpleNamespace, db: _ProjectionDB) -> None:
    assert candidate.raw_cv_text == "tekst CV właściwej osoby"
    assert candidate.ai_summary == "Podsumowanie rekrutera."
    assert candidate.skills == [{"name": "Python"}]
    assert candidate.years_it_experience == 7
    assert candidate.email == "osoba@example.com"
    assert candidate.cv_parsed_at is not None
    assert candidate.embedding_id == "wektor-1"
    assert db.added == []
    # Profil mówi rekruterowi, że wgrane CV nie zasiliło danych.
    assert candidate.cv_extracted_data["_identity_quarantine_source"] == {
        "kind": "document",
        "id": 22,
    }
    assert candidate.cv_extracted_data["skills"] == [{"name": "Python"}]


@pytest.mark.asyncio
async def test_quarantined_fresh_upload_hands_primary_back_and_keeps_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """12.10.2026: nowe CV jest domyślnie głównym, a bramka tożsamości biegnie w tle.

    Upload przejmuje flagę głównego CV i `cv_filename`, zanim odczyt dojdzie do
    bramki. Gdy plik okaże się CV innej osoby, profil dalej opisuje właściwą
    osobę z POPRZEDNIEGO CV — do tej poprawki kwarantanna brała zgodność nazwy
    pliku za dowód, że fakty pochodzą z nowego pliku, i kasowała tekst CV,
    podsumowanie i wektor, zostawiając kandydata bez głównego CV. Na produkcji
    91% profili nie ma zapisanego dokumentu źródłowego, więc decyduje jawna
    informacja z uploadu o tym, co plik zastąpił.
    """
    candidate = _profile_with_cv_facts()
    quarantined = _fresh_upload()
    previous = SimpleNamespace(id=21, filename="stare.pdf", is_primary=False)
    _forbid_invalidation(monkeypatch)
    db = _ProjectionDB(candidate, quarantined, previous)

    result = await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        replaced_primary=quarantine.ReplacedPrimaryCv(
            document_id=21, cv_filename="stare.pdf"
        ),
    )

    assert result == {"cleared_fields": 0, "tombstoned_languages": 0}
    assert quarantined.is_primary is False
    assert previous.is_primary is True
    # Zdjęcie flagi musi trafić do bazy przed nadaniem jej poprzedniemu plikowi
    # (unikalny indeks „jedno główne CV na kandydata”). Od 14.10.2026 kopia CV
    # etapu wypycha decyzję jeszcze raz przed wyborem następcy (audyt 13.10).
    assert db.flushes >= 1
    assert candidate.cv_filename == "stare.pdf"
    _assert_profile_untouched(candidate, db)


@pytest.mark.asyncio
async def test_quarantined_first_cv_document_keeps_facts_that_came_from_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profil ma dane z CV (import, stary odczyt), ale żadnego głównego dokumentu.

    Wgrany plik niczego jeszcze w profilu nie zapisał — odczyt biegnie po bramce
    tożsamości — więc brak zastąpionego dokumentu nie robi z niego źródła faktów.
    Na produkcji 12.10.2026 takich profili było 254.
    """
    candidate = _profile_with_cv_facts()
    quarantined = _fresh_upload()
    _forbid_invalidation(monkeypatch)
    db = _ProjectionDB(candidate, quarantined)

    result = await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        replaced_primary=quarantine.ReplacedPrimaryCv(
            document_id=None, cv_filename="z-importu.pdf"
        ),
    )

    assert result == {"cleared_fields": 0, "tombstoned_languages": 0}
    assert quarantined.is_primary is False
    assert candidate.cv_filename == "z-importu.pdf"
    _assert_profile_untouched(candidate, db)


@pytest.mark.asyncio
async def test_quarantined_upload_never_leaves_the_pointer_on_its_own_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Poprzednie CV zniknęło, a stary wskaźnik miał tę samą nazwę co nowy plik —
    kopia na dysku jest już nadpisana, więc wskaźnik nie może na nią wskazywać."""
    candidate = _profile_with_cv_facts()
    quarantined = _fresh_upload()
    _forbid_invalidation(monkeypatch)
    db = _ProjectionDB(candidate, quarantined, None)

    await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        replaced_primary=quarantine.ReplacedPrimaryCv(
            document_id=21, cv_filename="nowe.pdf"
        ),
    )

    assert quarantined.is_primary is False
    assert candidate.cv_filename is None
    assert candidate.raw_cv_text == "tekst CV właściwej osoby"


@pytest.mark.asyncio
async def test_reread_of_the_file_that_fed_the_profile_still_clears_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ponowny odczyt pliku, który od dawna jest głównym CV (żądanie niczego nie
    zastępowało): bez zapisanego pochodzenia zgodność nazwy dalej oznacza, że
    fakty pochodzą z tego pliku — po kwarantannie znikają jak dotąd."""

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )
    candidate = _profile_with_cv_facts(
        cv_extracted_data={
            "skills": [{"name": "Python"}],
            "email": "osoba@example.com",
        }
    )
    long_standing_primary = _fresh_upload()
    db = _ProjectionDB(candidate, long_standing_primary)

    await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
    )

    assert long_standing_primary.is_primary is False
    assert candidate.raw_cv_text is None
    assert candidate.cv_filename is None
    assert candidate.ai_summary is None
    assert candidate.skills == []
    assert candidate.email is None


@pytest.mark.asyncio
async def test_quarantine_clear_keeps_a_manually_written_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Podsumowanie poprawione ręcznie nie jest faktem z CV — czyszczenie
    profilu po kwarantannie go nie rusza (blokada z 12.10.2026)."""

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )
    candidate = _profile_with_cv_facts(
        cv_extracted_data={
            "cv_highlights": {"source_document_id": 22},
            "_manual_override_ai_summary": True,
        }
    )
    db = _ProjectionDB(candidate, _fresh_upload())

    await quarantine._clear_quarantined_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
    )

    assert candidate.raw_cv_text is None
    assert candidate.ai_summary == "Podsumowanie rekrutera."


@pytest.mark.asyncio
async def test_repair_clears_facts_read_from_a_foreign_document_but_not_the_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audyt 22.10.2026 (F114): skrypt naprawczy sam ustala, że profil czytano
    z cudzego dokumentu, i sam prowadzi wskaźnik pliku — czyszczenie zabiera
    fakty z CV, podsumowanie i wektor jak kwarantanna."""

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )
    candidate = _profile_with_cv_facts(
        cv_extracted_data={
            "cv_highlights": {"source_document_id": 22},
            "skills": [{"name": "Wrong Person Skill"}],
            "email": "own@example.com",
            "phone": "+48 600 000 000",
        }
    )
    candidate.skills = [{"name": "Wrong Person Skill"}]
    candidate.cv_filename = "own-next.pdf"
    candidate.email = "own@example.com"
    candidate.phone = "+48 600 000 000"
    candidate.embedding_id = "vec-11"
    db = _ProjectionDB(candidate, language_batches=[[]])
    db.execute = AsyncMock()

    result = await quarantine.clear_foreign_cv_projection(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        document_id=22,
        document_hash="a" * 64,
    )

    assert candidate.raw_cv_text is None
    assert candidate.ai_summary is None
    assert candidate.skills == []
    assert candidate.cv_filename == "own-next.pdf"
    # Odczyt mógł pochodzić z własnego załącznika osoby (#2449) — dane
    # kontaktowe zostają, decyzja dotyczy tekstu, umiejętności, podsumowania
    # i wektora.
    assert candidate.email == "own@example.com"
    assert candidate.phone == "+48 600 000 000"
    assert candidate.embedding_id is None
    assert isinstance(db.added[0], IndexOutboxEvent)
    assert db.added[0].operation == "delete"
    db.execute.assert_awaited_once()  # podsumowanie aktywności wyczyszczone
    assert result["cleared_fields"] >= 3


@pytest.mark.parametrize(
    ("candidate", "observed"),
    [
        # Traffit dzielił nazwę po pierwszej spacji, model po sensie (pomiar
        # 05.11.2026: 280 z 608 sprzeczności to te same słowa w innym podziale).
        (("Jan", "Adam Testowy"), ("Jan Adam", "Testowy")),
        (("Anna Maria", "Przykladowa Testowa"), ("Anna", "Przykladowa")),
        # Literówka i transliteracja jednej części: ta sama klasa co częściowa
        # niezgodność, a nie dowód cudzego pliku.
        (("Oleksandr", "Fikcyjnenko"), ("Aleksandr", "Fikcyjnienko")),
        (("Katarzyna", "Przykladowska"), ("Kasia", "Przykladowski")),
    ],
)
def test_other_form_of_the_same_name_is_not_a_confirmed_mismatch(
    candidate: tuple[str, str], observed: tuple[str, str]
) -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name=candidate[0],
        candidate_last_name=candidate[1],
        observed_first_name=observed[0],
        observed_last_name=observed[1],
    )

    assert result.decision == "inconclusive"


def test_a_different_person_with_a_double_name_is_still_a_mismatch() -> None:
    result = quarantine.evaluate_identity_match(
        candidate_first_name="Jan Adam",
        candidate_last_name="Testowy",
        observed_first_name="Maria Ewa",
        observed_last_name="Fikcyjna-Bak",
    )

    assert result.decision == "confirmed_mismatch"


def _silence_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", noop)
    monkeypatch.setattr(
        "app.services.embedding_service.delete_candidate_embedding",
        AsyncMock(return_value=True),
    )


async def _clear_projection_of(candidate: SimpleNamespace) -> None:
    await quarantine._clear_cv_projection(
        _ProjectionDB(language_batches=[[]]),  # type: ignore[arg-type]
        candidate=candidate,
        extracted=dict(candidate.cv_extracted_data),
        source_kind="document",
        source_id=22,
        document_filename=None,
        document_hash=None,
    )


@pytest.mark.parametrize(
    "parsed_skills",
    [
        ["Python", "SQL"],
        [{"name": "Python", "level": "SENIOR"}, {"name": " SQL "}],
        '["Python", "SQL"]',
        {"level": "senior", "technologies": ["Python", "SQL"]},
    ],
)
@pytest.mark.asyncio
async def test_clear_removes_skills_the_enrichment_normalized(
    monkeypatch: pytest.MonkeyPatch, parsed_skills
) -> None:
    """Kolumna ma `normalize_llm_skills(x.skills)`, a odczyt zostaje surowy.

    Profil 80774 (05.11.2026): `skills == x.skills` fałsz, `skills ==
    normalize_llm_skills(x.skills)` prawda, 8 z 8 nazw wspólnych. Porównanie
    z surowym odczytem zostawiało umiejętności innej osoby.
    """
    _silence_invalidation(monkeypatch)
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"skills": parsed_skills},
        skills=normalize_llm_skills(parsed_skills),
    )

    await _clear_projection_of(candidate)

    assert candidate.skills == []


@pytest.mark.asyncio
async def test_clear_keeps_skills_appended_from_notes_after_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Odczyt notatek dopisuje na końcu kolumny (`existing + new_items`), więc
    początek listy to odczyt CV, a dopisek pochodzi od rekrutera."""
    _silence_invalidation(monkeypatch)
    from_notes = {"name": "Z notatki", "level": None}
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"skills": ["Python", "SQL"]},
        skills=[*normalize_llm_skills(["Python", "SQL"]), from_notes],
    )

    await _clear_projection_of(candidate)

    assert candidate.skills == [from_notes]


@pytest.mark.asyncio
async def test_clear_leaves_skills_that_did_not_come_from_this_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ta sama nazwa w innej kolejności nie dowodzi pochodzenia: FILL_EMPTY nie
    nadpisuje kolumny, więc lista mogła istnieć przed odczytem."""
    _silence_invalidation(monkeypatch)
    own_skills = [
        {"name": "SQL", "level": None},
        {"name": "Python", "level": None},
        {"name": "Java", "level": None},
    ]
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"skills": ["Python", "SQL"]},
        skills=own_skills,
    )

    await _clear_projection_of(candidate)

    assert candidate.skills == own_skills


@pytest.mark.parametrize(
    "lock",
    [
        {"cv_extracted_data": {"_manual_override_skills": True}},
        {"skills_manually_curated": True},
    ],
)
@pytest.mark.asyncio
async def test_clear_respects_manual_skill_locks(
    monkeypatch: pytest.MonkeyPatch, lock: dict
) -> None:
    """Obie blokady są tak samo wiążące jak w `_apply_cv_enrichment`."""
    _silence_invalidation(monkeypatch)
    skills = normalize_llm_skills(["Python"])
    extracted = {"skills": ["Python"], **lock.get("cv_extracted_data", {})}
    candidate = _profile_with_cv_facts(cv_extracted_data=extracted, skills=skills)
    if "skills_manually_curated" in lock:
        candidate.skills_manually_curated = True

    await _clear_projection_of(candidate)

    assert candidate.skills == skills


@pytest.mark.asyncio
async def test_clear_respects_manual_education_and_years_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _silence_invalidation(monkeypatch)
    education = [{"school": "Poprawiona ręcznie"}]
    candidate = _profile_with_cv_facts(
        cv_extracted_data={
            "education": education,
            "years_it_experience": 7,
            "_manual_override_education": True,
            "_manual_override_years_it_experience": True,
        },
        education=education,
        years_it_experience=7,
    )

    await _clear_projection_of(candidate)

    assert candidate.education == education
    assert candidate.years_it_experience == 7


@pytest.mark.asyncio
async def test_clear_removes_education_and_years_written_unchanged_by_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_apply_cv_enrichment` zapisuje oba pola bez zmian, więc tu wystarcza
    równość z odczytem; test pilnuje, że ten kontrakt się nie rozjedzie."""
    _silence_invalidation(monkeypatch)
    parsed = {"education": [{"school": "Obca"}], "years_it_experience": 9}
    candidate = _profile_with_cv_facts(
        cv_extracted_data={},
        education=[],
        skills=[],
        years_it_experience=None,
        experience=[],
    )
    _apply_cv_enrichment(candidate, parsed)
    assert candidate.education == parsed["education"]
    assert candidate.years_it_experience == 9

    await _clear_projection_of(candidate)

    assert candidate.education == []
    assert candidate.years_it_experience is None


@pytest.mark.asyncio
async def test_clear_removes_linkedin_and_email_in_the_written_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LinkedIn trafia do kolumny po `normalize_linkedin_url`, a e-mail małymi
    literami: to ten sam rozjazd zapisu i porównania co przy umiejętnościach."""
    _silence_invalidation(monkeypatch)
    url = "http://www.linkedin.com/in/obca-osoba/?trk=abc"
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"linkedin_url": url, "email": " Obca@Example.com "},
        linkedin=normalize_linkedin_url(url),
        email="obca@example.com",
    )
    assert candidate.linkedin != url

    await _clear_projection_of(candidate)

    assert candidate.linkedin is None
    assert candidate.email is None


def _foreign_side_file() -> SimpleNamespace:
    return SimpleNamespace(
        id=22,
        filename="inny.pdf",
        storage_key="klucz",
        content_sha256="c" * 64,
        is_primary=False,
    )


async def _human_marks_side_file(
    monkeypatch: pytest.MonkeyPatch, candidate: SimpleNamespace, file_text: str
) -> None:
    document = _foreign_side_file()
    monkeypatch.setattr(
        "app.services.object_storage.download_cv", lambda _key: b"bajty"
    )
    monkeypatch.setattr(
        "app.services.cv_backfill._extract_text_from_bytes",
        AsyncMock(return_value=file_text),
    )
    db = _ProjectionDB(document, candidate.raw_cv_text, None, candidate, document)
    db.execute = AsyncMock()
    await quarantine.mark_confirmed_mismatch(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        actor_id=7,
        provenance="test",
    )


@pytest.mark.asyncio
async def test_human_mark_clears_facts_when_profile_text_comes_from_a_side_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile 6502 i 80774 (05.11.2026): plik nie był główny, odczyt nie miał
    `source_document_id`, a tekst CV w profilu był tekstem tego pliku. Bez tego
    dowodu oznaczenie cudzego pliku zostawiało w profilu wszystkie fakty."""
    _silence_invalidation(monkeypatch)
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"skills": ["Python"], "cv_highlights": {}},
        raw_cv_text="Tekst CV  innej\nosoby",
        skills=normalize_llm_skills(["Python"]),
    )

    await _human_marks_side_file(monkeypatch, candidate, "tekst cv innej osoby")

    assert candidate.raw_cv_text is None
    assert candidate.skills == []


@pytest.mark.asyncio
async def test_human_mark_keeps_profile_when_its_text_comes_from_another_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_invalidation(monkeypatch)
    skills = normalize_llm_skills(["Python"])
    candidate = _profile_with_cv_facts(
        cv_extracted_data={"skills": ["Python"], "cv_highlights": {}},
        skills=skills,
    )

    await _human_marks_side_file(monkeypatch, candidate, "zupełnie inny tekst")

    assert candidate.raw_cv_text == "tekst CV właściwej osoby"
    assert candidate.skills == skills


@pytest.mark.asyncio
async def test_unreadable_file_does_not_block_the_human_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Awaria magazynu nie jest dowodem pochodzenia ani powodem, by nie zapisać
    decyzji człowieka: plik trafia do kwarantanny, a fakty zostają."""
    _forbid_invalidation(monkeypatch)

    def broken(_key: str) -> bytes:
        raise OSError("magazyn niedostępny")

    candidate = _profile_with_cv_facts(cv_extracted_data={"cv_highlights": {}})
    document = _foreign_side_file()
    monkeypatch.setattr("app.services.object_storage.download_cv", broken)
    db = _ProjectionDB(document, candidate.raw_cv_text, None, candidate, document)
    db.execute = AsyncMock()

    row = await quarantine.mark_confirmed_mismatch(
        db,  # type: ignore[arg-type]
        candidate_id=11,
        source_kind="document",
        source_id=22,
        actor_id=7,
        provenance="test",
    )

    assert row.decision == "confirmed_mismatch"
    assert candidate.raw_cv_text == "tekst CV właściwej osoby"
