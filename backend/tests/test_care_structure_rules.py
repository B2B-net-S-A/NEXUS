"""Reguły propozycji struktury u klienta (bez bazy) — „Propozycja automatu + akcept DL”."""

from __future__ import annotations

import pytest

from app.services.care import structure_rules as rules
from app.services.care.structure_rules import (
    ContactIndex,
    ContractFacts,
    PeerManager,
    PersonRow,
    Signal,
)

ANNA = PersonRow(
    id=1,
    name="Anna Nowak",
    position="Kierownik Zespołu Płatności",
    email="anna.nowak@klient.example",
)
JAN = PersonRow(id=2, name="Jan Kowalski", position="Dyrektor Departamentu IT")
EWA = PersonRow(id=3, name="Ewa Zielińska", position="Head of Data")
PIOTR = PersonRow(id=4, name="Piotr Wiśniewski", position="CTO")
PEOPLE = (ANNA, JAN, EWA, PIOTR)


def facts(**kwargs) -> ContractFacts:
    return ContractFacts(
        contract_id=kwargs.pop("contract_id", 100), client_id=10, **kwargs
    )


def propose(f: ContractFacts, peers=(), people=PEOPLE) -> rules.Proposal:
    return rules.decide(rules.manager_signals(f, ContactIndex(people), peers=peers))


@pytest.mark.parametrize(
    ("position", "rank"),
    [
        (None, None),
        ("   ", None),
        ("Senior Java Developer", 1),
        ("Kierownik Zespołu Rozwoju", 2),
        ("Team Leader", 2),
        ("Menedżer projektu", 2),
        ("Dyrektor Departamentu", 3),
        ("Head of Data", 3),
        ("Dyrektor Generalny", 4),
        ("Członek Zarządu", 4),
        ("Chief Data Officer", 4),
        ("CTO", 4),
    ],
)
def test_title_rank(position, rank) -> None:
    assert rules.title_rank(position) == rank


def test_line_manager_text_is_a_certain_proposal_with_its_source() -> None:
    proposal = propose(facts(line_manager="  anna   NOWAK "))
    assert proposal.confidence == "certain"
    assert proposal.contact_id == ANNA.id
    assert [s.source for s in proposal.top.signals] == ["line_manager"]
    assert proposal.top.signals[0].detail == "anna NOWAK"


def test_name_matching_ignores_word_order_and_diacritics() -> None:
    proposal = propose(facts(client_pm_name="Zielinska Ewa"))
    assert proposal.contact_id == EWA.id
    assert proposal.confidence == "certain"


def test_first_name_or_initial_points_to_nobody() -> None:
    assert propose(facts(line_manager="Anna")).confidence == "none"
    assert propose(facts(line_manager="Anna N.")).confidence == "none"


def test_pm_email_points_to_the_contact_with_that_address() -> None:
    proposal = propose(facts(client_pm_email=" Anna.Nowak@klient.example "))
    assert proposal.contact_id == ANNA.id
    assert proposal.confidence == "certain"


def test_hiring_manager_alone_is_never_certain() -> None:
    """Często menedżer to NIE hiring manager — HM sam daje propozycję niepewną."""

    proposal = propose(
        facts(job_id=7, job_title="Java Developer", job_hm_contact_id=JAN.id)
    )
    assert proposal.contact_id == JAN.id
    assert proposal.confidence == "uncertain"


def test_hiring_manager_and_order_contact_agreeing_make_it_certain() -> None:
    proposal = propose(
        facts(job_id=7, job_hm_contact_id=JAN.id, order_contacts=("Jan Kowalski",))
    )
    assert proposal.confidence == "certain"
    assert proposal.top.score == 4


def test_two_strong_sources_pointing_at_different_people_are_uncertain() -> None:
    proposal = propose(facts(line_manager="Anna Nowak", client_pm_name="Jan Kowalski"))
    assert proposal.confidence == "uncertain"
    assert {c.contact_id for c in proposal.candidates} == {ANNA.id, JAN.id}


def test_strong_source_beats_a_weaker_conflicting_one() -> None:
    proposal = propose(
        facts(line_manager="Anna Nowak", job_id=7, job_hm_contact_id=JAN.id)
    )
    assert proposal.confidence == "certain"
    assert proposal.contact_id == ANNA.id
    assert proposal.candidates[1].contact_id == JAN.id


def test_order_sender_alone_stays_uncertain() -> None:
    proposal = propose(facts(order_senders=("anna.nowak@klient.example",)))
    assert proposal.confidence == "uncertain"


