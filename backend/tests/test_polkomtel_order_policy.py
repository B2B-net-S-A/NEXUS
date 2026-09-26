"""Polityka odczytu „Zlecenia wykonawczego" Polkomtela — na SYNTETYCZNYCH tekstach.

Fixture'y odtwarzają układ dokumentu z ticketu 09.2026 (numer „SAP … / rok",
„zawarte w dniu …", tabela „Cena netto 1MD po upuście [PLN] | Cena total [PLN]
| Konsultant" ze scaloną komórką kwoty). Nazwiska, numery i kwoty są zmyślone
(repo jest publiczne). Trzy kształty tekstu, które daje pipeline:

* ``PDF_ROW`` — pdfplumber składa wiersz tabeli w jedną linię, a komórka
  scalona stoi osobną linią MIĘDZY wierszami (trafiłaby do bufora następnej
  osoby, gdyby nie znana kwota zlecenia);
* ``PDF_ROW_INLINE`` — komórka scalona w linii pierwszego wiersza;
* ``DOCX_CELLS`` — python-docx: każda komórka osobną linią, na końcu dokumentu,
  komórka scalona powtórzona przy każdym wierszu, BEZ „na kwotę".

Lata w datach: 2031+ (wolny zakres w bazie testowej, patrz CLAUDE.md).
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.services.order_policies import (
    active_policies,
    apply_rate_kind,
    parse_plan,
    policy_by_key,
)
from app.services.order_policies import polkomtel
from app.services.order_policies._shared import number_after_nr

HEAD = """1
ZLECENIE WYKONAWCZE nr SAP 4500987654 / 2031 rok
zawarte w dniu 30.03.2031
pomiędzy:
Przykładowa Telekomunikacja sp. z o.o., KRS nr 0000000001, NIP 000-00-00-000
a
B2B.net S.A., KRS nr 0000000002
I. Informacje ogólne
Referencja do Oferty: PZ/0000001111 – Zakup usługi testów
II. Harmonogram prac albo czas realizacji Zlecenia
III. Warunki finansowe i harmonogram płatności
1. Wartość Zlecenia albo stawki z planowaną pracochłonnością (szczegółowe wyliczenia):
na kwotę 40 000 PLN
na co składa się:
"""
TAIL = """2. Wskazanie sposobu rozliczenia:
[ ] na zasadzie wynagrodzenia ryczałtowego,
[x] na zasadzie przepracowanego czasu (tzw. „time&material”).
3. Kwoty należne z tytułu przeniesienia praw majątkowych - 10% wartości zamówienia
"""
HEADER = "Cena netto 1MD po upuście [PLN] Cena total [PLN] Konsultant\n"

PDF_ROW = (
    HEAD
    + HEADER
    + "840,00 zł Nowak-Testowa Ewa\n40 000,00 zł\n1 280,00 zł Przykładowy Adam\n"
    + TAIL
)
PDF_ROW_INLINE = (
    HEAD
    + HEADER
    + "840,00 zł 40 000,00 zł Nowak-Testowa Ewa\n1 280,00 zł Przykładowy Adam\n"
    + TAIL
)
DOCX_CELLS = (
    HEAD.replace("na kwotę 40 000 PLN\n", "")
    + TAIL
    + "Cena netto 1MD po upuście [PLN]\nCena total [PLN]\nKonsultant\n"
    + "840,00 zł\n40 000,00 zł\nNowak-Testowa Ewa\n"
    + "1 280,00 zł\n40 000,00 zł\nPrzykładowy Adam\n"
    + "Wykonawca\nNabywca\n(podpis i pieczęć albo czytelny podpis)\n"
)

EXPECTED_ROWS = [
    ("Nowak-Testowa Ewa", Decimal("840.00")),
    ("Przykładowy Adam", Decimal("1280.00")),
]


def _run(text: str, *, model_reasons: list[str] | None = None) -> OrderExtraction:
    model = OrderExtraction(
        title="Umowa ramowa 12/2030",
        start_date="2031-01-01",
        end_date="2031-12-31",
        md_total=Decimal("64"),
        uncertain=True,
        uncertain_reasons=model_reasons or ["Brak informacji o liczbie MD"],
        source="claude",
    )
    return polkomtel.apply_polkomtel_order_policy(model, text)


# ── Numer zamówienia: skrót + numer, bez części po ukośniku ─────────────────


@pytest.mark.parametrize(
    "line, expected",
    [
        ("ZLECENIE WYKONAWCZE nr SAP 4500987654 / 2031 rok", "SAP 4500987654"),
        ("Zlecenie wykonawcze nr SAP 4500987654/2031", "SAP 4500987654"),
        ("ZLECENIE WYKONAWCZE nr CP 7788 / 2031 rok", "CP 7788"),
        ("ZLECENIE WYKONAWCZE nr. XYZ-12 / 2031", "XYZ-12"),
        ("ZLECENIE WYKONAWCZE nr SAP   4500987654 z dnia 01.02.2031", "SAP 4500987654"),
        ("ZLECENIE WYKONAWCZE nr 4500987654 / 2031", "4500987654"),
    ],
)
def test_number_is_the_prefix_and_digits_after_nr_up_to_the_slash(line, expected):
    assert polkomtel.order_number(f"1\n{line}\nzawarte w dniu 30.03.2031\n") == expected


def test_number_is_anchored_to_the_header_not_to_any_nr_in_the_document():
    text = "Spółka wpisana do KRS nr 0000000001 / 2031\nZLECENIE WYKONAWCZE nr SAP 45 / 2031"
    assert polkomtel.order_number(text) == "SAP 45"
    assert polkomtel.order_number("KRS nr 0000000001 / 2031") is None


def test_number_without_digits_is_not_a_number():
    assert (
        number_after_nr(
            "ZLECENIE WYKONAWCZE nr SAP / 2031", label=polkomtel.NUMBER_LABEL
        )
        is None
    )


# ── Okres: start z „zawarte w dniu", koniec bezterminowo ────────────────────


@pytest.mark.parametrize("text", [PDF_ROW, PDF_ROW_INLINE, DOCX_CELLS])
def test_start_date_from_signing_phrase_and_open_ended(text):
    result = _run(text)
    assert result.title == "SAP 4500987654"
    assert result.confidence["title"] == 1.0
    assert result.start_date == "2031-03-30"
    assert result.end_date is None


def test_missing_signing_date_needs_manual_start_and_is_not_guessed():
    result = _run(PDF_ROW.replace("zawarte w dniu 30.03.2031\n", ""))
    assert result.start_date is None
    assert any("zawarte w dniu" in reason for reason in result.uncertain_reasons)


# ── Wiersze: stawka z WŁASNEGO wiersza ──────────────────────────────────────


@pytest.mark.parametrize("text", [PDF_ROW, PDF_ROW_INLINE, DOCX_CELLS])
def test_each_consultant_gets_the_rate_from_their_own_row(text):
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == EXPECTED_ROWS
    assert all(r.rate_unit == "day" and not r.uncertain for r in rows)
    assert all(r.md_total is None for r in rows)


@pytest.mark.parametrize("text", [PDF_ROW, PDF_ROW_INLINE, DOCX_CELLS])
def test_order_amount_is_the_total_of_the_whole_order(text):
    result = _run(text)
    assert result.total_value == Decimal("40000")
    assert result.currency == "PLN"
    # Kilka osób: stawka istnieje wyłącznie per wiersz.
    assert result.rate_client is None
    assert result.rate_unit == "day"


def test_name_first_column_order_keeps_rates_with_their_people():
    text = (
        HEAD
        + "Konsultant Cena netto 1MD po upuście [PLN] Cena total [PLN]\n"
        + "Nowak-Testowa Ewa 840,00 zł 40 000,00 zł\nPrzykładowy Adam 1 280,00 zł\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == EXPECTED_ROWS


def test_per_row_totals_sum_to_the_order_and_do_not_become_rates():
    text = (
        HEAD
        + HEADER
        + "840,00 zł 14 280,00 zł Nowak-Testowa Ewa\n"
        + "1 280,00 zł 25 720,00 zł Przykładowy Adam\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == EXPECTED_ROWS
    assert polkomtel.table_total(text) == Decimal("40000.00")
    assert not any("różni się" in r for r in _run(text).uncertain_reasons)


def test_amount_and_table_total_mismatch_is_flagged():
    text = PDF_ROW.replace("40 000,00 zł", "39 000,00 zł")
    reasons = _run(text).uncertain_reasons
    assert any("różni się od kolumny „Cena total”" in r for r in reasons)


def test_missing_table_keeps_model_rows_and_says_so():
    text = HEAD + TAIL
    model_rows = [
        ConsultantOrderRow(consultant_name="Nowak Ewa", rate_client=Decimal("900"))
    ]
    model = OrderExtraction(consultant_rows=model_rows, source="claude")
    result = polkomtel.apply_polkomtel_order_policy(model, text)
    assert result.consultant_rows == model_rows
    assert any(
        "Nie rozpoznano tabeli konsultantów" in r for r in result.uncertain_reasons
    )


# ── MD: brak to poprawny odczyt; dwa warianty, gdy jest ─────────────────────


def test_cost_order_without_md_is_not_uncertain_about_md():
    """Sedno ticketu: „brak informacji o liczbie MD" od modelu znika."""
    result = _run(PDF_ROW)
    assert result.md_total is None
    assert result.uncertain is False
    assert result.uncertain_reasons == []


