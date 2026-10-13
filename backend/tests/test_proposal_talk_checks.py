"""Karta propozycji: „Sprawdzone w CV” i „Zapytaj w rozmowie” (D5, 13.10.2026).

Czyste testy, bez bazy:

* propozycja z nowego CV nie pokazuje „✕ niespełnione” przy wymaganiu, którego
  nie znaleźliśmy — brak w liście umiejętności to nie dowód (B3);
* krytyczna fraza Delivery Leada, której słów bramka szuka, nie trafia na listę
  „nieszukanych” (B4);
* `proposal-counts` niesie listę do rozmowy: sekcja 4, język i must spoza bramki.
"""

from types import SimpleNamespace

from app.api.job_proposals import _talk_checks
from app.api.search import _non_technology_must
from app.services.auto_match_service import Scored, _requirement_statuses
from app.services.job_proposals import sanitize_evidence


def _scored(matching, gap) -> Scored:
    fields = Scored.__dataclass_fields__
    values = {name: None for name in fields}
    values.update(matching_must=tuple(matching), gap_must=tuple(gap))
    return Scored(**values)


def test_new_cv_evidence_has_no_not_met_status():
    rows = _requirement_statuses(_scored(["Java"], ["doświadczenie w przetargach"]))
    assert rows == [
        {"name": "Java", "level": "must", "status": "met"},
        {"name": "doświadczenie w przetargach", "level": "must", "status": "unknown"},
    ]
    # Przechodzi allowlistę dowodów bez zmian.
    assert sanitize_evidence({"requirements": rows})["requirements"] == rows


def test_critical_phrase_with_row_words_is_not_listed_as_unsearched():
    breakdowns = {"job": {"matching_must": ["architektura chmury", "Java"]}}
    assert _non_technology_must(breakdowns) == ["architektura chmury"]
    options = {"architektura chmury": ("architektura chmury",)}
    assert _non_technology_must(breakdowns, options) == []


def test_talk_checks_join_experience_language_and_unsearched_must():
    job = SimpleNamespace(
        champion_profile={
            "basics": {"language": "angielski B2"},
            "experience": {
                "domains": [{"name": "sektor publiczny"}],
                "skills": [{"name": "doświadczenie w przetargach"}],
            },
        }
    )
    checks = _talk_checks(job, ["Praca w zespole", "doświadczenie w przetargach"])
    assert checks == [
        {"label": "sektor publiczny", "kind": "domains"},
        {"label": "doświadczenie w przetargach", "kind": "skills"},
        {"label": "angielski B2", "kind": "language"},
        {"label": "Praca w zespole", "kind": "must"},
    ]


def test_talk_checks_of_an_empty_profile_are_empty():
    assert _talk_checks(SimpleNamespace(champion_profile=None), []) == []
