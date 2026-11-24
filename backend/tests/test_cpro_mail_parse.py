"""Odczyt maili CPro: tematy i treści w budowie z maili produkcyjnych, dane fikcyjne."""

from app.services import cpro_mail_parse as parse_module
from app.services.cpro_mail_parse import parse

FOOTER = (
    "This email is sent from CPro, Nordea's consultant procurement system. "
    "Please contact consultant.procurement@nordea.com if you are not the correct recipient."
)


def test_closed_with_reason():
    event = parse(
        "Windows Expert - Testowy Program was closed. (41000)",
        "Dear Supplier,Request has now been closed.Show request (41000)"
        f"Close reason: consultant contracted--Anna TestNordea Bank Abp {FOOTER}",
    )
    assert event.kind == parse_module.KIND_CLOSED
    assert event.request == "41000"
    assert event.reason == "consultant contracted"


def test_closed_with_empty_body_keeps_request_without_reason():
    event = parse("PL_IT Analyst was closed. (41001)", "")
    assert (event.kind, event.request, event.reason) == (
        parse_module.KIND_CLOSED,
        "41001",
        None,
    )


def test_closed_without_number_is_ignored():
    assert parse("Some project was closed.", "") is None


def test_rejected_with_reason():
    event = parse(
        "Rejected: Jan Testowy (43084)",
        "Urgent Rejected: Jan Testowy (43084) Profile do not match request "
        f"Offer: Jan Testowy, Request: 43084 - AMLAShow Offer {FOOTER}",
    )
    assert event.kind == parse_module.KIND_REJECTED
    assert event.person == "Jan Testowy"
    assert event.request == "43084"
    assert event.reason == "Profile do not match request"


def test_rejected_strips_role_after_name():
    event = parse("Rejected: Jan Testowy - IT Analyst (42000)", "")
    assert event.person == "Jan Testowy"
    assert event.request == "42000"


def test_interview_request():
    event = parse("I would like to interview Jan Testowy, Request 43031", "")
    assert event.kind == parse_module.KIND_INTERVIEW
    assert event.person == "Jan Testowy"
    assert event.request == "43031"


def test_interview_withdrawn_takes_details_from_body():
    event = parse(
        "Interview has been withdrawn",
        "HiThe requester has withdrawn the interview.Consultant: Jan Testowy"
        f"Request:Show request - System Engineer C/C++ (43031)--Anna Test {FOOTER}",
    )
    assert event.kind == parse_module.KIND_INTERVIEW_WITHDRAWN
    assert event.person == "Jan Testowy"
    assert event.request == "43031"


def test_slots_changed_takes_details_from_body():
    event = parse(
        "Interview slots have changed on the interview",
        "HiThe requester has changed slots.Show interviewConsultant: Jan Testowy"
        f"Request:Show request - Tester (Senior) (43032)--Anna Test {FOOTER}",
    )
    assert event.kind == parse_module.KIND_SLOTS_CHANGED
    assert event.request == "43032"


def test_other_cpro_subjects_do_nothing():
    for subject in (
        "Offer: Jan Testowy",
        "Re: Jan Testowy",
        "Jan Testowy",
        "Request: PAM Developer (43147)",
        "Contract terminated: 284527 - Change Manager",
        "FW: Important changes made to contract 285787",
        "Important changes made to contract",
        "You have 1 contract extensions to handle",
        'No offers on request for over a month "Tester (42929)"',
        "SKILLS MATCHING",
        "",
    ):
        assert parse(subject, "cokolwiek") is None


def test_withdrawal_is_recognised_in_reason():
    assert parse_module.is_withdrawal("Candidate withdrew.")
    assert parse_module.is_withdrawal("consultant has withdrawn")
    assert not parse_module.is_withdrawal("Profile not matching")
    assert not parse_module.is_withdrawal(None)


def test_link_host_is_required():
    assert parse_module.has_cpro_link('<a href="https://nordea.onevms.se/x">Show</a>')
    assert not parse_module.has_cpro_link('<a href="https://evil.example/x">Show</a>')
    assert not parse_module.has_cpro_link(None)


def test_name_comparison_ignores_case_and_spacing():
    assert parse_module.normalized_name(
        " JAN  Testowy "
    ) == parse_module.normalized_name("jan testowy")