def test_md_per_consultant_column():
    text = (
        HEAD
        + "Cena netto 1MD po upuście [PLN] Liczba MD Cena total [PLN] Konsultant\n"
        + "840,00 zł 20 40 000,00 zł Nowak-Testowa Ewa\n"
        + "1 280,00 zł 18 Przykładowy Adam\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client, r.md_total) for r in rows] == [
        ("Nowak-Testowa Ewa", Decimal("840.00"), Decimal("20")),
        ("Przykładowy Adam", Decimal("1280.00"), Decimal("18")),
    ]
    assert _run(text).md_total is None  # MD jest przy osobach, nie na dokumencie


def test_md_for_the_whole_order():
    text = PDF_ROW.replace(
        "na kwotę 40 000 PLN\n",
        "na kwotę 40 000 PLN (planowana pracochłonność: 38 MD)\n",
    )
    result = _run(text)
    assert result.md_total == Decimal("38")
    assert all(row.md_total is None for row in result.consultant_rows)


def test_header_1md_is_not_read_as_an_md_count():
    assert polkomtel.order_md(PDF_ROW) is None


# ── Stawka zawsze netto ─────────────────────────────────────────────────────


def test_rates_are_always_net_without_gross_detection():
    text = PDF_ROW.replace(
        "Cena netto 1MD po upuście",
        "Cena netto 1MD po upuście (kwoty brutto w załączniku)",
    )
    result = _run(text)
    result.rate_client_gross = Decimal("1")
    result = apply_rate_kind(result, text, [policy_by_key("polkomtel")])
    assert result.rate_client_gross is None
    assert [r.rate_client for r in result.consultant_rows] == [
        Decimal("840.00"),
        Decimal("1280.00"),
    ]
    assert all(r.rate_client_gross is None for r in result.consultant_rows)


