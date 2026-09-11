"""Champion intake must not destroy data it did not need to touch (09.2026).

Two regressions of the v4 intake (#1477), both silent — the profile still
opened, only scoring and the search quietly lost what it had:

1. Every content-changing save re-normalised the WHOLE profile. A document rate
   written as a range ("120–140 zł/h" in `rate_raw`) replaced the number next
   to it and nulled `rate_value`, so the Champion budget disappeared from
   scoring after, say, an edit of the project description.
2. MUST/NICE entries over 12 words or 120 characters were moved to
   `intake.unresolved` and out of the list that is synced to `jobs.must_skills`.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.schemas.champion import ChampionProfile
from app.services.champion_intake import (
    prepare_profile,
    sync_skill_column,
    user_edit,
    validation,
)

LONG = (
    "Minimum pięć lat komercyjnego doświadczenia w projektowaniu systemów "
    "rozproszonych opartych na Apache Kafka w środowisku produkcyjnym"
)
VERY_LONG = "Bardzo dobra znajomość " + "zagadnień architektury " * 6


def legacy_profile() -> dict:
    """Stored before the v4 intake: AI number next to a range, a long MUST."""
    return ChampionProfile.model_validate(
        {
            "basics": {
                "role_name": "Senior Java Developer",
                "rate_value": 140.0,
                "rate_raw": "120-140 zł/h",
                "work_mode": "hybrydowo",
                "onsite_days_per_week": 2,
                "candidate_location_pref": "Warszawa",
                "start_date": "01.10.2026",
            },
            "stack": {
                "must": [{"name": "Java 17"}, {"name": LONG}],
                "nice": [],
                "notes": "",
            },
            "project": {"about": "Projekt bankowy.", "responsibilities": "API"},
        }
    ).model_dump(mode="json")


def names(profile: dict, key: str = "must") -> list[str]:
    return [item["name"] for item in profile["stack"][key]]


def test_unrelated_edit_keeps_a_rate_backed_by_a_range() -> None:
    stored = legacy_profile()

    edited = user_edit(stored, {"project": {"about": "Nowy opis projektu."}}, 7)

    assert edited["basics"]["rate_value"] == 140.0, (
        "an edit of the project description nulled the Champion budget"
    )
    assert edited["basics"]["rate_raw"] == "120-140 zł/h"
    assert "basics.rate_value" not in edited["intake"]["unresolved"]
    assert edited["project"]["about"] == "Nowy opis projektu."
    assert edited["intake"]["applied_by"] == 7


def test_untouched_fields_are_not_renormalised() -> None:
    """Only what the save changed goes through the normaliser."""
    stored = legacy_profile()

    edited = user_edit(stored, {"project": {"about": "Inny opis."}}, 7)

    # A full pass would rewrite this to ISO; nobody asked for that here.
    assert edited["basics"]["start_date"] == "01.10.2026"
    assert names(edited) == ["Java 17", LONG]


def test_a_range_in_the_document_text_never_erases_a_number() -> None:
    cp = legacy_profile()
    cp["basics"]["rate_raw"] = "120–140 zł/h"

    prepared = prepare_profile(cp)

    assert prepared["basics"]["rate_value"] == 140.0
    assert prepared["intake"]["advisory"]["basics.rate_value"] == "120–140 zł/h"
    assert "basics.rate_value" not in prepared["intake"]["unresolved"]


def test_a_parseable_document_rate_still_wins() -> None:
    cp = legacy_profile()
    cp["basics"].update(rate_value=999.0, rate_raw="150 PLN/h")

    prepared = prepare_profile(cp)

    assert prepared["basics"]["rate_value"] == 150.0
    assert "basics.rate_value" not in prepared["intake"]["advisory"]


def test_a_range_typed_into_the_rate_field_is_still_unresolved() -> None:
    """Explicit input is not guessed: no number exists to keep."""
    stored = legacy_profile()

    edited = user_edit(stored, {"basics": {"rate_value": "120-150 EUR/h"}}, 7)

    assert edited["basics"]["rate_value"] is None
    assert edited["intake"]["unresolved"]["basics.rate_value"] == "120-150 EUR/h"


def test_long_requirements_stay_in_the_list_and_are_only_flagged() -> None:
    cp = legacy_profile()
    cp["stack"]["must"] = f"Java 17\n{LONG}\n{VERY_LONG.strip()}\ndo ustalenia"

    prepared = prepare_profile(cp)

    assert names(prepared) == ["Java 17", LONG, VERY_LONG.strip()]
    assert prepared["intake"]["advisory"]["stack.must"].splitlines() == [
        LONG,
        VERY_LONG.strip(),
    ]
    # A placeholder is still not a requirement.
    assert prepared["intake"]["unresolved"]["stack.must"] == "do ustalenia"


def test_long_requirement_reaches_the_job_column() -> None:
    prepared = prepare_profile(legacy_profile())
    job = SimpleNamespace(must_skills=None, matching_requirements=None)

    sync_skill_column(
        job,
        "must",
        [{"name": item["name"], "level": None} for item in prepared["stack"]["must"]],
    )

    assert [s["name"] for s in job.must_skills] == ["Java 17", LONG]


def test_requirements_set_aside_by_the_old_normaliser_rejoin_the_list() -> None:
    """Profiles saved under #1477 carry the dropped entries in `unresolved`."""
    stored = legacy_profile()
    stored["stack"]["must"] = [{"name": "Java 17"}]
    stored = prepare_profile(stored)
    stored["intake"]["unresolved"]["stack.must"] = f"{LONG}\ndo ustalenia"

    edited = user_edit(
        stored,
        {"stack": {"must": [{"name": "Java 17"}, {"name": "Docker"}]}},
        7,
    )

    assert names(edited) == ["Java 17", "Docker", LONG]
    # The leftover placeholder note is obsolete once the list has requirements
    # (the pre-existing rule) — only real requirements come back.
    assert "stack.must" not in edited["intake"]["unresolved"]
    assert edited["intake"]["advisory"]["stack.must"] == LONG


