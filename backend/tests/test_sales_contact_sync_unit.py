"""Kontakty jako jedna lista (decyzje Artura z 13.11.2026), bez bazy. Dane fikcyjne.

Reguły: ``docs/claude/sprzedaz/kontakty-jedna-lista.md``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.sales import bot_card_history as history
from app.services.sales import contact_sync
from app.services.sales.bot_tasks.people import FirmPeople, LeftPerson

SRC = "https://firma.example/zarzad"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jan Fikcyjny (Prezes Zarządu)", ("Jan Fikcyjny", "Prezes Zarządu")),
        ("  Anna Testowa  ( CTO ) ", ("Anna Testowa", "CTO")),
        ("Jan Fikcyjny", None),
        # Jedno słowo przed nawiasem to nie imię i nazwisko.
        ("Zarząd (sekretariat)", None),
        ("Jan (Janek) Fikcyjny", None),
        ("", None),
        (None, None),
    ],
)
def test_split_name_only_for_name_followed_by_title(raw, expected) -> None:
    assert contact_sync.split_name(raw) == expected


def test_marks_ignore_word_order_title_in_brackets_and_email_case() -> None:
    assert contact_sync.marks("Fikcyjny Jan", None) == contact_sync.marks(
        "Jan Fikcyjny (CEO)", None
    )
    assert "e:jan@firma.example" in contact_sync.marks("X Y", " Jan@Firma.example ")


def test_same_title_ignores_case_accents_and_spacing() -> None:
    assert contact_sync.same_title("Dyrektor  IT", "dyrektor it")
    assert contact_sync.same_title("Członek Zarządu", "czlonek zarzadu")
    assert not contact_sync.same_title("CTO", "CIO")


def test_newer_needs_a_dated_source_strictly_after_the_current_state() -> None:
    state = date(2026, 10, 28)
    assert contact_sync.newer(date(2026, 11, 5), state)
    assert not contact_sync.newer(date(2026, 10, 28), state)
    assert not contact_sync.newer(date(2025, 3, 1), state)
    assert not contact_sync.newer(None, state)


def _contact(updated: datetime) -> datetime:
    """``updated_at`` kontaktu z chwili wczytania."""

    return updated


WROTE = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


def test_without_bot_writes_the_state_is_the_day_of_the_last_change() -> None:
    # 23:30 UTC 12.11 to 00:30 w Warszawie: już 13.11 według kalendarza firmy.
    contact = _contact(datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc))
    assert contact_sync.title_state(contact, None) == date(2026, 11, 13)
    assert contact_sync.work_state(contact, None) == date(2026, 11, 13)


def test_after_a_bot_write_the_state_is_the_source_date_and_the_earlier_human_day() -> (
    None
):
    contact = _contact(WROTE + timedelta(seconds=2))
    writes = contact_sync.Writes(
        at=WROTE, human=date(2026, 10, 29), as_of=date(2026, 11, 12), published=None
    )
    assert contact_sync.title_state(contact, writes) == date(2026, 11, 12)
    # Odczyt Cognism nie dowodzi, że osoba dalej pracuje.
    assert contact_sync.work_state(contact, writes) == date(2026, 10, 29)


def test_contact_created_by_cognism_does_not_block_a_dated_departure() -> None:
    contact = _contact(WROTE + timedelta(seconds=2))
    writes = contact_sync.Writes(at=WROTE, human=None, as_of=date(2026, 11, 12))
    assert contact_sync.work_state(contact, writes) == date.min
    assert contact_sync.newer(
        date(2026, 10, 7), contact_sync.work_state(contact, writes)
    )
    assert not contact_sync.newer(
        date(2026, 10, 7), contact_sync.title_state(contact, writes)
    )


def test_manual_change_after_the_bot_write_counts_from_its_own_day() -> None:
    contact = _contact(datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    writes = contact_sync.Writes(
        at=WROTE, human=None, as_of=date(2026, 6, 1), published=date(2026, 6, 1)
    )
    assert contact_sync.human_date(contact, writes) == date(2026, 11, 20)
    assert contact_sync.work_state(contact, writes) == date(2026, 11, 20)


def test_left_person_needs_a_link_and_a_publication_date() -> None:
    gone = LeftPerson(
        full_name="Jan Fikcyjny", source_url=SRC, published=date(2026, 10, 2)
    )
    assert gone.left_on is None
    with pytest.raises(ValidationError):
        LeftPerson(full_name="Jan Fikcyjny", source_url=SRC)
    with pytest.raises(ValidationError):
        LeftPerson(
            full_name="Jan Fikcyjny", source_url="ftp://x", published=date(2026, 1, 1)
        )
    with pytest.raises(ValidationError):
        LeftPerson(
            full_name="Jan Fikcyjny",
            source_url=SRC,
            published=date(2026, 10, 2),
            reason="zgadnięte",
        )
    firm = FirmPeople.model_validate(
        {
            "company_ref": 1,
            "left": [
                {
                    "full_name": "Jan Fikcyjny",
                    "source_url": SRC,
                    "published": "2026-10-02",
                }
            ],
        }
    )
    assert firm.people == [] and firm.left[0].published == date(2026, 10, 2)


def test_history_lines_for_contact_changes() -> None:
    payload = {
        "source": contact_sync.BOT,
        "changes": [
            {
                "name": "Anna Testowa",
                "change": "added",
                "after": "CTO",
                "source_url": SRC,
            },
            {
                "name": "Jan Fikcyjny",
                "change": "title",
                "before": "Dyrektor IT",
                "after": "CIO",
                "source_url": SRC,
                "as_of": "2026-11-02",
            },
            {
                "name": "Ewa Przykładowa",
                "change": "left",
                "before": "Prezes Zarządu",
                "source_url": SRC,
                "as_of": "2026-10-01",
            },
            {
                "name": "Piotr Wzorcowy",
                "change": "split",
                "before": "Piotr Wzorcowy (CFO)",
                "after": "Piotr Wzorcowy · CFO",
            },
        ],
    }
    lines = {line.label: line for line in history.contact_lines(payload)}
    assert (lines["Anna Testowa"].after, lines["Anna Testowa"].note) == (
        "CTO",
        "nowy kontakt",
    )
    assert (lines["Jan Fikcyjny"].before, lines["Jan Fikcyjny"].after) == (
        "Dyrektor IT",
        "CIO",
    )
    assert lines["Ewa Przykładowa"].after == "nie pracuje"
    assert lines["Ewa Przykładowa"].before == "Prezes Zarządu"
    assert lines["Ewa Przykładowa"].note == "według źródła z 2026-10-01"
    assert lines["Piotr Wzorcowy"].before == "Piotr Wzorcowy (CFO)"


def test_contact_history_is_for_editors_and_names_the_source_bot() -> None:
    at = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
    rows = [
        (
            contact_sync.KIND,
            at,
            {
                "source": contact_sync.COGNISM,
                "changes": [
                    {"name": "Jan Fikcyjny", "change": "added", "after": "CTO"}
                ],
            },
        )
    ]
    assert history.build(rows, with_people=False) == []
    [entry] = history.build(rows, with_people=True)
    assert entry.bot == "Cognism"
