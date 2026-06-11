"""Unit tests for skill matching helpers (app.api.matching).

Regression for the case where Traffit-imported candidates store ``skills`` as a
JSON-encoded string (``'["Java", "Spring Boot"]'``) instead of a real array. The
old comma-split produced broken tokens (``["java``) so a candidate who clearly
listed the required skills still showed every requirement as a red ✗ gap.
"""

from __future__ import annotations

import pytest

from app.api.matching import (
    _candidate_has_skill,
    _extract_skills,
)


@pytest.mark.unit
class TestExtractSkills:
    def test_json_encoded_string_is_parsed(self) -> None:
        raw = '["Java", "Spring Boot", "Hibernate", "Oracle", "Kafka"]'
        assert _extract_skills(raw) == [
            "java",
            "spring boot",
            "hibernate",
            "oracle",
            "kafka",
        ]

    def test_real_list_still_works(self) -> None:
        assert _extract_skills(["Java", "Python"]) == ["java", "python"]

    def test_list_of_dicts(self) -> None:
        assert _extract_skills([{"name": "Java"}, {"name": "Go"}]) == ["java", "go"]

    def test_plain_comma_string(self) -> None:
        assert _extract_skills("Java, Python") == ["java", "python"]

    def test_empty(self) -> None:
        assert _extract_skills(None) == []
        assert _extract_skills([]) == []


@pytest.mark.unit
class TestCandidateHasSkill:
    def test_konrad_stringified_skills_all_match(self) -> None:
        # Real production shape: skills column holds a JSON string.
        raw = '["Java", "Spring", "Spring Boot", "Kafka", "Oracle", "Postgres", "Hibernate"]'
        skills = set(_extract_skills(raw))
        required = ["java", "spring boot", "hibernate", "postgresql", "oracle", "kafka"]
        gaps = [r for r in required if not _candidate_has_skill(r, skills)]
        assert gaps == []

    def test_postgres_variant_matches_postgresql(self) -> None:
        assert _candidate_has_skill("postgresql", {"postgres"})
        assert _candidate_has_skill("postgres", {"postgresql"})

    def test_nodejs_variant_matches(self) -> None:
        assert _candidate_has_skill("node.js", {"nodejs"})

    def test_genuinely_missing_skill_is_gap(self) -> None:
        assert not _candidate_has_skill("rust", {"java", "kafka"})
