"""Alior Bank: cztery pola z PDF-a, dopasowanie do szkicu, ta sama reguła wszędzie.

Zgłoszenie 09.2026: jednoosobowe zamówienie Alior z maila trafiało do
weryfikacji, choć osoba miała szkic zamówienia. Osoby, numery i kwoty w tym
pliku są ZMYŚLONE — ``TICKET`` odtwarza wyłącznie układ i formaty dokumentu
ze zgłoszenia (stawka bazowa bez groszy, marża bez przecinka, „Razem stawka
dla Banku" z jedną cyfrą po przecinku). Układ tekstu odtwarza pipeline
(pdfplumber): wiersz liczbowy między liniami komórki z nazwiskiem, nagłówek
przeplatany jak w realnym PDF-ie Aliora. Dokument wieloosobowy (``FOUR``) ma
układ z korpusu; osoby, firmy, numery i kwoty są zmyślone.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import order_mail_ingest as ingest
from app.services.order_client_identity import ClientIdentification, ClientRegistry
from app.services.order_document_text import OrderDocumentText
from app.services.order_mail_gate import GateInput, evaluate
from app.services.order_mail_planner import ExistingOrder, plan_document
from app.services.order_mail_resolver import RosterContract, RosterPerson, resolve_rows
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    parse_plan,
    policy_by_key,
)
from app.services.order_policies import alior
from tests.conftest import db_without_client_merges

POLICIES = [policy_by_key("alior")]

HEADER = """Zamówienie:
Do Umowy Ramowej: OIT/9990/2023/ITVM
Zamówienie nr: {number}
w ramach postępowania zakupowego ITVM-9999
do realizacji przedmiotu Umowy Ramowej nr: OIT/9990/2023/ITVM,
na warunkach w niej określonych.
Wykonawca: Zamawiający – płatnik:
B2B.NET S.A. Alior Bank Spółka Akcyjna
NIP: 5711707392 NIP: 1070010731
Kierownik Zamówienia Wykonawcy: Kierownik Zamówienia Zamawiającego:
Anna Kierownicza Ewa Zamawiająca
Jan Nowak (poz 1)
Bank składa zapotrzebowanie na Konsultantów / członków Zespołu spełniających niżej określone kompetencje
Praca w soboty +50 % Stawki za Roboczodzień
Nadgodziny (praca w godzinach 22:00 – 06:00) oraz praca w niedziele i
+ 100 % Stawki za Roboczodzień
inne dni ustawowo wolne od pracy
Imię i Stawka
Rodzaj Razem stawka
Nazwisko bazowa Total
kompetencji Liczba dla Banku
L.P Konsultanta / za MD Marża
(stanowisko, Roboczodni
członków [PLN
kompetencja) [PLN netto] [PLN netto]
Zespołu netto]
"""
CONDITIONS = """Razem PLN netto: {total} zł
Szczególne warunki zamówienia
L.P. Zagadnienie Założenie
1. Maksymalna wartość Zamówienia (z marżą): {total} zł
2. Maksymalna liczba Roboczodni: 18
3. Model wynagrodzenia T&M: wg stawek wskazanych powyżej
5. Moment wejścia w życie Zamówienia: {start}
czas oznaczony: {end} lub do wyczerpania
6. Okres obowiązywania:
kwoty zamówienia
7. Okres wypowiedzenia Zamówienia przez Bank 14 dni
"""

#: Cztery układy tego samego wiersza, które daje ekstraktor zależnie od
#: szerokości kolumn: nazwisko nad liczbami (PDF ze zgłoszenia), w jednej linii
#: z liczbami, zakres dat zaczęty w linii liczbowej, słowo kompetencji obok.
TICKET_ROWS = {
    "name_above": "Łucja Próbna\n1 UI 18 1100 15% 1265,5 22 779,00 zł\n(05.10.2026-28.10.2026)",
    "name_inline": "1 Łucja Próbna UI 18 1100 15% 1265,5 22 779,00 zł\n(05.10.2026-28.10.2026)",
    "period_on_numbers": "Łucja Próbna\n1 (05.10.2026- UI 18 1100 15% 1265,5 22 779,00 zł\n28.10.2026)",
    "competence_beside_name": "Łucja Próbna UX/UI\n1 Designer 18 1100 15% 1265,5 22 779,00 zł\n(05.10.2026-28.10.2026)",
}


def order_text(
    rows: str,
    *,
    number="OIT/9991/2026/ITVM",
    start="05.10.2026",
    end="28.10.2026",
    total="22 779,00",
) -> str:
    return (
        HEADER.format(number=number)
        + rows
        + "\n"
        + CONDITIONS.format(total=total, start=start, end=end)
    )


TICKET = order_text(TICKET_ROWS["name_above"])
#: Kolejne zamówienie tej samej osoby (osobny mail): październik–grudzień.
TICKET_NEXT = order_text(
    TICKET_ROWS["name_above"].replace(
        "(05.10.2026-28.10.2026)", "(02.11.2026-31.12.2026)"
    ),
    number="OIT/9992/2026/ITVM",
    start="02.11.2026",
    end="31.12.2026",
)

FOUR_ROWS = """Wiktoria
Testowa Business
1 189 1 155,00 13,81% 1 340,00 253 260,00 zł
(01.04.2031- Analyst
31.12.2031)
Jakub
Wzorcowy
Senior Mobile
2 189 1 200,00 15,00% 1 380,00 260 820,00 zł
(01.04.2031- Engineer
31.12.2031)
Jakub Przykładny
Developer
3 (01.04.2031- Backend 189 1 155,00 14,44% 1 350,00 255 150,00 zł
31.12.2031) Senior
Piotr
Przykładowski
Senior Mobile
4 189 1 400,00 15,00% 1 610,00 304 290,00 zł
(01.04.2031- Engineer
31.12.2031)"""
SUBCONTRACTORS = """
Załącznik nr 1 do zamówienia
Lista podwykonawców świadczących usługi w ramach niniejszego zamówienia
1 PRZYKŁAD IT Piotr Przykładowski NIP: 0000000000
2 Testowa Firma Jakub Wzorcowy NIP: 1111111111
"""
FOUR = (
    order_text(
        FOUR_ROWS,
        number="OIT/0189/2031/ITVM",
        start="01.04.2031",
        end="31.12.2031",
        total="1 073 520,00",
    )
    + SUBCONTRACTORS
)


def person(
    name: str,
    rate: str | None = "1265.5",
    *,
    start: str | None = "2026-10-05",
    end: str | None = "2026-10-28",
    unit: str | None = "day",
    reason: str | None = None,
) -> ConsultantOrderRow:
    return ConsultantOrderRow(
        consultant_name=name,
        rate_client=Decimal(rate) if rate is not None else None,
        rate_unit=unit,
        md_total=Decimal("18"),
        start_date=start,
        end_date=end,
        uncertain=reason is not None,
        uncertain_reason=reason,
    )


def model_reading(
    *rows: ConsultantOrderRow, reasons: tuple[str, ...] = ()
) -> OrderExtraction:
    """Niezależny odczyt modelu w trybie all-rows (pola dokumentu puste)."""
    return OrderExtraction(
        title="OIT/9990/2023/ITVM",  # model pomylił numer z umową ramową
        start_date="2026-10-01",
        end_date=None,
        total_value=Decimal("22779"),
        md_total=Decimal("18"),
        confidence={"total_value": 0.9, "md_total": 0.9},
        consultant_rows=list(rows),
        uncertain=bool(reasons),
        uncertain_reasons=list(reasons),
        source="claude",
    )


def read(
    text: str, reading: OrderExtraction, *, target: str | None = None
) -> OrderExtraction:
    """Ta sama sekwencja co w mailu i w „Zczytaj": polityki, potem rodzaj stawki."""
    result, applied = apply_policies(
        reading, PolicyContext(document_text=text, target_consultant=target), POLICIES
    )
    assert applied == ["Alior"]
    return apply_rate_kind(result, text, POLICIES)


