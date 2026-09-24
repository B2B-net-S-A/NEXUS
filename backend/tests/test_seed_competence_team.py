"""Plan przypisań ze screena Artura (24.09.2026) jest spójny, zanim trafi do bazy."""

import pytest

from scripts.seed_competence_team_2026_09 import ASSIGNMENTS, EXCLUDED, validate_plan


@pytest.mark.unit
def test_plan_has_one_primary_per_person_and_no_duplicates() -> None:
    assert validate_plan() == []


@pytest.mark.unit
def test_excluded_accounts_get_no_category() -> None:
    assigned = {user_id for ids in ASSIGNMENTS.values() for user_id in ids}
    assert assigned.isdisjoint(EXCLUDED)


@pytest.mark.unit
def test_every_category_has_someone_in_first_priority() -> None:
    slugs = {slug for slug, _priority in ASSIGNMENTS}
    assert all(ASSIGNMENTS.get((slug, 1)) for slug in slugs)