# Zmiana referencji faktury w CPro (24.11.2026). Budowa z maili produkcyjnych:
# linie „<Pole> was updated from: X, to: Y” rozdzielone <br>, link do kontraktu.
CHANGE_INTRO = (
    "Please update your invoice reference details with the information provided below"
)
CHANGE_TAIL = (
    "Anna TestA - PL - IT Developer (283051)** This is an auto-generated "
    f"notification email, triggered from an event in CPro **--Anna Test {FOOTER}"
)


def test_invoice_address_change_from_graph_text():
    event = parse(
        "Important changes made to contract 283051",
        f"{CHANGE_INTRO}\n\nInvoice address was updated from: F218 Nordea Bank Abp "
        "S.A., to: F206 Nordea Bank Abp Finland\nCost center was updated from: 1, "
        f"to: 2\n\n\n{CHANGE_TAIL}",
    )
    assert event.kind == parse_module.KIND_INVOICE_ADDRESS
    assert event.request == "283051"
    assert event.invoice_code == "F206"
    assert event.reason == ("F218 Nordea Bank Abp S.A. → F206 Nordea Bank Abp Finland")
    assert event.person is None


def test_invoice_address_change_from_stored_text_without_line_breaks():
    # ``emails.body_text`` gubi <br>: pola i link stoją jednym ciągiem.
    event = parse(
        "Important changes made to contract 283051",
        f"{CHANGE_INTRO}Invoice address was updated from: F218 Nordea Bank Abp S.A., "
        "to: F206 Nordea Bank Abp FinlandResponsible line manager was updated "
        f"from: Jan Testowy, to: Ewa Testowa (ewa@example.com){CHANGE_TAIL}",
    )
    assert event.kind == parse_module.KIND_INVOICE_ADDRESS
    assert event.invoice_code == "F206"
    assert event.reason.startswith("F218 Nordea Bank Abp S.A. → F206 Nordea Bank Abp")
    assert "Testow" not in event.reason


def test_other_contract_changes_are_logged_without_values():
    event = parse(
        "Important changes made to contract 285775",
        f"{CHANGE_INTRO}NIIDS No / Initiative ID / Appl.code was updated from: "
        "2018-000046, to: 2026-001933\nResponsible line manager was updated from: "
        "Jan Testowy, to: Ewa Testowa (ewa@example.com)\nCost center was updated "
        f"from: 1050000273, to: 2080009273\n{CHANGE_TAIL}",
    )
    assert event.kind == parse_module.KIND_CONTRACT_CHANGED
    assert event.request == "285775"
    assert event.invoice_code is None
    # Nazwiska i numery zostają w CPro: dziennik mówi tylko, co się zmieniło.
    assert event.reason == "NIIDS, line manager, cost center"


def test_contract_change_without_known_field_keeps_number():
    event = parse("Important changes made to contract 285787", "cokolwiek")
    assert (event.kind, event.request, event.reason, event.invoice_code) == (
        parse_module.KIND_CONTRACT_CHANGED,
        "285787",
        None,
        None,
    )


def test_invoice_address_without_code_still_goes_to_finance():
    # Bez kodu adresu (F206) NEXUS nie wie, którego nabywcy szukać — ale to nadal
    # zmiana nabywcy: idzie do „Do ręcznego” z dzwonkiem, nie do „Bez zmian”.
    event = parse(
        "Important changes made to contract 283051",
        f"{CHANGE_INTRO}Invoice address was updated from: Nordea Bank Abp S.A., "
        "to: Nordea Bank Abp Finland",
    )
    assert event.kind == parse_module.KIND_INVOICE_ADDRESS
    assert event.invoice_code is None
    assert event.reason == "Nordea Bank Abp S.A. → Nordea Bank Abp Finland"


def test_invoice_address_with_line_break_after_comma():
    event = parse(
        "Important changes made to contract 283051",
        f"{CHANGE_INTRO}\nInvoice address was updated from: F218 Nordea Bank Abp S.A.,"
        "\nto: F206 Nordea Bank Abp Finland\n",
    )
    assert (event.kind, event.invoice_code) == (
        parse_module.KIND_INVOICE_ADDRESS,
        "F206",
    )


def test_invoice_address_with_code_in_brackets():
    event = parse(
        "Important changes made to contract 283051",
        f"{CHANGE_INTRO}\nInvoice address was updated from: Nordea Bank Abp S.A. (F218), "
        "to: Nordea Bank Abp Finland (F206)\n",
    )
    assert (event.kind, event.invoice_code) == (
        parse_module.KIND_INVOICE_ADDRESS,
        "F206",
    )