def test_rate_already_divided_by_vat_returns_to_the_pdf_amount():
    """N3 (audyt 24.09): stawka po ÷ 1,23 wraca do kwoty z PDF-a.

    Reguła zerowała sam oryginał brutto, więc odczyt zapisany przed nią
    (albo wiersze modelu bez rozpoznanej tabeli) zostawał z zaniżoną stawką
    netto i bez śladu przeliczenia. Tak robią Nordea, PKO BP i Alior.
    """
    divided = OrderExtraction(
        rate_client=Decimal("682.93"),
        rate_client_gross=Decimal("840.00"),
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Jan Testowy",
                rate_client=Decimal("682.93"),
                rate_client_gross=Decimal("840.00"),
                rate_unit="day",
            )
        ],
        source="claude",
    )
    ruled = polkomtel.apply_rate_rules(divided, HEAD)
    ruled = polkomtel.apply_rate_rules(ruled, HEAD)  # idempotentne
    for item in [ruled, *ruled.consultant_rows]:
        assert (item.rate_client, item.rate_client_gross) == (Decimal("840.00"), None)
    # Wersja reguły nie może wrócić sprzed tej poprawki (późniejsze ją podbijają).
    assert policy_by_key("polkomtel").rule_version >= "2026-09-24.2"


def test_rate_rule_keeps_gross_net_decision_for_other_templates():
    """Audyt 24.09.2026: stawka sprzed ÷ 1,23 wraca TYLKO w „Zleceniu
    wykonawczym nr …" (lustro BIK). Inny szablon od Polkomtela (np. faktura
    albo pismo z kwotą brutto) idzie ogólnym rozpoznaniem brutto/netto —
    reguła „zawsze netto" podnosiła tam stawkę o VAT."""
    divided = OrderExtraction(
        rate_client=Decimal("682.93"),
        rate_client_gross=Decimal("840.00"),
        source="claude",
    )
    assert (
        polkomtel.apply_rate_rules(divided, "Zamówienie 12/2031\n840 zł brutto") is None
    )
    assert divided.rate_client == Decimal("682.93")


