from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import app.models  # noqa: F401
import pytest

from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage
from app.schemas.candidate_profile_facts import CandidateLanguagesPut
from app.services.candidate_language_writer import (
    merge_automated_languages,
    normalize_language_payload,
    sync_candidate_languages_from_source,
)


def _row(
    code: str,
    *,
    provenance: str = "cv",
    manual_lock: bool = False,
    deleted: bool = False,
) -> CandidateLanguage:
    return CandidateLanguage(
        id=1,
        candidate_id=7,
        language_code=code,
        language_name=code.upper(),
        cefr_level="B1",
        is_native=False,
        is_level_unknown=False,
        provenance=provenance,
        manual_lock=manual_lock,
        version=1,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )


def test_normalizer_supports_source_shapes_without_guessing_descriptive_cefr():
    facts, invalid = normalize_language_payload(
        [
            {"name": "English", "level": "C1"},
            {"lang": "Polski", "level": "ojczysty"},
            {"code": "DE", "name": "German", "level": "advanced"},
            "French - B2; Spanish fluent",
        ]
    )

    assert invalid == 0
    by_code = {fact.language_code: fact for fact in facts}
    assert by_code["en"].cefr_level == "C1"
    assert by_code["pl"].is_native is True
    assert by_code["de"].is_level_unknown is True
    assert by_code["fr"].cefr_level == "B2"
    assert by_code["es"].is_level_unknown is True


def test_normalizer_counts_malformed_source_entries():
    facts, invalid = normalize_language_payload(
        [{"name": ""}, 123, {"name": "English", "level": "B2"}]
    )

    assert [fact.language_code for fact in facts] == ["en"]
    assert invalid == 2


def test_normalizer_accepts_sixteen_character_language_code():
    code = "a123456789012345"

    facts, invalid = normalize_language_payload(
        [{"code": code, "name": "Constructed language"}]
    )

    assert invalid == 0
    assert [fact.language_code for fact in facts] == [code]


def test_automated_normalizer_deduplicates_transliterated_display_names():
    facts, invalid = normalize_language_payload(
        [
            {"code": "x-lodz", "name": "Język łódzki", "level": "B1"},
            {"code": "x-alt", "name": "JEZYK LODZKI", "level": "C1"},
        ]
    )

    assert invalid == 0
    assert len(facts) == 1
    assert facts[0].language_code == "x-alt"
    assert facts[0].cefr_level == "C1"


def test_put_rejects_duplicate_names_after_whitespace_case_and_transliteration():
    with pytest.raises(ValueError, match="language_name must be unique"):
        CandidateLanguagesPut.model_validate(
            {
                "languages": [
                    {
                        "language_code": "pl",
                        "language_name": "  Język   łódzki ",
                        "is_level_unknown": True,
                    },
                    {
                        "language_code": "x-lodz",
                        "language_name": "JEZYK LODZKI",
                        "is_level_unknown": True,
                    },
                ]
            }
        )


def test_put_keeps_distinct_languages_with_different_normalized_names():
    payload = CandidateLanguagesPut.model_validate(
        {
            "languages": [
                {
                    "language_code": "nb",
                    "language_name": "Norwegian Bokmål",
                    "is_level_unknown": True,
                },
                {
                    "language_code": "nn",
                    "language_name": "Norwegian Nynorsk",
                    "is_level_unknown": True,
                },
            ]
        }
    )

    assert [language.language_code for language in payload.languages] == ["nb", "nn"]


def test_automated_writer_never_overwrites_manual_or_resurrects_tombstone():
    manual = _row("en", manual_lock=True)
    tombstone = _row("de", manual_lock=True, deleted=True)
    incoming, _ = normalize_language_payload(
        [
            {"code": "EN", "name": "English", "level": "C2"},
            {"code": "DE", "name": "German", "level": "C2"},
            {"code": "PL", "name": "Polish", "level": "native"},
        ]
    )

    rows, result = merge_automated_languages(
        candidate_id=7,
        existing_rows=[manual, tombstone],
        incoming=incoming,
        provenance="cv",
        source_ref="cv:123",
        replace_source_snapshot=True,
    )

    assert manual.cefr_level == "B1"
    assert tombstone.deleted_at is not None
    assert result.protected_manual == 1
    assert result.protected_tombstone == 1
    assert result.inserted == 1
    assert {row.language_code for row in rows} == {"en", "de", "pl"}


def test_complete_snapshot_only_tombstones_its_own_unlocked_source():
    cv_fact = _row("en", provenance="cv")
    traffit_fact = _row("de", provenance="traffit")

    _, result = merge_automated_languages(
        candidate_id=7,
        existing_rows=[cv_fact, traffit_fact],
        incoming=[],
        provenance="cv",
        source_ref="cv:new",
        replace_source_snapshot=True,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert cv_fact.deleted_at is not None
    assert traffit_fact.deleted_at is None
    assert result.tombstoned == 1


@pytest.mark.asyncio
async def test_db_writer_updates_only_compatibility_projection_and_version():
    candidate = Candidate(
        id=7,
        name="Jan",
        lastname="Nowak",
        languages=[],
        languages_version=3,
    )
    db = Mock()
    db.scalar = AsyncMock(return_value=candidate)
    scalar_result = Mock()
    scalar_result.all.return_value = []
    db.scalars = AsyncMock(return_value=scalar_result)
    db.flush = AsyncMock()

    result = await sync_candidate_languages_from_source(
        db,
        candidate_id=7,
        raw_languages=[{"code": "EN", "name": "English", "level": "B2"}],
        provenance="cv",
        source_ref="cv:one",
    )

    assert result.inserted == 1
    assert candidate.languages == [{"code": "EN", "lang": "English", "level": "B2"}]
    assert candidate.languages_version == 4
    candidate_stmt = db.scalar.await_args.args[0]
    assert candidate_stmt.get_execution_options()["populate_existing"] is True
    assert candidate_stmt._for_update_arg is not None
    db.add.assert_called_once()
    db.flush.assert_awaited_once()
