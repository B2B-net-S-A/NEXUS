"""Reguła tolerancji dopasowania osoby z PDF-a do kontraktu (ticket 09.2026).

Kryteria akceptacji ticketu „Automatyzacja tworzenia zamówień MD/Kosztowe":
* „Pawel Laski" w kontrakcie dopasowuje się automatycznie do „Paweł Łaski",
* „Active Jan Kowalski" dopasowuje się do „Jan Kowalski" z odznaką do potwierdzenia,
* „Jan Kowalczyk" NIE jest dopasowany do „Jan Kowalski",
* dwie różne osoby o tym samym imieniu i nazwisku u klienta → ręczny wybór.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.order_consultant_match import (
    MATCH_AMBIGUOUS,
    MATCH_AUTO,
    MATCH_CONFIRM,
    MATCH_INACTIVE,
    MATCH_NONE,
    ContractCandidate,
    match_names,
    resolve_contract,
    split_name,
)


def _contract(
    contract_id: int,
    name: str,
    *,
    candidate_id: int | None = None,
    status: str = "active",
    start: date | None = date(2025, 1, 1),
    end: date | None = None,
) -> ContractCandidate:
    return ContractCandidate(
        contract_id=contract_id,
        candidate_id=candidate_id if candidate_id is not None else contract_id,
        contractor_name=name,
        status=status,
        start_date=start,
        end_date=end,
    )


# ── Rdzeń i dopisek ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "prefix", "core"),
    [
        ("Active Jan Kowalski", "Active", ("jan", "kowalski")),
        ("UR – Jan Kowalski", "UR", ("jan", "kowalski")),
        ("Projekt 2 Jan Kowalski", "Projekt 2", ("jan", "kowalski")),
        ("Jan Kowalski", "", ("jan", "kowalski")),
        ("Anna Prus-Rudzińska", "", ("anna", "prus", "rudzinska")),
        ("jan kowalski", "", ("jan", "kowalski")),
    ],
)
def test_core_is_the_last_two_capitalized_words(value, prefix, core):
    parts = split_name(value)
    assert parts.prefix == prefix
    assert parts.core == core


# ── Poziomy dopasowania nazw ────────────────────────────────────────────────


def test_polish_diacritics_alone_are_an_automatic_match():
    match = match_names("Paweł Łaski", "Pawel Laski")
    assert match is not None and match.level == MATCH_AUTO


@pytest.mark.parametrize(
    ("document", "contract"),
    [
        ("Łukasz Goceł", "Lukasz Gocel"),
        ("JAN KOWALSKI", "Jan Kowalski"),
        ("Anna Prus-Rudzińska", "Anna Prus Rudzinska"),
    ],
)
def test_formatting_differences_are_automatic(document, contract):
    match = match_names(document, contract)
    assert match is not None and match.level == MATCH_AUTO


@pytest.mark.parametrize(
    ("contract", "prefix"),
    [
        ("Active Jan Kowalski", "Active"),
        ("UR – Jan Kowalski", "UR"),
        ("Projekt 2 Jan Kowalski", "Projekt 2"),
        ("Active Jan Kowalśki", "Active"),
    ],
)
def test_prefix_before_the_core_needs_confirmation(contract, prefix):
    match = match_names("Jan Kowalski", contract)
    assert match is not None
    assert match.level == MATCH_CONFIRM
    assert match.contract_prefix == prefix
    assert prefix in match.reason


@pytest.mark.parametrize(
    "contract",
    [
        "Jan Kowalczyk",  # inna końcówka nazwiska
        "Jan Kowlaski",  # przestawione litery
        "Janusz Kowalski",  # inne imię
        "Jan Kowalsky",  # inna litera
        "Active Jan Kowalczyk",  # dopisek nie ratuje różnicy w rdzeniu
        "Kowalski",  # samo nazwisko
    ],
)
def test_any_other_difference_in_the_core_is_not_a_match(contract):
    assert match_names("Jan Kowalski", contract) is None


def test_reversed_first_and_last_name_needs_confirmation():
    match = match_names("Kowalski Jan", "Jan Kowalski")
    assert match is not None
    assert match.level == MATCH_CONFIRM
    assert match.reversed_order is True


def test_prefix_in_the_document_is_tolerated_but_confirmed():
    match = match_names("Profil UR – Paweł Łaski", "Pawel Laski")
    assert match is not None
    assert match.level == MATCH_CONFIRM
    assert match.document_prefix == "Profil UR"


# ── Wybór kontraktu ─────────────────────────────────────────────────────────


def test_single_contract_with_identical_name_is_picked_automatically():
    result = resolve_contract(
        "Paweł Łaski",
        [_contract(1, "Pawel Laski"), _contract(2, "Krzysztof Suwała")],
    )
    assert result.status == MATCH_AUTO
    assert result.contract is not None and result.contract.contract_id == 1


def test_prefixed_contract_is_picked_but_needs_confirmation():
    result = resolve_contract("Jan Kowalski", [_contract(7, "Active Jan Kowalski")])
    assert result.status == MATCH_CONFIRM
    assert result.contract is not None and result.contract.contract_id == 7
    assert "Active" in result.reason


def test_similar_surname_is_never_picked_only_hinted():
    result = resolve_contract("Jan Kowalski", [_contract(3, "Jan Kowalczyk")])
    assert result.status == MATCH_NONE
    assert result.contract is None
    assert [c.contractor_name for c in result.nearest] == ["Jan Kowalczyk"]


def test_two_different_people_with_the_same_name_require_manual_choice():
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(10, "Jan Kowalski", candidate_id=100, start=date(2024, 3, 1)),
            _contract(11, "Jan Kowalski", candidate_id=101, start=date(2026, 2, 1)),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS
    assert result.contract is None
    assert {c.contract_id for c in result.options} == {10, 11}
    assert "różne osoby" in result.reason


def test_people_differing_only_by_diacritics_are_also_ambiguous():
    result = resolve_contract(
        "Łukasz Nowak",
        [
            _contract(20, "Łukasz Nowak", candidate_id=200),
            _contract(21, "Lukasz Nowak", candidate_id=201),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS


def test_second_person_with_a_draft_contract_still_blocks_the_automatic_pick():
    """Nowo zatrudniona osoba o tym samym nazwisku ma dopiero szkic kontraktu."""
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(30, "Jan Kowalski", candidate_id=300),
            _contract(31, "Jan Kowalski", candidate_id=301, status="draft"),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS


@pytest.mark.parametrize(
    "returning_name", ["Jan Kowalski", "Anna Jan Kowalski", "Active Jan Kowalski"]
)
def test_other_person_with_an_ended_contract_blocks_the_automatic_pick(
    returning_name,
):
    """Osoba B wraca po przerwie — PDF może dotyczyć właśnie jej, nie A."""
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(35, "Jan Kowalski", candidate_id=350),
            _contract(36, returning_name, candidate_id=360, status="ended"),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS
    assert {c.contract_id for c in result.options} == {35, 36}


def test_same_person_ended_contract_does_not_block_own_live_contract():
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(37, "Jan Kowalski", candidate_id=370),
            _contract(38, "Jan Kowalski", candidate_id=370, status="ended"),
        ],
    )
    assert result.status == MATCH_AUTO
    assert result.contract is not None and result.contract.contract_id == 37


def test_same_person_live_contract_wins_over_own_draft():
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(40, "Jan Kowalski", candidate_id=400),
            _contract(41, "Jan Kowalski", candidate_id=400, status="draft"),
        ],
    )
    assert result.status == MATCH_AUTO
    assert result.contract is not None and result.contract.contract_id == 40


def test_same_person_with_two_live_contracts_is_ambiguous():
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(50, "Jan Kowalski", candidate_id=500),
            _contract(51, "Jan Kowalski", candidate_id=500, status="ending"),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS
    assert {c.contract_id for c in result.options} == {50, 51}


def test_only_ended_contract_is_an_inactive_person_to_decide():
    """Zakończona współpraca nie jest cichym „potwierdź i wznów" (ticket 09.2026).

    Karta mówi wprost, że osoba nie ma już aktywnej współpracy, i każe wybrać:
    zapis historyczny, wznowienie, zastępstwo albo usunięcie z zamówienia.
    """
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(
                60,
                "Jan Kowalski",
                candidate_id=600,
                status="ended",
                end=date(2025, 6, 30),
            ),
            _contract(
                61,
                "Jan Kowalski",
                candidate_id=600,
                status="ended",
                end=date(2026, 3, 31),
            ),
        ],
    )
    assert result.status == MATCH_INACTIVE
    assert result.contract is not None and result.contract.contract_id == 61
    assert "„Jan Kowalski” nie ma już aktywnej współpracy" in result.reason
    assert "kontrakt zakończony 31.03.2026" in result.reason
    for choice in ("zapis historyczny", "wznów", "zastąp", "usuń z zamówienia"):
        assert choice in result.reason


def test_person_missing_from_the_system_is_named_in_the_message():
    result = resolve_contract("Adam Nieobecny", [_contract(70, "Jan Kowalski")])
    assert result.status == MATCH_NONE
    assert result.reason.startswith("Nie znaleziono „Adam Nieobecny” w systemie")
    assert "zastąp" in result.reason and "usuń z zamówienia" in result.reason


def test_two_people_with_only_ended_contracts_are_ambiguous():
    result = resolve_contract(
        "Jan Kowalski",
        [
            _contract(62, "Jan Kowalski", candidate_id=620, status="ended"),
            _contract(63, "Jan Kowalski", candidate_id=630, status="ended"),
        ],
    )
    assert result.status == MATCH_AMBIGUOUS


def test_void_like_unknown_statuses_are_ignored():
    result = resolve_contract(
        "Jan Kowalski", [_contract(70, "Jan Kowalski", status="void")]
    )
    assert result.status == MATCH_NONE


def test_document_without_a_name_needs_manual_choice():
    result = resolve_contract(None, [_contract(80, "Jan Kowalski")])
    assert result.status == MATCH_NONE
    assert "nie podaje imienia" in result.reason