# ── Rejestr ─────────────────────────────────────────────────────────────────


def test_polkomtel_policy_is_active_for_the_canonical_client(monkeypatch):
    """Produkcyjne ID 15 działa bez env; conftest odpina je od seriala testów."""
    from app.services.order_policies import registry

    assert polkomtel.CANONICAL_CLIENT_IDS == frozenset({15})
    real = replace(
        policy_by_key("polkomtel"), canonical_client_ids=polkomtel.CANONICAL_CLIENT_IDS
    )
    monkeypatch.setattr(
        registry,
        "POLICIES",
        tuple(real if p.key == "polkomtel" else p for p in registry.POLICIES),
    )
    monkeypatch.setitem(registry._BY_KEY, "polkomtel", real)
    monkeypatch.delenv(polkomtel.CLIENT_IDS_ENV, raising=False)
    assert [p.key for p in active_policies(15)] == ["polkomtel"]
    assert registry.closes_on_md_exhaustion(15) is True
    assert active_policies(4243) == []
    monkeypatch.setenv(polkomtel.CLIENT_IDS_ENV, "4243")
    assert [p.key for p in active_policies(4243)] == ["polkomtel"]


def test_registry_declares_the_canonical_ids():
    import inspect

    from app.services.order_policies import registry

    source = inspect.getsource(registry)
    assert "canonical_client_ids=polkomtel.CANONICAL_CLIENT_IDS" in source
    assert (
        "canonical_client_ids=polkomtel.CYFROWY_POLSAT_CANONICAL_CLIENT_IDS" in source
    )


def test_flags():
    policy = policy_by_key("polkomtel")
    assert parse_plan([policy]).rate_unit_default == "day"
    assert policy.open_ended_period is True
    assert policy.closes_on_md_exhaustion is True
    assert policy.exposes_consultant_rows is True
    assert policy.extract_rows is polkomtel.extract_rows


# ── Cyfrowy Polsat: ten sam szablon, sama reguła numeru ─────────────────────


def test_cyfrowy_polsat_takes_only_the_number():
    text = PDF_ROW.replace("nr SAP 4500987654", "nr CP 5566")
    model = OrderExtraction(
        title="Umowa 1/2030",
        start_date="2031-05-01",
        end_date="2031-12-31",
        source="claude",
    )
    result = polkomtel.apply_cyfrowy_polsat_order_number(model, text)
    assert result.title == "CP 5566"
    assert result.confidence["title"] == 1.0
    # Okres zostaje przy odczycie ogólnym — CP ma też zamówienia okresowe.
    assert (result.start_date, result.end_date) == ("2031-05-01", "2031-12-31")


def test_cyfrowy_polsat_without_the_number_line_keeps_the_model_reading():
    model = OrderExtraction(title="Zamówienie 12", source="claude")
    result = polkomtel.apply_cyfrowy_polsat_order_number(model, "Zamówienie nr 12")
    assert result.title == "Zamówienie 12"


def test_env_gates_are_fail_closed(monkeypatch):
    for key in ("polkomtel", "cyfrowy_polsat"):
        monkeypatch.delenv(policy_by_key(key).env_var, raising=False)
        assert policy_by_key(key) not in active_policies(4244)
    monkeypatch.setenv("CYFROWY_POLSAT_ORDER_EXTRACTION_CLIENT_IDS", "4244")
    assert [p.key for p in active_policies(4244)] == ["cyfrowy_polsat"]


