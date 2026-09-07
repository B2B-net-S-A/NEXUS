"""Polityki klientowe z korpusu 09.2026 — na SYNTETYCZNYCH fixture'ach.

Każdy fixture odtwarza UKŁAD tekstu z pipeline'u (pdfplumber: wiersz tabeli
w jednej linii, nagłówek w linii nad wartościami, numer umowy ramowej
powtórzony przed numerem zamówienia), ale nazwiska, numery i kwoty są
zmyślone. Realny korpus zostaje poza repo; kontraktem jakości jest harness
(``scripts/order_corpus_harness.py``), a te testy pilnują, żeby regexy nie
cofnęły się na kształtach, które harness raz potwierdził.

Lata w datach: 2031+ (wolny zakres w bazie testowej, patrz CLAUDE.md).
"""

from decimal import Decimal

import pytest

from app.services.order_pdf_parser import OrderExtraction
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    policy_by_key,
)
from app.services.order_policies import (
    alior,
    bank_pocztowy,
    cardif,
    kir,
    mleasing,
    nordea,
    pko_bp,
    velobank,
)


def _run(key: str, text: str, *, target: str | None = None) -> OrderExtraction:
    result = OrderExtraction(source="claude")
    result, applied = apply_policies(
        result,
        PolicyContext(document_text=text, target_consultant=target),
        [policy_by_key(key)],
    )
    assert applied == [policy_by_key(key).display_name]
    return result


# ── PKO BP ───────────────────────────────────────────────────────────────────

PKO = """PKO Bank Polski SA
Zamówienie nr 1830/2031
Zgodnie z postanowieniem Umowy ramowej numer DIT-2031-0005 o świadczeniu usług z dnia 2031-08-19, PKO BP SA zleca firmie
1. Wykonawcy, Profile, Terminy, Stawki:
Imię i nazwisko Początek Planowany Koniec Stawka
Profil Liczba MD Lokalizacja Numer SSGW
Wykonawców Zaangażowania Zaangażowania PLN/MD netto
Projektant
Anna Przykładowa 2031-09-01 2031-11-30 64 900,00 Warszawa 103587-1
UI/UX Senior
Łączna wartość zamówienia wynosi: 57 600,00 PLN netto i 70 848,00 PLN brutto.
"""


class TestPkoBp:
    def test_number_ignores_framework_agreement(self):
        assert pko_bp.order_number(PKO) == "1830/2031"

    def test_row_per_line_layout(self):
        rows = pko_bp.extract_rows(PKO)
        assert len(rows) == 1
        r = rows[0]
        assert r.consultant_name == "Anna Przykładowa"
        assert (r.start_date, r.end_date) == ("2031-09-01", "2031-11-30")
        assert (r.md_total, r.rate_client, r.rate_unit) == (
            Decimal("64"),
            Decimal("900.00"),
            "day",
        )

    def test_policy_sets_document_fields_from_single_row(self):
        r = _run("pko_bp", PKO)
        assert r.title == "1830/2031"
        assert (r.start_date, r.end_date) == ("2031-09-01", "2031-11-30")
        assert (r.rate_client, r.rate_unit, r.md_total) == (
            Decimal("900.00"),
            "day",
            Decimal("64"),
        )
        assert r.confidence["rate_client"] == 1.0
        assert r.uncertain is False

    def test_cell_per_line_layout_still_parses(self):
        text = "Numer SSGW\nJan Testowy\nProjektant\n2031-01-01\n2031-03-31\n40\n1 000,00\nWarszawa\nŁączna wartość"
        rows = pko_bp.extract_rows(text)
        assert [r.consultant_name for r in rows] == ["Jan Testowy"]


# ── KIR ──────────────────────────────────────────────────────────────────────

KIR = """Krajowa Izba Rozliczeniowa S.A., NIP 526-030-05-17
L.dz. KIR/DAZ/MD/01351/6/2031/DSR/ZAM
ZAMÓWIENIE
Termin realizacji 1.07.2031 - 30.09.2031
Przedmiot zamówienia:
Zatrudnienie kontraktora - P. Konrad
Testowy, stawka 210,00 zł netto/h = 1680.00 1. 66
zł netto/1 MD
"""