# ── Cztery pola z przykładu ze zgłoszenia ────────────────────────────────────


@pytest.mark.parametrize("layout", sorted(TICKET_ROWS))
def test_ticket_example_reads_exactly_the_four_fields(layout):
    text = order_text(TICKET_ROWS[layout])
    ex = read(text, model_reading(person("Łucja Próbna")))

    assert ex.title == "OIT/9991/2026/ITVM"
    assert ex.confidence["title"] == 1.0 and ex.title_needs_review is False
    assert (ex.start_date, ex.end_date) == ("2026-10-05", "2026-10-28")
    assert (ex.rate_client, ex.rate_unit) == (Decimal("1265.5"), "day")
    [row] = ex.consultant_rows
    assert row.consultant_name == "Łucja Próbna"
    assert (row.start_date, row.end_date) == ("2026-10-05", "2026-10-28")
    assert (row.rate_client, row.rate_unit) == (Decimal("1265.5"), "day")
    assert row.uncertain is False and row.uncertain_reason is None
    # Liczba Roboczodni i Total są pomijane — nie trafiają do zamówienia.
    assert ex.md_total is None and row.md_total is None and ex.total_value is None
    assert "md_total" not in ex.confidence and "total_value" not in ex.confidence
    assert ex.uncertain is False and ex.uncertain_reasons == []


@pytest.mark.parametrize("layout", sorted(TICKET_ROWS))
def test_deterministic_table_confirms_the_person_and_rate_without_a_model(layout):
    [row] = alior.extract_rows(order_text(TICKET_ROWS[layout]))
    assert row.consultant_name == "Łucja Próbna"
    assert (row.start_date, row.end_date) == ("2026-10-05", "2026-10-28")
    assert (row.rate_client, row.rate_unit, row.md_total) == (
        Decimal("1265.5"),
        "day",
        None,
    )
    assert row.uncertain is False


def test_reasons_about_ignored_fields_never_reach_the_review():
    concerns = (
        "Stawka bazowa 1100 różni się od „Razem stawka dla Banku” 1265,5",
        "Marża 15% nie zgadza się z wyliczeniem",
        "Total 22 779,00 zł nie jest oznaczony jako total_value",
        "Liczba Roboczodni 18 nie odpowiada okresowi",
        "Nie ustalono, czy stawka jest brutto czy netto",
        "Stawka może być w innej jednostce niż miesięczna — sprawdź przeliczenie",
        "Okres obowiązywania: czas oznaczony lub do wyczerpania kwoty zamówienia",
    )
    ex = read(
        TICKET,
        model_reading(
            person(
                "Łucja Próbna", reason="Nie ustalono, czy stawka jest brutto czy netto"
            ),
            reasons=concerns,
        ),
    )
    assert ex.uncertain is False, ex.uncertain_reasons
    assert ex.uncertain_reasons == []
    assert ex.consultant_rows[0].uncertain is False


def test_no_table_reason_appears_only_when_the_table_is_really_missing():
    assert (
        alior.REASON_NO_TABLE
        not in read(TICKET, model_reading(person("Łucja Próbna"))).uncertain_reasons
    )
    without_table = TICKET.replace("1 UI 18 1100 15% 1265,5 22 779,00 zł", "")
    ex = read(without_table, model_reading(person("Łucja Próbna")))
    assert alior.REASON_NO_TABLE in ex.uncertain_reasons
    # Wiersz modelu zostaje w propozycji (DL widzi osobę), ale bez pól pomijanych.
    assert [r.consultant_name for r in ex.consultant_rows] == ["Łucja Próbna"]
    assert ex.consultant_rows[0].md_total is None


# ── Netto z definicji, jawne „brutto" → weryfikacja ──────────────────────────


def test_netto_is_the_default_and_the_universal_vat_detector_is_not_used(monkeypatch):
    monkeypatch.setenv("ALIOR_ORDER_EXTRACTION_CLIENT_IDS", "39")
    detector = Mock(side_effect=AssertionError("Alior must not guess brutto/netto"))
    monkeypatch.setattr(
        "app.services.order_pdf_parser.detect_rate_gross_marking", detector
    )
    ex, _ = apply_policies(
        model_reading(person("Łucja Próbna")),
        PolicyContext(document_text=TICKET),
        active_policies(39),
    )
    ex = apply_rate_kind(ex, TICKET, active_policies(39))
    assert (ex.rate_client, ex.rate_client_gross) == (Decimal("1265.5"), None)
    assert ex.uncertain is False
    detector.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        TICKET.replace("[PLN netto] [PLN netto]", "[PLN netto] [PLN brutto]"),
        TICKET.replace("1265,5 22 779,00 zł", "1265,5 zł brutto 22 779,00 zł"),
    ],
    ids=["column_header", "next_to_amount"],
)
def test_explicit_brutto_in_the_table_stops_the_order_without_converting(text):
    ex = read(text, model_reading(person("Łucja Próbna")))
    assert alior.REASON_GROSS in ex.uncertain_reasons
    assert ex.uncertain is True
    # Kwota zostaje taka, jak w PDF-ie — sprzeczność rozstrzyga człowiek.
    assert ex.consultant_rows[0].rate_client == Decimal("1265.5")
    assert ex.consultant_rows[0].rate_client_gross is None
    assert ex.consultant_rows[0].uncertain is True


def test_brutto_outside_the_consultant_table_is_not_about_the_rate():
    text = TICKET.replace(
        "1. Maksymalna wartość Zamówienia (z marżą): 22 779,00 zł",
        "1. Maksymalna wartość Zamówienia (z marżą): 28 018,17 zł brutto",
    )
    assert read(text, model_reading(person("Łucja Próbna"))).uncertain_reasons == []


def test_brutto_next_to_the_table_total_is_not_about_the_rate():
    """„Razem PLN" pod tabelą to suma (Total), a Total jest pomijany."""
    text = TICKET.replace(
        "Razem PLN netto: 22 779,00 zł",
        "Razem PLN netto: 22 779,00 zł (brutto: 28 018,17 zł)",
    )
    assert alior.table_marks_gross(text) is False
    assert read(text, model_reading(person("Łucja Próbna"))).uncertain_reasons == []


def test_old_gross_conversion_is_restored_to_the_document_amount():
    reading = model_reading(person("Łucja Próbna"))
    ex = read(TICKET, reading)
    ex.consultant_rows[0].rate_client = Decimal("956.50")
    ex.consultant_rows[0].rate_client_gross = Decimal("1265.5")
    ex = apply_rate_kind(ex, TICKET, POLICIES)
    assert (
        ex.consultant_rows[0].rate_client,
        ex.consultant_rows[0].rate_client_gross,
    ) == (
        Decimal("1265.5"),
        None,
    )


# ── Okres: nawias pod nazwiskiem, potem pola dokumentu ───────────────────────


