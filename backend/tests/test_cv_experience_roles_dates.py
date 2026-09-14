"""UAT M01-B05: doświadczenie z CV ze stanowiskami i datami.

Odczyt CV zapisywał wyłącznie nazwy firm (`role`/`start`/`end` = null), a
`end = null` to kanoniczny znacznik bieżącej pracy — każda firma z CV, także
zakończona lata temu, trafiała w filtr „Obecna firma”.
"""

from __future__ import annotations

from app.models.candidate import Candidate
from app.services.candidate_quick_view import format_cv_highlight_bullets
from app.services.cv_enrichment import (
    CvWritePolicy,
    _apply_cv_enrichment,
    cv_experience_entries,
)
from app.services.cv_parser import _normalize_cv_output
from app.services.experience_end import is_current_end


def _candidate(**kw) -> Candidate:
    return Candidate(
        id=1,
        name="Jan",
        lastname="Testowy",
        experience=kw.get("experience", []),
        cv_extracted_data=kw.get("cv_extracted_data", {}),
    )


def test_parser_normalizes_experience_dates_and_drops_garbage():
    out = _normalize_cv_output(
        {
            "experience": [
                {
                    "company": "Firma Testowa Iota",
                    "role": "Data Engineer",
                    "start": "07.2023",
                    "end": "obecnie",
                },
                {
                    "company": "Firma Testowa Delta",
                    "role": "Backend Developer",
                    "start": "2019-3",
                    "end": "06/2023",
                },
                {"company": "Firma Testowa Kappa", "start": "kiedyś", "end": "2018"},
                {
                    "company": "Firma Testowa Lambda",
                    "start": "2015",
                    "end": "Dec  2016",
                },
                {"company": "", "role": ""},
                "nie-słownik",
            ]
        }
    )
    assert out["experience"] == [
        {
            "company": "Firma Testowa Iota",
            "role": "Data Engineer",
            "start": "2023-07",
            "end": "present",
        },
        {
            "company": "Firma Testowa Delta",
            "role": "Backend Developer",
            "start": "2019-03",
            "end": "2023-06",
        },
        {"company": "Firma Testowa Kappa", "role": None, "start": None, "end": "2018"},
        # Nieczytelny koniec zostaje tekstem z CV — `None` znaczyłoby „obecnie”.
        {
            "company": "Firma Testowa Lambda",
            "role": None,
            "start": "2015",
            "end": "Dec 2016",
        },
    ]
    assert _normalize_cv_output({})["experience"] == []


def test_enrichment_writes_roles_and_dates_and_only_ongoing_job_is_current():
    c = _candidate()
    parsed = _normalize_cv_output(
        {
            "companies": ["Firma Testowa Iota", "Firma Testowa Delta"],
            "experience": [
                {
                    "company": "Firma Testowa Iota",
                    "role": "Data Engineer",
                    "start": "2023-07",
                    "end": "present",
                },
                {
                    "company": "Firma Testowa Delta",
                    "role": "Backend Developer",
                    "start": "2019-03",
                    "end": "2023-06",
                },
            ],
        }
    )
    written = _apply_cv_enrichment(c, parsed, policy=CvWritePolicy.REFRESH)

    assert written == 2
    assert c.experience[0]["role"] == "Data Engineer"
    assert c.experience[0]["start"] == "2023-07"
    assert c.experience[0]["end"] == "present"
    assert c.experience[1]["end"] == "2023-06"
    current = [e["company"] for e in c.experience if is_current_end(e["end"])]
    assert current == ["Firma Testowa Iota"]


def test_flat_company_list_is_still_used_for_older_parses():
    parsed = {"companies": ["Firma Testowa Alfa"]}
    assert cv_experience_entries(parsed) == [
        {
            "company": "Firma Testowa Alfa",
            "role": None,
            "start": None,
            "end": None,
            "desc": None,
        }
    ]


def test_rich_cv_experience_replaces_existing_only_on_refresh():
    existing = [
        {"company": "Stara Firma", "role": "Tester", "start": None, "end": None}
    ]
    parsed = {
        "experience": [
            {"company": "Nowa Firma", "role": "QA Lead", "start": "2020", "end": None}
        ]
    }
    kept = _candidate(experience=list(existing))
    _apply_cv_enrichment(kept, parsed)  # FILL_EMPTY
    assert kept.experience == existing

    refreshed = _candidate(experience=list(existing))
    _apply_cv_enrichment(refreshed, parsed, policy=CvWritePolicy.REFRESH)
    assert refreshed.experience[0]["company"] == "Nowa Firma"

    # Płaska lista firm nigdy nie zastępuje stanowisk, nawet przy REFRESH.
    flat = _candidate(experience=list(existing))
    _apply_cv_enrichment(
        flat, {"companies": ["Nowa Firma"]}, policy=CvWritePolicy.REFRESH
    )
    assert flat.experience == existing


def test_current_role_start_label_uses_polish_month_order():
    bullets = format_cv_highlight_bullets(
        {"current_role": "Data Engineer", "current_role_started_at": "2023-07"}
    )
    assert "Aktualna rola: Data Engineer, od 07.2023." in bullets
    bullets = format_cv_highlight_bullets(
        {"current_role": "Data Engineer", "current_role_started_at": "2023-07-15"}
    )
    assert "Aktualna rola: Data Engineer, od 15.07.2023." in bullets


def test_cv_refresh_does_not_replace_imported_history_with_descriptions():
    """Historia z importu niesie opisy stanowisk (tekst kanoniczny, embeddingi,
    CV HTML). Odczyt CV bez opisów nie może jej skasować przy „użyj tego CV”."""
    existing = [
        {
            "company": "Firma Testowa Omega",
            "role": "Architect",
            "start": "2018-01",
            "end": None,
            "desc": "Projektowanie systemów rozliczeniowych.",
        },
        {
            "company": "Firma Testowa Sigma",
            "role": "Developer",
            "start": "2012-01",
            "end": "2017-12",
            "desc": "Rozwój aplikacji.",
        },
    ]
    parsed = {
        "experience": [
            {"company": "Firma Testowa Omega", "role": "Architect", "start": "2018"}
        ]
    }
    candidate = _candidate(experience=[dict(e) for e in existing])
    _apply_cv_enrichment(candidate, parsed, policy=CvWritePolicy.REFRESH)
    assert candidate.experience == existing


def test_unreadable_end_date_does_not_make_a_past_job_current():
    parsed = _normalize_cv_output(
        {
            "experience": [
                {"company": "Firma Testowa Nowa", "role": "Lead", "end": "obecnie"},
                {
                    "company": "Firma Testowa Stara",
                    "role": "Dev",
                    "end": "grudzień 2022",
                },
            ]
        }
    )
    current = [
        e["company"] for e in cv_experience_entries(parsed) if is_current_end(e["end"])
    ]
    assert current == ["Firma Testowa Nowa"]
