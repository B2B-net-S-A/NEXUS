from __future__ import annotations

from datetime import date

import app.models  # noqa: F401
from scripts.backfill_client_person_numbers_from_ksef import (
    SKIP_AMBIGUOUS,
    SKIP_MANY_CODES,
    SKIP_MANY_CONTRACTS,
    SKIP_NO_CONTRACT,
    SKIP_OWNED,
    Holder,
    Seen,
    parse_args,
    seen_in_item,
    select_pairs,
)

JAN = Holder(1, 10, "Jan Przykładowy", date(2025, 1, 1), None)
ANNA = Holder(2, 20, "Anna Testowa-Wzorcowa", date(2026, 1, 1), None)


def _seen(code: str, person: str, month: str = "2026-05", invoice: int = 1) -> Seen:
    return Seen(code, person, month, invoice)


def test_dry_run_is_default():
    args = parse_args(["--client-id", "1"])

    assert args.apply is False
    assert args.review is None


def test_item_gives_person_and_code_with_and_without_colon():
    assert seen_in_item("Contractor Jan Przykładowy ID: X012345, NIDS: 1") == (
        "Jan Przykładowy",
        "X012345",
    )
    assert seen_in_item("Contractor Jan Przykładowy ID X012345") == (
        "Jan Przykładowy",
        "X012345",
    )


def test_item_without_code_or_with_name_in_id_gives_nothing():
    assert seen_in_item("Contractor Jan Przykładowy") is None
    assert seen_in_item("Contractor Jan Przykładowy ID: Jan") is None
    assert seen_in_item("Usługi IT, maj 2026") is None


def test_contact_marked_as_contractor_is_not_the_person():
    text = "Contractor Ewa Kliencka ID: X012345 Contact: Ewa Kliencka"

    assert seen_in_item(text) is None


def test_new_code_of_one_person_with_one_contract_is_paired():
    pairs, skipped = select_pairs(
        [
            _seen("X012345", "Jan Przykładowy", "2026-04", 1),
            _seen("X012345", "Jan Przykładowy", "2026-06", 2),
        ],
        [JAN, ANNA],
        [],
    )

    assert [(p.contract_id, p.code) for p in pairs] == [(1, "X012345")]
    assert pairs[0].valid_from == date(2026, 4, 1)
    assert pairs[0].valid_to == date(2026, 6, 30)
    assert pairs[0].invoices == 2
    assert not skipped


def test_shortened_double_surname_still_matches():
    pairs, _ = select_pairs([_seen("X022222", "Anna Testowa")], [JAN, ANNA], [])

    assert [(p.contract_id, p.code) for p in pairs] == [(2, "X022222")]


def test_code_already_in_registry_is_skipped_even_for_other_person():
    pairs, skipped = select_pairs(
        [_seen("X012345", "Jan Przykładowy")], [JAN, ANNA], [(2, "X012345")]
    )

    assert pairs == []
    assert skipped[SKIP_OWNED] == 1


def test_person_without_contract_is_skipped():
    pairs, skipped = select_pairs([_seen("X012345", "Piotr Nieznany")], [JAN], [])

    assert pairs == []
    assert skipped[SKIP_NO_CONTRACT] == 1


def test_name_matching_two_people_is_skipped():
    twin = Holder(3, 30, "Jan Przykładowy", date(2025, 1, 1), None)

    pairs, skipped = select_pairs(
        [_seen("X012345", "Jan Przykładowy")], [JAN, twin], []
    )

    assert pairs == []
    assert skipped[SKIP_AMBIGUOUS] == 1


def test_code_on_invoices_of_two_people_is_skipped():
    pairs, skipped = select_pairs(
        [
            _seen("X012345", "Jan Przykładowy"),
            _seen("X012345", "Anna Testowa-Wzorcowa"),
        ],
        [JAN, ANNA],
        [],
    )

    assert pairs == []
    assert skipped[SKIP_AMBIGUOUS] == 1


def test_person_with_two_codes_on_invoices_is_skipped():
    pairs, skipped = select_pairs(
        [_seen("X012345", "Jan Przykładowy"), _seen("X054321", "Jan Przykładowy")],
        [JAN],
        [],
    )

    assert pairs == []
    assert skipped[SKIP_MANY_CODES] == 2


def test_person_with_other_code_in_registry_is_skipped():
    pairs, skipped = select_pairs(
        [_seen("X054321", "Jan Przykładowy")], [JAN], [(1, "X012345")]
    )

    assert pairs == []
    assert skipped[SKIP_MANY_CODES] == 1


def test_two_contracts_pick_the_one_covering_invoices():
    old = Holder(4, 10, "Jan Przykładowy", date(2024, 1, 1), date(2025, 12, 31))
    new = Holder(5, 10, "Jan Przykładowy", date(2026, 1, 1), None)

    pairs, _ = select_pairs(
        [_seen("X012345", "Jan Przykładowy", "2026-05")], [old, new], []
    )

    assert [(p.contract_id, p.code) for p in pairs] == [(5, "X012345")]


def test_two_contracts_both_covering_invoices_are_skipped():
    one = Holder(4, 10, "Jan Przykładowy", date(2026, 1, 1), None)
    two = Holder(5, 10, "Jan Przykładowy", date(2026, 3, 1), None)

    pairs, skipped = select_pairs([_seen("X012345", "Jan Przykładowy")], [one, two], [])

    assert pairs == []
    assert skipped[SKIP_MANY_CONTRACTS] == 1