def test_period_under_the_name_wins_over_document_fields():
    text = TICKET.replace(
        "życie Zamówienia: 05.10.2026", "życie Zamówienia: 01.10.2026"
    ).replace("czas oznaczony: 28.10.2026", "czas oznaczony: 30.11.2026")
    ex = read(text, model_reading(person("Łucja Próbna")))
    assert (ex.start_date, ex.end_date) == ("2026-10-05", "2026-10-28")


def test_document_fields_are_used_only_when_the_name_has_no_period():
    text = TICKET.replace("(05.10.2026-28.10.2026)", "")
    ex = read(text, model_reading(person("Łucja Próbna", start=None, end=None)))
    assert (ex.start_date, ex.end_date) == ("2026-10-05", "2026-10-28")
    assert ex.consultant_rows[0].start_date is None
    assert ex.uncertain_reasons == []


def test_period_under_the_name_may_be_written_with_od_do():
    text = TICKET.replace(
        "(05.10.2026-28.10.2026)", "(od 05.10.2026 do 28.10.2026)"
    ).replace("życie Zamówienia: 05.10.2026", "życie Zamówienia: 01.10.2026")
    [row] = alior.extract_rows(text)
    assert (row.consultant_name, row.start_date, row.end_date) == (
        "Łucja Próbna",
        "2026-10-05",
        "2026-10-28",
    )
    assert read(text, model_reading(person("Łucja Próbna"))).uncertain_reasons == []


def test_model_period_contradicting_the_document_period_is_reviewed():
    """Zakres w nieznanej regule formie nie może po cichu ustąpić okresowi dokumentu."""
    text = TICKET.replace("(05.10.2026-28.10.2026)", "")
    ex = read(
        text,
        model_reading(person("Łucja Próbna", start="2026-10-12", end="2026-10-28")),
    )
    assert ex.uncertain is True
    assert any("okres z odczytu modelu" in reason for reason in ex.uncertain_reasons)


def test_missing_period_everywhere_is_a_specific_reason():
    text = (
        TICKET.replace("(05.10.2026-28.10.2026)", "")
        .replace("życie Zamówienia: 05.10.2026", "życie Zamówienia:")
        .replace("czas oznaczony: 28.10.2026", "czas oznaczony:")
    )
    ex = read(text, model_reading(person("Łucja Próbna", start=None, end=None)))
    assert alior.REASON_NO_PERIOD in ex.uncertain_reasons


def test_reversed_document_period_is_a_reason_and_never_auto():
    """Tabela zamówień odwróconego okresu nie odrzuci — zatrzymuje go reguła i bramka."""
    text = (
        TICKET.replace("(05.10.2026-28.10.2026)", "")
        .replace("życie Zamówienia: 05.10.2026", "życie Zamówienia: 28.10.2026")
        .replace("czas oznaczony: 28.10.2026", "czas oznaczony: 05.10.2026")
    )
    ex = read(text, model_reading(person("Łucja Próbna", start=None, end=None)))
    assert any("jest odwrócony" in reason for reason in ex.uncertain_reasons), (
        ex.uncertain_reasons
    )
    _, verdict = gate(ex, text, [recruitment_draft()])
    assert not verdict.is_auto
    assert any("okres odwrócony" in reason for reason in verdict.reasons)


def test_reversed_period_under_the_name_is_never_used():
    text = TICKET.replace("(05.10.2026-28.10.2026)", "(28.10.2026-05.10.2026)")
    [row] = alior.extract_rows(text)
    assert (row.start_date, row.end_date) == (None, None)
    assert row.uncertain is True and "odwrócony" in row.uncertain_reason
    ex = read(
        text,
        model_reading(person("Łucja Próbna", start="2026-10-28", end="2026-10-05")),
    )
    assert ex.uncertain is True
    assert any("odwrócony" in reason for reason in ex.uncertain_reasons)


# ── Odczyt modelu: wstrzymanie się i wątpliwość to nie zgoda ─────────────────


def test_model_that_left_the_rate_empty_does_not_confirm_the_table():
    """Prompt każe zostawić stawkę pustą, gdy model nie umie jej powiązać z osobą."""
    ex = read(TICKET, model_reading(person("Łucja Próbna", rate=None)))
    assert ex.uncertain is True
    assert any("nie potwierdził stawki" in reason for reason in ex.uncertain_reasons)
    # Kwota nadal pochodzi z tabeli — do sprawdzenia, nie do wyrzucenia.
    assert ex.consultant_rows[0].rate_client == Decimal("1265.5")
    _, verdict = gate(ex, TICKET, [recruitment_draft()])
    assert not verdict.is_auto


def test_model_without_a_period_confirms_only_the_document_period():
    text = TICKET.replace(
        "życie Zamówienia: 05.10.2026", "życie Zamówienia: 01.10.2026"
    )
    ex = read(text, model_reading(person("Łucja Próbna", start=None, end=None)))
    assert any("nie potwierdził okresu" in reason for reason in ex.uncertain_reasons)
    # Zakres pod nazwiskiem równy okresowi dokumentu: brak okresu u modelu nic nie zmienia.
    same = read(TICKET, model_reading(person("Łucja Próbna", start=None, end=None)))
    assert same.uncertain_reasons == []


@pytest.mark.parametrize(
    "concern,blocks",
    [
        ("Stawka nieczytelna — nie można jej powiązać z osobą", True),
        ("Niejednoznaczne przypisanie okresu do osoby", True),
        ("Brak oznaczenia netto/brutto przy stawce", False),
        ("Stawka bazowa nieczytelna", False),
        ("Model odczytał dokument bez problemów", False),
    ],
    ids=["rate_doubt", "period_doubt", "vat_only", "ignored_field", "comment"],
)
def test_only_model_doubts_about_the_four_fields_stop_the_order(concern, blocks):
    ex = read(TICKET, model_reading(person("Łucja Próbna", reason=concern)))
    assert ex.uncertain is blocks, ex.uncertain_reasons
    if blocks:
        assert any("zgłasza wątpliwość" in reason for reason in ex.uncertain_reasons)


# ── Dokument wieloosobowy (układ z korpusu) ──────────────────────────────────


def four_reading(**overrides: ConsultantOrderRow) -> OrderExtraction:
    people = {
        "Wiktoria Testowa": person(
            "Testowa Wiktoria", "1340", start="2031-04-01", end="2031-12-31"
        ),
        "Jakub Wzorcowy": person(
            "Jakub Wzorcowy", "1380", start="2031-04-01", end="2031-12-31"
        ),
        "Jakub Przykładny": person(
            "Jakub Przykładny", "1350", start="2031-04-01", end="2031-12-31"
        ),
        "Piotr Przykładowski": person(
            "Piotr Przykładowski", "1610", start="2031-04-01", end="2031-12-31"
        ),
    }
    people.update(overrides)
    return model_reading(*people.values())


def test_multi_person_layout_reads_full_names_rates_and_periods():
    rows = alior.extract_rows(FOUR)
    assert [(r.consultant_name, r.rate_client) for r in rows] == [
        ("Wiktoria Testowa", Decimal("1340.00")),
        ("Jakub Wzorcowy", Decimal("1380.00")),
        ("Jakub Przykładny", Decimal("1350.00")),
        ("Piotr Przykładowski", Decimal("1610.00")),
    ]
    assert all((r.start_date, r.end_date) == ("2031-04-01", "2031-12-31") for r in rows)
    assert not any(r.uncertain for r in rows)

    ex = read(FOUR, four_reading())
    assert ex.title == "OIT/0189/2031/ITVM"
    assert (ex.start_date, ex.end_date) == ("2031-04-01", "2031-12-31")
    # Kilka osób: stawka dokumentu nic nie znaczy, jednostka to reguła klienta.
    assert (ex.rate_client, ex.rate_unit) == (None, "day")
    assert ex.uncertain is False, ex.uncertain_reasons
    assert len(ex.consultant_rows) == 4


