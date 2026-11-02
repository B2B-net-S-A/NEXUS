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
        "Important changes made to contract 285787",
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