class TestKir:
    def test_number_from_ldz(self):
        assert kir.order_number(KIR) == "KIR/DAZ/MD/01351/6/2031/DSR/ZAM"

    def test_person_with_honorific_split_across_lines_and_hourly_rate(self):
        rows = kir.extract_rows(KIR)
        assert len(rows) == 1
        assert rows[0].consultant_name == "Konrad Testowy"
        assert (rows[0].rate_client, rows[0].rate_unit) == (Decimal("210.00"), "hour")
        assert (rows[0].start_date, rows[0].end_date) == ("2031-07-01", "2031-09-30")

    def test_policy_ignores_md_recalculation(self):
        r = _run("kir", KIR)
        assert r.md_total is None
        assert (r.rate_client, r.rate_unit) == (Decimal("210.00"), "hour")
        assert r.uncertain is False


# ── mLeasing ─────────────────────────────────────────────────────────────────

MLEASING = """Numer zamówienia DO/CEO/CEO/31/013226
Wersja nr 1
Nabywca Adres dostawy faktury
mLeasing Sp. z o.o.
Lp. Dane pozycji Dostawa IlośćJm Cena jedn. Wartość netto Wartość bruttoMPK / R
netto
1 Nazwa: Adres dostawy: 225,00dzień 869,92 PLN 195 732,00 PLN 240 750,00 PLN
BL(mL) - ‪‪‪Ewa Testowa, Tester mLeasing Sp. z o.o.:
manualny - Regular, kontynuacja
Opis:
Okres zatrudnienia od 01.01.2031 r.
do 31.12.2031 r.
"""


class TestMleasing:
    def test_number(self):
        assert mleasing.order_number(MLEASING) == "DO/CEO/CEO/31/013226"

    def test_unit_price_and_unit_from_position_cell(self):
        assert mleasing.unit_price(MLEASING) == (Decimal("869.92"), "day")

    def test_name_strips_directional_marks(self):
        rows = mleasing.extract_rows(MLEASING)
        assert [r.consultant_name for r in rows] == ["Ewa Testowa"]

    def test_policy(self):
        r = _run("mleasing", MLEASING)
        assert (r.start_date, r.end_date) == ("2031-01-01", "2031-12-31")
        assert (r.rate_client, r.rate_unit) == (Decimal("869.92"), "day")
        assert r.uncertain is False


# ── VeloBank ─────────────────────────────────────────────────────────────────

VELO = """Zamówienie nr 3/07/2031/BL
VeloBank S.A. … NIP 7011105189 … Umowy Ramowej z 09.02.2023r.
1. Dane wykonawców:
Nazwisko i imię Wartość brutto
(profil) (dd-mm-rrrr) (dd-mm-rrrr) MD netto/MD netto
Testowy Marcin Starszy Tester 1.07.2031 31.08.2031 43 1 400,00 60 200,00 zł 74 046,00 zł
Przykładowa-Nowak Barbara Tester 1.07.2031 31.08.2031 43 900,00 38 700,00 zł 47 601,00 zł
4. Akceptacja wartości zlecenia:
Wartość zlecenia Podpis Zleceniodawcy
98 900,00 PLN NETTO
"""


class TestVelobank:
    def test_rows_have_own_period_and_rate(self):
        rows = velobank.extract_rows(VELO)
        assert [r.consultant_name for r in rows] == [
            "Testowy Marcin",
            "Przykładowa-Nowak Barbara",
        ]
        assert all(
            (r.start_date, r.end_date) == ("2031-07-01", "2031-08-31") for r in rows
        )
        assert [r.rate_client for r in rows] == [Decimal("1400.00"), Decimal("900.00")]
        assert all(r.md_total == Decimal("43") for r in rows)

    def test_total_reconciles(self):
        rows = velobank.extract_rows(VELO)
        assert (
            velobank.rows_reconcile_with_total(rows, velobank.total_net(VELO)) is True
        )

    def test_policy_multi_row_clears_document_rate_and_keeps_shared_period(self):
        r = _run("velobank", VELO)
        assert r.title == "3/07/2031/BL"
        assert (r.start_date, r.end_date) == ("2031-07-01", "2031-08-31")
        assert r.rate_client is None and r.md_total is None
        assert len(r.consultant_rows) == 2
        assert r.uncertain is False

    def test_mismatched_total_is_flagged(self):
        text = VELO.replace("98 900,00 PLN NETTO", "10 000,00 PLN NETTO")
        r = _run("velobank", text)
        assert r.uncertain is True
        assert any("nie zgadza się" in reason for reason in r.uncertain_reasons)