def test_targeted_read_picks_the_row_of_that_person():
    """„Dodaj konsultanta" czyta PDF dla jednej osoby — stawka z jej wiersza."""
    model = OrderExtraction(source="claude")
    result = polkomtel.apply_polkomtel_order_policy(
        model, PDF_ROW, target_consultant="Adam Przykładowy", target_given_names="Adam"
    )
    assert result.rate_client == Decimal("1280.00")
    assert result.rate_unit == "day"
    assert result.consultant_rate_matched is True
    assert result.title == "SAP 4500987654"


def test_targeted_read_of_absent_person_keeps_the_rate_empty():
    model = OrderExtraction(source="claude")
    result = polkomtel.apply_polkomtel_order_policy(
        model, PDF_ROW, target_consultant="Zenon Nieobecny", target_given_names="Zenon"
    )
    assert result.rate_client is None
    assert result.consultant_rate_matched is False


# ── Przegląd adwersarialny: tabela nie może po cichu przesunąć stawki ──────


def test_unrecognised_name_never_moves_a_rate_to_the_next_person():
    text = (
        HEAD
        + HEADER
        + "840,00 zł MARIA WIŚNIEWSKA-NOWAK de la Cruz\n40 000,00 zł\n"
        + "1 280,00 zł Przykładowy Adam\n"
        + TAIL
    ).replace("MARIA WIŚNIEWSKA-NOWAK de la Cruz", "maria de la cruz")
    rows = polkomtel.extract_rows(text)
    assert [r.consultant_name for r in rows] == ["Przykładowy Adam"]
    assert rows[0].rate_client is None and rows[0].uncertain is True
    assert rows[0].rate_client != Decimal("840.00")


def test_all_caps_and_apostrophe_names_are_read():
    text = (
        HEAD
        + HEADER
        + "840,00 zł NOWAK-TESTOWA EWA\n40 000,00 zł\n1 280,00 zł O'Neil John\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == [
        ("NOWAK-TESTOWA EWA", Decimal("840.00")),
        ("O'Neil John", Decimal("1280.00")),
    ]


def test_name_wrapped_across_lines_is_flagged_not_guessed():
    text = (
        HEAD
        + HEADER
        + "840,00 zł Nowak-Testowa\nEwa\n40 000,00 zł\n1 280,00 zł Przykładowy Adam\n"
        + TAIL
    )
    result = _run(text)
    adam = [
        r for r in result.consultant_rows if r.consultant_name == "Przykładowy Adam"
    ]
    assert adam and adam[0].rate_client is None and adam[0].uncertain is True
    assert result.uncertain is True


def test_the_word_konsultantow_above_the_table_does_not_flip_the_columns():
    text = PDF_ROW.replace(
        "Referencja do Oferty: PZ/0000001111 – Zakup usługi testów",
        "Referencja do Oferty: PZ/0000001111 – Zakup usług konsultantów",
    )
    rows = polkomtel.extract_rows(text)
    assert [(r.consultant_name, r.rate_client) for r in rows] == EXPECTED_ROWS