def test_identical_repeat_of_a_person_is_not_a_second_position():
    reading = four_reading()
    # Ta sama pozycja wymieniona drugi raz (np. lista podwykonawców) — te same wartości.
    reading.consultant_rows.append(
        person("Jakub Wzorcowy", "1380", start="2031-04-01", end="2031-12-31")
    )
    ex = read(FOUR, reading)
    assert ex.uncertain is False, ex.uncertain_reasons
    assert len(ex.consultant_rows) == 4


def test_every_unconfirmed_person_from_the_model_goes_to_review():
    """Osoba z odczytu modelu bez wiersza w tabeli nigdy nie znika po cichu."""
    reading = four_reading()
    reading.consultant_rows.append(person("Jan Nowak", "1000", start=None, end=None))
    ex = read(FOUR, reading)
    assert ex.uncertain is True
    assert any("„Jan Nowak”" in reason for reason in ex.uncertain_reasons)
    assert "Jan Nowak" in [r.consultant_name for r in ex.consultant_rows]


def test_second_position_of_the_same_person_that_did_not_parse_is_reviewed():
    """Recenzja: dwie pozycje tej samej osoby, druga bez marży — dawniej AUTO z jedną."""
    text = order_text(
        "Wiktoria\nTestowa Business\n"
        "1 63 1 155,00 13,81% 1 340,00 84 420,00 zł\n(01.04.2031- Analyst\n30.06.2031)\n"
        "Wiktoria\nTestowa Business\n"
        "2 126 1 200,00 – 1 400,00 176 400,00 zł\n(01.07.2031- Analyst\n31.12.2031)",
        number="OIT/0189/2031/ITVM",
        start="01.04.2031",
        end="31.12.2031",
    )
    assert len(alior.extract_rows(text)) == 1
    reading = model_reading(
        person("Wiktoria Testowa", "1340", start="2031-04-01", end="2031-06-30"),
        person("Wiktoria Testowa", "1400", start="2031-07-01", end="2031-12-31"),
    )
    ex = read(text, reading)
    assert ex.uncertain is True
    assert [(r.start_date, r.rate_client) for r in ex.consultant_rows] == [
        ("2031-04-01", Decimal("1340.00")),
        ("2031-07-01", Decimal("1400")),
    ]
    roster = [
        RosterPerson(
            1,
            "Wiktoria",
            "Testowa",
            (RosterContract(11, "draft", date(2031, 4, 1), None),),
        )
    ]
    assert not gate_for_roster(ex, text, roster).is_auto


def test_rows_on_a_later_page_that_did_not_parse_are_reviewed():
    page_two = (
        "\n\nZamówienie:\nDo Umowy Ramowej: OIT/9990/2023/ITVM\n"
        + HEADER.split("inne dni ustawowo wolne od pracy\n")[1]
        + "Adam\nTestowy\nSenior Mobile\n"
        "5 189 1 400,00 – 1 610,00 304 290,00 zł\n(01.04.2031- Engineer\n31.12.2031)"
    )
    text = FOUR.replace(
        "31.12.2031)\nRazem PLN", "31.12.2031)" + page_two + "\nRazem PLN"
    )
    reading = four_reading(
        **{
            "Adam Testowy": person(
                "Adam Testowy", "1610", start="2031-04-01", end="2031-12-31"
            )
        }
    )
    ex = read(text, reading)
    assert ex.uncertain is True
    assert any("„Adam Testowy”" in reason for reason in ex.uncertain_reasons)


@pytest.mark.parametrize(
    "override,fragment",
    [
        (
            {
                "Jakub Wzorcowy": person(
                    "Jakub Wzorcowski", "1380", start="2031-04-01", end="2031-12-31"
                )
            },
            "nie potwierdził odczyt modelu",
        ),
        (
            {
                "Jakub Przykładny": person(
                    "Jakub Przykładny", "1155", start="2031-04-01", end="2031-12-31"
                )
            },
            "różni się od odczytu modelu",
        ),
        (
            {
                "Jakub Przykładny": person(
                    "Jakub Przykładny", "1350", start="2031-05-01", end="2031-12-31"
                )
            },
            "okres w nawiasie",
        ),
    ],
    ids=["name", "rate", "period"],
)
def test_model_disagreement_with_the_table_goes_to_review(override, fragment):
    ex = read(FOUR, four_reading(**override))
    assert ex.uncertain is True
    assert any(fragment in reason for reason in ex.uncertain_reasons), (
        ex.uncertain_reasons
    )
    # Wartości zawsze z tabeli — nie z modelu.
    assert [r.rate_client for r in ex.consultant_rows[:4]] == [
        Decimal("1340.00"),
        Decimal("1380.00"),
        Decimal("1350.00"),
        Decimal("1610.00"),
    ]


def test_competence_word_outside_the_dictionary_proposes_the_model_name_for_review():
    text = order_text(
        "Łucja Próbna Kwantyzator\n1 UI 18 1100 15% 1265,5 22 779,00 zł\n(05.10.2026-28.10.2026)"
    )
    assert alior.extract_rows(text)[0].consultant_name == "Łucja Próbna Kwantyzator"
    ex = read(text, model_reading(person("Łucja Próbna")))
    assert ex.consultant_rows[0].consultant_name == "Łucja Próbna"
    assert ex.uncertain is True
    assert any(
        "odczytano jako „Łucja Próbna Kwantyzator”" in r for r in ex.uncertain_reasons
    )


def test_person_listed_in_the_table_but_not_parsed_is_kept_and_reviewed():
    text = FOUR.replace(
        "4 189 1 400,00 15,00% 1 610,00 304 290,00 zł",
        "4 189 1 400,00 1 610,00 304 290,00 zł",
    )
    ex = read(text, four_reading())
    assert ex.uncertain is True
    assert any(
        "Piotr Przykładowski" in r and "nie ma odczytanego wiersza" in r
        for r in ex.uncertain_reasons
    )
    assert "Piotr Przykładowski" in [r.consultant_name for r in ex.consultant_rows]


def test_reapplying_the_rule_is_idempotent_and_never_launders_a_disagreement():
    once = read(
        FOUR,
        four_reading(
            **{
                "Jakub Wzorcowy": person(
                    "Jakub Wzorcowski", "1380", start="2031-04-01", end="2031-12-31"
                )
            }
        ),
    )
    twice = read(FOUR, deepcopy(once))
    assert twice.uncertain_reasons == once.uncertain_reasons
    assert [(r.consultant_name, r.uncertain_reason) for r in twice.consultant_rows] == [
        (r.consultant_name, r.uncertain_reason) for r in once.consultant_rows
    ]
    assert twice.uncertain is True

    clean_once = read(TICKET, model_reading(person("Łucja Próbna")))
    clean_twice = read(TICKET, deepcopy(clean_once))
    assert (
        clean_twice.uncertain_reasons == []
        and clean_twice.consultant_rows == clean_once.consultant_rows
    )


# ── Kolumna „Razem stawka dla Banku": podział kwot za marżą ──────────────────


