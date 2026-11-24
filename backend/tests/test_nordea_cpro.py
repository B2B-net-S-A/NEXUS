"""Powiadomienia portalu Nordei CPro (``admin_cases/nordea_cpro``) i ich ślad w regułach końca.

Maile fikcyjne, w układzie powiadomień CPro z archiwum administracja@ i poczty
DL-i Nordei (2023–2026): numery CoA, nazwiska i adresy zmyślone, bo repo jest
publiczne.
"""

from datetime import date

from app.services.admin_cases import nordea_cpro as cpro
from app.services.admin_cases import nordea_cpro_case as plan
from app.services.admin_cases import notice_rules as r
from app.services.back_office import triage

TODAY = date(2026, 11, 24)

TERMINATED_FORWARD = (
    "Hej, DW. Internalizacja?\n\n"
    "From: NOREPLY CPro <noreply@onevms.se>\n"
    "Sent: Monday, September 14, 2026 1:16 PM\n"
    "To: consultant.procurement@nordea.com; line.manager@example.com\n"
    "Subject: Contract terminated: 900001 - Penetration Test Services - Jan Testowy\n"
    "The contract has been terminated for 900001 - Penetration Test Services\n"
    "CoA\n900001 Penetration Test Services\n"
    "Contract Consultant\nJan Testowy\n"
    "Termination reason\nConsultant employed at Nordea\n"
    "New end date\n2026-09-14\n"
    "Comment\nConsultant no more working at the supplier, he has been internalized\n"
    "Show CoA - Penetration Test Services (900001)\n"
    "This email is sent from CPro, Nordea's consultant procurement system.\n"
)

TERMINATED_TABLE = (
    "From: NOREPLY CPro <noreply@onevms.se>\n"
    "To: consultant.procurement@nordea.com; dl@example.com\n"
    "Subject: Contract terminated: 900002 - Windows expert developer\n"
    "The contract has been terminated for 900002 - Windows expert developer\n"
    "CoA\n900002 Windows expert developer\n"
    "Consultant\nAnna Przykładowa\n"
    "Termination reason\nNo more budget\n"
    "New end date\n2026-12-18\n"
    "Comment\nTermination of the contract due to budget constraints.\n"
)

NOT_EXTENDED_FORWARD = (
    "„Nie spełnił oczekiwań, dlatego nie przedłużamy kontraktu.”\n"
    "End day: 12.12.2026.\n"
    "@TCM: offboarding i nowe CV plis.\n\n"
    "From: NOREPLY CPro <noreply@onevms.se>\n"
    "Subject: Contract 900003 will not be extended\n"
    "Contract 900003 will not be extended\nwill not be prolonged\n"
    "CoA: System Engineer for legacy application (900003)\n"
    "Show CoA - System Engineer for legacy application (900003)\n"
)

NOT_EXTENDED_PLAIN = (
    "Contract 900004 will not be extended\n"
    "LM did not approve prolongation.\n"
    "CoA: PL Data Architect (900004)\n"
    "Show CoA - PL Data Architect (900004)\n"
    "This email is sent from CPro, Nordea's consultant procurement system.\n"
)

INVOICE_CHANGES = (
    "Please update your invoice reference details with the information provided below\n\n"
    "Invoice address was updated from: F218 Nordea Bank Abp S.A. oddział w Polsce,"
    " to: F206 Nordea Bank Abp Finland\n\n"
    "Cost center was updated from: 1000000001, to: 1000000002\n\n"
    "Show CoA - PL - IT Developer - TP#00001 (900005)\n\n"
    "** This is an auto-generated notification email, triggered from an event in CPro **\n"
)

REFERENCE_CHANGES_WRAPPED = (
    "Please update your invoice reference details with the information provided \n"
    "below\n"
    "Responsible line manager was updated from: Ewa Przykład, to: Piotr \n"
    "Wzorcowy (piotr.wzorcowy@example.com\n"
    "NIIDS No / Initiative ID / Appl.code was updated from: 2018-000001, to: 2026-000002\n"
    "Show CoA - PL - Tester (900006) \n"
    "** This is an auto-generated notification email, triggered from an event in \n"
    "CPro **\n"
)

PROLONGATION = (
    "Oracle Stabilization Project Technical lead - 900007\n"
    "Hello,\nPlease indicate whether this contract should be prolonged by selecting the"
    " appropriate response under prolongation status in CPro. If this CoA should expire"
    " and end, please set the prolongation status as 'will not be'.\n"
    "CoA: Oracle Stabilization Project Technical lead (900007)\n"
    "Show CoA - Oracle Stabilization Project Technical lead (900007)\n"
)


# ── rozpoznanie (czyste funkcje) ─────────────────────────────────────────────


def test_terminated_table_with_value_on_next_line() -> None:
    event = cpro.parse(
        "FW: Contract terminated: 900002 - Windows expert developer", TERMINATED_TABLE
    )
    assert event is not None
    assert event.kind == cpro.TERMINATED
    assert event.cpro_number == "900002"
    assert event.end_day == date(2026, 12, 18)
    # „To: consultant.procurement@…” w nagłówku przekazania to nie konsultant.
    assert event.consultant_name == "Anna Przykładowa"
    assert event.reason == "No more budget"