# ── Alior ────────────────────────────────────────────────────────────────────

ALIOR = """Zamówienie:
Do Umowy Ramowej: OIT/0258/2023/ITVM
Zamówienie nr: OIT/0189/2031/ITVM
do realizacji przedmiotu Umowy Ramowej nr: OIT/0258/2023/ITVM,
Imię i Stawka
Wiktoria
Testowa Business
1 189 1 155,00 13,81% 1 340,00 253 260,00 zł
(01.04.2031- Analyst
31.12.2031)
Jan Przykład
Developer
2 (01.04.2031- Backend 189 1 155,00 14,44% 1 350,00 255 150,00 zł
31.12.2031) Senior
Razem PLN netto: 508 410,00 zł
Szczególne warunki zamówienia
1. Maksymalna wartość Zamówienia (z marżą): 508 410,00 PLN netto
5. Moment wejścia w życie Zamówienia: 01.04.2031
czas oznaczony: 31.12.2031 lub do wyczerpania
6. Okres obowiązywania:
kwoty zamówienia
"""


class TestAlior:
    def test_number_is_the_order_not_the_framework(self):
        assert alior.order_number(ALIOR) == "OIT/0189/2031/ITVM"

    def test_rate_is_the_fourth_number_razem_stawka_dla_banku(self):
        rows = alior.extract_rows(ALIOR)
        assert [r.rate_client for r in rows] == [Decimal("1340.00"), Decimal("1350.00")]
        assert all(r.md_total == Decimal("189") for r in rows)
        assert all(
            (r.start_date, r.end_date) == ("2031-04-01", "2031-12-31") for r in rows
        )

    def test_document_period_ignores_do_wyczerpania_kwoty(self):
        r = _run("alior", ALIOR)
        assert (r.start_date, r.end_date) == ("2031-04-01", "2031-12-31")
        assert r.title == "OIT/0189/2031/ITVM"

    def test_names_are_best_effort_and_marked(self):
        rows = alior.extract_rows(ALIOR)
        # Nazwisko rozsypane po liniach: pieniądze pewne, tożsamość do potwierdzenia.
        assert rows[0].consultant_name == "Wiktoria Testowa"
        assert rows[0].uncertain is False
        assert rows[1].consultant_name == "Jan Przykład"


# ── Cardif ───────────────────────────────────────────────────────────────────

CARDIF = """Classification : Internal
Zamówienie z dnia 27.04.2031 do umowy ramowej z dnia 3 lipca 2017 (Time and Material)
Lista specjalistów wraz z harmonogramem prac
LP Grupa kompetencyjna Od Do Liczba MD
1. Jakub Testowy 27.04.2031 31.12.2031 172
9. Daty od do wskazują okres, w którym będą wykorzystane 172MDs przy zastosowaniu stawki dla Testera
Manualnego (1040 PLN/MD net.).
"""


class TestCardif:
    def test_identifier_is_the_order_date(self):
        assert cardif.order_number(CARDIF) == "27.04.2031"

    def test_row_and_rate_from_prose(self):
        rows = cardif.extract_rows(CARDIF)
        assert len(rows) == 1
        assert rows[0].consultant_name == "Jakub Testowy"
        assert (rows[0].start_date, rows[0].end_date) == ("2031-04-27", "2031-12-31")
        assert (rows[0].rate_client, rows[0].rate_unit) == (Decimal("1040"), "day")

    def test_policy_is_periodic_and_ignores_md(self):
        r = _run("cardif", CARDIF)
        assert r.md_total is None
        assert (r.start_date, r.end_date) == ("2031-04-27", "2031-12-31")
        assert r.uncertain is False


# ── Nordea (warstwa dla układu przeplecionego) ──────────────────────────────

NORDEA = """Docusign Envelope ID: ABC
Call Off Agreement
Company name (hereinafter referred to as "Nordea") Company number
Nordea Bank Abp 2858394-9
Nordea contact e-mail address Nordea Request number (if Frame Agreement Call Off
applicable) number Agreement
consultant.procurement@nordea.com number
40517 CW2117535
277157
Initial Term
Start date End date
2031-02-02 2031-11-30
Person(s) at the Supplier who Competence Category Location Quantity (max Unit Rate Subtotal
Łukasz Testowy IT Operations - Senior Poland - 1 728 Hours 175,00 PLN 302 400,00 PLN
Gdańsk
Total, excl. VAT 302 400,00 PLN
"""