def test_rate_without_decimals_is_split_from_total_by_the_row_identity():
    text = order_text(
        "Łucja Próbna\n1 UI 189 1 155,00 13,81% 1 340 253 260,00 zł\n(01.04.2026-31.12.2026)",
        start="01.04.2026",
        end="31.12.2026",
    )
    [row] = alior.extract_rows(text)
    assert row.rate_client == Decimal("1340") and row.uncertain is False


def test_unresolvable_split_is_a_reason_about_the_rate_not_about_the_total():
    text = order_text(
        "Łucja Próbna\n1 UI 1 155,00 13,81% 1 340 253 260,00 zł\n(05.10.2026-28.10.2026)"
    )
    [row] = alior.extract_rows(text)
    assert row.rate_client is None and row.uncertain is True
    assert "Razem stawka dla Banku" in row.uncertain_reason
    assert "Total" not in row.uncertain_reason


# ── „Zczytaj", uzupełnienie i przedłużenie: ta sama reguła ───────────────────


def test_targeted_form_picks_the_person_from_the_table():
    ex = read(FOUR, four_reading(), target="Jakub Przykładny")
    assert (ex.rate_client, ex.rate_unit) == (Decimal("1350.00"), "day")
    assert ex.consultant_rate_matched is True
    assert (ex.start_date, ex.end_date) == ("2031-04-01", "2031-12-31")
    assert ex.uncertain is False, ex.uncertain_reasons


def test_targeted_form_for_someone_not_on_the_order_leaves_the_rate_empty():
    ex = read(TICKET, model_reading(person("Łucja Próbna")), target="Anna Obca")
    assert ex.rate_client is None and ex.consultant_rate_matched is False
    assert any("Anna Obca" in reason for reason in ex.uncertain_reasons)


@pytest.mark.parametrize(
    "in_table,target",
    [("Anna Nowak-Kowalska", "Anna Nowak"), ("Jan Piotr Nowak", "Piotr Nowak")],
    ids=["double_surname", "extra_given_name"],
)
def test_targeted_form_never_takes_the_rate_of_a_similar_name(in_table, target):
    """Ten sam ścisły matcher osoby co wszędzie — podobne nazwisko to inna osoba."""
    text = order_text(
        f"{in_table}\n1 UI 18 1100 15% 1265,5 22 779,00 zł\n(05.10.2026-28.10.2026)"
    )
    assert alior.extract_rows(text)[0].consultant_name == in_table
    ex = read(text, model_reading(person(in_table)), target=target)
    assert ex.rate_client is None and ex.consultant_rate_matched is False
    assert any(target in reason for reason in ex.uncertain_reasons)
    matched = read(text, model_reading(person(in_table)), target=in_table)
    assert matched.rate_client == Decimal("1265.5")


def test_targeted_form_works_deterministically_without_the_model():
    ex = read(TICKET, OrderExtraction(source="regex"), target="Łucja Próbna")
    assert (ex.title, ex.start_date, ex.end_date) == (
        "OIT/9991/2026/ITVM",
        "2026-10-05",
        "2026-10-28",
    )
    assert (ex.rate_client, ex.rate_unit, ex.consultant_rate_matched) == (
        Decimal("1265.5"),
        "day",
        True,
    )
    assert ex.uncertain is False


@pytest.mark.asyncio
async def test_mail_and_every_form_use_the_same_all_rows_reading(monkeypatch):
    from app.api import client_orders
    from app.services import order_pdf_parser as parser_module
    from app.services.order_pdf_parser import parse_order_document

    assert parse_plan(POLICIES).all_rows is True
    # Świeży odczyt przy każdym wywołaniu — polityka zmienia wynik w miejscu.
    model = AsyncMock(side_effect=lambda *a, **k: model_reading(person("Łucja Próbna")))
    monkeypatch.setattr(parser_module, "_extract_all_rows_with_claude", model)
    monkeypatch.setattr(
        parser_module,
        "_extract_with_claude",
        AsyncMock(side_effect=AssertionError("Alior must always read all consultants")),
    )
    mail = read(TICKET, await parse_order_document(TICKET, all_rows=True))
    for target in (None, "Łucja Próbna"):
        form = await client_orders._extract_with_plan(
            TICKET,
            plan=parse_plan(POLICIES),
            target_consultant=target,
            target_given_names=None,
        )
        form = read(TICKET, form, target=target)
        assert form.consultant_rows == mail.consultant_rows
        assert (
            form.title,
            form.start_date,
            form.end_date,
            form.rate_client,
            form.rate_unit,
        ) == (
            "OIT/9991/2026/ITVM",
            "2026-10-05",
            "2026-10-28",
            Decimal("1265.5"),
            "day",
        )
        assert form.uncertain_reasons == []


# ── Mail: dopasowanie do szkicu i bramka automatu ────────────────────────────


def ticket_roster() -> list[RosterPerson]:
    return [
        RosterPerson(
            7000,
            "Łucja",
            "Próbna",
            (RosterContract(7001, "draft", date(2026, 10, 1), None),),
        )
    ]


def recruitment_draft() -> ExistingOrder:
    return ExistingOrder(
        9001,
        "draft",
        "Łucja Próbna — UI Designer (ITVM-9998)",
        date(2026, 10, 1),
        None,
        rate_unit="hourly",
    )


def gate(ex: OrderExtraction, text: str, orders: list[ExistingOrder]):
    resolved = resolve_rows(ex.consultant_rows, ticket_roster())
    proposal = plan_document(
        client_id=39,
        extraction=ex,
        resolved=resolved,
        existing_orders_by_contract={7001: orders},
        is_group_client=False,
        today=date(2026, 10, 10),
        order_type="periodic",
    )
    verdict = evaluate(
        GateInput(
            identification_method="registry_id",
            policies_applied=("Alior",),
            extraction=ex,
            document_truncated=False,
            ocr_capped=False,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(alior.extract_rows(text)),
            current_rates={7001: (None, "hour")},
            autoapply_enabled=True,
        )
    )
    return proposal, verdict


def gate_for_roster(ex: OrderExtraction, text: str, roster: list[RosterPerson]):
    """Bramka dla dowolnego rostera — każda osoba z kontraktem-szkicem bez zamówień."""
    resolved = resolve_rows(ex.consultant_rows, roster)
    proposal = plan_document(
        client_id=39,
        extraction=ex,
        resolved=resolved,
        existing_orders_by_contract={},
        is_group_client=False,
        today=date(2031, 3, 10),
        order_type="periodic",
    )
    return evaluate(
        GateInput(
            identification_method="registry_id",
            policies_applied=("Alior",),
            extraction=ex,
            document_truncated=False,
            ocr_capped=False,
            resolved=tuple(resolved),
            proposal=proposal,
            deterministic_rows=tuple(alior.extract_rows(text)),
            current_rates={},
            autoapply_enabled=True,
        )
    )


def test_ticket_mail_fills_the_existing_draft_automatically():
    ex = read(TICKET, model_reading(person("Łucja Próbna")))
    proposal, verdict = gate(ex, TICKET, [recruitment_draft()])
    [row] = proposal.rows
    assert (row.action, row.target_order_id, row.contract_id) == (
        "fill_draft",
        9001,
        7001,
    )
    assert (
        row.title,
        row.start_date,
        row.end_date,
        row.rate_client,
        row.rate_unit,
    ) == (
        "OIT/9991/2026/ITVM",
        "2026-10-05",
        "2026-10-28",
        "1265.5",
        "day",
    )
    assert verdict.is_auto, verdict.reasons
    assert verdict.reasons == []


