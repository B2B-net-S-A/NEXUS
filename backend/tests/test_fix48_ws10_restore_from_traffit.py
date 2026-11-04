"""„Przywróć z Traffita” nie wkłada dopisku z powrotem w imię (audyt 13.10.2026).

Migawka `_nexus_identity.traffit_name` sprzed reguły D6 bywa „[ACTIVE] Jan”.
Przywrócenie zapisywało ją w imieniu 1:1, z pominięciem
`candidate_name_rules`. Bez bazy — sama funkcja serwisu. Imiona wymyślone.
"""

from __future__ import annotations

import pytest

from app.models.candidate import Candidate
from app.services.candidate_identity_ownership import (
    IDENTITY_META_KEY,
    identity_sync_state,
    restore_traffit_identity_fields,
)

TOKEN = "2026-10-13T08:00:00+00:00"


def _candidate(traffit_name: str) -> Candidate:
    return Candidate(
        name="Janek",
        lastname="Testowy",
        external_source="traffit",
        custom_fields={
            IDENTITY_META_KEY: {
                "name_manual": True,
                "traffit_name": traffit_name,
                "name_set_at": TOKEN,
                "name_set_by": 1,
                "name_ownership_reason": "manual_edit",
            }
        },
    )


def _restore(candidate: Candidate, traffit_name: str) -> list[str]:
    return restore_traffit_identity_fields(
        candidate,
        ["name"],
        expected_current_values={"name": "Janek"},
        expected_source_values={"name": traffit_name},
        expected_override_tokens={"name": TOKEN},
    )


@pytest.mark.parametrize(
    ("traffit_name", "restored"),
    [("[ACTIVE] Jan", "Jan"), ("Jan (zaakceptowany)", "Jan"), ("Jan", "Jan")],
)
def test_restore_writes_the_name_without_the_marker(
    traffit_name: str, restored: str
) -> None:
    candidate = _candidate(traffit_name)
    assert _restore(candidate, traffit_name) == ["name"]
    assert candidate.name == restored
    assert "name_manual" not in candidate.custom_fields[IDENTITY_META_KEY]


def test_snapshot_that_is_only_a_marker_cannot_be_restored() -> None:
    candidate = _candidate("[ACTIVE]")
    assert identity_sync_state(candidate)["name"]["can_restore"] is False
    with pytest.raises(ValueError, match="traffit_identity_value_unavailable:name"):
        _restore(candidate, "[ACTIVE]")
    assert candidate.name == "Janek"
