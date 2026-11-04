"""„W bazie od” u praktykanta: rok w kalendarzu firmy (audyt 48 h, 13.10.2026).

Lista praktykanta pokazuje sam rok wejścia osoby do bazy. Liczony z UTC dawał
poprzedni rok osobie dodanej w sylwestra po 23:00 czasu polskiego — reguła
„dziś to kalendarz firmy” (Europe/Warsaw) dotyczy też dat w przeszłości.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.candidate import Candidate
from app.models.trainee import TraineeCallItem
from app.services.trainee_program import item_row


def _row(created_at: datetime, source_created_at: datetime | None) -> dict:
    candidate = Candidate(
        id=7,
        name="Ewa",
        lastname="Testowa",
        created_at=created_at,
        source_created_at=source_created_at,
        external_source=None,
    )
    item = TraineeCallItem(id=1, position=1, reasons={}, attempts=0)
    return item_row(item, candidate)


def test_new_years_eve_evening_in_warsaw_is_already_the_new_year() -> None:
    # 31.12.2025 23:30 UTC = 01.01.2026 00:30 w Warszawie.
    at = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert (
        _row(datetime(2026, 5, 4, 8, tzinfo=timezone.utc), at)["in_base_since"] == 2026
    )


def test_ordinary_date_keeps_its_year() -> None:
    at = datetime(2025, 6, 10, 9, tzinfo=timezone.utc)
    assert (
        _row(datetime(2026, 5, 4, 8, tzinfo=timezone.utc), at)["in_base_since"] == 2025
    )


def test_inexact_date_still_shows_nothing() -> None:
    # Bez daty u źródła i z dniem pierwszego importu — „przed …”, bez roku.
    assert (
        _row(datetime(2026, 4, 16, 6, tzinfo=timezone.utc), None)["in_base_since"]
        is None
    )
