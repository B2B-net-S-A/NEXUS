"""Chipy ✓/✗ na `/ai-matches` muszą czytać tę samą regułę skilli co ranking.

Wiersz jest rankowany przez Qdranta po `_build_candidate_text` (raw CV,
`verified_tech`, doświadczenie, tagi), a chipy pod nim czytały WYŁĄCZNIE
kolumnę `candidate.skills`. Ta kolumna jest pusta dla 49 440 z 49 802
kandydatów na produkcji, więc najlepszy kandydat w rankingu renderował się
cały na czerwono pod wynikiem 0.94 — rekruter czyta chipy, nie wektor,
i pomijał go.

Regresja tutaj jest CICHA (zła lista, nie błąd), więc test sprawdza wynik
`_build_match_info`, a nie to, którą funkcję woła.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.matching import _build_match_info
from app.services import scoring_service


def _candidate(**overrides) -> SimpleNamespace:
    base = dict(
        id=1,
        name="Jan",
        lastname="Kowalski",
        email="jan@example.com",
        phone=None,
        location=None,
        status=None,
        competence_category=None,
        tags=None,
        skills=None,
        verified_tech=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        ai_summary=None,
        avatar_url=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.unit
class TestSkillSources:
    def test_traffit_technologie_counts_as_matching_skill(self) -> None:
        """Kształt produkcyjny: `skills` pusty, technologie w `cv_extracted_data`."""
        cand = _candidate(
            skills=None,
            cv_extracted_data={"traffit_technologie": "Java, Spring Boot, Kafka"},
        )
        info = _build_match_info(cand, ["java", "spring boot"])
        assert info["gaps"] == [], "wymagania obecne w CV pokazane jako braki"
        assert info["matching_skills"] == ["java", "spring boot"]

    def test_missing_skill_is_still_a_gap(self) -> None:
        """Fallbacki mogą DODAWAĆ skille, nigdy nie mogą zmyślać zielonego ✓."""
        cand = _candidate(cv_extracted_data={"traffit_technologie": "Java"})
        info = _build_match_info(cand, ["java", "rust"])
        assert info["matching_skills"] == ["java"]
        assert info["gaps"] == ["rust"]

    def test_structured_skills_still_work(self) -> None:
        cand = _candidate(skills=[{"name": "Python"}, {"name": "FastAPI"}])
        info = _build_match_info(cand, ["python", "fastapi"])
        assert info["gaps"] == []

    def test_json_encoded_skills_column_still_works(self) -> None:
        """Kolumna bywa JSON-em w stringu — naiwny split dawał tokeny `["java`."""
        cand = _candidate(skills='["Java", "Spring Boot"]')
        info = _build_match_info(cand, ["java", "spring boot"])
        assert info["gaps"] == []

    def test_alias_family_from_taxonomy_is_honoured(self, monkeypatch) -> None:
        """`MSSQL` = `SQL Server` — rodziny z bazy, nie dwie pary w tym module."""
        monkeypatch.setattr(
            scoring_service,
            "ALIAS_MAP",
            {"mssql": "sql server", "sql server": "sql server"},
        )
        cand = _candidate(skills=[{"name": "MSSQL"}])
        info = _build_match_info(cand, ["SQL Server"])
        assert info["gaps"] == [], "rodzina aliasów z taksonomii pokazana jako brak"
        # Etykieta zostaje TA z treści rekrutacji — obok stoi lista „Wymagane"
        # zbudowana z tych samych stringów.
        assert info["matching_skills"] == ["sql server"]

    def test_score_fallback_uses_the_same_skill_set(self) -> None:
        """Bez wyniku z Qdranta score to pokrycie wymagań — z tego samego zbioru.

        To jest druga, ostrzejsza twarz tego defektu: w gałęzi tag-fallback
        pusta kolumna `skills` dawała 0.0 CAŁEJ puli, próg odsiewał wszystkich
        i awaria Qdranta renderowała się jako „Brak pasujących kandydatów".
        """
        cand = _candidate(
            cv_extracted_data={"traffit_technologie": "Java, Spring Boot"}
        )
        info = _build_match_info(cand, ["java", "spring boot"], score=None)
        assert info["match_score"] == 1.0

    def test_duplicate_requirements_do_not_skew_the_score(self) -> None:
        cand = _candidate(cv_extracted_data={"traffit_technologie": "Java"})
        info = _build_match_info(cand, ["Java", "java", "JAVA"], score=None)
        assert info["match_score"] == 1.0
        assert info["matching_skills"] == ["java"]