def test_the_same_source_counts_once_per_person() -> None:
    """Pięć zamówień z tą samą osobą kontaktową to jedno źródło, nie pięć."""

    proposal = propose(facts(order_contacts=("Jan Kowalski",) * 5))
    assert proposal.top.score == rules.MANAGER_WEIGHTS["order_contact"]
    assert proposal.confidence == "uncertain"


def test_hiring_manager_of_another_client_is_ignored() -> None:
    proposal = propose(facts(job_id=7, job_hm_contact_id=999))
    assert proposal.confidence == "none"


def test_colleagues_from_the_same_team_and_recruitment_point_to_their_manager() -> None:
    peers = (
        PeerManager(
            contract_id=200,
            manager_id=EWA.id,
            team_name="Data Platform",
            job_id=8,
            job_title="Data Engineer",
        ),
    )
    proposal = propose(
        facts(team_name=" data  platform", job_id=8, job_title="Data Engineer"),
        peers=peers,
    )
    assert proposal.contact_id == EWA.id
    assert {s.source for s in proposal.top.signals} == {"same_team", "same_job"}
    assert proposal.confidence == "certain"


def test_a_contract_is_not_its_own_peer() -> None:
    peers = (
        PeerManager(
            contract_id=100,
            manager_id=EWA.id,
            team_name="Data",
            job_id=None,
            job_title=None,
        ),
    )
    assert propose(facts(team_name="Data"), peers=peers).confidence == "none"


def test_sole_manager_of_the_consultants_area_is_a_stronger_hint() -> None:
    people = (
        PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5),
        PersonRow(id=2, name="Jan Kowalski", position="Analityk", area_id=5),
    )
    proposal = propose(facts(area_id=5, area_name="Płatności"), people=people)
    assert proposal.contact_id == 1
    assert proposal.top.score == rules.AREA_SOLE_WEIGHT
    assert proposal.confidence == "uncertain"


def test_several_managers_in_the_area_are_weak_hints_each() -> None:
    people = (
        PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5),
        PersonRow(id=2, name="Jan Kowalski", position="Team Lead", area_id=5),
    )
    proposal = propose(facts(area_id=5), people=people)
    assert [c.score for c in proposal.candidates] == [1, 1]


def test_no_data_means_no_proposal() -> None:
    assert propose(facts()).confidence == "none"
    assert propose(facts()).top is None


def test_rank_candidates_breaks_ties_by_number_of_sources_then_id() -> None:
    signals = [
        Signal("job_hiring_manager", 5, 2),
        Signal("order_sender", 3, 1),
        Signal("order_sender", 4, 1),
        Signal("same_team", 4, 1),
    ]
    ranked = rules.rank_candidates(signals)
    assert [c.contact_id for c in ranked] == [4, 5, 3]


# ── Przełożony osoby klienta ────────────────────────────────────────────────


def test_unique_superior_one_level_up_in_the_department_is_certain() -> None:
    lead = PersonRow(id=1, name="Anna Nowak", position="Kierownik Zespołu", area_id=5)
    director = PersonRow(
        id=2, name="Jan Kowalski", position="Dyrektor Płatności", area_id=5
    )
    other = PersonRow(
        id=3, name="Ewa Zielińska", position="Dyrektor Kredytów", area_id=6
    )
    proposal = rules.decide(rules.reports_to_signals(lead, (lead, director, other)))
    assert proposal.confidence == "certain"
    assert proposal.contact_id == director.id


def test_department_text_works_when_the_area_is_not_set() -> None:
    lead = PersonRow(id=1, name="Anna Nowak", position="Team Lead", department="Data")
    head = PersonRow(
        id=2, name="Jan Kowalski", position="Head of Data", department=" data "
    )
    proposal = rules.decide(rules.reports_to_signals(lead, (lead, head)))
    assert proposal.contact_id == head.id


def test_two_superiors_at_the_same_level_are_uncertain() -> None:
    lead = PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5)
    a = PersonRow(id=2, name="Jan Kowalski", position="Dyrektor", area_id=5)
    b = PersonRow(id=3, name="Ewa Zielińska", position="Head of Payments", area_id=5)
    proposal = rules.decide(rules.reports_to_signals(lead, (lead, a, b)))
    assert proposal.confidence == "uncertain"
    assert len(proposal.candidates) == 2


