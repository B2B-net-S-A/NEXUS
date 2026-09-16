"""Backfill dat w `experience` z tekstu CV.

Trzy rzeczy, które ten plik przybija:

* prompt prosi WYŁĄCZNIE o historię zatrudnienia (to jest cała oszczędność
  wobec pełnego odczytu), a masowy prompt Fali 3 zostaje bez `experience`;
* definicja „wpis z datą" jest jedna dla scope'u SQL i dla Pythona — rozjazd
  = płacenie za wiersze, których bieg nie zapisze, albo wieczna pętla;
* scalanie: odczyt z datami wchodzi w całości, stare firmy nieobecne w
  odczycie zostają bez dat, a firma obecna w obu nie jest dublowana.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.candidate import Candidate
from app.services.experience_backfill import (
    MAX_KEPT_UNDATED,
    NO_RESULT_KEY,
    _scope_filter,
    entry_is_dated,
    merge_experience,
    needs_dates,
)
from app.services.llm_prompts import CV_ENRICHMENT_BULK, CV_EXPERIENCE_DATES


def test_prompt_asks_only_for_experience():
    rendered = CV_EXPERIENCE_DATES.render(cv_text="x")
    assert '"experience"' in rendered
    assert '"present"' in rendered
    for field in ("skills", "city", "years_it_experience", "education", "email"):
        assert f'"{field}"' not in rendered, field
    # Fala 3 świadomie bez `experience` — ten bieg jej nie zmienia.
    assert '"experience"' not in CV_ENRICHMENT_BULK.render(cv_text="x")


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"company": "Sii", "start": None, "end": None}, False),
        ({"company": "Sii", "start": "", "end": ""}, False),
        ({"company": "Sii", "start": None, "end": "present"}, False),
        ({"company": "Sii", "start": None, "end": " Obecnie "}, False),
        ({"company": "Sii", "start": "2020", "end": None}, True),
        ({"company": "Sii", "start": None, "end": "2021-06"}, True),
        ("not a dict", False),
    ],
)
def test_entry_is_dated(entry, expected):
    assert entry_is_dated(entry) is expected


def _candidate(experience, extracted=None):
    return SimpleNamespace(experience=experience, cv_extracted_data=extracted)


def test_needs_dates_mirrors_scope():
    assert needs_dates(_candidate([{"company": "Sii", "start": None, "end": None}]))
    assert needs_dates(_candidate([]))
    assert needs_dates(_candidate(None))
    assert not needs_dates(
        _candidate([{"company": "Sii", "start": "2020", "end": None}])
    )
    assert not needs_dates(
        _candidate([{"company": "Sii"}], {"_manual_override_experience": True})
    )
    assert not needs_dates(
        _candidate([{"company": "Sii"}], {NO_RESULT_KEY: "2026-09-16"})
    )


def test_scope_sql_compiles_and_excludes_dated_locked_and_marked():
    sql = str(
        select(Candidate.id)
        .where(*_scope_filter())
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "raw_cv_text IS NOT NULL" in sql
    assert "jsonb_array_elements" in sql
    assert "'present'" in sql and "'obecnie'" in sql
    assert "_manual_override_experience" in sql
    assert NO_RESULT_KEY in sql


class TestMergeExperience:
    OLD = [
        {"company": "Sii", "role": None, "start": None, "end": None, "desc": None},
        {"company": "Shoper", "role": None, "start": None, "end": None, "desc": None},
        {"company": "Nokia", "role": None, "start": None, "end": None, "desc": None},
    ]

    def test_no_dates_in_parse_returns_none(self):
        parsed = [{"company": "Shoper", "role": "Dev", "start": None, "end": None}]
        assert merge_experience(self.OLD, parsed) is None

    def test_dated_parse_leads_and_old_companies_follow_undated(self):
        parsed = [
            {
                "company": "Shoper S.A.",
                "role": "Dev",
                "start": "2022-01",
                "end": "present",
            },
            {"company": "Nokia", "role": "Tester", "start": "2019", "end": "2021"},
        ]
        merged = merge_experience(self.OLD, parsed)
        assert [e["company"] for e in merged] == [
            "Shoper S.A.",
            "Nokia",
            "Sii",
            "Shoper",
        ]
        assert merged[0]["start"] == "2022-01" and merged[0]["end"] == "present"
        assert merged[1]["end"] == "2021"
        # Stare firmy — bez dat, bez wymyślania.
        assert merged[2] == {
            "company": "Sii",
            "role": None,
            "start": None,
            "end": None,
            "desc": None,
        }

    def test_old_company_present_in_parse_is_not_duplicated(self):
        parsed = [{"company": "nokia", "role": "Dev", "start": "2019", "end": "2021"}]
        merged = merge_experience(self.OLD, parsed)
        assert [e["company"] for e in merged] == ["nokia", "Sii", "Shoper"]

    def test_kept_undated_is_capped(self):
        old = [{"company": f"Firma {i}"} for i in range(MAX_KEPT_UNDATED + 10)]
        parsed = [{"company": "Nowa", "role": "Dev", "start": "2020", "end": None}]
        merged = merge_experience(old, parsed)
        assert len(merged) == 1 + MAX_KEPT_UNDATED

    def test_garbage_existing_is_ignored(self):
        parsed = [{"company": "Nowa", "role": "Dev", "start": "2020", "end": None}]
        assert merge_experience("not a list", parsed)[0]["company"] == "Nowa"
        assert merge_experience([None, 3, "x"], parsed)[0]["company"] == "Nowa"
