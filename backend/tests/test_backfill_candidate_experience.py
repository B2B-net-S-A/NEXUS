"""Testy parserów `backfill_candidate_experience.py`.

Pure-Python — bez DB. Trzymane tutaj a nie w `scripts/tests/`, żeby trafić
do tego samego pytest-test job-a co reszta backendu.

Sprawdzamy że parsery:

* poprawnie wyciągają work_history z TalentRadar JSON-stringu
* potrafią znaleźć work_history w środku Traffit-arraya (z duplikatami)
* obsługują flat Traffit-object (current role + past employers CSV) — partial
* są idempotentne (dedupe po company+role+start)
* nie crashują na niepoprawnym JSON / pustych payloadach / scalarach
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ nie jest packagem — dodaj parent do sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR / "scripts"))

import backfill_candidate_experience as bf  # noqa: E402


# ── TalentRadar (string variant) ──────────────────────────────────────────────


def test_parse_tr_string_full_work_history():
    payload = {
        "current_role": "DevOps Engineer",
        "work_history": [
            {
                "role": "DevOps Engineer",
                "company": "XTM International",
                "start_date": "2021-01",
                "end_date": None,  # current
                "description": "CI/CD work",
                "technologies": ["Jenkins", "Docker"],
            },
            {
                "role": "IT Specialist",
                "company": "Santander Leasing S.A.",
                "start_date": "2016-09",
                "end_date": "2020-04",
                "description": "Windows admin",
            },
        ],
    }
    raw = json.dumps(payload)
    experience, lcc = bf.parse_tr_string(raw)

    assert len(experience) == 2
    assert experience[0]["company"] == "XTM International"
    assert experience[0]["role"] == "DevOps Engineer"
    assert experience[0]["start"] == "2021-01"
    assert experience[0]["end"] is None
    assert experience[0]["desc"] == "CI/CD work"
    assert experience[1]["company"] == "Santander Leasing S.A."
    assert experience[1]["end"] == "2020-04"
    # Current company derived because end is None
    assert lcc == "XTM International"


def test_parse_tr_string_sort_finished_by_end_desc():
    payload = {
        "work_history": [
            {
                "role": "A",
                "company": "X",
                "start_date": "2015-01",
                "end_date": "2018-01",
            },
            {
                "role": "B",
                "company": "Y",
                "start_date": "2018-01",
                "end_date": "2022-12",
            },
            {
                "role": "C",
                "company": "Z",
                "start_date": "2010-01",
                "end_date": "2014-01",
            },
        ]
    }
    experience, lcc = bf.parse_tr_string(json.dumps(payload))
    assert [e["company"] for e in experience] == ["Y", "X", "Z"]
    assert lcc is None  # nothing current


def test_parse_tr_string_current_first_even_without_dates():
    payload = {
        "work_history": [
            {"role": "Past", "company": "Past Co", "end_date": "2020-01"},
            {"role": "Now", "company": "Now Co"},  # no end → current
        ]
    }
    experience, lcc = bf.parse_tr_string(json.dumps(payload))
    assert experience[0]["company"] == "Now Co"
    assert lcc == "Now Co"


def test_parse_tr_string_dedupe_by_company_role_start():
    payload = {
        "work_history": [
            {
                "role": "Dev",
                "company": "Acme",
                "start_date": "2020-01",
                "end_date": "2022-01",
            },
            {
                "role": "dev",
                "company": "ACME",
                "start_date": "2020-01",
                "end_date": "2022-01",
            },
            {
                "role": "Dev",
                "company": "Acme",
                "start_date": "2023-01",
            },  # different start, keep
        ]
    }
    experience, _ = bf.parse_tr_string(json.dumps(payload))
    assert len(experience) == 2


def test_parse_tr_string_skip_empty_rows():
    payload = {
        "work_history": [
            {"role": None, "company": None},  # totally empty → skip
            {"role": "Dev", "company": "Acme"},
        ]
    }
    experience, _ = bf.parse_tr_string(json.dumps(payload))
    assert len(experience) == 1


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        '{"work_history": "wrong type"}',
        '"escaped scalar string"',
        json.dumps({"work_history": []}),
        json.dumps({}),
    ],
)
def test_parse_tr_string_robust_to_garbage(raw):
    experience, lcc = bf.parse_tr_string(raw)
    assert experience == []
    assert lcc is None


# ── Traffit array variant ─────────────────────────────────────────────────────


def test_parse_tr_array_finds_work_history_among_placeholders():
    rich = json.dumps(
        {
            "work_history": [
                {"role": "Dev", "company": "Acme", "start_date": "2020-01"},
            ],
            "current_role": "Dev",
        }
    )
    arr = [
        {},
        {"legacy_source": "traffit"},
        rich,
        {"legacy_source": "talent_radar"},
        rich,  # duplicate — first match wins, no harm
    ]
    experience, lcc = bf.parse_tr_array(arr)
    assert len(experience) == 1
    assert experience[0]["company"] == "Acme"
    assert lcc == "Acme"  # end_date None → current


def test_parse_tr_array_dict_with_work_history():
    arr = [
        {"work_history": [{"role": "A", "company": "B", "end_date": "2020-01"}]},
    ]
    experience, lcc = bf.parse_tr_array(arr)
    assert experience[0]["company"] == "B"
    assert lcc is None


def test_parse_tr_array_returns_empty_when_no_work_history_anywhere():
    arr = [
        {},
        {"legacy_source": "traffit"},
        '{"skills": ["python"]}',  # has data, no work_history
    ]
    experience, lcc = bf.parse_tr_array(arr)
    assert experience == []
    assert lcc is None


@pytest.mark.parametrize("garbage", [None, "not a list", 42, {"k": "v"}])
def test_parse_tr_array_robust_to_non_arrays(garbage):
    experience, lcc = bf.parse_tr_array(garbage)
    assert experience == []
    assert lcc is None


# ── Traffit object variant (partial) ──────────────────────────────────────────


def test_parse_traffit_object_position_and_employers():
    obj = {
        "traffit_Position": "QA Engineer",
        "traffit_previous_employers": "mTab, Headwire",
        "legacy_source": "traffit",
    }
    experience, lcc = bf.parse_traffit_object(obj)
    assert lcc is None  # no current company derivable from variant 3
    # 1 role + 2 employers = 3 entries (no placeholder — position present)
    assert len(experience) == 3
    assert experience[0] == {
        "company": None,
        "role": "QA Engineer",
        "start": None,
        "end": None,
        "desc": None,
    }
    assert experience[1]["company"] == "mTab"
    assert experience[1]["role"] is None
    assert experience[2]["company"] == "Headwire"


def test_parse_traffit_object_multi_role_career_order():
    obj = {
        "traffit_Position": "Scrum Master, Junior Scrum Master, Scrum Master Trainee",
        "traffit_previous_employers": "Arla Foods, Santander Bank",
    }
    experience, _ = bf.parse_traffit_object(obj)
    # 3 roles + 2 employers
    assert len(experience) == 5
    # First role = current
    assert experience[0]["role"] == "Scrum Master"
    assert experience[1]["role"] == "Junior Scrum Master"
    assert experience[2]["role"] == "Scrum Master Trainee"
    # Employers after
    assert experience[3]["company"] == "Arla Foods"
    assert experience[4]["company"] == "Santander Bank"


def test_parse_traffit_object_only_employers_prepends_null_placeholder():
    """Employers-only candidates get NULL placeholder at experience[0].

    Bez placeholdera "obecna firma=Acme" matchowałoby tego kandydata (false
    positive — Acme to past employer), bo filter sprawdza experience[0].company.
    """
    obj = {"traffit_previous_employers": "Acme, Globex"}
    experience, _ = bf.parse_traffit_object(obj)
    assert len(experience) == 3
    # Index 0 — placeholder (current unknown)
    assert experience[0] == {
        "company": None,
        "role": None,
        "start": None,
        "end": None,
        "desc": None,
    }
    # Past employers shifted to index 1+
    assert experience[1]["company"] == "Acme"
    assert experience[2]["company"] == "Globex"


def test_parse_traffit_object_position_present_no_placeholder():
    """Gdy traffit_Position jest podane, experience[0] = ta rola (no placeholder)."""
    obj = {"traffit_Position": "QA", "traffit_previous_employers": "Acme"}
    experience, _ = bf.parse_traffit_object(obj)
    assert len(experience) == 2
    assert experience[0]["role"] == "QA"
    assert experience[0]["company"] is None
    assert experience[1]["company"] == "Acme"


def test_parse_traffit_object_only_position():
    obj = {"traffit_Position": "Software Engineer"}
    experience, _ = bf.parse_traffit_object(obj)
    assert len(experience) == 1
    assert experience[0]["role"] == "Software Engineer"


def test_parse_traffit_object_dedup_employers_case_insensitive():
    obj = {"traffit_previous_employers": "Acme, ACME, acme, Globex"}
    experience, _ = bf.parse_traffit_object(obj)
    # 1 placeholder + Acme + Globex (case-folded dedup) = 3
    assert len(experience) == 3
    assert experience[0]["company"] is None  # placeholder
    assert experience[1]["company"] == "Acme"
    assert experience[2]["company"] == "Globex"


def test_parse_traffit_object_returns_empty_when_only_legacy_keys():
    obj = {"legacy_source": "traffit"}
    experience, lcc = bf.parse_traffit_object(obj)
    assert experience == []
    assert lcc is None


@pytest.mark.parametrize(
    "obj",
    [
        None,
        [],
        "not a dict",
        {"traffit_Position": None, "traffit_previous_employers": None},
        {"traffit_Position": "", "traffit_previous_employers": ""},
    ],
)
def test_parse_traffit_object_robust_to_garbage(obj):
    experience, lcc = bf.parse_traffit_object(obj)
    assert experience == []
    assert lcc is None


# ── End-to-end dispatch (parse_row) ───────────────────────────────────────────


def test_parse_row_dispatches_correctly():
    # tr_string
    raw = json.dumps({"work_history": [{"role": "A", "company": "B"}]})
    exp, lcc, variant = bf.parse_row(raw, "string", "talent_radar")
    assert variant == "tr_string"
    assert exp[0]["company"] == "B"
    assert lcc == "B"

    # tr_array
    arr = [{"work_history": [{"role": "X", "company": "Y", "end_date": "2020-01"}]}]
    exp, lcc, variant = bf.parse_row(arr, "array", "traffit")
    assert variant == "tr_array"
    assert exp[0]["company"] == "Y"
    assert lcc is None  # end_date present → not current

    # traffit_obj
    obj = {"traffit_Position": "Dev"}
    exp, lcc, variant = bf.parse_row(obj, "object", "traffit")
    assert variant == "traffit_obj"
    assert exp[0]["role"] == "Dev"
    assert lcc is None


def test_parse_row_unknown_jtype_returns_none_variant():
    exp, lcc, variant = bf.parse_row(None, "null", None)
    assert variant is None
    assert exp == []
    assert lcc is None


def test_parse_row_catches_parser_errors():
    # Force a parser to blow up by giving it an unparseable thing through tr_string.
    # parse_tr_string is robust to garbage already (returns [], None) — pick a
    # case that exercises the try/except wrapper rather than the parser internals.
    exp, lcc, variant = bf.parse_row(b"binary data", "string", "talent_radar")
    # parse_tr_string only accepts str → returns empty
    assert variant == "tr_string"
    assert exp == []
    assert lcc is None
