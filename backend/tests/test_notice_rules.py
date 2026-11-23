"""Reguły rozpoznania wypowiedzeń z poczty (``admin_cases/notice_rules``).

Przypadki odwzorowują maile z archiwum administracja@ z 20.11.2026 i skrzynki
wsparcie@ z 19–20.11 — dane osobowe i numery zmienione (repo jest publiczne).
"""

from datetime import date

from app.services.admin_cases import notice_rules as r

TODAY = date(2026, 11, 23)


def test_consultant_notice_with_pdf_and_contract_number() -> None:
    signal = r.classify(
        subject="Wypowiedzenie umowy B2B – nr 1234/2026",
        body=(
            "Cześć,\nChciałbym poinformować, że podjąłem decyzję o zakończeniu "
            "współpracy, w związku z czym przesyłam w załączeniu wypowiedzenie."
        ),
        attachment_names=["Jan Testowy - Wypowiedzenie umowy 31.10.2026.pdf"],
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CONSULTANT_NOTICE
    assert signal.contract_number == "1234/2026"
    assert "załącznik z wypowiedzeniem" in signal.evidence
    assert signal.agreement is False


def test_notice_with_only_attachment_and_short_body() -> None:
    signal = r.classify(
        subject="Wypowiedzenie",
        body="W załączniku wypowiedzenie umowy (Klaudia zna szczegóły).",
        attachment_names=["wypowiedzenie b2b.pdf"],
        today=TODAY,
    )
    assert signal is not None and signal.kind == r.CONSULTANT_NOTICE


def test_agreement_is_marked() -> None:
    signal = r.classify(
        subject="Porozumienie o rozwiązaniu umowy B2B nr 1381/2026",
        body="W załączniku podpisane porozumienie.",
        attachment_names=["porozumienie.pdf"],
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CONSULTANT_NOTICE and signal.agreement is True


def test_reply_quoting_notice_is_not_a_new_notice() -> None:
    body = (
        "Dzięki, potwierdzam odbiór.\n\n"
        "12.11.2026 15:30 CET jan testowy <jan.testowy@example.com> napisał(a):\n"
        "Nawiązując do naszej rozmowy, załączam wypowiedzenie."
    )
    assert (
        r.classify(subject="Re: Wypowiedzenie umowy współpracy", body=body, today=TODAY)
        is None
    )


def test_medical_package_resignation_is_ignored() -> None:
    assert (
        r.classify(
            subject="Rezygnacja z pakietu medycznego",
            body="Proszę o wypowiedzenie pakietu medycznego od grudnia.",
            today=TODAY,
        )
        is None
    )


def test_plain_question_is_not_a_notice() -> None:
    assert (
        r.classify(subject="Faktura za październik", body="Kiedy przelew?", today=TODAY)
        is None
    )


def test_cpro_contract_terminated_forwarded() -> None:
    body = (
        "Wleciał oficjalny mail\nPracuje do 18.12.2026\n\n"
        "From: NOREPLY CPro <noreply@onevms.se>\n"
        "Subject: Contract terminated: 123456 - PL - Release Manager\n"
        "The contract has been terminated for 123456 - PL - Release Manager\n"
        "CoA 123456 PL - Release Manager\nConsultant Jan Testowy\n"
        "Termination reason Consultant quit\nNew end date 2026-12-18\n"
    )
    signal = r.classify(
        subject="FW: Contract terminated: 123456 - PL - Release Manager",
        body=body,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.CLIENT_TERMINATION
    assert signal.cpro_number == "123456"
    assert signal.client_end_date == date(2026, 12, 18)
    assert signal.consultant_name == "Jan Testowy"
    assert signal.reason == "Consultant quit"


def test_cpro_change_without_end_date_is_ignored() -> None:
    assert (
        r.classify(
            subject="FW: Important changes made to contract 276752",
            body="DW\nRate changed from 150 to 160.",
            today=TODAY,
        )
        is None
    )


def test_date_change_takes_date_after_the_request() -> None:
    body = (
        "Cześć,\nProszę o pilny kontakt. Data jaką przekazano klientowi, jako "
        "zakończenie współpracy to 18.12.\nJest prośba o zmianę na 31.12, "
        "w razie gdybym był potrzebny."
    )
    signal = r.classify(
        subject="Re: Wypowiedzenie umowy współpracy",
        body=body,
        in_notice_thread=True,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.DATE_CHANGE
    assert signal.new_last_day == date(2026, 12, 31)


def test_pm_reply_in_cpro_thread_is_date_change_not_new_termination() -> None:
    body = (
        "Hej,\nChcą go jednak do 31.12, ale od 18.12 nie będzie w pracy.\n\n"
        "From: NOREPLY CPro <noreply@onevms.se>\nNew end date 2026-12-18\n"
    )
    signal = r.classify(
        subject="Re: Contract terminated: 123456 - PL - Release Manager",
        body=body,
        in_notice_thread=True,
        today=TODAY,
    )
    assert signal is not None
    assert signal.kind == r.DATE_CHANGE
    assert signal.new_last_day == date(2026, 12, 31)


def test_withdrawal_in_thread() -> None:
    signal = r.classify(
        subject="Re: Wypowiedzenie",
        body="Po rozmowie z klientem wycofuję złożone wypowiedzenie i zostaję.",
        in_notice_thread=True,
        today=TODAY,
    )
    assert signal is not None and signal.kind == r.WITHDRAWAL


def test_withdrawal_words_outside_notice_thread_do_nothing() -> None:
    assert (
        r.classify(
            subject="Zgłoszenie",
            body="Wycofuję wniosek o urlop.",
            in_notice_thread=False,
            today=TODAY,
        )
        is None
    )


def test_thread_reply_without_change_is_ignored() -> None:
    assert (
        r.classify(
            subject="Re: Wypowiedzenie",
            body="Poproszę o detale w sprawie zwrotu telefonu.",
            in_notice_thread=True,
            today=TODAY,
        )
        is None
    )


def test_first_date_without_year_rolls_to_next_year() -> None:
    assert r.first_date_in("do 15.01", today=TODAY) == date(2027, 1, 15)
    assert r.first_date_in("do 31.12", today=TODAY) == date(2026, 12, 31)
    assert r.first_date_in("31.02 i 05.03.2027", today=TODAY) == date(2027, 3, 5)


def test_name_from_company_address() -> None:
    assert r.name_from_address("jan.testowy@b2bnetwork.pl") == "jan testowy"
    assert r.name_from_address("jtestowy@b2bnetwork.pl") is None
    assert r.name_from_address(None) is None


def test_fresh_text_cuts_outlook_history() -> None:
    body = "Nowa treść\n\nFrom: Ktoś <a@b.pl>\nSent: wtorek\nStara treść"
    assert r.fresh_text(body).strip() == "Nowa treść"


def test_cooperation_end_mentioned_in_a_billing_dispute_is_not_a_notice() -> None:
    assert (
        r.classify(
            subject="Rozliczenie usług świadczonych w maju oraz dalsza współpraca",
            body=(
                "Przyznam, że wzmianka dotycząca możliwego zakończenia współpracy "
                "wynikała z mojego zaniepokojenia."
            ),
            today=TODAY,
        )
        is None
    )


def test_cooperation_end_in_subject_still_counts() -> None:
    signal = r.classify(
        subject="Zakończenie współpracy z dniem 31.12",
        body="Informuję o zakończeniu współpracy.",
        today=TODAY,
    )
    assert signal is not None and signal.kind == r.CONSULTANT_NOTICE


def test_thread_replies_that_are_not_date_changes() -> None:
    for body in (
        "Jestem nieobecny do 28.11, w pilnych sprawach proszę pisać do biura.",
        "Proszę o zwrot sprzętu do 05.12.",
        "Przesunąłem spotkanie na jutro.",
    ):
        assert (
            r.classify(
                subject="Re: Wypowiedzenie",
                body=body,
                in_notice_thread=True,
                today=TODAY,
            )
            is None
        ), body


def test_withdrawing_something_else_is_not_withdrawing_the_notice() -> None:
    assert (
        r.classify(
            subject="Re: Wypowiedzenie",
            body="Wycofaliśmy dostęp do VPN zgodnie z procedurą.",
            in_notice_thread=True,
            today=TODAY,
        )
        is None
    )


def test_cancelling_the_notice_counts_as_withdrawal() -> None:
    signal = r.classify(
        subject="Re: Renegocjacja umowy",
        body="Chciałbym anulować obecne wypowiedzenie i złożyć kolejne.",
        in_notice_thread=True,
        today=TODAY,
    )
    assert signal is not None and signal.kind == r.WITHDRAWAL


def test_attachment_about_solving_a_problem_is_not_a_notice() -> None:
    assert (
        r.classify(
            subject="Faktura za listopad",
            body="W załączniku zrzut.",
            attachment_names=["rozwiazanie_problemu.png"],
            today=TODAY,
        )
        is None
    )
    signal = r.classify(
        subject="Dokumenty",
        body="W załączniku.",
        attachment_names=["Porozumienie_o_rozwiazaniu_umowy.pdf"],
        today=TODAY,
    )
    assert signal is not None and signal.agreement is True