class TestNordeaLayout:
    def test_call_off_number_is_the_standalone_line_after_frame_token(self):
        assert nordea.call_off_number_interleaved(NORDEA) == "277157"

    def test_layer_overrides_company_number_picked_by_label_window(self):
        r = _run("nordea", NORDEA)
        assert r.title == "277157"
        assert (r.start_date, r.end_date) == ("2031-02-02", "2031-11-30")
        assert (r.rate_client, r.rate_unit) == (Decimal("175.00"), "hour")
        assert r.consultant_rows[0].consultant_name == "Łukasz Testowy"
        assert r.consultant_rows[0].uncertain is False

    def test_quantity_times_rate_must_equal_subtotal(self):
        rows = nordea.extract_rows(
            NORDEA.replace("302 400,00 PLN\nGdańsk", "300 000,00 PLN\nGdańsk")
        )
        assert rows[0].uncertain is True


# ── Bank Pocztowy (warstwa) / Credit Agricole (warstwa) ─────────────────────

BP = """Zamówienie nr 231 /2031
Numer pisma 231/2031/ZAM/B2B
Profil Specjalisty (Stanowisko) Imię i nazwisko
Kierownik projektu Wojciech Testowy
Maksymalna kwota zamówienia nie może przekroczyć: 1400*1,23*38 = 65 436,00 PLN
Termin rozpoczęcia Planowany termin zakończenia Miejsce świadczenia usług
10.08.2031 30.09.2031
"""


class TestBankPocztowyLayout:
    def test_period_from_header_then_values_line(self):
        assert bank_pocztowy.period(BP) == ("2031-08-10", "2031-09-30")

    def test_full_policy_number_rate_period_person(self):
        r = _run("bank_pocztowy", BP)
        assert r.title == "231/2031/ZAM/B2B"
        assert (r.start_date, r.end_date) == ("2031-08-10", "2031-09-30")
        assert (r.rate_client, r.rate_unit, r.rate_client_md) == (
            Decimal("175.00"),
            "hour",
            Decimal("1400"),
        )
        assert r.consultant_rows[0].consultant_name == "Wojciech Testowy"
        assert r.uncertain is False


CA = """Zamówienie nr 26138 z dnia 2031-08-12 do Umowy Ramowej nr CA/B2B.NET/short/kwalif/2031
Wynagrodzenie
Poziom Szacowana
Nazwisko, imię Rola za 1MD (8h)
doświadczenia ilość MD
Specjaliści (PLN netto)
Testowy Wiktor Junior 54,00 700,00
Termin obowiązywania
Zamówienia - 2031-08-18 - 2031-10-31
"""


class TestCreditAgricoleLayout:
    def test_number_period_and_row(self):
        r = _run("credit_agricole", CA)
        assert r.title == "26138"
        assert (r.start_date, r.end_date) == ("2031-08-18", "2031-10-31")
        assert (r.rate_client, r.rate_unit) == (Decimal("700.00"), "day")
        assert r.consultant_rows[0].consultant_name == "Testowy Wiktor"


# ── Rejestr ──────────────────────────────────────────────────────────────────


def test_new_policies_are_env_gated_and_fail_closed(monkeypatch):
    for key in ("pko_bp", "kir", "mleasing", "velobank", "alior", "cardif"):
        monkeypatch.delenv(policy_by_key(key).env_var, raising=False)
        assert policy_by_key(key) not in active_policies(4242)
    monkeypatch.setenv("VELOBANK_ORDER_EXTRACTION_CLIENT_IDS", "4242")
    assert [p.key for p in active_policies(4242)] == ["velobank"]


# ── P1: deterministyczna stawka przeżywa enforce po no-match matchera ────────
#
# Bug: w manualnym /extract z candidate_id dla klienta z własną regułą (nie-BNP)
# polityka ustawia rate_client deterministycznie z układu dokumentu, po czym
# enforce_consultant_policy_safety kasuje ją, gdy matcher nie potwierdził wiersza
# osoby — czyli DOKŁADNIE w sytuacji, dla której ten deterministyczny parser
# layoutu istnieje. Fix: polityka ustawia consultant_rate_matched=True tam, gdzie
# stawkę ustawia jednoznacznie (jeden wiersz albo wspólna stawka dokumentu). Bez
# flagi bezpiecznik traktuje deterministyczną stawkę jak zgadniętą z globalnej
# etykiety i ją czyści.