def test_second_order_for_the_next_period_does_not_overwrite_the_filled_draft():
    filled = ExistingOrder(
        9001,
        "draft",
        "OIT/9991/2026/ITVM",
        date(2026, 10, 5),
        date(2026, 10, 28),
        rate_client=Decimal("1265.5"),
        rate_unit="daily",
        from_order_mail=True,
    )
    ex = read(
        TICKET_NEXT,
        model_reading(person("Łucja Próbna", start="2026-11-02", end="2026-12-31")),
    )
    proposal, verdict = gate(ex, TICKET_NEXT, [filled])
    assert (
        proposal.rows[0].action == "future" and proposal.rows[0].target_order_id is None
    )
    assert verdict.is_auto, verdict.reasons

    # Ten sam numer (ponownie przysłany dokument) nadal uzupełnia ten sam szkic.
    same = read(TICKET, model_reading(person("Łucja Próbna")))
    assert gate(same, TICKET, [filled])[0].rows[0].action == "fill_draft"


def test_draft_with_an_attached_order_pdf_is_not_overwritten_by_another_period():
    """Szkic z PDF-em dołączonym ręcznie też niesie zamówienie — nie tylko zapis z maila."""
    with_file = ExistingOrder(
        9003,
        "draft",
        "OIT/9991/2026/ITVM",
        date(2026, 10, 5),
        date(2026, 10, 28),
        has_file=True,
    )
    ex = read(
        TICKET_NEXT,
        model_reading(person("Łucja Próbna", start="2026-11-02", end="2026-12-31")),
    )
    proposal, verdict = gate(ex, TICKET_NEXT, [with_file])
    assert (proposal.rows[0].action, proposal.rows[0].target_order_id) == (
        "future",
        None,
    )
    assert verdict.is_auto, verdict.reasons


def test_group_line_draft_written_from_mail_keeps_the_group_path():
    """Osobne zamówienie obok linii MD rozdwoiłoby współpracę — decyduje człowiek."""
    group_line = ExistingOrder(
        9002,
        "draft",
        "OIT/0400/2026/ITVM",
        date(2026, 7, 1),
        date(2026, 8, 31),
        order_group_id=77,
        from_order_mail=True,
    )
    ex = read(TICKET, model_reading(person("Łucja Próbna")))
    proposal, verdict = gate(ex, TICKET, [group_line])
    assert proposal.rows[0].action == "group"
    assert not verdict.is_auto


# ── „Przelicz plan" na dokumencie zapisanym przed poprawką reguły ─────────────


def stale_extraction() -> dict:
    """Odczyt zapisany starą regułą — dokładnie powody ze zgłoszenia."""
    return ingest.extraction_to_json(
        OrderExtraction(
            title="OIT/9991/2026/ITVM",
            start_date="2026-10-05",
            end_date="2026-10-28",
            rate_unit="day",
            confidence={"title": 1.0, "start_date": 1.0, "end_date": 1.0},
            consultant_rows=[
                person(
                    "Łucja Próbna",
                    reason="Nie ustalono, czy stawka jest brutto czy netto",
                )
            ],
            uncertain=True,
            uncertain_reasons=[
                "Nie rozpoznano tabeli Konsultantów — wpisz osoby ręcznie",
                "Nie ustalono, czy każda stawka jest brutto czy netto",
            ],
            source="claude",
        )
    )


@pytest.mark.asyncio
async def test_przelicz_plan_reapplies_the_rule_without_the_model(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ALIOR_ORDER_EXTRACTION_CLIENT_IDS", "39")
    row = SimpleNamespace(
        client_id=39,
        extraction=stale_extraction(),
        storage_path="alior.pdf",
        attachment_name="Zamówienie B2B UIv2-sig.pdf",
        identification_method="registry_id",
        client_policy="Alior",
        error="old",
    )
    doc = OrderDocumentText(TICKET, 2, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *a: doc)
    monkeypatch.setattr(
        ingest.storage_service, "get_order_mail_attachment_path", lambda p: tmp_path / p
    )
    monkeypatch.setattr(
        ingest,
        "parse_order_document",
        AsyncMock(side_effect=AssertionError("no model")),
    )

    async def proposal(db, extraction, client_id):
        resolved = resolve_rows(extraction.consultant_rows, ticket_roster())
        planned = plan_document(
            client_id=client_id,
            extraction=extraction,
            resolved=resolved,
            existing_orders_by_contract={7001: [recruitment_draft()]},
            is_group_client=False,
            today=date(2026, 10, 10),
            order_type="periodic",
        )
        return planned, resolved, {7001: (None, "hour")}

    monkeypatch.setattr(ingest, "current_proposal", proposal)
    await ingest.refresh_review_plan(db_without_client_merges(), row)

    assert row.extraction["uncertain"] is False
    assert row.extraction["uncertain_reasons"] == []
    assert row.extraction["consultant_rows"][0]["uncertain"] is False
    assert row.extraction["md_total"] is None
    assert row.gate_verdict == "auto", row.gate_reasons
    assert row.gate_reasons == []
    assert row.proposal["rows"][0]["action"] == "fill_draft"
    assert row.proposal["rows"][0]["target_order_id"] == 9001
    assert row.error is None


def reapply(stored: OrderExtraction, text: str) -> OrderExtraction:
    """„Przelicz plan": reguła na zapisanym odczycie, bez modelu."""
    result, applied = apply_policies(
        stored, PolicyContext(document_text=text, reapplied=True), POLICIES
    )
    assert applied == ["Alior"]
    return apply_rate_kind(result, text, POLICIES)


def test_old_record_of_an_old_format_document_does_not_confirm_itself():
    """Stara reguła mogła zapisać SWOJĄ tabelę zamiast odczytu modelu.

    Na takim zapisie nie da się odróżnić jednego od drugiego, więc wiersze nie
    potwierdzają tabeli: dokument idzie do człowieka zamiast potwierdzić sam siebie.
    """
    stored = OrderExtraction(
        title="OIT/0189/2031/ITVM",
        consultant_rows=four_reading().consultant_rows,
        source="claude",
    )
    ex = reapply(stored, FOUR)
    assert ex.uncertain is True
    assert all(row.uncertain for row in ex.consultant_rows)
    assert any("przed zmianą reguły Aliora" in r for r in ex.uncertain_reasons)
    # Świeży odczyt tych samych wierszy (mail, formularz) jest zwykłym odczytem modelu.
    assert read(FOUR, four_reading()).uncertain is False


def test_stored_model_reading_survives_the_database_and_keeps_a_disagreement():
    once = read(
        FOUR,
        four_reading(
            **{
                "Jakub Wzorcowy": person(
                    "Jakub Wzorcowski", "1380", start="2031-04-01", end="2031-12-31"
                )
            }
        ),
    )
    assert [r.consultant_name for r in once.model_rows][:2] == [
        "Testowa Wiktoria",
        "Jakub Wzorcowski",
    ]
    restored = ingest.restore_extraction(ingest.extraction_to_json(once))
    assert restored.model_rows == once.model_rows
    again = reapply(restored, FOUR)
    # Zapisany odczyt modelu, nie wiersze wyniku: rozbieżność nie znika po przeliczeniu.
    assert again.uncertain_reasons == once.uncertain_reasons
    assert any("nie potwierdził odczyt modelu" in r for r in again.uncertain_reasons)
    assert not any("przed zmianą reguły" in r for r in again.uncertain_reasons)


# ── Pełna ścieżka mailowa na bazie: szkic uzupełniony, drugi PDF osobno ──────


async def _ingest(db, client_id: int, text: str, reading: OrderExtraction, monkeypatch):
    from app.models.order_mail import OrderMailDocument

    doc = OrderDocumentText(text, 2, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *a: doc)
    monkeypatch.setattr(
        ingest,
        "identify_client",
        lambda *a, **k: ClientIdentification(
            client_key=str(client_id), method="registry_id"
        ),
    )
    monkeypatch.setattr(ingest, "parse_order_document", AsyncMock(return_value=reading))
    row = OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@alior.test>",
        attachment_name="Zamówienie B2B UIv2-sig.pdf",
        sender_email="rozliczenia@b2bnetwork.pl",
    )
    return await ingest.process_pdf_bytes(
        db, row, b"%PDF-1.4 dummy", registry=ClientRegistry({})
    )


