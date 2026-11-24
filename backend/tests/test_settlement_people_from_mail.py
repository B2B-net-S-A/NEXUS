"""Osoba z poczty rozliczeń bez bazy: nazwisko po zmianie, literówka w imieniu, numer
umowy wykonawczej, cytat z Gmaila i deklaracja „dni wolnych od pracy”.

Przypadki z próby rozliczeń IX–X 2026 na kopii produkcji (24.11.2026). Osoby,
adresy i numery fikcyjne.
"""

from __future__ import annotations

from app.services.client_settlements import acceptance_mail, mail_declaration
from app.services.client_settlements.mail_text import Senders
from app.services.client_settlements.rcp_checks import name_tokens
from app.services.consultant_portal import identity
from app.services.order_policies import known_clients


def test_nazwisko_z_nawiasem_to_dwa_warianty() -> None:
    assert identity._surnames("Nowa (Stara)") == [["nowa"], ["stara"]]
    assert identity._surnames("Nowa-Kowal (Stara)") == [["nowa", "kowal"], ["stara"]]
    assert identity._surnames("Kowalska-Nowak") == [["kowalska", "nowak"]]
    # Nawias bez pary nie zostaje w słowie.
    assert identity._surnames("Nowa (Stara") == [["nowa", "stara"]]


def test_adres_firmowy_ze_starym_i_nowym_nazwiskiem() -> None:
    forms = identity._address_forms("Kornelia", "Nowa (Stara)")
    assert {"kornelia.nowa", "kornelia.stara", "k.stara"} <= forms
    assert not any("(" in form for form in forms)


def test_jedna_litera_roznicy_w_imieniu() -> None:
    assert identity._one_typo("tomasz", "tomsz")  # brak litery
    assert identity._one_typo("tomasz", "tomaasz")  # nadmiar
    assert identity._one_typo("tomasz", "tomesz")  # zamiana
    assert identity._one_typo("tomasz", "tomazs")  # przestawienie
    assert not identity._one_typo("tomasz", "tomasz")  # to samo imię
    assert not identity._one_typo("tomasz", "romasz")  # inna pierwsza litera
    assert not identity._one_typo("tomasz", "tosz")  # dwie litery


def test_numer_umowy_wykonawczej_w_temacie_i_nazwie_pliku() -> None:
    assert identity.agreement_numbers("RE: Protokół do umowy AbC/77/2026") == {
        "abc/77/2026"
    }
    assert identity.agreement_numbers("Protokół 10_2026 do AbC_077_2026-sig.pdf") == {
        "abc/77/2026"
    }
    # Okres („za 10/2026”, „10_2026”) i numer bez liter z przodu to nie numer umowy.
    assert identity.agreement_numbers(
        "RE: Protokół odbioru za 10/2026 do umowy AbC/77/2026"
    ) == {"abc/77/2026"}
    assert identity.agreement_numbers("Protokół 10_2026.pdf") == frozenset()
    assert identity.agreement_numbers("Umowa B2B 1516-2026") == frozenset()


def test_rejestr_zna_domene_i_numer_boscha() -> None:
    assert known_clients.KNOWN_SENDER_DOMAINS["bosch.com"] == "bosch"
    assert known_clients.KNOWN_REGISTRY_IDS["bosch"]


def test_imie_i_nazwisko_z_kontraktu_po_zmianie_nazwiska() -> None:
    person = name_tokens("Kornelia Nowa (Stara)")
    assert name_tokens("Kornelia Stara") <= person
    assert name_tokens("Kornelia Nowa") <= person


GMAIL_REPLY = """Dzień dobry,

przesyłam Time Sheet.

czw., 12 lis 2026 o 09:31 Kierownik Testowy <kierownik@klient.example> пише:
> akceptuję
>
> *From:* Konsultantka <konsultantka@klient.example>
> *Sent:* Friday, November 6, 2026 11:11 AM
> *Subject:* Time Sheet - październik 2026
"""

GMAIL_PL = """Potwierdzenie poniżej.

W dniu czw., 12 lis 2026 o 16:44 Kierownik Testowy <kierownik@klient.example>
napisał(a):

> Potwierdzam
"""


def test_cytat_z_gmaila_ma_wiadomosc_klienta() -> None:
    senders = Senders(client=frozenset({"klient.example"}))
    found = acceptance_mail.quoted_messages(GMAIL_REPLY)
    assert {m.sender for m in found} == {
        "kierownik@klient.example",
        "konsultantka@klient.example",
    }
    assert acceptance_mail.from_client(found, senders) is True
    # Linia „… napisał(a):” przeniesiona do następnej linii też otwiera cytat.
    assert [m.sender for m in acceptance_mail.quoted_messages(GMAIL_PL)] == [
        "kierownik@klient.example"
    ]


def test_zdanie_z_adresem_bez_czasownika_to_nie_cytat() -> None:
    text = "Proszę pisać na adres kierownik@klient.example w sprawie godzin."
    assert acceptance_mail.quoted_messages(text) == []


def test_deklaracja_dni_wolnych_od_pracy_i_literowka_w_miesiacu() -> None:
    said = mail_declaration.parse_text(
        "Fakturę przesłałam przez KSeF.\nWe wrzeniu nie miałam dni wolnych od pracy.",
        "2026-09",
    )
    assert said == mail_declaration.Declaration(days_off=0, month="2026-09")
    two = mail_declaration.parse_text(
        "W październiku miałam 2 dni wolnego od pracy.", "2026-10"
    )
    assert two == mail_declaration.Declaration(days_off=2, month="2026-10")


def test_krotka_nazwa_miesiaca_bez_litery_to_nie_miesiac() -> None:
    # „maja” bez litery to „mja”/„maa”: krótkich nazw nie poprawiamy.
    said = mail_declaration.parse_text("W mja nie miałam dni wolnych.", "2026-05")
    assert said is not None and said.days_off is None
