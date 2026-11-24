"""Akceptacja godzin liczy się tylko od klienta (``mail_text.judge``). Bez bazy.

Przegląd skrzynek Finansów z 23.11.2026: koordynatorka rozliczeń pisze na
rozliczenia@ wewnętrzne zestawienie „Zaakceptowane godziny … 160 h” z adresu
firmy. Liczba godzin, miesiąc i słowo akceptacji są w treści, więc kontrola
``proof.accept_has_hours`` brała je za akceptację klienta. Akceptuje tylko
wiadomość z domeny klienta: sam mail albo wiadomość zacytowana w wątku.
Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.client_settlements import mail_text

MONTH = "2026-10"
OURS = frozenset({"firma.example"})
CLIENT = frozenset({"klient.example"})


def _judge(mail: mail_text.Mail, *, client=CLIENT, own=OURS) -> mail_text.Verdict:
    return mail_text.judge(
        [mail],
        month=MONTH,
        hours=Decimal("160"),
        md=None,
        senders=mail_text.Senders(client=client, own=own),
    )


def test_nasze_zestawienie_godzin_to_nie_akceptacja_klienta():
    mail = mail_text.Mail(
        subject="Zaakceptowane godziny przez klienta - październik",
        sender="Koordynator Rozliczeń <koordynator@firma.example>",
        body="Zaakceptowane godziny za październik 2026:\nOsoba A: 160 h\n",
    )
    verdict = _judge(mail)
    assert not verdict.ok
    assert verdict.title == "Brak akceptacji klienta"
    assert "klient.example" in (verdict.detail or "")


def test_nasz_forward_z_zacytowana_odpowiedzia_klienta_akceptuje():
    mail = mail_text.Mail(
        subject="FW: Akceptacja godzin październik",
        sender="Koordynator Rozliczeń <koordynator@firma.example>",
        body=(
            "Przekazuję akceptację.\n\n"
            "From: Kierownik <kierownik@klient.example>\n"
            "Sent: Monday, November 2, 2026 9:54 AM\n"
            "Subject: RE: Akceptacja godzin\n"
            "Akceptuję 160 h za październik 2026.\n"
        ),
    )
    verdict = _judge(mail)
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja: 160 h za październik 2026"


def test_nasz_forward_naszej_prosby_bez_odpowiedzi_klienta():
    mail = mail_text.Mail(
        subject="FW: Odbiór usług za 10.2026",
        sender="Opiekun <opiekun@firma.example>",
        body=(
            "Potwierdzam, liczba godzin się zgadza.\n\n"
            "Od: Koordynator <koordynator@firma.example>\n"
            "Wysłano: 2 listopada 2026 09:54\n"
            "Proszę o akceptację 160 h za październik 2026.\n"
        ),
    )
    assert _judge(mail).title == "Brak akceptacji klienta"


def test_odpowiedz_z_domeny_klienta_akceptuje():
    mail = mail_text.Mail(
        subject="RE: Odbiór usług za 10.2026",
        sender="Kierownik <kierownik@klient.example>",
        body="Potwierdzam 160 h za październik 2026.",
    )
    assert _judge(mail).ok


def test_poddomena_i_inna_domena_to_nie_klient():
    for address in ("konsultant@external.klient.example", "ktos@inny.example"):
        mail = mail_text.Mail(
            subject="RE: Odbiór usług za 10.2026",
            sender=address,
            body="Potwierdzam 160 h za październik 2026.",
        )
        assert _judge(mail).title == "Brak akceptacji klienta", address


def test_bez_domen_klienta_wystarczy_adres_spoza_firmy():
    """Klient bez kontaktów i bez domeny w regułach: akceptuje każdy adres
    spoza domen firmy, ale nie nadawca bez adresu."""

    outside = mail_text.Mail(
        subject="RE: godziny",
        sender="kierownik@klient.example",
        body="Akceptuję 160 h za październik 2026.",
    )
    assert _judge(outside, client=frozenset()).ok
    ours = mail_text.Mail(
        subject="godziny",
        sender="koordynator@firma.example",
        body="Akceptuję 160 h za październik 2026.",
    )
    assert _judge(ours, client=frozenset()).title == "Brak akceptacji klienta"
    unknown = mail_text.Mail(
        subject="godziny",
        body="Od: Kierownik Anna\nAkceptuję 160 h za październik 2026.",
    )
    assert _judge(unknown, client=frozenset()).title == "Brak akceptacji klienta"


def test_prosba_bez_akceptacji_zostaje_prosba():
    mail = mail_text.Mail(
        subject="Odbiór usług za 10.2026",
        sender="koordynator@firma.example",
        body="Proszę o potwierdzenie 160 h za październik 2026.",
    )
    assert _judge(mail).title == "Mail bez odpowiedzi akceptującego"


def test_linia_od_do_w_tresci_to_nie_naglowek_cytatu():
    mail = mail_text.Mail(
        subject="RE: Protokół",
        sender="Kierownik <kierownik@klient.example>",
        body="Dzień dobry,\nOd: 01.10.2026 do 31.10.2026\nPotwierdzam 160 h za październik.\n",
    )
    assert _judge(mail).ok


def _bare(sender: str, body: str = "Akceptuję.") -> mail_text.Mail:
    return mail_text.Mail(subject="RE: Time Sheet", sender=sender, body=body)


def _judge_sheet(mail: mail_text.Mail, sheet_month: str | None) -> mail_text.Verdict:
    return mail_text.judge(
        [mail],
        month=MONTH,
        hours=Decimal("160"),
        md=None,
        senders=mail_text.Senders(client=CLIENT, own=OURS),
        sheet_month=sheet_month,
    )


def test_samo_akceptuje_od_klienta_z_godzinami_z_ts_za_miesiac():
    """Decyzja Artura z 23.11.2026 (PKO, BIK): „Akceptuję” bez liczby wystarcza,
    gdy godziny są w Time Sheet za rozliczany miesiąc."""

    verdict = _judge_sheet(_bare("kierownik@klient.example"), MONTH)
    assert verdict.ok, verdict
    assert verdict.title == "Akceptacja bez liczby, godziny z TS"
    assert "160 h" in (verdict.detail or "")


def test_samo_akceptuje_bez_ts_za_miesiac_albo_nie_od_klienta_to_uwaga():
    client = _bare("kierownik@klient.example")
    assert _judge_sheet(client, None).title == "Akceptacja bez liczby godzin lub MD"
    assert (
        _judge_sheet(client, "2026-09").title == "Akceptacja bez liczby godzin lub MD"
    )
    ours = _bare("koordynator@firma.example")
    assert not _judge_sheet(ours, MONTH).ok
    other_month = _bare("kierownik@klient.example", "Akceptuję godziny za wrzesień.")
    assert not _judge_sheet(other_month, MONTH).ok
    request = _bare("kierownik@klient.example", "Proszę o uzupełnienie.")
    assert not _judge_sheet(request, MONTH).ok


def test_akceptacja_z_liczba_wygrywa_z_akceptacja_bez_liczby():
    with_number = _bare("kierownik@klient.example", "Akceptuję 160 h za październik.")
    verdict = mail_text.judge(
        [_bare("kierownik@klient.example"), with_number],
        month=MONTH,
        hours=Decimal("160"),
        md=None,
        senders=mail_text.Senders(client=CLIENT, own=OURS),
        sheet_month=MONTH,
    )
    assert verdict.title == "Akceptacja: 160 h za październik 2026"