# Warianty przycięte do JEDNEGO wiersza — gałąź len(rows)==1. W korpusie
# velobank/alior są wielo-wierszowe i CELOWO czyszczą stawkę (per osoba), więc
# ich gałęzi „set" nie pokrywają dokumenty wyżej.
VELO_SINGLE = """Zamówienie nr 3/07/2031/BL
VeloBank S.A. … NIP 7011105189 … Umowy Ramowej z 09.02.2023r.
1. Dane wykonawców:
Nazwisko i imię Wartość brutto
(profil) (dd-mm-rrrr) (dd-mm-rrrr) MD netto/MD netto
Testowy Marcin Starszy Tester 1.07.2031 31.08.2031 43 1 400,00 60 200,00 zł 74 046,00 zł
4. Akceptacja wartości zlecenia:
Wartość zlecenia Podpis Zleceniodawcy
60 200,00 PLN NETTO
"""

ALIOR_SINGLE = """Zamówienie:
Do Umowy Ramowej: OIT/0258/2023/ITVM
Zamówienie nr: OIT/0189/2031/ITVM
do realizacji przedmiotu Umowy Ramowej nr: OIT/0258/2023/ITVM,
Imię i Stawka
Wiktoria
Testowa Business
1 189 1 155,00 13,81% 1 340,00 253 260,00 zł
(01.04.2031- Analyst
31.12.2031)
Razem PLN netto: 253 260,00 zł
Szczególne warunki zamówienia
1. Maksymalna wartość Zamówienia (z marżą): 253 260,00 PLN netto
5. Moment wejścia w życie Zamówienia: 01.04.2031
czas oznaczony: 31.12.2031 lub do wyczerpania
"""

_DETERMINISTIC_SINGLE_RATE = [
    ("pko_bp", PKO),
    ("kir", KIR),
    ("mleasing", MLEASING),
    ("cardif", CARDIF),
    ("bank_pocztowy", BP),
    ("velobank", VELO_SINGLE),
    ("alior", ALIOR_SINGLE),
]


@pytest.mark.parametrize("key,text", _DETERMINISTIC_SINGLE_RATE)
def test_deterministic_rate_survives_enforce_after_no_match(key, text):
    from app.services.order_pdf_parser import enforce_consultant_policy_safety

    r = _run(key, text)
    # Sanity: fixture faktycznie ustawił stawkę z układu dokumentu.
    assert r.rate_client is not None, f"{key}: fixture nie ustawił stawki"
    # Fix P1: polityka oznacza, że stawka pochodzi z jednoznacznego wiersza, więc
    # bezpiecznik jej nie skasuje. Bez fixu ta flaga byłaby False.
    assert r.consultant_rate_matched is True, f"{key}: brak flagi (regresja P1)"

    enforce_consultant_policy_safety(r)
    assert r.rate_client is not None, f"{key}: enforce skasował stawkę (regresja P1)"


def test_real_matcher_no_confirm_then_deterministic_rate_survives():
    """Ścieżka z REALNYM matcherem (`apply_consultant_row_match`, którego NIE
    monkeypatchujemy): matcher nie potwierdza osoby, bo w wyniku „po LLM" nie ma
    jej wiersza. Mimo to deterministyczna stawka polityki przeżywa enforce."""
    from app.services.order_pdf_parser import (
        apply_consultant_row_match,
        enforce_consultant_policy_safety,
    )

    ext = OrderExtraction(source="claude")
    ext.consultant_rows = []  # LLM nie dostarczył wiersza tej osoby
    ext = apply_consultant_row_match(
        ext,
        "Nieobecny Człowiek",
        consultant_given_names="Nieobecny",
        rate_unit_default=None,
    )
    assert ext.consultant_rate_matched is False  # realny matcher nie potwierdził

    ext, _ = apply_policies(
        ext,
        PolicyContext(document_text=PKO, target_consultant="Nieobecny Człowiek"),
        [policy_by_key("pko_bp")],
    )
    ext = enforce_consultant_policy_safety(ext)
    assert ext.rate_client is not None  # deterministyczna stawka pko_bp przeżyła
