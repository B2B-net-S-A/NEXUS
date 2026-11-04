"""Sprawy ↔ kontrakt konsultanta — reguły bez bazy (decyzja 7, 22.10.2026).

* imię i nazwisko konsultanta w treści maila: bez wielkości liter, polskich
  znaków i kolejności słów, słowa obok siebie; samo imię i odmienione
  nazwisko nie wskazują nikogo,
* automat wpisuje kontrakt tylko przy DOKŁADNIE jednym kandydacie
  i uwierzytelnionym nadawcy (``Authentication-Results``),
* propozycje w kolejności siły dowodu, każdy kontrakt raz,
* checklista „Koniec współpracy” z pakietu klienta i stanu opieki,
* import z Compassa: klient po nazwie + osoba + dzień — pewny albo nic.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date

from app.services.admin_cases import rules
from app.services.admin_cases.contract_links import (
    MAX_SUGGESTIONS,
    REASON_CLIENT_MAIL,
    REASON_SENDER,
    REASON_TEXT,
    LiveContract,
    names_in_text,
    only_matches,
    rank_suggestions,
    sender_authenticated,
    sender_contract,
)
from app.services.care.card_linking import ContractIndex, ContractRow
from app.services.hr.compass_import.cases import ContractLinker

PEOPLE = {
    11: "Anna Przykładowa",
    12: "Łukasz Zażółć-Gęślą",
    13: "Jan Nowak",
}


def test_name_found_regardless_of_case_accents_and_order() -> None:
    text = "Dzień dobry, w sprawie PRZYKLADOWA anna — prośba o aneks."
    assert names_in_text(text, PEOPLE) == [11]
    assert names_in_text("Pan lukasz zazolc gesla prosi o kontakt", PEOPLE) == [12]


def test_name_needs_both_words_next_to_each_other() -> None:
    assert names_in_text("Anna dzwoniła. Potem Przykładowa pisała.", PEOPLE) == []
    assert names_in_text("Rozmawiałam z Anną", PEOPLE) == []
    # Odmienione nazwisko nie wskazuje nikogo — lepiej brak propozycji niż zła.
    assert names_in_text("Umowa Jana Nowaka", PEOPLE) == []
    assert names_in_text("Umowa: Jan Nowak, Anna Przykładowa", PEOPLE) == [11, 13]


def test_single_word_name_is_never_a_person() -> None:
    assert names_in_text("Anna", {21: "Anna"}) == []


def test_sender_link_only_for_exactly_one_contract() -> None:
    assert sender_contract([7]) == 7
    assert sender_contract([7, 7]) == 7
    assert sender_contract([7, 8]) is None
    assert sender_contract([]) is None


def _live(cid: int, name: str) -> LiveContract:
    return LiveContract(
        contract_id=cid, client_id=1, candidate_name=name, client_name="Klient"
    )


def test_suggestions_are_ranked_and_deduplicated() -> None:
    contracts = {cid: _live(cid, name) for cid, name in PEOPLE.items()}
    out = rank_suggestions(
        by_sender=[12],
        client_named=[12, 11],
        text_named=[13, 99],
        contracts=contracts,
    )
    assert [item["contract_id"] for item in out] == [12, 11, 13]
    assert out[0]["reason"] == REASON_SENDER
    assert out[1]["reason"] == REASON_CLIENT_MAIL.format(name="Anna Przykładowa")
    assert out[2]["reason"] == REASON_TEXT.format(name="Jan Nowak")
    many = {cid: _live(cid, f"Osoba Numer{cid}") for cid in range(1, 20)}
    assert (
        len(
            rank_suggestions(
                by_sender=list(many), client_named=[], text_named=[], contracts=many
            )
        )
        == MAX_SUGGESTIONS
    )


def test_suggestion_says_who_wrote_and_whether_the_name_is_unique() -> None:
    """„Kogo dotyczy?” (S4): kontakt klienta i „jedyny nasz konsultant o tym
    nazwisku u tego klienta”; dwie takie same osoby u klienta — nie jedyny."""

    contracts = {
        11: LiveContract(11, 1, "Anna Przykładowa", "Telekom Wzorcowy"),
        12: LiveContract(12, 1, "Jan Nowak", "Telekom Wzorcowy"),
        13: LiveContract(13, 1, "Nowak Jan", "Telekom Wzorcowy"),
        14: LiveContract(14, 2, "Anna Przykładowa", "Bank Przykładowy"),
    }
    assert only_matches([11, 12, 13, 14, 99], contracts) == {11, 14}
    out = rank_suggestions(
        by_sender=[14],
        client_named=[11, 12],
        text_named=[13],
        contracts=contracts,
        sender_contacts={1: "Katarzyna Kierownicza"},
    )
    by_id = {item["contract_id"]: item for item in out}
    assert by_id[11]["sender_kind"] == "client_contact"
    assert by_id[11]["sender_contact_name"] == "Katarzyna Kierownicza"
    assert by_id[11]["only_match"] is True
    assert by_id[12]["only_match"] is False
    assert by_id[13]["sender_kind"] is None
    assert by_id[13]["sender_contact_name"] is None
    assert by_id[14]["sender_kind"] == "consultant"
    assert by_id[14]["sender_contact_name"] is None


def test_end_checklist_from_pack_and_care_state() -> None:
    ours = rules.end_of_cooperation_checklist(
        equipment_ours=True,
        accesses=["Konto VPN", " Konto  VPN ", "Jira"],
        feedback_done=True,
    )
    texts = [item["text"] for item in ours]
    assert texts == [
        rules.END_EQUIPMENT_ITEM,
        f"{rules.END_ACCESS_PREFIX}Konto VPN",
        f"{rules.END_ACCESS_PREFIX}Jira",
        rules.END_FEEDBACK_ITEM,
        rules.END_DECISION_ITEM,
        rules.END_SETTLEMENT_ITEM,
    ]
    done = {item["text"]: item["done"] for item in ours}
    assert done[rules.END_FEEDBACK_ITEM] is True
    assert done[rules.END_DECISION_ITEM] is False

    theirs = rules.end_of_cooperation_checklist(
        equipment_ours=False, accesses=[], decision_done=True
    )
    texts = [item["text"] for item in theirs]
    assert rules.END_EQUIPMENT_ITEM not in texts
    assert rules.END_ACCESS_GENERIC in texts
    assert {i["text"]: i["done"] for i in theirs}[rules.END_DECISION_ITEM] is True


def test_end_checklist_stays_within_limits() -> None:
    items = rules.end_of_cooperation_checklist(
        equipment_ours=True,
        accesses=[f"Dostęp {n} " + "x" * 400 for n in range(80)],
    )
    assert len(items) <= rules.CHECKLIST_MAX_ITEMS
    assert all(len(item["text"]) <= rules.CHECKLIST_TEXT_MAX for item in items)
    assert items[-1]["text"] == rules.END_SETTLEMENT_ITEM


def _linker(rows: list[tuple[ContractRow, str]], clients: dict[str, set[int]]):
    return ContractLinker(
        by_key=clients,
        by_loose={},
        by_words={},
        index=ContractIndex.build(rows),
    )


def _row(cid: int, candidate: int, client: int, start: date, end=None):
    return ContractRow(
        contract_id=cid, candidate_id=candidate, client_id=client, start=start, end=end
    )


def test_compass_case_links_only_a_sure_contract() -> None:
    from app.services.client_portfolio_import import normalize_client_name

    key = normalize_client_name("Firma Przykładowa")
    day = date(2026, 9, 1)
    linker = _linker(
        [
            (_row(1, 100, 5, date(2026, 1, 1)), "Ewa Testowa"),
            (_row(2, 200, 5, date(2026, 1, 1)), "Jan Testowy"),
            (_row(3, 300, 5, date(2026, 1, 1)), "Jan Testowy"),  # imiennik
        ],
        {key: {5}},
    )
    assert linker.contract_for("Firma Przykładowa", "testowa ewa", day) == 1
    assert linker.contract_for("Firma Przykładowa", "Jan Testowy", day) is None
    assert linker.contract_for("Inna Firma", "Ewa Testowa", day) is None
    assert linker.contract_for("Firma Przykładowa", None, day) is None
    # Dzień przed startem umowy — tylko propozycja przy odczycie, nie kontrakt.
    assert (
        linker.contract_for("Firma Przykładowa", "Ewa Testowa", date(2025, 6, 1))
        is None
    )


def test_compass_duplicate_client_resolved_by_the_sure_contract() -> None:
    from app.services.client_portfolio_import import normalize_client_name

    key = normalize_client_name("PFRON")
    day = date(2026, 9, 1)
    linker = _linker(
        [(_row(9, 900, 8, date(2026, 1, 1)), "Ola Przykładowa")], {key: {7, 8}}
    )
    assert linker.contract_for("PFRON", "Ola Przykładowa", day) == 9


# ── Uwierzytelniony nadawca (audyt bezpieczeństwa 22.10.2026) ────────────────

_EOP_PASS = (
    "spf=pass (sender IP is 192.0.2.10) smtp.mailfrom=example.com; "
    "dkim=pass (signature was verified) header.d=example.com;"
    "dmarc=pass action=none header.from=example.com;compauth=pass reason=100"
)


def _auth(value: str) -> list[dict[str, str]]:
    return [{"name": "Authentication-Results", "value": value}]


def test_dmarc_pass_for_sender_domain_authenticates() -> None:
    assert sender_authenticated(_auth(_EOP_PASS), "anna@example.com")
    assert sender_authenticated(
        _auth("mx.example.net; dmarc=pass header.from=example.com"),
        "anna@mail.example.com",
    )


def test_spf_and_dkim_pass_without_dmarc_authenticate() -> None:
    value = (
        "spf=pass smtp.mailfrom=bounce@example.com; "
        "dkim=pass header.d=example.com; dmarc=none header.from=example.com"
    )
    assert sender_authenticated(_auth(value), "anna@example.com")
    only_spf = "spf=pass smtp.mailfrom=example.com; dkim=none"
    assert not sender_authenticated(_auth(only_spf), "anna@example.com")


def test_failed_or_foreign_domain_results_do_not_authenticate() -> None:
    failed = (
        "spf=fail smtp.mailfrom=example.com; dkim=none; "
        "dmarc=fail action=quarantine header.from=example.com"
    )
    assert not sender_authenticated(_auth(failed), "anna@example.com")
    # Przechodzi, ale dla innej domeny niż ``From``.
    foreign = "dmarc=pass header.from=attacker.example; spf=pass smtp.mailfrom=attacker.example"
    assert not sender_authenticated(_auth(foreign), "anna@example.com")
    assert not sender_authenticated(_auth(_EOP_PASS), "anna@notexample.com")


def test_missing_header_or_sender_does_not_authenticate() -> None:
    assert not sender_authenticated([], "anna@example.com")
    assert not sender_authenticated(None, "anna@example.com")
    assert not sender_authenticated(
        [{"name": "In-Reply-To", "value": "<x@example.com>"}], "anna@example.com"
    )
    assert not sender_authenticated(_auth(_EOP_PASS), None)


def test_only_the_topmost_header_counts() -> None:
    """Niższy nagłówek mógł wstawić nadawca — liczy się ten od bramki."""

    headers = [
        {
            "name": "Authentication-Results",
            "value": "dmarc=fail header.from=example.com",
        },
        {"name": "Authentication-Results", "value": _EOP_PASS},
    ]
    assert not sender_authenticated(headers, "anna@example.com")


# ── Zakres czytającego i tytuły spraw w opiece (audyt 22.10.2026) ────────────


def test_consultant_section_out_of_scope_keeps_only_person_and_client() -> None:
    from app.services.admin_cases.queries import CARE_ONLY_FIELDS, redact_out_of_scope

    section = {
        "contract_id": 1,
        "candidate_name": "Anna Przykładowa",
        "client_name": "Przykład sp. z o.o.",
        "owner_user_id": 5,
        "owner_name": "Opiekun Przykładowy",
        "cadence_label": "co miesiąc",
        "last_conversation": {"on": "2026-10-01", "excerpt": None},
        "other_open_cases": 2,
        "health": {"level": "risk"},
    }
    assert redact_out_of_scope(section, in_scope=True) == section
    hidden = redact_out_of_scope(section, in_scope=False)
    assert all(hidden[key] is None for key in CARE_ONLY_FIELDS)
    assert hidden["candidate_name"] == "Anna Przykładowa"
    assert hidden["client_name"] == "Przykład sp. z o.o."


def test_client_scope_helper() -> None:
    from app.services.care.access import client_in_scope

    assert client_in_scope(3, None)
    assert client_in_scope(3, frozenset({3}))
    assert not client_in_scope(4, frozenset({3}))
    assert not client_in_scope(3, frozenset())


def test_case_title_replaced_without_may_read(monkeypatch) -> None:
    from app.models.admin_case import AdminCase
    from app.services.admin_cases import queries

    talk = AdminCase(id=1, title="Nowa stawka od stycznia", area="negotiation")
    plain = AdminCase(id=2, title="Laptop dla Anny", area="administration")
    monkeypatch.setattr(queries, "may_read", lambda viewer, case: False)
    assert queries.redact_case_title(talk, object()) == "Sprawa: Negocjacje"
    assert queries.redact_case_title(plain, object()) == "Sprawa: Administracja"
    monkeypatch.setattr(queries, "may_read", lambda viewer, case: True)
    assert queries.redact_case_title(talk, object()) is None