def test_new_end_date_wins_over_the_old_contract_end_date() -> None:
    event = cpro.parse(
        "Contract terminated: 900012 - Tester",
        "Contract end date\n2026-12-31\nTermination reason\nNo more budget\n"
        "New end date\n2026-11-28\n",
        "noreply@onevms.se",
    )
    assert event is not None
    assert event.end_day == date(2026, 11, 28)


def test_internalization_is_an_exit_with_its_own_kind() -> None:
    event = cpro.parse(
        "ODP: Contract terminated: 900001 - Penetration Test Services - Jan Testowy",
        TERMINATED_FORWARD,
    )
    assert event is not None
    assert event.kind == cpro.INTERNALIZATION
    assert event.kind in cpro.EXIT_EVENTS
    assert event.end_day == date(2026, 9, 14)
    assert event.consultant_name == "Jan Testowy"


def test_not_extended_takes_end_day_written_by_the_dl() -> None:
    event = cpro.parse("FW: Contract 900003 will not be extended", NOT_EXTENDED_FORWARD)
    assert event is not None
    assert event.kind == cpro.NOT_EXTENDED
    assert event.cpro_number == "900003"
    assert event.end_day == date(2026, 12, 12)


def test_not_extended_without_end_day_has_no_date() -> None:
    event = cpro.parse(
        "Contract 900004 will not be extended", NOT_EXTENDED_PLAIN, "noreply@onevms.se"
    )
    assert event is not None
    assert event.kind == cpro.NOT_EXTENDED
    assert event.end_day is None
    assert "bez daty" in event.evidence[0]


def test_invoice_address_change_is_an_invoice_party_change() -> None:
    event = cpro.parse(
        "Important changes made to contract 900005",
        INVOICE_CHANGES,
        "noreply@onevms.se",
    )
    assert event is not None
    assert event.kind == cpro.CHANGES
    assert event.invoice_party_changed
    by_key = {change.key: change for change in event.changes}
    assert (
        by_key[cpro.INVOICE_ADDRESS].old == "F218 Nordea Bank Abp S.A. oddział w Polsce"
    )
    assert by_key[cpro.INVOICE_ADDRESS].new == "F206 Nordea Bank Abp Finland"
    assert by_key[cpro.COST_CENTER].new == "1000000002"
    assert event.end_day is None


def test_wrapped_reference_changes_keep_full_values() -> None:
    event = cpro.parse(
        "FW: Important changes made to contract 900006", REFERENCE_CHANGES_WRAPPED
    )
    assert event is not None
    assert not event.invoice_party_changed
    by_key = {change.key: change for change in event.changes}
    assert by_key[cpro.LINE_MANAGER].new == (
        "Piotr Wzorcowy (piotr.wzorcowy@example.com"
    )
    assert by_key[cpro.NIIDS].old == "2018-000001"
    assert by_key[cpro.NIIDS].new == "2026-000002"


def test_change_with_new_end_date_only() -> None:
    event = cpro.parse(
        "FW: Important changes made to contract 900008",
        "Please update your invoice reference details\nNew end date: 2026-12-31\n",
    )
    assert event is not None
    assert event.end_day == date(2026, 12, 31)
    assert event.invoice_reference_changes == ()


def test_change_without_any_known_line_is_nothing() -> None:
    assert (
        cpro.parse(
            "FW: Important changes made to contract 900009", "DW\nRate 150 → 160"
        )
        is None
    )


def test_prolongation_request_and_extensions_to_handle() -> None:
    event = cpro.parse(
        "FW: Oracle Stabilization Project Technical lead - 900007", PROLONGATION
    )
    assert event is not None
    assert event.kind == cpro.PROLONGATION
    assert event.cpro_number == "900007"
    reminder = cpro.parse(
        "You have 2 contract extensions to handle",
        "Show CoA - PL - Tester (900010)\n",
        "noreply@onevms.se",
    )
    assert reminder is not None
    assert reminder.kind == cpro.PROLONGATION
    assert reminder.pending_extensions == 2


def test_free_text_note_that_contract_wont_be_prolonged() -> None:
    event = cpro.parse(
        "RE: Structured finance team - 900011",
        "Hi,\nPlease note that the project failed to get budget and unfortunately the"
        " current contract won't be prolonged.\nCoA: Structured finance team (900011)\n"
        "Show CoA - Structured finance team (900011)\n",
    )
    assert event is not None
    assert event.kind == cpro.NOT_EXTENDED
    assert event.cpro_number == "900011"
    # „set the prolongation status as 'will not be'” to prośba o decyzję, nie koniec.
    request = cpro.parse(
        "FW: Oracle Stabilization Project Technical lead - 900007", PROLONGATION
    )
    assert request is not None and request.kind == cpro.PROLONGATION


def test_not_extended_is_not_mistaken_for_prolongation() -> None:
    event = cpro.parse("Contract 900004 will not be extended", NOT_EXTENDED_PLAIN)
    assert event is not None and event.kind == cpro.NOT_EXTENDED