def test_skipping_a_level_is_uncertain() -> None:
    lead = PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5)
    board = PersonRow(id=2, name="Jan Kowalski", position="Członek Zarządu", area_id=5)
    proposal = rules.decide(rules.reports_to_signals(lead, (lead, board)))
    assert proposal.confidence == "uncertain"


def test_director_without_department_candidate_gets_weak_board_hint() -> None:
    director = PersonRow(id=1, name="Anna Nowak", position="Dyrektor IT", area_id=5)
    cto = PersonRow(id=2, name="Jan Kowalski", position="CTO", area_id=9)
    proposal = rules.decide(rules.reports_to_signals(director, (director, cto)))
    assert proposal.contact_id == cto.id
    assert proposal.top.score == rules.TITLE_COMPANY


def test_candidate_already_below_the_person_is_never_proposed() -> None:
    """Zatwierdzenie zamknęłoby pętlę — kandydat odpada przed policzeniem."""

    lead = PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5)
    director = PersonRow(
        id=2, name="Jan Kowalski", position="Dyrektor", area_id=5, reports_to_id=1
    )
    assert rules.reports_to_signals(lead, (lead, director)) == []


def test_unknown_title_gets_only_the_hiring_manager_hint() -> None:
    person = PersonRow(id=1, name="Anna Nowak", area_id=5)
    director = PersonRow(id=2, name="Jan Kowalski", position="Dyrektor", area_id=5)
    assert rules.reports_to_signals(person, (person, director)) == []
    signals = rules.reports_to_signals(
        person, (person, director), hm_of_team=[(2, "Java")]
    )
    assert [(s.source, s.contact_id) for s in signals] == [("hm_of_team", 2)]


def test_hiring_manager_below_the_person_is_not_a_superior() -> None:
    director = PersonRow(id=1, name="Anna Nowak", position="Dyrektor", area_id=5)
    lead = PersonRow(id=2, name="Jan Kowalski", position="Kierownik", area_id=5)
    assert (
        rules.reports_to_signals(director, (director, lead), hm_of_team=[(2, "Java")])
        == []
    )


def test_title_and_hiring_manager_agreeing_add_up() -> None:
    lead = PersonRow(id=1, name="Anna Nowak", position="Kierownik", area_id=5)
    a = PersonRow(id=2, name="Jan Kowalski", position="Dyrektor", area_id=5)
    b = PersonRow(id=3, name="Ewa Zielińska", position="Dyrektor", area_id=5)
    proposal = rules.decide(
        rules.reports_to_signals(lead, (lead, a, b), hm_of_team=[(2, "Java")])
    )
    assert proposal.contact_id == 2
    assert proposal.confidence == "certain"


def test_chain_reaches_survives_a_loop_in_old_data() -> None:
    chain = {1: 2, 2: 1, 3: None}
    assert rules.chain_reaches(chain, start_id=1, target_id=2)
    assert not rules.chain_reaches(chain, start_id=1, target_id=3)


# ── Nic nie wychodzi do klienta ─────────────────────────────────────────────


def test_feedback_requests_and_proposals_have_no_outbound_channel() -> None:
    """Prośby o opinię liczą się przy odczycie (D10) — żadna z tych ścieżek nie
    wysyła maila. Propozycje struktury dają tylko dzwonek w NEXUSIE dla DL.
    Wysyłka do menedżerów u klienta wymaga zgody Artura i osobnej zmiany."""

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    outbound = (
        "announcement_mail",
        "hr_mail",
        "send_mail",
        "send_email",
        "sendMail",
        "graph_mail",
        "outbox",
        "smtp",
    )
    for relative in (
        "services/care/client_people.py",
        "services/care/client_feedback.py",
        "services/care/structure_rules.py",
        "services/care/structure_proposals.py",
        "api/care_structure.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        for word in outbound:
            assert word not in source, f"{relative}: {word}"


def test_reminder_message_counts_in_polish() -> None:
    from app.services.care.structure_proposals import reminder_message

    assert reminder_message("Bank", {"open": 1, "certain": 0}) == (
        "Bank: 1 konsultant bez menedżera u klienta."
    )
    assert reminder_message("Bank", {"open": 3, "certain": 2}) == (
        "Bank: 3 konsultantów bez menedżera u klienta, 2 pewne propozycje do zatwierdzenia."
    )
    assert reminder_message("Bank", {"open": 12, "certain": 12}).endswith(
        "12 pewnych propozycji do zatwierdzenia."
    )