async def test_mail_order_fills_the_recruitment_draft_and_next_period_is_separate(
    monkeypatch,
):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Alior Bank Spółka Akcyjna {uuid.uuid4().hex[:6]}")
        candidate = Candidate(name="Łucja", lastname="Próbna")
        db.add_all([client, candidate])
        await db.flush()
        monkeypatch.setenv("ALIOR_ORDER_EXTRACTION_CLIENT_IDS", str(client.id))
        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            status=ContractStatus.draft,
            start_date=date(2026, 10, 1),
            rate_candidate=Decimal("110"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        draft = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title="Łucja Próbna — UI Designer (ITVM-9998)",
            status=ClientOrderStatus.draft,
            order_type="periodic",
            start_date=date(2026, 10, 1),
            rate_candidate=Decimal("110"),
            rate_unit=RateUnit.hourly,
        )
        db.add(draft)
        await db.flush()

        first = await _ingest(
            db, client.id, TICKET, model_reading(person("Łucja Próbna")), monkeypatch
        )
        assert first.gate_reasons == [] and first.outcome == "auto_applied", (
            first.gate_reasons
        )
        await db.refresh(draft)
        assert draft.title == "OIT/9991/2026/ITVM"
        assert (draft.start_date, draft.end_date) == (
            date(2026, 10, 5),
            date(2026, 10, 28),
        )
        assert (draft.rate_client, draft.rate_unit) == (
            Decimal("1265.5"),
            RateUnit.daily,
        )
        assert first.applied_order_id == draft.id
        assert await db.scalar(
            select(Activity.id).where(
                Activity.entity_type == "client_order",
                Activity.entity_id == draft.id,
                Activity.action == "order_mail_fill_draft",
            )
        )

        second = await _ingest(
            db,
            client.id,
            TICKET_NEXT,
            model_reading(person("Łucja Próbna", start="2026-11-02", end="2026-12-31")),
            monkeypatch,
        )
        assert second.outcome == "auto_applied", second.gate_reasons
        assert second.applied_order_id != draft.id
        await db.refresh(draft)
        # Pierwszy PDF nie został nadpisany drugim.
        assert (draft.title, draft.end_date) == (
            "OIT/9991/2026/ITVM",
            date(2026, 10, 28),
        )
        follow_up = await db.get(ClientOrder, second.applied_order_id)
        assert (follow_up.title, follow_up.start_date, follow_up.end_date) == (
            "OIT/9992/2026/ITVM",
            date(2026, 11, 2),
            date(2026, 12, 31),
        )
        await db.rollback()


# ── Kolejka po zmianie reguły: wpis sprzed wdrożenia przelicza się sam ───────


def old_rule_extraction() -> dict:
    """Odczyt kolejnego okresu zapisany STARĄ regułą — bez ``model_rows``.

    Kształt wpisu, który po wdrożeniu nowej reguły wisiał w kolejce ze starymi
    powodami, bo nikt nie kliknął „Przelicz plan" (09.2026).
    """
    return ingest.extraction_to_json(
        OrderExtraction(
            title="OIT/9992/2026/ITVM",
            start_date="2026-11-02",
            end_date="2026-12-31",
            rate_unit="day",
            total_value=Decimal("50620"),
            confidence={"title": 1.0, "start_date": 1.0, "end_date": 1.0},
            consultant_rows=[
                person(
                    "Łucja Próbna",
                    "1265.5",
                    start="2026-11-02",
                    end="2026-12-31",
                    reason="Nie ustalono, czy stawka jest brutto czy netto",
                )
            ],
            uncertain=True,
            uncertain_reasons=[
                "Nie rozpoznano tabeli Konsultantów — wpisz osoby ręcznie",
                "Nie ustalono, czy każda stawka jest brutto czy netto",
            ],
            source="claude",
        )
    )


async def _alior_with_a_pending_next_period(db, monkeypatch, tmp_path, **doc_fields):
    """Stan z produkcji: kontrakt aktywny, pierwszy okres zapisany, drugi czeka.

    Pierwsze zamówienie jest AKTYWNE (zapis z maila aktywuje je przy
    podpisanej umowie), a wpis kolejnego okresu ma odczyt starej reguły i nie
    ma znacznika wersji — tak wyglądał dokument „nie do przyjęcia".
    """
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.order_mail import OrderMailDocument

    client = Client(name=f"Alior Bank Spółka Akcyjna {uuid.uuid4().hex[:6]}")
    candidate = Candidate(name="Łucja", lastname="Próbna")
    db.add_all([client, candidate])
    await db.flush()
    monkeypatch.setenv("ALIOR_ORDER_EXTRACTION_CLIENT_IDS", str(client.id))
    contract = Contract(
        client_id=client.id,
        candidate_id=candidate.id,
        status=ContractStatus.active,
        start_date=date(2026, 10, 1),
        rate_candidate=Decimal("880"),
        rate_client=Decimal("1265.5"),
        rate_unit=RateUnit.daily,
    )
    db.add(contract)
    await db.flush()
    first = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        title="OIT/9991/2026/ITVM",
        status=ClientOrderStatus.active,
        order_type="periodic",
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 28),
        rate_client=Decimal("1265.5"),
        rate_candidate=Decimal("880"),
        rate_unit=RateUnit.daily,
    )
    storage = tmp_path / f"alior-{uuid.uuid4().hex[:6]}.pdf"
    storage.write_bytes(b"%PDF-1.4 dummy")
    fields = dict(
        internet_message_id=f"<{uuid.uuid4()}@alior.test>",
        attachment_name="Zamowienie kolejny okres.pdf",
        sender_email="rozliczenia@b2bnetwork.pl",
        outcome="needs_review",
        client_id=client.id,
        identification_method="registry_id",
        client_policy="Alior",
        storage_path=storage.name,
        extraction=old_rule_extraction(),
        document_meta={"page_count": 2, "text_chars": 2658},
        gate_verdict="review",
        gate_reasons=[
            "Brak niezależnego potwierdzenia osób i stawek z pól dokumentu PDF",
            "Odczyt niepewny: Nie rozpoznano tabeli Konsultantów — wpisz osoby ręcznie",
        ],
    )
    fields.update(doc_fields)
    doc = OrderMailDocument(**fields)
    db.add_all([first, doc])
    await db.commit()
    text = OrderDocumentText(TICKET_NEXT, 2, False, False, None, 0.0)
    monkeypatch.setattr(ingest, "extract_order_text", lambda *a: text)
    monkeypatch.setattr(
        ingest.storage_service,
        "get_order_mail_attachment_path",
        lambda p: tmp_path / p,
    )
    return first, doc


