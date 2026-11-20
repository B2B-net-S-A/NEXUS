"""Powody odrzucenia/rezygnacji nigdy nie trafiają do człowieka jako surowy kod.

Test na produkcji 23.09.2026: okno „Kandydat zrezygnował” pokazywało
``counter_offer``, ``lost_interest`` itd. (nazwy zasiane migracją 0068) oraz
„Inne (rejected)” / „Inne (withdrawn)” (0006).
"""

from datetime import datetime, timezone

import pytest

from app.models.pipeline_template import TerminalType
from app.schemas.pipeline_template import RejectionReasonResponse
from app.services.rejection_reason_labels import rejection_reason_label

SEEDED = {
    "counter_offer": "Kontroferta od obecnego pracodawcy",
    "personal_reasons": "Powody osobiste",
    # Etykiety jednego słownika powodów (19.11.2026, `close_reasons.py`).
    "lost_interest": "Straciła zainteresowanie / za długi proces",
    "accepted_other_offer": "Przyjęła inną ofertę",
    "salary_mismatch": "Za droga",
    "process_too_long": "Straciła zainteresowanie / za długi proces",
    "Inne (rejected)": "Inne",
    "Inne (withdrawn)": "Inne",
}


@pytest.mark.parametrize("code,label", sorted(SEEDED.items()))
def test_seeded_codes_have_polish_labels(code: str, label: str) -> None:
    assert rejection_reason_label(code) == label


def test_unknown_name_passes_through_and_none_stays_none() -> None:
    assert rejection_reason_label("Kandydat się wycofał") == "Kandydat się wycofał"
    assert rejection_reason_label(None) is None


def test_response_carries_label_next_to_the_stored_name() -> None:
    now = datetime.now(timezone.utc)
    body = RejectionReasonResponse(
        id=1,
        template_id=1,
        stage_def_id=None,
        name="counter_offer",
        order=0,
        category=TerminalType.withdrawn,
        active=True,
        disqualifies_person=False,
        created_at=now,
        updated_at=now,
    ).model_dump()
    # `name` zostaje kluczem (importer i ocena ryzyka szukają po nim).
    assert body["name"] == "counter_offer"
    assert body["label"] == "Kontroferta od obecnego pracodawcy"