def test_polish_internalization_word_without_cpro_is_not_cpro() -> None:
    assert (
        cpro.parse("Internalizacja zespołu", "Klient rozważa internalizację w 2027.")
        is None
    )


def test_plain_mail_is_not_cpro() -> None:
    assert cpro.parse("Faktura za październik", "W załączniku faktura.") is None


# ── reguły końca (``notice_rules``): CPro → „Klient kończy” ───────────────────


def test_not_extended_becomes_client_termination_proposal() -> None:
    signal = r.classify(
        subject="FW: Contract 900003 will not be extended",
        body=NOT_EXTENDED_FORWARD,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CLIENT_TERMINATION
    assert signal.cpro_number == "900003"
    assert signal.client_end_date == date(2026, 12, 12)
    assert signal.cpro_event == cpro.NOT_EXTENDED


def test_not_extended_without_date_is_still_a_proposal() -> None:
    signal = r.classify(
        subject="Contract 900004 will not be extended",
        body=NOT_EXTENDED_PLAIN,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CLIENT_TERMINATION
    assert signal.client_end_date is None


def test_internalization_proposal_is_marked() -> None:
    signal = r.classify(
        subject="ODP: Contract terminated: 900001 - Penetration Test Services",
        body=TERMINATED_FORWARD,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CLIENT_TERMINATION
    assert signal.cpro_event == cpro.INTERNALIZATION
    assert signal.consultant_name == "Jan Testowy"


def test_invoice_change_is_not_a_termination() -> None:
    assert (
        r.classify(
            subject="Important changes made to contract 900005",
            body=INVOICE_CHANGES,
            today=TODAY,
        )
        is None
    )


def test_prolongation_is_not_a_termination() -> None:
    assert (
        r.classify(
            subject="FW: Oracle Stabilization Project Technical lead - 900007",
            body=PROLONGATION,
            today=TODAY,
        )
        is None
    )


# ── sprawa z maila: zadanie Finansów, przedłużenie ────────────────────────────


def test_invoice_party_change_is_a_p1_finance_task_from_the_day() -> None:
    event = cpro.parse("Important changes made to contract 900005", INVOICE_CHANGES)
    assert event is not None
    result = plan.case_plan(event, received_on=date(2026, 9, 15), contract_ids=[42])
    assert result is not None
    assert result.title == "Nordea CPro: zmiana nabywcy od 15.09.2026 · CoA 900005"
    assert result.area == "settlements"
    assert result.priority == "P1"
    assert "Adres faktury (nabywca): F218 Nordea Bank Abp S.A." in result.description
    assert "→ F206 Nordea Bank Abp Finland" in result.description
    assert "kontrakt #42" in result.description
    texts = [item["text"] for item in result.checklist]
    assert texts[0].startswith(plan.FINANCE_BUYER_ITEM + "15.09.2026")
    assert "(od miesiąca 09.2026)" in texts[0]
    assert texts[1].startswith(plan.FINANCE_INVOICES_ITEM + "09.2026")


def test_reference_change_is_a_p2_finance_task() -> None:
    event = cpro.parse(
        "FW: Important changes made to contract 900006", REFERENCE_CHANGES_WRAPPED
    )
    assert event is not None
    result = plan.case_plan(event, received_on=date(2026, 11, 12), contract_ids=[])
    assert result is not None
    assert result.title == "Nordea CPro: dane do faktury od 12.11.2026 · CoA 900006"
    assert result.priority == "P2"
    assert "Żadna linia zamówienia nie ma numeru CPro 900006" in result.description
    assert [item["text"] for item in result.checklist] == [
        "Finanse: nowe dane do faktury od 12.11.2026: Line manager, NIIDS / Initiative ID"
    ]


def test_new_end_date_alone_is_left_to_the_termination_proposal() -> None:
    event = cpro.parse(
        "FW: Important changes made to contract 900008", "New end date: 2026-12-31\n"
    )
    assert event is not None
    assert plan.case_plan(event, received_on=TODAY, contract_ids=[]) is None


def test_prolongation_case_plan() -> None:
    event = cpro.parse(
        "FW: Oracle Stabilization Project Technical lead - 900007", PROLONGATION
    )
    assert event is not None
    result = plan.case_plan(event, received_on=TODAY, contract_ids=[7, 8])
    assert result is not None
    assert result.title == "Nordea CPro: przedłużenie do decyzji · CoA 900007"
    assert result.area == "negotiation"
    assert "kilku kontraktów: #7, #8" in result.description


def test_triage_routes_cpro_without_the_model() -> None:
    assert triage.cpro_route(
        "Contract 900004 will not be extended", NOT_EXTENDED_PLAIN
    ) == triage.Route("contracts", "ending")
    assert triage.cpro_route(
        "Important changes made to contract 900005", INVOICE_CHANGES
    ) == triage.Route("finance", "changes")
    assert triage.cpro_route(
        "FW: Oracle Stabilization Project Technical lead - 900007", PROLONGATION
    ) == triage.Route("orders", "extend")
    assert triage.cpro_route("Faktura za październik", "W załączniku faktura.") is None
