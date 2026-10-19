"""Parowanie karty z Compassa z kontraktem i propozycje słownika — bez bazy.

Dane zmyślone (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date

from app.services.care.card_linking import ContractIndex, ContractRow, person_key
from app.services.care.skills import SkillDictionary, loose_key, suggester


def _row(contract_id: int, candidate_id: int, start, end, client_id: int = 1):
    return ContractRow(
        contract_id=contract_id,
        candidate_id=candidate_id,
        client_id=client_id,
        start=start,
        end=end,
    )


def test_person_key_ignores_case_diacritics_order_and_traffit_markers() -> None:
    key = person_key("Łukasz Żółwiński")
    assert key == person_key("ZOLWINSKI lukasz")
    assert key == person_key("Żółwiński Łukasz [ACTIVE]")
    assert key == person_key("  łukasz   żółwiński (zaakceptowany) ")
    assert person_key("Łukasz") == ""  # samo imię nie paruje
    assert person_key(None) == ""
    assert person_key("Anna Nowak") != person_key("Anna Nowakowska")


def test_one_contract_in_period_links_automatically() -> None:
    index = ContractIndex.build(
        [
            (_row(10, 1, date(2025, 1, 1), date(2025, 12, 31)), "Ewa Kot"),
            (_row(11, 1, date(2026, 1, 1), None), "Ewa Kot"),
            # Ta sama osoba u innego klienta nie przeszkadza.
            (_row(12, 2, date(2025, 1, 1), None, client_id=2), "Ewa Kot"),
        ]
    )
    match = index.match(1, "kot ewa", date(2025, 6, 1))
    assert (match.contract_id, match.state) == (10, "auto")
    assert match.contract_ids == (10,)
    later = index.match(1, "Ewa Kot", date(2026, 3, 1))
    assert later.contract_id == 11


def test_two_contracts_in_period_wait_for_confirmation() -> None:
    index = ContractIndex.build(
        [
            (_row(20, 1, date(2026, 1, 1), None), "Anna Nowak"),
            (_row(21, 2, date(2026, 3, 1), None), "Anna Nowak"),
        ]
    )
    match = index.match(1, "Anna Nowak", date(2026, 8, 10))
    assert match.contract_id is None
    assert match.state == "suggested"
    assert set(match.suggestions) == {20, 21}


def test_namesakes_with_one_contract_in_period_wait_for_confirmation() -> None:
    # Dwie różne osoby o tym samym nazwisku u klienta: umowa drugiej zaczyna
    # się w NEXUSIE później niż faktyczna praca, więc w dniu rozmowy „pasuje”
    # tylko pierwsza. Bez potwierdzenia karta wylądowałaby u obcej osoby.
    index = ContractIndex.build(
        [
            (_row(100, 1, date(2026, 1, 1), None), "Jan Kowalski"),
            (_row(200, 2, date(2026, 9, 1), None), "Jan Kowalski"),
        ]
    )
    match = index.match(1, "Jan Kowalski", date(2026, 8, 10))
    assert match.contract_id is None
    assert match.state == "suggested"
    assert set(match.suggestions) == {100, 200}


def test_contract_outside_period_is_only_a_suggestion_nearest_first() -> None:
    index = ContractIndex.build(
        [
            (_row(30, 1, date(2024, 1, 1), date(2024, 3, 31)), "Jan Kowal"),
            (_row(31, 1, date(2026, 5, 1), None), "Jan Kowal"),
        ]
    )
    match = index.match(1, "Jan Kowal", date(2026, 1, 15))
    assert match.contract_id is None
    assert match.suggestions == (31, 30)


def test_no_contract_with_that_name_means_no_suggestions() -> None:
    index = ContractIndex.build([(_row(40, 1, None, None), "Jan Kowal")])
    match = index.match(1, "Jan Kowalski", date(2026, 1, 1))
    assert (match.contract_id, match.suggestions, match.state) == (None, (), "none")
    assert index.match(1, None, date(2026, 1, 1)).state == "none"


def _dictionary(names: dict[int, str], aliases: dict[str, int] | None = None):
    by_key = {name.lower(): sid for sid, name in names.items()}
    by_key.update(aliases or {})
    return SkillDictionary(by_key=by_key, names=names, categories={})


def test_loose_key_drops_version_punctuation_and_case() -> None:
    assert loose_key("React.js 18") == "reactjs"
    assert loose_key("Spring-Boot") == "springboot"
    assert loose_key("C++") == "c++"
    assert loose_key("C#") == "c#"


def test_suggester_proposes_existing_skill_instead_of_a_duplicate() -> None:
    dictionary = _dictionary(
        {1: "React", 2: "Spring Boot", 3: "Node.js", 4: "C#", 5: "C++"},
        aliases={"nodejs": 3},
    )
    suggest = suggester(dictionary)
    assert suggest("ReactJS") == [1]
    assert suggest("spring-boot 3") == [2]
    assert suggest("NodeJS") == [3]
    assert suggest("C #") == [4]
    assert suggest("Zupełnie nowa platforma") == []


async def test_pool_member_without_care_role_sees_link_button(monkeypatch) -> None:
    # Trasa „Połącz” wpuszcza osobę z puli opiekunów (CareWriter), więc lista
    # musi pokazać jej przycisk — wcześniej liczyła samą rolą (False).
    from types import SimpleNamespace

    from app.api import contract_care
    from app.services.care import access, card_inbox, owner_pool

    async def fake_client(db, client_id, user):
        return SimpleNamespace(id=client_id)

    async def fake_cards(db, client_id):
        return {"items": []}

    async def fake_writers(db):
        return frozenset({7})

    monkeypatch.setattr(access, "load_client", fake_client)
    monkeypatch.setattr(card_inbox, "unlinked_cards", fake_cards)
    monkeypatch.setattr(owner_pool, "writer_ids", fake_writers)
    member = SimpleNamespace(id=7, has_any_role=lambda *roles: False)
    outsider = SimpleNamespace(id=8, has_any_role=lambda *roles: False)

    listed = await contract_care.client_unlinked_tech_cards(1, member, None)
    assert listed["can_link"] is True
    refused = await contract_care.client_unlinked_tech_cards(1, outsider, None)
    assert refused["can_link"] is False