def test_three_rows_with_an_unreadable_middle_row_flag_the_row_after_it():
    text = (
        HEAD
        + HEADER
        + "840,00 zł 40 000,00 zł Nowak-Testowa Ewa\n"
        + "900,00 zł ???\n"
        + "1 280,00 zł Przykładowy Adam\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert rows[0].rate_client == Decimal("840.00")
    assert rows[1].consultant_name == "Przykładowy Adam"
    assert rows[1].rate_client is None and rows[1].uncertain is True


def test_dot_as_thousands_separator():
    text = PDF_ROW.replace("na kwotę 40 000 PLN", "na kwotę 40.000 PLN").replace(
        "1 280,00 zł", "1.280,00 zł"
    )
    result = _run(text)
    assert result.total_value == Decimal("40000")
    assert [r.rate_client for r in result.consultant_rows] == [
        Decimal("840.00"),
        Decimal("1280.00"),
    ]


def test_foreign_currency_amounts_are_not_read_as_pln_rates():
    text = PDF_ROW.replace("840,00 zł", "840,00 EUR")
    result = _run(text)
    assert all(r.rate_client != Decimal("840.00") for r in result.consultant_rows)
    assert any("innej walucie" in reason for reason in result.uncertain_reasons)


def test_model_disagreeing_with_the_table_sends_the_row_to_review():
    model = OrderExtraction(
        source="claude",
        consultant_rows=[
            ConsultantOrderRow(
                consultant_name="Nowak-Testowa Ewa",
                rate_client=Decimal("1280"),
                rate_unit="day",
                uncertain=False,
            ),
            ConsultantOrderRow(consultant_name="Trzeci Tomasz", uncertain=True),
        ],
    )
    result = polkomtel.apply_polkomtel_order_policy(model, PDF_ROW)
    ewa = result.consultant_rows[0]
    assert ewa.rate_client == Decimal("840.00") and ewa.uncertain is True
    assert "różni się od odczytu AI" in (ewa.uncertain_reason or "")
    assert any("„Trzeci Tomasz”" in r for r in result.uncertain_reasons)
    assert result.uncertain is True


def test_other_polkomtel_documents_keep_the_general_reading():
    model = OrderExtraction(
        title="Aneks 3",
        start_date="2031-01-01",
        end_date="2031-06-30",
        rate_client=Decimal("150"),
        rate_unit="hour",
        source="claude",
    )
    text = "ANEKS nr 3 do umowy\nStawka 150 zł/h od 01.01.2031 do 30.06.2031\n"
    result = polkomtel.apply_polkomtel_order_policy(model, text)
    assert (result.title, result.end_date, result.rate_unit) == (
        "Aneks 3",
        "2031-06-30",
        "hour",
    )
    assert result.uncertain is True
    assert any("ZLECENIE WYKONAWCZE" in r for r in result.uncertain_reasons)


def test_number_does_not_run_across_words():
    text = "ZLECENIE WYKONAWCZE nr SAP 4500 do Umowy nr 12/2020\n"
    assert polkomtel.order_number(text) is None


# ── Runda 6 audytu: kolumna MD na lewo od stawki sklejona z kwotą ───────────

MD_LEFT_HEADER = "Liczba MD Cena netto 1MD po upuście [PLN] Cena total [PLN] Konsultant\n"
MD_LEFT = (
    HEAD.replace("na kwotę 40 000 PLN\n", "")
    + MD_LEFT_HEADER
    + "10 840,00 zł 8 400,00 zł Nowak Ewa\n"
    + TAIL
)


def test_md_column_left_of_rate_is_not_glued_into_the_rate():
    # pdfplumber: „10" (MD) i „840,00 zł" (stawka) w jednej linii ze spacją —
    # _MONEY_RE czytało to jako 10 840,00, największa kwota szła do sum,
    # a stawką zostawała kwota osoby 8 400,00 bez żadnej uwagi.
    rows = polkomtel.extract_rows(MD_LEFT)
    assert [(r.consultant_name, r.rate_client, r.md_total) for r in rows] == [
        ("Nowak Ewa", Decimal("840.00"), Decimal("10")),
    ]
    # MD × stawka = kwota osoby — sklejenie rozstrzygnięte arytmetyką.
    assert not rows[0].uncertain
    assert polkomtel.table_total(MD_LEFT) == Decimal("8400.00")


def test_glued_md_without_arithmetic_proof_is_uncertain():
    text = MD_LEFT.replace("8 400,00 zł", "9 999,00 zł")
    rows = polkomtel.extract_rows(text)
    assert len(rows) == 1
    assert rows[0].uncertain
    assert "skleić" in rows[0].uncertain_reason
    result = _run(text)
    assert result.uncertain
    assert result.rate_client is None


def test_glued_md_without_total_column_is_uncertain():
    text = (
        HEAD.replace("na kwotę 40 000 PLN\n", "")
        + "Liczba MD Cena netto 1MD po upuście [PLN] Konsultant\n"
        + "10 840,00 zł Nowak Ewa\n"
        + TAIL
    )
    rows = polkomtel.extract_rows(text)
    assert len(rows) == 1 and rows[0].uncertain


def test_separate_md_cell_left_of_rate_is_read_without_concern():
    text = MD_LEFT.replace("10 840,00 zł 8 400,00 zł", "10 1 200,00 zł 12 000,00 zł")
    rows = polkomtel.extract_rows(text)
    assert [(r.rate_client, r.md_total, r.uncertain) for r in rows] == [
        (Decimal("1200.00"), Decimal("10"), False)
    ]