async def test_pending_document_from_before_the_rule_change_is_replanned_by_the_mailbox_run(
    monkeypatch, tmp_path
):
    """Zgłoszenie 09.2026: zamówienie na kolejny okres „nie chciało się przyjąć".

    Reguła czytała PDF poprawnie, ale wpis z kolejki niósł odczyt starej reguły
    do chwili ręcznego „Przelicz plan". Najbliższy bieg skrzynki przelicza go
    sam i zapisuje osobne zamówienie na kolejny okres — pierwsze zostaje nietknięte.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    monkeypatch.setattr(
        ingest,
        "parse_order_document",
        AsyncMock(side_effect=AssertionError("przeliczenie nie woła modelu")),
    )
    async with AsyncSessionLocal() as db:
        first, doc = await _alior_with_a_pending_next_period(db, monkeypatch, tmp_path)
        stats = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, stats)
        assert (stats.replanned, stats.replanned_auto_applied) == (1, 1), stats.errors
        await db.refresh(doc)
        assert doc.outcome == "auto_applied", doc.gate_reasons
        assert doc.gate_reasons == []
        assert doc.document_meta["rule_versions"] == {
            "alior": policy_by_key("alior").rule_version
        }
        follow_up = await db.get(ClientOrder, doc.applied_order_id)
        assert follow_up.id != first.id
        assert (
            follow_up.title,
            follow_up.start_date,
            follow_up.end_date,
            follow_up.rate_client,
        ) == (
            "OIT/9992/2026/ITVM",
            date(2026, 11, 2),
            date(2026, 12, 31),
            Decimal("1265.5"),
        )
        await db.refresh(first)
        assert (first.title, first.end_date, first.status) == (
            "OIT/9991/2026/ITVM",
            date(2026, 10, 28),
            ClientOrderStatus.active,
        )

        # Jednorazowo: wpis przeczytany aktualną wersją nie wraca w kolejnym biegu.
        again = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, again)
        assert again.replanned == 0


async def test_replan_after_a_rule_change_respects_the_autoapply_switch(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal

    monkeypatch.setattr(ingest.settings, "ORDER_MAIL_AUTOAPPLY_ENABLED", False)
    async with AsyncSessionLocal() as db:
        _, doc = await _alior_with_a_pending_next_period(db, monkeypatch, tmp_path)
        stats = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, stats)
        await db.refresh(doc)
        assert (stats.replanned, stats.replanned_auto_applied) == (1, 0)
        assert doc.outcome == "needs_review" and doc.applied_order_id is None
        # Nowy plan jest pewny — czeka już tylko na „Zastosuj".
        assert doc.gate_reasons == [ingest.AUTOAPPLY_DISABLED_REASON]
        assert doc.document_meta["rule_versions"] == {
            "alior": policy_by_key("alior").rule_version
        }


async def test_document_read_with_the_current_rule_is_not_replanned(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal

    current = {"alior": policy_by_key("alior").rule_version}
    refresh = AsyncMock(side_effect=AssertionError("wpis jest aktualny"))
    async with AsyncSessionLocal() as db:
        _, doc = await _alior_with_a_pending_next_period(
            db, monkeypatch, tmp_path, document_meta={"rule_versions": current}
        )
        monkeypatch.setattr(ingest, "refresh_review_plan", refresh)
        stats = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, stats)
        await db.refresh(doc)
        assert stats.replanned == 0 and stats.errors == []
        assert doc.outcome == "needs_review"
        refresh.assert_not_awaited()


async def test_failed_replan_is_reported_once_and_not_retried_every_run(
    monkeypatch, tmp_path
):
    from app.core.database import AsyncSessionLocal

    refresh = AsyncMock(side_effect=RuntimeError("pdf nieczytelny"))
    async with AsyncSessionLocal() as db:
        _, doc = await _alior_with_a_pending_next_period(db, monkeypatch, tmp_path)
        monkeypatch.setattr(ingest, "refresh_review_plan", refresh)
        stats = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, stats)
        await db.refresh(doc)
        assert stats.replanned == 0
        assert any(f"replan doc {doc.id}" in e for e in stats.errors)
        assert doc.outcome == "needs_review"
        assert doc.error.startswith("Automatyczne przeliczenie po zmianie reguły")
        assert doc.document_meta["rule_versions"] == {
            "alior": policy_by_key("alior").rule_version
        }
        again = ingest.IngestStats()
        await ingest.replan_outdated_documents(db, again)
        assert refresh.await_count == 1 and again.errors == []


def test_alior_rule_carries_a_version_so_pending_documents_follow_rule_changes():
    """Bez wersji poprawka reguły nie dotarłaby do wpisów czekających w kolejce."""
    from app.services.order_policies import rule_versions

    assert rule_versions(POLICIES) == {"alior": policy_by_key("alior").rule_version}
    assert policy_by_key("alior").rule_version


# ── Endpoint „Zczytaj dane z dokumentu" ──────────────────────────────────────


@pytest.mark.parametrize("targeted", [False, True])
async def test_zczytaj_endpoint_returns_the_same_four_fields(
    app_client, app_auth_headers, monkeypatch, targeted
):
    from app.api import client_orders as co
    from tests.test_order_extract_endpoint import _seed_candidate, _seed_client

    client_id = await _seed_client(f"Alior Bank {uuid.uuid4().hex[:6]}")
    candidate_id = await _seed_candidate(
        "Łucja", "Próbna", contract_client_id=client_id
    )
    monkeypatch.setenv("ALIOR_ORDER_EXTRACTION_CLIENT_IDS", str(client_id))
    monkeypatch.setattr(co, "extract_text", lambda *args: TICKET)

    async def parse(text, **kwargs):
        assert kwargs == {"all_rows": True}
        return model_reading(
            person(
                "Łucja Próbna", reason="Nie ustalono, czy stawka jest brutto czy netto"
            ),
            reasons=(
                "Stawka bazowa 1100 różni się od stawki dla Banku",
                "Total nie jest total_value",
            ),
        )

    monkeypatch.setattr(co, "parse_order_document", parse)
    response = await app_client.post(
        f"/api/clients/{client_id}/orders/extract",
        data={"candidate_id": str(candidate_id)} if targeted else {},
        files={
            "file": ("Zamówienie B2B UIv2-sig.pdf", b"%PDF-dummy", "application/pdf")
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["client_policy"] == "Alior"
    assert data["title"] == "OIT/9991/2026/ITVM" and data["title_needs_review"] is False
    assert (data["start_date"], data["end_date"]) == ("2026-10-05", "2026-10-28")
    assert Decimal(str(data["rate_client"])) == Decimal("1265.5")
    assert data["rate_unit"] == "day"
    assert data["md_total"] is None and data["total_value"] is None
    assert data["uncertain"] is False and data["uncertain_reasons"] == []


# ── Kolejka: odczyt modelu niesie kwoty ──────────────────────────────────────


def test_queue_hides_model_reading_amounts_from_roles_without_finance():
    from app.api.order_mail_queue import _redact_extraction

    stored = ingest.extraction_to_json(
        read(TICKET, model_reading(person("Łucja Próbna")))
    )
    assert stored["model_rows"][0]["rate_client"] is not None
    redacted = _redact_extraction(stored, show_finance=False)
    assert redacted["model_rows"][0]["rate_client"] is None
    assert redacted["consultant_rows"][0]["rate_client"] is None
    assert redacted["model_rows"][0]["consultant_name"] == "Łucja Próbna"
    assert _redact_extraction(stored, show_finance=True) is stored
