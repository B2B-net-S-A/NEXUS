"""Strażnik parametrów płac na 1 stycznia — bez bazy (``next_year``)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.hr.payroll_lists import next_year, params
from app.services.hr_payroll_lists_schema import NOTE_MAX

SEED = next_year.Version(date(2026, 1, 1), dict(params.SEED_2026))


@pytest.mark.parametrize(
    ("today", "year"),
    [
        (date(2026, 11, 16), 2026),
        (date(2026, 12, 1), 2026),  # 31 dni przed — jeszcze nie
        (date(2026, 12, 2), 2027),  # 30 dni przed — już tak
        (date(2026, 12, 31), 2027),
        (date(2027, 1, 20), 2027),  # po Nowym Roku nadal pilnuje 2027
    ],
)
def test_target_year_starts_30_days_before_new_year(today: date, year: int) -> None:
    assert next_year.target_year(today) == year


def test_no_message_before_the_lead_window() -> None:
    assert next_year.gap(date(2026, 12, 1), [SEED]) is None


def test_message_from_30_days_before_without_january_version() -> None:
    gap = next_year.gap(date(2026, 12, 2), [SEED])
    assert gap is not None
    assert gap["year"] == 2027
    assert gap["effective_from"] == "2027-01-01"
    assert gap["base_effective_from"] == "2026-01-01"


def test_message_stays_after_new_year_until_version_exists() -> None:
    assert next_year.gap(date(2027, 1, 20), [SEED])["year"] == 2027


def test_message_disappears_once_january_version_exists() -> None:
    draft = next_year.Version(date(2027, 1, 1), dict(params.SEED_2026))
    assert next_year.gap(date(2026, 12, 15), [SEED, draft]) is None


def test_later_version_does_not_replace_january_one() -> None:
    february = next_year.Version(date(2027, 2, 1), dict(params.SEED_2026))
    gap = next_year.gap(date(2026, 12, 15), [SEED, february])
    assert gap is not None
    assert gap["base_effective_from"] == "2026-01-01"


def test_no_draft_without_any_version() -> None:
    assert next_year.gap(date(2026, 12, 15), []) is None


def test_draft_takes_known_2027_values_with_sources() -> None:
    gap = next_year.gap(date(2026, 12, 15), [SEED])
    assert gap["params"]["minimum_wage"] == "4950.00"
    assert gap["params"]["minimum_hourly_rate"] == "32.30"
    assert gap["params"]["annual_pension_limit"] == "300990.00"
    known = {item["key"]: item for item in gap["known"]}
    assert set(known) == {"minimum_wage", "minimum_hourly_rate", "annual_pension_limit"}
    assert known["minimum_wage"]["before"] == "4806.00"
    assert (
        known["minimum_wage"]["url"] == "https://api.sejm.gov.pl/eli/acts/DU/2026/1213"
    )
    assert known["annual_pension_limit"]["url"] == (
        "https://api.sejm.gov.pl/eli/acts/MP/2026/1098"
    )
    assert all(item["source"] and item["published"] for item in gap["known"])


def test_draft_keeps_everything_else_from_current_version() -> None:
    gap = next_year.gap(date(2026, 12, 15), [SEED])
    known = {item["key"] for item in gap["known"]}
    for key in params.SPECS:
        if key not in known:
            assert gap["params"][key] == SEED.params[key], key
    # Progi PIT bez zgadywania — jak w bieżącej wersji, a komunikat to mówi.
    assert gap["params"]["pit_threshold"] == "120000.00"
    assert "PIT" in gap["unchanged_note"] and "2027" in gap["unchanged_note"]


def test_draft_passes_server_validation_and_note_fits() -> None:
    gap = next_year.gap(date(2026, 12, 15), [SEED])
    assert params.normalized(gap["params"])["minimum_wage"] == "4950.00"
    assert len(gap["note"]) <= NOTE_MAX
    assert "Dz.U. 2026 poz. 1213" in gap["note"]
    assert "M.P. 2026 poz. 1098" in gap["note"]


def test_old_version_without_k7b_keys_gets_defaults() -> None:
    old = {k: v for k, v in params.SEED_2026.items() if k not in params.LATER_DEFAULTS}
    gap = next_year.gap(date(2026, 12, 15), [next_year.Version(date(2026, 1, 1), old)])
    assert gap["params"]["sick_pay_rate"] == params.LATER_DEFAULTS["sick_pay_rate"]


def test_draft_does_not_touch_the_base_version() -> None:
    base = dict(params.SEED_2026)
    next_year.gap(date(2026, 12, 15), [next_year.Version(date(2026, 1, 1), base)])
    assert base == params.SEED_2026


def test_every_known_value_is_a_valid_parameter() -> None:
    for values in next_year.KNOWN.values():
        for item in values:
            assert item.key in params.SPECS
            params._number(item.key, item.value)
            assert item.url.startswith("https://")
