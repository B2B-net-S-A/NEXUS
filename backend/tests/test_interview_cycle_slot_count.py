"""Licznik terminów w kroku „Wybór terminu”: 36 z 70 wniosków ma jeden termin."""

import pytest

from app.services.interview_cycle import slots_to_choose_label


@pytest.mark.parametrize(
    ("count", "label"),
    [
        (1, "1 termin do wyboru"),
        (2, "2 terminy do wyboru"),
        (4, "4 terminy do wyboru"),
        (5, "5 terminów do wyboru"),
    ],
)
def test_slot_count_uses_polish_plural(count: int, label: str) -> None:
    assert slots_to_choose_label(count) == label