def test_an_entry_too_long_to_store_is_kept_in_intake_not_lost() -> None:
    paragraph = "wymaganie " * 60
    cp = legacy_profile()
    cp["stack"]["must"] = [{"name": "Java 17"}, {"name": paragraph}]

    prepared = prepare_profile(cp)

    assert names(prepared) == ["Java 17"]
    assert prepared["intake"]["unresolved"]["stack.must"] == paragraph.strip()


@pytest.mark.parametrize("gate", ["true", "false"])
def test_advisory_notes_are_warnings_that_block_nothing(monkeypatch, gate) -> None:
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", gate)
    prepared = prepare_profile(legacy_profile())

    result = validation(prepared)
    advisory = {
        i["code"]: i
        for i in result["issues"]
        if i["code"] in {"rate_source_ambiguous", "long_requirement"}
    }

    assert set(advisory) == {"rate_source_ambiguous", "long_requirement"}
    assert all(i["severity"] == "warning" for i in advisory.values())
    assert all(i["blocked_operations"] == [] for i in advisory.values())
    assert advisory["long_requirement"]["source"] == LONG
    codes = {i["code"] for i in result["issues"]}
    assert "missing_budget" not in codes, "the kept rate must count as a budget"


def test_a_requirement_longer_than_a_skill_name_does_not_break_the_contract() -> None:
    """Kept long entries reach `jobs.must_skills`; the search contract must hold them.

    `SkillRequirement` caps a name at 100 characters, and one longer label used
    to fail `requirements_for_job` — i.e. every search on the job.
    """
    from app.services.champion_intake import skill_groups
    from app.services.requirement_contract import (
        explicit_contract,
        requirements_for_job,
    )

    job = SimpleNamespace(
        must_skills=[{"name": "Java 17"}, {"name": LONG}],
        nice_skills=None,
        matching_requirements=None,
        requirements_reviewed=False,
        champion_profile=None,
        title="Java Developer",
        requirements=None,
        description=None,
    )

    contract = requirements_for_job(job)
    must = [group.any_of for group in contract.all_of if group.level == "must"]

    assert len(must) == 2
    assert must[1] == [LONG.lower()[:100].rstrip()]
    assert len(explicit_contract(["Java 17", LONG], []).all_of) == 2
    assert skill_groups(["Java 17", LONG]) == skill_groups(["java 17", LONG.upper()])


def test_template_copy_keeps_the_profile_as_stored() -> None:
    """`copy_profile`: the source is its own `previous` — nothing re-derived."""
    from app.services.champion_intake import copy_profile

    stored = prepare_profile(legacy_profile())
    stored["basics"]["rate_raw"] = "do 140 zł netto/h"
    stored["intake"]["advisory"]["basics.rate_value"] = "do 140 zł netto/h"
    stored["intake"]["unresolved"]["stack.must"] = VERY_LONG.strip()
    stored["basics"]["start_date"] = "01.10.2026"

    copy = copy_profile(stored, 42)

    assert copy["basics"]["rate_value"] == 140.0
    assert copy["basics"]["rate_raw"] == "do 140 zł netto/h"
    assert copy["intake"]["advisory"]["basics.rate_value"] == "do 140 zł netto/h"
    assert copy["intake"]["unresolved"]["stack.must"] == VERY_LONG.strip()
    assert copy["basics"]["start_date"] == "01.10.2026"
    assert names(copy) == names(stored)
    assert copy["intake"]["applied_by"] == 42


def test_no_op_edit_keeps_the_stored_intake() -> None:
    stored = prepare_profile(legacy_profile())
    before = deepcopy(stored)

    same = user_edit(stored, deepcopy(stored), 7)

    assert same["intake"] == before["intake"]
    assert same["basics"] == before["basics"]
